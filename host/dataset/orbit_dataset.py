"""Validate orbit inputs and map geometry samples to telemetry fields."""

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import struct
import tempfile
from collections.abc import Buffer, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from pathlib import Path
from time import sleep as _retry_sleep
from typing import SupportsFloat, SupportsIndex, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from astropy.time import Time
from astropy.units import Quantity
from astropy.utils import iers
from sgp4 import omm
from sgp4.api import WGS72, Satrec
from sgp4.conveniences import check_satrec

from host.dataset.orbit_geometry import (
    GeometrySample,
    GroundStation,
    LINZ_GROUND_STATION,
    NOMINAL_CARRIER_HZ,
    SPEED_OF_LIGHT_MPS,
    SX1278_FSTEP_HZ,
    SX1278_NOMINAL_FRF_WORD,
    compute_geometry_sample,
    propagate_itrs,
    quantize_sx1278_doppler,
    round_half_away_from_zero,
)
from host.common.canonical import (
    canonical_json_bytes,
    format_rfc3339_utc,
    parse_decimal,
    sha256_file,
    write_bytes_exclusive,
)
from host.dataset.orbit_record import MissionRecord, pack_mission_record
from host.common.runtime_config import load_settings


# Project-selected source freshness is independent of the
# adaptive past-pass window.  An OMM epoch may be no later than retrieval and
# no more than 72 hours old at retrieval.
_ORBIT_MODEL = load_settings("main_dataset")["orbit_model"]
_DATASET_DEFAULTS = load_settings("main_dataset")["acquire"]
MAX_OMM_AGE = timedelta(hours=_ORBIT_MODEL["sources"]["maximum_omm_age_hours"])
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_SOURCE_USER_AGENT = _ORBIT_MODEL["download"]["user_agent"]
_SOURCE_ATTEMPTS = _ORBIT_MODEL["download"]["attempts"]

class OrbitDatasetError(ValueError):
    """Reject an orbit source or artifact that violates the frozen contract."""

# These values identify the single orbit model accepted by this dataset stage.
_EXPECTED_OMM_FIELDS = {
    "OBJECT_NAME": "GOMX-1",
    "OBJECT_ID": "2013-066Q",
    "CENTER_NAME": "EARTH",
    "REF_FRAME": "TEME",
    "TIME_SYSTEM": "UTC",
    "MEAN_ELEMENT_THEORY": "SGP4",
    "NORAD_CAT_ID": "39430",
}

# The explicit column order is the Level 1 interchange contract.
# It prevents dictionary construction order
# or later internal refactors from changing the dataset bytes.
PASS_CSV_FIELDS = (
    "pass_id",
    "target_peak_elevation_deg",
    "actual_peak_elevation_deg",
    "peak_error_deg",
    "aos_utc",
    "first_sample_utc",
    "tca_utc",
    "last_sample_utc",
    "los_utc",
    "duration_seconds",
    "sample_count",
    "min_slant_range_m",
    "max_slant_range_m",
    "start_doppler_hz",
    "end_doppler_hz",
)

SAMPLE_CSV_FIELDS = (
    "pass_id",
    "target_peak_elevation_deg",
    "actual_peak_elevation_deg",
    "pass_sample_index",
    "timestamp_utc",
    "orbit_age_seconds",
    "trace_time_ms",
    "trace_sample_id",
    "position_x_ecef_m_float",
    "position_y_ecef_m_float",
    "position_z_ecef_m_float",
    "velocity_x_ecef_mps_float",
    "velocity_y_ecef_mps_float",
    "velocity_z_ecef_mps_float",
    "azimuth_deg",
    "elevation_deg",
    "slant_range_m_float",
    "range_rate_mps",
    "doppler_hz",
    "doppler_steps",
    "reg_frf_word",
    "programmed_doppler_hz",
    "quantization_error_hz",
    "position_x_m",
    "position_y_m",
    "position_z_m",
    "velocity_x_mmps",
    "velocity_y_mmps",
    "velocity_z_mmps",
    "slant_range_m",
    "range_rate_mmps",
    "doppler_millihz",
    "mission_state",
    "workload",
)

ORBIT_SCHEDULE_HASH_ROW = struct.Struct(">HIddI50s")


def iter_utc_second_chunks(
    start_utc: datetime,
    end_utc: datetime,
    *,
    chunk_days: int = _DATASET_DEFAULTS["chunk_days"],
) -> Iterator[tuple[datetime, ...]]:
    """Yield right-exclusive one-second UTC grids in bounded chunks.

    Inputs:
        start_utc: Inclusive beginning of the UTC sampling interval.
        end_utc: Exclusive end of the UTC sampling interval.
        chunk_days: Maximum propagation chunk length in days.

    Returns:
        Iterator of consecutive UTC datetime tuples at one-second spacing.

    Processing flow:
        UTC interval -> consecutive bounded chunks -> one-second UTC samples
        -> right-exclusive chunk boundaries without duplicate timestamps.

    Direct call tree (static source order):
        iter_utc_second_chunks
        +-- start_utc.utcoffset
        +-- timedelta
        +-- ValueError
        +-- end_utc.utcoffset
        +-- isinstance
        +-- min
        +-- int
        +-- <BinOp expression>.total_seconds
        +-- range
        +-- timestamps.append
        `-- tuple
    """
    if start_utc.tzinfo is None or start_utc.utcoffset() != timedelta(0):
        raise ValueError("start_utc and end_utc must be timezone-aware UTC")
    if end_utc.tzinfo is None or end_utc.utcoffset() != timedelta(0):
        raise ValueError("start_utc and end_utc must be timezone-aware UTC")
    if start_utc.microsecond != 0 or end_utc.microsecond != 0:
        raise ValueError("start_utc and end_utc must fall on integral UTC seconds")
    if end_utc <= start_utc:
        raise ValueError("end_utc must be after start_utc")
    if (
        not isinstance(chunk_days, int)
        or isinstance(chunk_days, bool)
        or chunk_days <= 0
    ):
        raise ValueError("chunk_days must be a positive integer")

    chunk_span = timedelta(days=chunk_days)
    chunk_start = start_utc
    while chunk_start < end_utc:
        chunk_end = min(chunk_start + chunk_span, end_utc)
        sample_count = int((chunk_end - chunk_start).total_seconds())
        timestamps: list[datetime] = []
        for offset in range(sample_count):
            timestamps.append(chunk_start + timedelta(seconds=offset))
        yield tuple(timestamps)
        chunk_start = chunk_end

def load_frozen_iers_a(
    path: str | Path,
    search_end_utc: datetime,
) -> iers.IERS_A:
    """Open frozen IERS-A bytes and require coverage through the search end.

    References:
        IERS, ``finals2000A.all`` Earth-orientation series; Astropy 8.0.1
        ``IERS_A.open``.

    Inputs:
        path: Source or artifact path used by this operation.
        search_end_utc: Exclusive end of the propagation search, or None for adaptive search.

    Returns:
        Frozen IERS-A table after coverage validation.

    Processing flow:
        Frozen IERS-A file + UTC search end -> local table parse -> final MJD
        coverage check -> table approved for propagation.

    Direct call tree (static source order):
        load_frozen_iers_a
        +-- search_end_utc.utcoffset
        +-- timedelta
        +-- ValueError
        +-- cast
        +-- iers.IERS_A.open
        +-- str
        +-- Path
        +-- float
        +-- last_mjd.to_value
        `-- Time
    """
    if (
        search_end_utc.tzinfo is None
        or search_end_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError("search_end_utc must be timezone-aware UTC")

    # Astropy's unannotated table accessors return these concrete runtime types.
    table = cast(iers.IERS_A, iers.IERS_A.open(str(Path(path))))
    last_mjd = cast(Quantity, table["MJD"][-1])
    last_table_mjd = float(cast(SupportsFloat, last_mjd.to_value("d")))
    search_end_mjd = float(
        cast(SupportsFloat, Time(search_end_utc, scale="utc").mjd)
    )
    if last_table_mjd < search_end_mjd:
        raise ValueError(
            "frozen IERS-A table does not cover search_end_utc: "
            f"last MJD {last_table_mjd}, required MJD {search_end_mjd}"
        )
    return table

def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of source bytes.

    Inputs:
        data: Exact bytes to hash.

    Returns:
        Lowercase SHA-256 text for the exact input bytes.

    Processing flow:
        Source bytes -> SHA-256 -> lowercase hexadecimal digest

    Direct call tree (static source order):
        sha256_bytes
        +-- hashlib.sha256
        `-- hashlib.sha256(...).hexdigest
    """
    return hashlib.sha256(data).hexdigest()


def write_source_atomically(
    destination: str | Path,
    content: bytes,
    validator: Callable[[Path], object],
) -> str:
    """Validate and atomically place one immutable source byte stream.

    Inputs:
        destination: Final source path for the validated source bytes.
        content: Original response bytes to preserve.
        validator: Callable that validates the staged source path.

    Returns:
        SHA-256 digest of the validated bytes written to the final path.

    Processing flow:
        Destination path + original response bytes
                         |
                         v
          Find the nearest existing parent directory
                         |
                         v
        Write into a temporary sibling directory tree
                         |
                         v
          Validate staged bytes and calculate SHA-256
                         |
                         v
             Atomically rename the new subtree
                         |
                         v
               Final source path + digest

    Direct call tree (static source order):
        write_source_atomically
        +-- Path
        +-- staging_parent.exists
        +-- staging_parent.is_dir
        +-- NotADirectoryError
        +-- destination_path.relative_to
        +-- tempfile.TemporaryDirectory
        +-- staged_path.parent.mkdir
        +-- staged_path.write_bytes
        +-- validator
        +-- sha256_bytes
        +-- staged_path.read_bytes
        `-- staged_subtree.replace
    """
    destination_path = Path(destination)
    staging_parent = destination_path.parent
    while not staging_parent.exists():
        staging_parent = staging_parent.parent
    if not staging_parent.is_dir():
        raise NotADirectoryError(staging_parent)

    relative_destination = destination_path.relative_to(staging_parent)
    with tempfile.TemporaryDirectory(dir=staging_parent) as temporary_directory:
        temporary_root = Path(temporary_directory)
        staged_path = temporary_root / relative_destination
        staged_path.parent.mkdir(parents=True)
        staged_path.write_bytes(content)
        validator(staged_path)
        digest = sha256_bytes(staged_path.read_bytes())

        staged_subtree = temporary_root / relative_destination.parts[0]
        final_subtree = staging_parent / relative_destination.parts[0]
        staged_subtree.replace(final_subtree)

    return digest


@dataclass(frozen=True)
class FetchedSource:
    """Hold one source response with its retrieval time and HTTP metadata."""

    url: str
    retrieved_at_utc: datetime
    headers: dict[str, str]
    content: bytes


def fetch_source(url: str) -> FetchedSource:
    """Retrieve one non-empty source with bounded connection retries.

    Inputs:
        url: Source URL to retrieve.

    Returns:
        FetchedSource containing response bytes and retrieval metadata.

    Processing flow:
        Source URL
            |
            v
        Send request with the project user agent
            |
            v
        Read response bytes once and timestamp completion
            |
       +----+-------------------+
       |                        |
       v                        v
    Non-empty             Connection/read error
       |                        |
       v                        v
    Capture headers       Wait 1 s, then 2 s
       |                        |
       v                        +----> Retry, at most three attempts
    FetchedSource

    Direct call tree (static source order):
        fetch_source
        +-- range
        +-- Request
        +-- urlopen
        +-- response.read
        +-- datetime.now
        +-- dict
        +-- response.headers.items
        +-- _retry_sleep
        +-- ValueError
        +-- FetchedSource
        `-- AssertionError
    """
    for attempt_index in range(_SOURCE_ATTEMPTS):
        request = Request(url, headers={"User-Agent": _SOURCE_USER_AGENT})
        try:
            with urlopen(request, timeout=_ORBIT_MODEL["download"]["timeout_seconds"]) as response:
                content = response.read()
                retrieved_at_utc = datetime.now(UTC)
                headers = dict(response.headers.items())
        except HTTPError:
            raise
        except (URLError, TimeoutError, ConnectionError, IncompleteRead):
            if attempt_index == _SOURCE_ATTEMPTS - 1:
                raise
            _retry_sleep(attempt_index + 1)
            continue

        if not content:
            raise ValueError("source response content must be non-empty")
        return FetchedSource(
            url=url,
            retrieved_at_utc=retrieved_at_utc,
            headers=headers,
            content=content,
        )

    raise AssertionError("source retrieval loop exhausted without returning")


@dataclass(frozen=True)
class ValidatedOmm:
    """Hold one checked OMM together with its initialized SGP4 satellite."""

    fields: dict[str, str]
    epoch_utc: datetime
    satellite: Satrec


@dataclass(frozen=True)
class CandidatePass:
    """Hold one complete AOS-to-LOS pass on the integer UTC sample grid."""

    aos_utc: datetime
    los_utc: datetime
    samples: tuple[GeometrySample, ...]
    tca_utc: datetime
    peak_elevation_deg: float


@dataclass(frozen=True)
class SelectedPass:
    """Pair one target peak elevation with its distinct candidate pass."""

    target_peak_elevation_deg: float
    candidate: CandidatePass


@dataclass(frozen=True)
class QuantizedSample:
    """Hold one geometry sample as frame integers and external RF settings."""

    trace_time_ms: int
    position_x_m: int
    position_y_m: int
    position_z_m: int
    velocity_x_mmps: int
    velocity_y_mmps: int
    velocity_z_mmps: int
    slant_range_m: int
    range_rate_mmps: int
    doppler_millihz: int
    mission_state: int
    workload: int
    trace_sample_id: int
    doppler_steps: int
    reg_frf_word: int
    programmed_doppler_hz: float
    quantization_error_hz: float

    def to_mission_record(self) -> MissionRecord:
        """Return the fields carried by the benchmark's 50-byte record.

        Inputs:
            self: Stored sample fields or accumulated pass state.

        Returns:
            MissionRecord containing the quantized fields for the 50-byte payload.

        Processing flow:
            Quantized sample fields -> MissionRecord field mapping -> payload value object

        Direct call tree (static source order):
            to_mission_record
            `-- MissionRecord
        """
        return MissionRecord(
            trace_time_ms=self.trace_time_ms,
            position_x_m=self.position_x_m,
            position_y_m=self.position_y_m,
            position_z_m=self.position_z_m,
            velocity_x_mmps=self.velocity_x_mmps,
            velocity_y_mmps=self.velocity_y_mmps,
            velocity_z_mmps=self.velocity_z_mmps,
            slant_range_m=self.slant_range_m,
            range_rate_mmps=self.range_rate_mmps,
            doppler_millihz=self.doppler_millihz,
            mission_state=self.mission_state,
            workload=self.workload,
            trace_sample_id=self.trace_sample_id,
        )


@dataclass(frozen=True)
class GeneratedDataset:
    """Describe the files and selections produced by one dataset generation."""

    dataset_directory: Path
    search_start_utc: datetime
    search_end_utc: datetime
    candidate_count: int
    selected_passes: tuple[SelectedPass, ...]
    passes_path: Path
    samples_path: Path
    provenance_path: Path
    mission_records_path: Path
    orbit_manifest_path: Path
    sample_count: int
    lookback_days: int


@dataclass(frozen=True)
class PastPassSelection:
    """Describe the first sufficient whole-day historical search window."""

    search_start_utc: datetime
    search_end_utc: datetime
    lookback_days: int
    candidates: tuple[CandidatePass, ...]
    selected_passes: tuple[SelectedPass, ...]


def quantize_sample(
    sample: GeometrySample,
    *,
    trace_time_ms: int,
    trace_sample_id: int,
) -> QuantizedSample:
    """Convert one floating-point geometry sample into deterministic integers.

    Inputs:
        sample: Physical geometry sample to quantize.
        trace_time_ms: Trace timestamp in milliseconds.
        trace_sample_id: Global sample identifier in the frozen trace.

    Returns:
        QuantizedSample with deterministic integer telemetry and RF fields.

    Processing flow:
        Geometry sample + trace identifiers
                       |
                       v
              Validate unsigned fields
                       |
                       v
        Quantize SI values with one tie rule
                       |
                       v
             Validate record widths
                       |
                       v
        Combine frame fields and RF settings
                       |
                       v
                QuantizedSample

    Direct call tree (static source order):
        quantize_sample
        +-- ValueError
        +-- round_half_away_from_zero
        +-- quantize_sx1278_doppler
        `-- QuantizedSample
    """
    if not 0 <= trace_time_ms <= 0xFFFF_FFFF:
        raise ValueError("trace_time_ms must fit in uint32")
    if not 0 <= trace_sample_id <= 0xFFFF:
        raise ValueError("trace_sample_id must fit in uint16")
    if sample.slant_range_m < 0.0:
        raise ValueError("slant_range_m must be non-negative")

    position_x_m = round_half_away_from_zero(sample.position_ecef_m[0])
    position_y_m = round_half_away_from_zero(sample.position_ecef_m[1])
    position_z_m = round_half_away_from_zero(sample.position_ecef_m[2])
    velocity_x_mmps = round_half_away_from_zero(
        sample.velocity_ecef_mps[0] * 1000.0
    )
    velocity_y_mmps = round_half_away_from_zero(
        sample.velocity_ecef_mps[1] * 1000.0
    )
    velocity_z_mmps = round_half_away_from_zero(
        sample.velocity_ecef_mps[2] * 1000.0
    )
    slant_range_m = round_half_away_from_zero(sample.slant_range_m)
    range_rate_mmps = round_half_away_from_zero(
        sample.range_rate_mps * 1_000.0
    )
    doppler_millihz = round_half_away_from_zero(sample.doppler_hz * 1_000.0)

    signed_fields = (
        position_x_m,
        position_y_m,
        position_z_m,
        velocity_x_mmps,
        velocity_y_mmps,
        velocity_z_mmps,
        range_rate_mmps,
        doppler_millihz,
    )
    for value in signed_fields:
        if value < _INT32_MIN or value > _INT32_MAX:
            raise ValueError(
                "quantized signed mission-record field must fit in int32"
            )
    if slant_range_m > 0xFFFF_FFFF:
        raise ValueError("slant_range_m must fit in uint32")

    tuning = quantize_sx1278_doppler(sample.doppler_hz)
    return QuantizedSample(
        trace_time_ms=trace_time_ms,
        position_x_m=position_x_m,
        position_y_m=position_y_m,
        position_z_m=position_z_m,
        velocity_x_mmps=velocity_x_mmps,
        velocity_y_mmps=velocity_y_mmps,
        velocity_z_mmps=velocity_z_mmps,
        slant_range_m=slant_range_m,
        range_rate_mmps=range_rate_mmps,
        doppler_millihz=doppler_millihz,
        mission_state=0,
        workload=0,
        trace_sample_id=trace_sample_id,
        doppler_steps=tuning.doppler_steps,
        reg_frf_word=tuning.reg_frf_word,
        programmed_doppler_hz=tuning.programmed_doppler_hz,
        quantization_error_hz=tuning.quantization_error_hz,
    )


def _format_utc(timestamp_utc: datetime) -> str:
    """Format a UTC instant using canonical CSV timestamp precision.

    Inputs:
        timestamp_utc: Timezone-aware UTC instant.

    Returns:
        Canonical UTC timestamp text.

    Processing flow:
        UTC timezone validation -> seconds or microseconds -> timestamp ending in Z

    Direct call tree (static source order):
        _format_utc
        +-- timestamp_utc.utcoffset
        +-- timedelta
        +-- ValueError
        +-- timestamp_utc.isoformat
        `-- timestamp_utc.isoformat(...).replace
    """
    if (
        timestamp_utc.tzinfo is None
        or timestamp_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError("CSV timestamps must be timezone-aware UTC")
    timespec = "seconds"
    if timestamp_utc.microsecond != 0:
        timespec = "microseconds"
    return timestamp_utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _format_physical_float(value: float) -> str:
    """Format a physical quantity with twelve digits after the decimal point.

    Inputs:
        value: Candidate field or provenance object to validate.

    Returns:
        Decimal text with exactly twelve fractional digits.

    Processing flow:
        Physical value -> fixed decimal precision -> deterministic CSV text

    Direct call tree (static source order):
        _format_physical_float
        `-- [no direct function calls; local state/return only]
    """
    return f"{value:.12f}"


def _minimum_slant_range(samples: Sequence[GeometrySample]) -> float:
    """Find the shortest station-to-satellite distance among the supplied samples.

    Inputs:
        samples: Ordered geometry relative to the station samples.

    Returns:
        Minimum slant range in metres.

    Processing flow:
        Nonempty geometry samples -> scan slant ranges -> minimum distance

    Direct call tree (static source order):
        _minimum_slant_range
        +-- len
        `-- OrbitDatasetError
    """
    if len(samples) == 0:
        raise OrbitDatasetError("cannot find a range in an empty sample list")
    minimum_value = samples[0].slant_range_m
    for sample in samples[1:]:
        if sample.slant_range_m < minimum_value:
            minimum_value = sample.slant_range_m
    return minimum_value


def _maximum_slant_range(samples: Sequence[GeometrySample]) -> float:
    """Find the longest station-to-satellite distance among the supplied samples.

    Inputs:
        samples: Ordered geometry relative to the station samples.

    Returns:
        Maximum slant range in metres.

    Processing flow:
        Nonempty geometry samples -> scan slant ranges -> maximum distance

    Direct call tree (static source order):
        _maximum_slant_range
        +-- len
        `-- OrbitDatasetError
    """
    if len(samples) == 0:
        raise OrbitDatasetError("cannot find a range in an empty sample list")
    maximum_value = samples[0].slant_range_m
    for sample in samples[1:]:
        if sample.slant_range_m > maximum_value:
            maximum_value = sample.slant_range_m
    return maximum_value


def _sample_with_minimum_slant_range(
    samples: Sequence[GeometrySample],
) -> GeometrySample:
    """Select the sample used to report the time of closest approach.

    Inputs:
        samples: Ordered geometry relative to the station samples.

    Returns:
        Geometry sample at the minimum sampled slant range.

    Processing flow:
        Nonempty pass samples -> compare slant ranges -> first minimum sample

    Direct call tree (static source order):
        _sample_with_minimum_slant_range
        +-- len
        `-- OrbitDatasetError
    """
    if len(samples) == 0:
        raise OrbitDatasetError("cannot find TCA in an empty sample list")
    chosen = samples[0]
    for sample in samples[1:]:
        if sample.slant_range_m < chosen.slant_range_m:
            chosen = sample
    return chosen


def _maximum_elevation(samples: Sequence[GeometrySample]) -> float:
    """Find the highest elevation relative to the station among the supplied samples.

    Inputs:
        samples: Ordered geometry relative to the station samples.

    Returns:
        Maximum sampled elevation in degrees.

    Processing flow:
        Nonempty pass samples -> compare elevation angles -> maximum elevation

    Direct call tree (static source order):
        _maximum_elevation
        +-- len
        `-- OrbitDatasetError
    """
    if len(samples) == 0:
        raise OrbitDatasetError("cannot find a peak in an empty sample list")
    peak = samples[0].elevation_deg
    for sample in samples[1:]:
        if sample.elevation_deg > peak:
            peak = sample.elevation_deg
    return peak


def write_dataset_csvs(
    output_directory: str | Path,
    selected_passes: Sequence[SelectedPass],
    *,
    orbit_epoch_utc: datetime,
) -> tuple[Path, Path]:
    """Write selected passes and samples as deterministic CSV files.

    Inputs:
        output_directory: Destination directory for generated Level 1 artifacts.
        selected_passes: Five selected visible passes and their target elevations.
        orbit_epoch_utc: UTC epoch of the selected orbit elements.

    Returns:
        Paths to passes.csv and samples.csv.

    Processing flow:
        Selected passes -> target-angle ordering -> global sample identifiers
        -> deterministic quantization -> explicit pass and sample CSV schemas.

    Direct call tree (static source order):
        write_dataset_csvs
        +-- orbit_epoch_utc.utcoffset
        +-- timedelta
        +-- ValueError
        +-- list
        +-- ordered_pass_list.sort
        +-- tuple
        +-- len
        +-- Path
        +-- output_path.mkdir
        +-- passes_path.open
        +-- csv.DictWriter
        +-- pass_writer.writeheader
        +-- enumerate
        +-- pass_writer.writerow
        +-- _format_physical_float
        +-- abs
        +-- _format_utc
        +-- <BinOp expression>.total_seconds
        +-- _minimum_slant_range
        +-- _maximum_slant_range
        +-- samples_path.open
        +-- sample_writer.writeheader
        +-- quantize_sample
        `-- sample_writer.writerow
    """
    if (
        orbit_epoch_utc.tzinfo is None
        or orbit_epoch_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError("orbit_epoch_utc must be timezone-aware UTC")

    ordered_pass_list = list(selected_passes)
    ordered_pass_list.sort(key=_selected_target_key)
    ordered_passes = tuple(ordered_pass_list)
    total_sample_count = 0
    for selected in ordered_passes:
        total_sample_count += len(selected.candidate.samples)
    if total_sample_count > 0x1_0000:
        raise ValueError("total sample count must fit in uint16 identifiers")

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    passes_path = output_path / "passes.csv"
    samples_path = output_path / "samples.csv"

    with passes_path.open("w", encoding="utf-8", newline="") as pass_file:
        pass_writer = csv.DictWriter(
            pass_file,
            fieldnames=PASS_CSV_FIELDS,
            lineterminator="\n",
        )
        pass_writer.writeheader()
        for pass_id, selected in enumerate(ordered_passes):
            candidate = selected.candidate
            if not candidate.samples:
                raise ValueError("selected passes must contain visible samples")
            pass_writer.writerow(
                {
                    "pass_id": pass_id,
                    "target_peak_elevation_deg": _format_physical_float(
                        selected.target_peak_elevation_deg
                    ),
                    "actual_peak_elevation_deg": _format_physical_float(
                        candidate.peak_elevation_deg
                    ),
                    "peak_error_deg": _format_physical_float(
                        abs(
                            candidate.peak_elevation_deg
                            - selected.target_peak_elevation_deg
                        )
                    ),
                    "aos_utc": _format_utc(candidate.aos_utc),
                    "first_sample_utc": _format_utc(
                        candidate.samples[0].timestamp_utc
                    ),
                    "tca_utc": _format_utc(candidate.tca_utc),
                    "last_sample_utc": _format_utc(
                        candidate.samples[-1].timestamp_utc
                    ),
                    "los_utc": _format_utc(candidate.los_utc),
                    "duration_seconds": _format_physical_float(
                        (candidate.los_utc - candidate.aos_utc).total_seconds()
                    ),
                    "sample_count": len(candidate.samples),
                    "min_slant_range_m": _format_physical_float(
                        _minimum_slant_range(candidate.samples)
                    ),
                    "max_slant_range_m": _format_physical_float(
                        _maximum_slant_range(candidate.samples)
                    ),
                    "start_doppler_hz": _format_physical_float(
                        candidate.samples[0].doppler_hz
                    ),
                    "end_doppler_hz": _format_physical_float(
                        candidate.samples[-1].doppler_hz
                    ),
                }
            )

    trace_sample_id = 0
    with samples_path.open("w", encoding="utf-8", newline="") as sample_file:
        sample_writer = csv.DictWriter(
            sample_file,
            fieldnames=SAMPLE_CSV_FIELDS,
            lineterminator="\n",
        )
        sample_writer.writeheader()
        for pass_id, selected in enumerate(ordered_passes):
            candidate = selected.candidate
            for pass_sample_index, sample in enumerate(candidate.samples):
                trace_time_ms = pass_sample_index * 1_000
                quantized = quantize_sample(
                    sample,
                    trace_time_ms=trace_time_ms,
                    trace_sample_id=trace_sample_id,
                )
                position_x, position_y, position_z = sample.position_ecef_m
                velocity_x, velocity_y, velocity_z = sample.velocity_ecef_mps
                sample_writer.writerow(
                    {
                        "pass_id": pass_id,
                        "target_peak_elevation_deg": _format_physical_float(
                            selected.target_peak_elevation_deg
                        ),
                        "actual_peak_elevation_deg": _format_physical_float(
                            candidate.peak_elevation_deg
                        ),
                        "pass_sample_index": pass_sample_index,
                        "timestamp_utc": _format_utc(sample.timestamp_utc),
                        "orbit_age_seconds": _format_physical_float(
                            (sample.timestamp_utc - orbit_epoch_utc).total_seconds()
                        ),
                        "trace_time_ms": quantized.trace_time_ms,
                        "trace_sample_id": quantized.trace_sample_id,
                        "position_x_ecef_m_float": _format_physical_float(
                            position_x
                        ),
                        "position_y_ecef_m_float": _format_physical_float(
                            position_y
                        ),
                        "position_z_ecef_m_float": _format_physical_float(
                            position_z
                        ),
                        "velocity_x_ecef_mps_float": _format_physical_float(
                            velocity_x
                        ),
                        "velocity_y_ecef_mps_float": _format_physical_float(
                            velocity_y
                        ),
                        "velocity_z_ecef_mps_float": _format_physical_float(
                            velocity_z
                        ),
                        "azimuth_deg": _format_physical_float(sample.azimuth_deg),
                        "elevation_deg": _format_physical_float(
                            sample.elevation_deg
                        ),
                        "slant_range_m_float": _format_physical_float(
                            sample.slant_range_m
                        ),
                        "range_rate_mps": _format_physical_float(
                            sample.range_rate_mps
                        ),
                        "doppler_hz": _format_physical_float(sample.doppler_hz),
                        "doppler_steps": quantized.doppler_steps,
                        "reg_frf_word": quantized.reg_frf_word,
                        "programmed_doppler_hz": _format_physical_float(
                            quantized.programmed_doppler_hz
                        ),
                        "quantization_error_hz": _format_physical_float(
                            quantized.quantization_error_hz
                        ),
                        "position_x_m": quantized.position_x_m,
                        "position_y_m": quantized.position_y_m,
                        "position_z_m": quantized.position_z_m,
                        "velocity_x_mmps": quantized.velocity_x_mmps,
                        "velocity_y_mmps": quantized.velocity_y_mmps,
                        "velocity_z_mmps": quantized.velocity_z_mmps,
                        "slant_range_m": quantized.slant_range_m,
                        "range_rate_mmps": quantized.range_rate_mmps,
                        "doppler_millihz": quantized.doppler_millihz,
                        "mission_state": quantized.mission_state,
                        "workload": quantized.workload,
                    }
                )
                trace_sample_id += 1

    return passes_path, samples_path


def _row_integer(row: Mapping[str, object], field_name: str) -> int:
    """Read a sample field as an integer with canonical decimal syntax.

    Inputs:
        row: Sample CSV fields before conversion to typed values.
        field_name: Name of the required CSV field.

    Returns:
        Integer field value; malformed input raises OrbitDatasetError.

    Processing flow:
        Required field -> reject Boolean -> integer or canonical decimal text -> value

    Direct call tree (static source order):
        _row_integer
        +-- OrbitDatasetError
        +-- isinstance
        `-- parse_decimal
    """
    if field_name not in row:
        raise OrbitDatasetError(f"sample row is missing {field_name}")
    value = row[field_name]
    if isinstance(value, bool):
        raise OrbitDatasetError(f"{field_name} must be a canonical integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return parse_decimal(value)
        except ValueError as error:
            raise OrbitDatasetError(
                f"{field_name} must be a canonical integer"
            ) from error
    raise OrbitDatasetError(f"{field_name} must be a canonical integer")


def _row_float(row: Mapping[str, object], field_name: str) -> float:
    """Read a sample field as a finite physical quantity.

    Inputs:
        row: Sample CSV fields before conversion to typed values.
        field_name: Name of the required CSV field.

    Returns:
        Finite floating point field value.

    Processing flow:
        Required field -> reject Boolean/empty/padded text -> numeric conversion -> finite check

    Direct call tree (static source order):
        _row_float
        +-- OrbitDatasetError
        +-- isinstance
        +-- value.strip
        +-- float
        `-- math.isfinite
    """
    if field_name not in row:
        raise OrbitDatasetError(f"sample row is missing {field_name}")
    value = row[field_name]
    if isinstance(value, bool):
        raise OrbitDatasetError(f"{field_name} must be a finite number")
    if isinstance(value, str):
        if value == "" or value != value.strip():
            raise OrbitDatasetError(f"{field_name} must be a finite number")
    if not isinstance(value, (str, Buffer, SupportsFloat, SupportsIndex)):
        raise OrbitDatasetError(f"{field_name} must be a finite number")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise OrbitDatasetError(f"{field_name} must be a finite number") from error
    if not math.isfinite(converted):
        raise OrbitDatasetError(f"{field_name} must be a finite number")
    return converted


def quantized_row_to_mission_record(
    row: Mapping[str, object],
) -> MissionRecord:
    """Convert one canonical samples.csv row to its 50-byte record fields.

    Inputs:
        row: Sample CSV fields before conversion to typed values.

    Returns:
        MissionRecord fields corresponding to one sample row.

    Processing flow:
        Sample row -> canonical integer parsing -> named mission fields ->
        MissionRecord ready for the shared packer.

    Direct call tree (static source order):
        quantized_row_to_mission_record
        +-- MissionRecord
        `-- _row_integer
    """
    return MissionRecord(
        trace_time_ms=_row_integer(row, "trace_time_ms"),
        position_x_m=_row_integer(row, "position_x_m"),
        position_y_m=_row_integer(row, "position_y_m"),
        position_z_m=_row_integer(row, "position_z_m"),
        velocity_x_mmps=_row_integer(row, "velocity_x_mmps"),
        velocity_y_mmps=_row_integer(row, "velocity_y_mmps"),
        velocity_z_mmps=_row_integer(row, "velocity_z_mmps"),
        slant_range_m=_row_integer(row, "slant_range_m"),
        range_rate_mmps=_row_integer(row, "range_rate_mmps"),
        doppler_millihz=_row_integer(row, "doppler_millihz"),
        mission_state=_row_integer(row, "mission_state"),
        workload=_row_integer(row, "workload"),
        trace_sample_id=_row_integer(row, "trace_sample_id"),
    )


def read_sample_rows(path: str | Path) -> tuple[dict[str, str], ...]:
    """Read samples.csv only when its UTF-8 header and LF bytes are exact.

    Inputs:
        path: Source or artifact path used by this operation.

    Returns:
        Tuple of complete sample dictionaries.

    Processing flow:
        CSV bytes -> UTF-8 and LF validation -> exact header check -> complete,
        nonblank string rows -> immutable row tuple.

    Direct call tree (static source order):
        read_sample_rows
        +-- Path
        +-- sample_path.read_bytes
        +-- raw.endswith
        +-- OrbitDatasetError
        +-- raw.decode
        +-- sample_path.open
        +-- csv.DictReader
        +-- tuple
        +-- row.get
        `-- rows.append
    """
    sample_path = Path(path)
    raw = sample_path.read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise OrbitDatasetError("samples.csv must use LF line endings")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OrbitDatasetError("samples.csv must be UTF-8") from error

    rows: list[dict[str, str]] = []
    with sample_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        if fieldnames is None or tuple(fieldnames) != SAMPLE_CSV_FIELDS:
            raise OrbitDatasetError("samples.csv columns changed")
        for row in reader:
            if None in row:
                raise OrbitDatasetError("samples.csv row has extra columns")
            checked: dict[str, str] = {}
            for field_name in SAMPLE_CSV_FIELDS:
                value = row.get(field_name)
                if value is None or value == "":
                    raise OrbitDatasetError(
                        f"samples.csv row is missing {field_name}"
                    )
                checked[field_name] = value
            rows.append(checked)
    return tuple(rows)


def write_mission_record_stream(
    path: str | Path,
    sample_rows: Sequence[Mapping[str, object]],
) -> int:
    """Write one exact 50-byte mission record per samples.csv row.

    Inputs:
        path: New destination for the stream of 50-byte mission records.
        sample_rows: Ordered quantized sample CSV fields.

    Returns:
        Number of 50-byte mission records written to the binary artifact.

    Processing flow:
        Ordered sample rows -> enforce at most 65,536 global contiguous IDs ->
        shared 50-byte packer -> exclusive durable binary artifact -> row count.

    Direct call tree (static source order):
        write_mission_record_stream
        +-- len
        +-- OrbitDatasetError
        +-- bytearray
        +-- _row_integer
        +-- quantized_row_to_mission_record
        +-- content.extend
        +-- pack_mission_record
        +-- write_bytes_exclusive
        `-- bytes
    """
    if len(sample_rows) > 65536:
        raise OrbitDatasetError(
            "Level 1 dataset exceeds 65,536 distinct TraceSampleId values"
        )
    content = bytearray()
    expected_trace_id = 0
    for row in sample_rows:
        trace_id = _row_integer(row, "trace_sample_id")
        if trace_id != expected_trace_id:
            raise OrbitDatasetError(
                "TraceSampleId must be dataset-global and contiguous"
            )
        record = quantized_row_to_mission_record(row)
        content.extend(pack_mission_record(record))
        expected_trace_id += 1
    write_bytes_exclusive(path, bytes(content))
    return len(sample_rows)


def orbit_schedule_hash_row(
    trace_sample_id: int,
    pass_sample_index: int,
    requested_cfo_hz: float,
    programmed_cfo_hz: float,
    reg_frf_word: int,
    mission_record: bytes,
) -> bytes:
    """Pack one dynamic schedule row for deterministic SHA-256 hashing.

    Inputs:
        trace_sample_id: Global sample identifier in the frozen trace.
        pass_sample_index: Sample position counted from zero within the pass.
        requested_cfo_hz: Requested carrier-frequency offset in hertz.
        programmed_cfo_hz: Offset represented by the programmed radio frequency word, in hertz.
        reg_frf_word: SX1278 synthesizer register word for this sample.
        mission_record: Exact 50-byte payload record for the schedule row.

    Returns:
        Packed bytes binding the sample identity, RF settings, and mission record.

    Processing flow:
        IDs + requested/programmed CFO + FRF word + mission bytes -> boundary
        validation -> fixed big-endian schedule-hash row.

    Direct call tree (static source order):
        orbit_schedule_hash_row
        +-- len
        +-- OrbitDatasetError
        +-- math.isfinite
        `-- ORBIT_SCHEDULE_HASH_ROW.pack
    """
    if len(mission_record) != 50:
        raise OrbitDatasetError("mission record must be exactly 50 bytes")
    if not math.isfinite(requested_cfo_hz):
        raise OrbitDatasetError("requested CFO must be finite")
    if not math.isfinite(programmed_cfo_hz):
        raise OrbitDatasetError("programmed CFO must be finite")
    try:
        return ORBIT_SCHEDULE_HASH_ROW.pack(
            trace_sample_id,
            pass_sample_index,
            requested_cfo_hz,
            programmed_cfo_hz,
            reg_frf_word,
            mission_record,
        )
    except struct.error as error:
        raise OrbitDatasetError(f"schedule hash field out of range: {error}") from error


def _selected_target_key(selected: SelectedPass) -> float:
    """Return the target elevation used to order selected passes.

    Inputs:
        selected: Pass paired with its target peak elevation.

    Returns:
        Target peak elevation in degrees.

    Processing flow:
        Selected pass -> target elevation sort key

    Direct call tree (static source order):
        _selected_target_key
        `-- [no direct function calls; local state/return only]
    """
    return selected.target_peak_elevation_deg


def build_pass_schedule_manifest_entries(
    mission_records_path: str | Path,
    selected_passes: Sequence[SelectedPass],
    sample_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Build five manifest entries from dynamic per-pass sample lengths.

    Inputs:
        mission_records_path: Binary stream of consecutive 50-byte mission records.
        selected_passes: Five selected visible passes and their target elevations.
        sample_rows: Ordered quantized sample CSV fields.

    Returns:
        Five schedule descriptor dictionaries with offsets, counts, and digests.

    Processing flow:
        Record stream + selected passes + CSV rows -> validate five ordered pass
        groups and both ID domains -> hash each exact dynamic schedule -> entries.

    Direct call tree (static source order):
        build_pass_schedule_manifest_entries
        +-- len
        +-- OrbitDatasetError
        +-- Path
        +-- Path(...).read_bytes
        +-- list
        +-- ordered.sort
        +-- _row_integer
        +-- rows.append
        +-- float
        +-- math.isfinite
        +-- bytearray
        +-- _row_float
        +-- orbit_schedule_hash_row
        +-- schedule_bytes.extend
        +-- trace_ids.append
        +-- sha256_bytes
        +-- bytes
        `-- entries.append
    """
    if len(selected_passes) != 5:
        raise OrbitDatasetError("orbit manifest requires five selected passes")
    records = Path(mission_records_path).read_bytes()
    if len(records) != 50 * len(sample_rows):
        raise OrbitDatasetError("mission record stream length is inconsistent")

    ordered = list(selected_passes)
    ordered.sort(key=_selected_target_key)
    entries: list[dict[str, object]] = []
    global_cursor = 0
    pass_id = 0
    for selected in ordered:
        rows: list[Mapping[str, object]] = []
        for row in sample_rows:
            row_pass_id = _row_integer(row, "pass_id")
            if row_pass_id == pass_id:
                rows.append(row)
        count = len(rows)
        if count == 0:
            raise OrbitDatasetError("selected passes must not be empty")
        target_peak = float(selected.target_peak_elevation_deg)
        actual_peak = float(selected.candidate.peak_elevation_deg)
        if not math.isfinite(target_peak) or not 10.0 <= target_peak <= 90.0:
            raise OrbitDatasetError("dynamic peak-elevation anchor is invalid")
        if not math.isfinite(actual_peak) or not 10.0 <= actual_peak <= 90.0:
            raise OrbitDatasetError("actual peak elevation is invalid")

        schedule_bytes = bytearray()
        local_index = 0
        trace_ids: list[int] = []
        for row in rows:
            parsed_local_index = _row_integer(row, "pass_sample_index")
            trace_id = _row_integer(row, "trace_sample_id")
            if parsed_local_index != local_index:
                raise OrbitDatasetError("PassSampleIndex must be pass-local")
            if trace_id != global_cursor + local_index:
                raise OrbitDatasetError("TraceSampleId must be dataset-global")
            elevation = _row_float(row, "elevation_deg")
            if elevation < 10.0:
                raise OrbitDatasetError("saved orbit sample is below 10 degrees")
            record_start = trace_id * 50
            record_end = record_start + 50
            mission_record = records[record_start:record_end]
            requested_cfo_hz = _row_float(row, "doppler_hz")
            programmed_cfo_hz = _row_float(row, "programmed_doppler_hz")
            reg_frf_word = _row_integer(row, "reg_frf_word")
            packed_row = orbit_schedule_hash_row(
                trace_id,
                local_index,
                requested_cfo_hz,
                programmed_cfo_hz,
                reg_frf_word,
                mission_record,
            )
            schedule_bytes.extend(packed_row)
            trace_ids.append(trace_id)
            local_index += 1

        entry: dict[str, object] = {
            "PassId": pass_id,
            "PassLabel": f"P{pass_id + 1}",
            # This is a dynamic quantile anchor derived from this candidate set.
            # It is not a preselected production target elevation.
            "TargetPeakElevationDeg": target_peak,
            "ActualPeakElevationDeg": actual_peak,
            "SampleCount": count,
            "FirstTraceSampleId": trace_ids[0],
            "LastTraceSampleId": trace_ids[-1],
            "ByteOffset": global_cursor * 50,
            "ByteCount": count * 50,
            "ScheduleSha256": sha256_bytes(bytes(schedule_bytes)),
        }
        entries.append(entry)
        global_cursor += count
        pass_id += 1

    if global_cursor != len(sample_rows):
        raise OrbitDatasetError("sample rows contain an unknown pass")
    return entries


def write_orbit_manifest(
    output_directory: str | Path,
    *,
    dataset_id: str,
    retrieval_utc: datetime,
    selected_passes: Sequence[SelectedPass],
    sample_rows: Sequence[Mapping[str, object]],
) -> Path:
    """Write the canonical Level 1 artifact and dynamic-schedule index.

    Inputs:
        output_directory: Destination directory for generated Level 1 artifacts.
        dataset_id: Identity recorded in the orbit manifest and publication directory.
        retrieval_utc: UTC retrieval instant used to end the historical search.
        selected_passes: Five selected visible passes and their target elevations.
        sample_rows: Ordered quantized sample CSV fields.

    Returns:
        Path to the canonical orbit manifest.

    Processing flow:
        Level 1 artifacts + sample rows -> five dynamic schedule entries -> raw
        artifact byte hashes -> canonical exclusive orbit_manifest.json.

    Direct call tree (static source order):
        write_orbit_manifest
        +-- isinstance
        +-- dataset_id.strip
        +-- OrbitDatasetError
        +-- Path
        +-- build_pass_schedule_manifest_entries
        +-- artifact_path.is_file
        +-- artifact_path.stat
        +-- sha256_file
        +-- format_rfc3339_utc
        +-- len
        +-- write_bytes_exclusive
        `-- canonical_json_bytes
    """
    if not isinstance(dataset_id, str) or dataset_id.strip() == "":
        raise OrbitDatasetError("dataset_id must be non-empty text")
    output_path = Path(output_directory)
    mission_records_path = output_path / "mission_records.bin"
    schedules = build_pass_schedule_manifest_entries(
        mission_records_path,
        selected_passes,
        sample_rows,
    )
    artifacts: dict[str, dict[str, object]] = {}
    artifact_names = (
        "provenance.json",
        "passes.csv",
        "samples.csv",
        "mission_records.bin",
    )
    for artifact_name in artifact_names:
        artifact_path = output_path / artifact_name
        if not artifact_path.is_file():
            raise OrbitDatasetError(f"missing Level 1 artifact: {artifact_name}")
        artifacts[artifact_name] = {
            "ByteCount": artifact_path.stat().st_size,
            "Sha256": sha256_file(artifact_path),
        }
    manifest: dict[str, object] = {
        "SchemaVersion": 1,
        "DatasetId": dataset_id,
        "RetrievalUtc": format_rfc3339_utc(retrieval_utc),
        "PassCount": len(schedules),
        "SampleCount": len(sample_rows),
        "PassSchedules": schedules,
        "Artifacts": artifacts,
    }
    target = output_path / "orbit_manifest.json"
    write_bytes_exclusive(target, canonical_json_bytes(manifest))
    return target


def _source_provenance(filename: str, source: FetchedSource) -> dict[str, object]:
    """Describe the original source bytes and the circumstances of retrieval.

    Inputs:
        filename: Exact source or artifact filename.
        source: Retrieved source bytes, timestamp, URL, and response headers.

    Returns:
        Source filename, URL, retrieval time, headers, size, and SHA-256.

    Processing flow:
        Source bytes and HTTP metadata -> byte count and digest -> provenance record

    Direct call tree (static source order):
        _source_provenance
        +-- len
        +-- dict
        +-- _format_utc
        `-- sha256_bytes
    """
    return {
        "byte_count": len(source.content),
        "filename": filename,
        "http_headers": dict(source.headers),
        "retrieved_at_utc": _format_utc(source.retrieved_at_utc),
        "sha256": sha256_bytes(source.content),
        "url": source.url,
    }


def _output_provenance(path: Path) -> dict[str, object]:
    """Describe the exact bytes of one generated dataset artifact.

    Inputs:
        path: Source or artifact path used by this operation.

    Returns:
        Dictionary containing byte_count and sha256.

    Processing flow:
        Artifact path -> raw bytes -> byte count and SHA-256

    Direct call tree (static source order):
        _output_provenance
        +-- path.read_bytes
        +-- len
        `-- sha256_bytes
    """
    content = path.read_bytes()
    return {
        "byte_count": len(content),
        "sha256": sha256_bytes(content),
    }


def write_dataset_provenance(
    output_directory: str | Path,
    *,
    omm_source: FetchedSource,
    iers_source: FetchedSource,
    validated_omm: ValidatedOmm,
    search_start_utc: datetime,
    search_end_utc: datetime,
    passes_path: str | Path,
    samples_path: str | Path,
    generator_git_commit: str,
    chunk_days: int,
    station: GroundStation = LINZ_GROUND_STATION,
    mission_records_path: str | Path | None = None,
    selected_passes: Sequence[SelectedPass] = (),
    lookback_days: int | None = None,
) -> Path:
    """Write deterministic provenance after hashing generated Level 1 files.

    Inputs:
        output_directory: Destination directory for generated Level 1 artifacts.
        omm_source: Frozen OMM XML response and its retrieval metadata.
        iers_source: Frozen IERS-A response and its retrieval metadata.
        validated_omm: Parsed orbital elements and the initialized SGP4 model.
        search_start_utc: Inclusive beginning of the propagation search, or None for adaptive search.
        search_end_utc: Exclusive end of the propagation search, or None for adaptive search.
        passes_path: Generated pass-summary CSV path.
        samples_path: Generated sample CSV path.
        generator_git_commit: Optional Git commit text recorded as generator metadata.
        chunk_days: Maximum propagation chunk length in days.
        station: Ground station geodetic coordinates and visibility mask.
        mission_records_path: Binary stream of consecutive 50-byte mission records.
        selected_passes: Five selected visible passes and their target elevations.
        lookback_days: Recorded historical search length in days, when supplied.

    Returns:
        Path to provenance.json.

    Processing flow:
        Frozen sources + validated orbit + generation parameters -> raw output
        hashes -> actual search/selection facts -> sorted JSON record.

    Direct call tree (static source order):
        write_dataset_provenance
        +-- len
        +-- ValueError
        +-- Path
        +-- _output_provenance
        +-- <BinOp expression>.total_seconds
        +-- int
        +-- anchors.append
        +-- float
        +-- actual_peaks.append
        +-- importlib.metadata.version
        +-- platform.python_version
        +-- _format_utc
        +-- dict
        +-- _source_provenance
        +-- provenance_path.parent.mkdir
        +-- provenance_path.open
        +-- output.write
        `-- json.dumps
    """
    invalid_git_commit = generator_git_commit != "" and len(generator_git_commit) != 40
    for character in generator_git_commit:
        if character not in "0123456789abcdef":
            invalid_git_commit = True
    if invalid_git_commit:
        raise ValueError("generator_git_commit must be empty or a full lowercase Git SHA")

    passes_file = Path(passes_path)
    samples_file = Path(samples_path)
    outputs: dict[str, object] = {
        "passes.csv": _output_provenance(passes_file),
        "samples.csv": _output_provenance(samples_file),
    }
    if mission_records_path is not None:
        mission_records_file = Path(mission_records_path)
        outputs["mission_records.bin"] = _output_provenance(mission_records_file)

    if lookback_days is None:
        duration_seconds = (search_end_utc - search_start_utc).total_seconds()
        lookback_days = int(duration_seconds // 86400)
    anchors: list[float] = []
    actual_peaks: list[float] = []
    for selected in selected_passes:
        anchors.append(float(selected.target_peak_elevation_deg))
        actual_peaks.append(float(selected.candidate.peak_elevation_deg))
    provenance = {
        "generator": {
            "git_commit": generator_git_commit,
            "gravity_model": "WGS-72",
            "schema_version": 1,
            "software_versions": {
                "astropy": importlib.metadata.version("astropy"),
                "numpy": np.__version__,
                "python": platform.python_version(),
                "sgp4": importlib.metadata.version("sgp4"),
            },
        },
        "orbit": {
            "epoch_age_seconds": (
                omm_source.retrieved_at_utc - validated_omm.epoch_utc
            ).total_seconds(),
            "epoch_utc": _format_utc(validated_omm.epoch_utc),
            "omm_fields": dict(validated_omm.fields),
        },
        "outputs": outputs,
        "rf": {
            "nominal_carrier_hz": NOMINAL_CARRIER_HZ,
            "speed_of_light_mps": SPEED_OF_LIGHT_MPS,
            "sx1278_fstep_hz": SX1278_FSTEP_HZ,
            "sx1278_nominal_frf_word": SX1278_NOMINAL_FRF_WORD,
        },
        "schema_version": 1,
        "search": {
            "actual_peak_elevations_deg": actual_peaks,
            "chunk_days": chunk_days,
            "dynamic_selection_anchors_deg": anchors,
            "end_utc": _format_utc(search_end_utc),
            "lookback_days": lookback_days,
            "selection_rule": (
                "five distinct complete passes spanning the actual candidate "
                "low-to-high peak-elevation range; dynamic anchors are derived "
                "from that range and ties use the newer AOS tuple"
            ),
            "start_utc": _format_utc(search_start_utc),
            "step_seconds": 1,
        },
        "sources": {
            "iers_a": _source_provenance(
                "source/iers_a_finals2000A.all",
                iers_source,
            ),
            "omm": _source_provenance(
                "source/gomx1_39430.omm.xml",
                omm_source,
            ),
        },
        "station": {
            "elevation_mask_deg": station.elevation_mask_deg,
            "height_m": station.height_m,
            "latitude_deg": station.latitude_deg,
            "longitude_deg": station.longitude_deg,
            "reference_frame": "WGS-84 geodetic / ITRS ECEF",
        },
    }

    provenance_path = Path(output_directory) / "provenance.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    with provenance_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(provenance, indent=2, sort_keys=True))
        output.write("\n")
    return provenance_path


def load_validated_omm(
    path: str | Path,
    retrieved_at_utc: datetime,
) -> ValidatedOmm:
    """Parse one GOMX-1 OMM and initialize its validated SGP4 model.

    References:
        CCSDS 502.0-B-3, ``Orbit Data Messages``, Issue 3 (April 2023),
        sections 4.1.1-4.1.2 and 4.2, plus section 8.9.14 for the OMM/XML
        logical-block tags.  The ``python-sgp4`` 2.27 ``sgp4.omm.initialize``
        interface initializes OMM mean elements with explicit WGS-72 gravity
        constants.
    Inputs:
        path: Source or artifact path used by this operation.
        retrieved_at_utc: Source retrieval UTC used to validate the OMM epoch.

    Returns:
        ValidatedOmm containing checked GOMX-1 elements and its SGP4 model.

    Processing flow:
        Frozen OMM/XML file + retrieval timestamp
                         |
                         v
               Parse exactly one segment
                         |
                         v
          Validate GOMX-1 and SGP4 metadata
                         |
                         v
             Parse epoch and enforce 72 h age
                         |
                         v
          Initialize and range-check WGS-72 Satrec
                         |
                         v
                    ValidatedOmm

    Direct call tree (static source order):
        load_validated_omm
        +-- retrieved_at_utc.utcoffset
        +-- timedelta
        +-- ValueError
        +-- Path
        +-- Path(...).open
        +-- list
        +-- omm.parse_xml
        +-- len
        +-- dict
        +-- _EXPECTED_OMM_FIELDS.items
        +-- fields.get
        +-- datetime.strptime
        +-- datetime.strptime(...).replace
        +-- OrbitDatasetError
        +-- Satrec
        +-- omm.initialize
        +-- check_satrec
        `-- ValidatedOmm
    """
    if (
        retrieved_at_utc.tzinfo is None
        or retrieved_at_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError("retrieved_at_utc must be timezone-aware UTC")

    with Path(path).open("rb") as source:
        segments = list(omm.parse_xml(source))

    if len(segments) != 1:
        raise ValueError(f"OMM must contain exactly one segment, found {len(segments)}")

    fields = dict(segments[0])
    for name, expected in _EXPECTED_OMM_FIELDS.items():
        actual = fields.get(name)
        if actual != expected:
            raise ValueError(f"{name} must be {expected!r}, received {actual!r}")

    epoch_utc = datetime.strptime(
        fields["EPOCH"],
        "%Y-%m-%dT%H:%M:%S.%f",
    ).replace(tzinfo=UTC)
    # The project-selected 72-hour gate measures source age
    # only.  It does not define the pass window, which is independently
    # anchored at the retrieval cutoff and extends only into the past.
    omm_age = retrieved_at_utc - epoch_utc
    if omm_age < timedelta(0):
        raise OrbitDatasetError(
            "OMM epoch is in the future relative to retrieval UTC"
        )
    if omm_age > MAX_OMM_AGE:
        raise OrbitDatasetError(
            "OMM epoch must be no more than 72 hours before retrieval"
        )

    # TLE-derived SGP4 mean elements use the WGS-72 constants they were fitted with.
    satellite = Satrec()
    omm.initialize(satellite, fields, WGS72)
    check_satrec(satellite)

    return ValidatedOmm(
        fields=fields,
        epoch_utc=epoch_utc,
        satellite=satellite,
    )

def _interpolate_mask_crossing(
    previous: GeometrySample,
    current: GeometrySample,
    elevation_mask_deg: float,
) -> datetime:
    """Estimate the UTC instant at which adjacent samples cross the elevation mask.

    Inputs:
        previous: Geometry sample immediately before the mask crossing.
        current: Next geometry sample in time order.
        elevation_mask_deg: Station elevation threshold in degrees used for acquisition and loss.

    Returns:
        Interpolated crossing timestamp.

    Processing flow:
        Adjacent elevations -> fractional mask position -> interpolation in UTC time

    Direct call tree (static source order):
        _interpolate_mask_crossing
        `-- [no direct function calls; local state/return only]
    """
    fraction = (
        elevation_mask_deg - previous.elevation_deg
    ) / (current.elevation_deg - previous.elevation_deg)
    return previous.timestamp_utc + (
        current.timestamp_utc - previous.timestamp_utc
    ) * fraction

class _CompletePassAccumulator:
    def __init__(self, elevation_mask_deg: float) -> None:
        """Initialize the state needed to accumulate complete visible passes.

        Inputs:
            elevation_mask_deg: Station elevation threshold in degrees used for acquisition and loss.

        Returns:
            None; the accumulator starts without a previous sample.

        Processing flow:
            Elevation mask -> empty crossing history -> empty complete-pass collection

        Direct call tree (static source order):
            __init__
            `-- [no direct function calls; local state/return only]
        """
        self.elevation_mask_deg = elevation_mask_deg
        self.previous: GeometrySample | None = None
        self.visible_samples: list[GeometrySample] | None = None
        self.aos_utc: datetime | None = None
        self.completed_passes: list[CandidatePass] = []

    def consume(self, current: GeometrySample) -> None:
        """Accumulate a visible pass and close it when elevation falls below the mask.

        Inputs:
            current: Next geometry sample in time order.

        Returns:
            None; updates crossing state and the completed-pass collection.

        Processing flow:
            First sample -> rising mask crossing starts pass -> visible samples accumulate
            -> falling crossing sets LOS, closest approach, and peak -> completed pass

        Direct call tree (static source order):
            consume
            +-- _interpolate_mask_crossing
            +-- self.visible_samples.append
            +-- _sample_with_minimum_slant_range
            +-- self.completed_passes.append
            +-- CandidatePass
            +-- tuple
            `-- _maximum_elevation
        """
        previous = self.previous
        if previous is None:
            self.previous = current
            return

        if (
            previous.elevation_deg < self.elevation_mask_deg
            <= current.elevation_deg
        ):
            self.aos_utc = _interpolate_mask_crossing(
                previous,
                current,
                self.elevation_mask_deg,
            )
            self.visible_samples = [current]
            self.previous = current
            return

        if self.visible_samples is not None:
            if current.elevation_deg >= self.elevation_mask_deg:
                self.visible_samples.append(current)

            if (
                previous.elevation_deg >= self.elevation_mask_deg
                > current.elevation_deg
            ):
                assert self.aos_utc is not None
                tca_sample = _sample_with_minimum_slant_range(self.visible_samples)
                self.completed_passes.append(
                    CandidatePass(
                        aos_utc=self.aos_utc,
                        los_utc=_interpolate_mask_crossing(
                            previous,
                            current,
                            self.elevation_mask_deg,
                        ),
                        samples=tuple(self.visible_samples),
                        tca_utc=tca_sample.timestamp_utc,
                        peak_elevation_deg=_maximum_elevation(
                            self.visible_samples
                        ),
                    )
                )
                self.visible_samples = None
                self.aos_utc = None

        self.previous = current

    def finish(self) -> tuple[CandidatePass, ...]:
        """Return the passes that have both acquisition and loss boundaries.

        Inputs:
            self: Stored sample fields or accumulated pass state.

        Returns:
            Tuple of completed candidates; an unfinished visible segment is excluded.

        Processing flow:
            Accumulated complete passes -> immutable result tuple

        Direct call tree (static source order):
            finish
            `-- tuple
        """
        return tuple(self.completed_passes)


def extract_complete_passes(
    samples: Sequence[GeometrySample],
    *,
    elevation_mask_deg: float,
) -> tuple[CandidatePass, ...]:
    """Extract complete visible passes from ordered 1 Hz geometry samples.

    Pipeline context:
        Search-window 1 Hz geometry samples
                        |
                        v
             Complete AOS-to-LOS candidates
                        |
                        v
           Five-pass selection in the next stage

    Inputs:
        samples: Ordered geometry relative to the station samples.
        elevation_mask_deg: Station elevation threshold in degrees used for acquisition and loss.

    Returns:
        Tuple of candidates containing both acquisition and loss boundaries.

    Processing flow:
        Ordered elevation samples + mask
                        |
                        v
             Detect rising mask crossing
                        |
                        v
            Interpolate AOS and retain samples
                        |
                        v
             Detect falling mask crossing
                        |
                        v
        Interpolate LOS, TCA, and peak elevation
                        |
                        v
          Discard incomplete boundary candidates
                        |
                        v
                Complete pass tuple

    Direct call tree (static source order):
        extract_complete_passes
        +-- _CompletePassAccumulator
        +-- accumulator.consume
        `-- accumulator.finish
    """
    accumulator = _CompletePassAccumulator(elevation_mask_deg)
    for sample in samples:
        accumulator.consume(sample)
    return accumulator.finish()

def generate_candidate_passes(
    validated_omm: ValidatedOmm,
    earth_orientation_table: iers.IERS,
    search_start_utc: datetime,
    search_end_utc: datetime,
    *,
    station: GroundStation = LINZ_GROUND_STATION,
    chunk_days: int = _DATASET_DEFAULTS["chunk_days"],
) -> tuple[CandidatePass, ...]:
    """Generate complete visible passes from a chunked one-second search.

    References:
        Vallado et al., AIAA 2006-6753, ``Revisiting Spacetrack Report #3``, Section
        VI.B, Table 2; Astropy 8.0.1 satellite-coordinate workflow.

    Inputs:
        validated_omm: Parsed orbital elements and the initialized SGP4 model.
        earth_orientation_table: Frozen IERS-A values used for Earth orientation.
        search_start_utc: Inclusive beginning of the propagation search.
        search_end_utc: Exclusive end of the propagation search.
        station: Ground station geodetic coordinates and visibility mask.
        chunk_days: Maximum propagation chunk length in days.

    Returns:
        Tuple of complete candidate passes found in the search interval.

    Processing flow:
        Validated OMM + frozen IERS-A + UTC chunks -> SGP4 TEME states -> ITRS
        ECEF states -> Linz geometry -> cross-chunk AOS/LOS pass state machine.

    Direct call tree (static source order):
        generate_candidate_passes
        +-- _CompletePassAccumulator
        +-- iter_utc_second_chunks
        +-- propagate_itrs
        +-- zip
        +-- accumulator.consume
        +-- compute_geometry_sample
        `-- accumulator.finish
    """
    accumulator = _CompletePassAccumulator(station.elevation_mask_deg)
    for timestamps_utc in iter_utc_second_chunks(
        search_start_utc,
        search_end_utc,
        chunk_days=chunk_days,
    ):
        positions_ecef_m, velocities_ecef_mps = propagate_itrs(
            satellite=validated_omm.satellite,
            timestamps_utc=timestamps_utc,
            earth_orientation_table=earth_orientation_table,
        )
        for timestamp_utc, position_ecef_m, velocity_ecef_mps in zip(
            timestamps_utc,
            positions_ecef_m,
            velocities_ecef_mps,
            strict=True,
        ):
            accumulator.consume(
                compute_geometry_sample(
                    timestamp_utc=timestamp_utc,
                    position_ecef_m=position_ecef_m,
                    velocity_ecef_mps=velocity_ecef_mps,
                    station=station,
                )
            )
    return accumulator.finish()


def _candidate_sort_key(candidate: CandidatePass) -> tuple[float, datetime]:
    """Order candidate passes by peak elevation and then acquisition time.

    Inputs:
        candidate: One complete visible pass.

    Returns:
        Tuple of peak elevation in degrees and acquisition UTC.

    Processing flow:
        Candidate peak and acquisition time -> deterministic ascending sort key

    Direct call tree (static source order):
        _candidate_sort_key
        `-- [no direct function calls; local state/return only]
    """
    return candidate.peak_elevation_deg, candidate.aos_utc


def _selection_aos_key(
    state: tuple[float, tuple[CandidatePass, ...]],
) -> tuple[float, tuple[float, ...]]:
    """Rank equal-cost pass selections so more recent acquisitions win ties.

    Inputs:
        state: Selection cost and its current tuple of candidate passes.

    Returns:
        Cost and tuple of negated Unix acquisition times.

    Processing flow:
        Selection cost -> negative acquisition timestamps -> comparison key

    Direct call tree (static source order):
        _selection_aos_key
        +-- newest_first_ranks.append
        +-- candidate.aos_utc.timestamp
        `-- tuple
    """
    newest_first_ranks: list[float] = []
    for candidate in state[1]:
        newest_first_ranks.append(-candidate.aos_utc.timestamp())
    return state[0], tuple(newest_first_ranks)


def quantize_peak_elevation_level(peak_elevation_deg: float) -> float:
    """Quantize a candidate peak elevation to the project's 0.01-degree level.

    Inputs:
        peak_elevation_deg: Candidate peak elevation in degrees.

    Returns:
        Peak elevation rounded to the project 0.01-degree level.

    Processing flow:
        Raw peak degrees -> finite/range validation -> scale to centidegrees ->
        half-away-from-zero integer -> two-decimal elevation level.

    Direct call tree (static source order):
        quantize_peak_elevation_level
        +-- float
        +-- math.isfinite
        +-- OrbitDatasetError
        +-- Decimal
        +-- str
        `-- decimal_value.quantize
    """
    value = float(peak_elevation_deg)
    if not math.isfinite(value) or value < 10.0 or value > 90.0:
        raise OrbitDatasetError("candidate peak elevation must be within 10 to 90")
    decimal_value = Decimal(str(value))
    quantum = Decimal("0.01")
    quantized = decimal_value.quantize(quantum, rounding=ROUND_HALF_UP)
    return float(quantized)


def _peak_level_centidegrees(peak_elevation_deg: float) -> int:
    """Represent a selected peak elevation as an integer number of centidegrees.

    Inputs:
        peak_elevation_deg: Candidate peak elevation in degrees.

    Returns:
        Quantized peak elevation multiplied by one hundred.

    Processing flow:
        Peak angle -> validated 0.01-degree level -> integer centidegrees

    Direct call tree (static source order):
        _peak_level_centidegrees
        +-- quantize_peak_elevation_level
        `-- round_half_away_from_zero
    """
    level = quantize_peak_elevation_level(peak_elevation_deg)
    return round_half_away_from_zero(level * 100.0)


def _derived_targets_for_candidates(
    candidates: Sequence[CandidatePass],
) -> tuple[float, ...]:
    """Place five selection targets across the available distinct elevation levels.

    Inputs:
        candidates: Complete visible passes available for selection.

    Returns:
        Five target peak elevations in degrees.

    Processing flow:
        Quantized peak levels -> retain newest pass per level -> require five levels
        -> observed minimum/maximum -> five equally spaced elevation targets

    Direct call tree (static source order):
        _derived_targets_for_candidates
        +-- _peak_level_centidegrees
        +-- newest_by_level.get
        +-- sorted
        +-- len
        +-- OrbitDatasetError
        +-- range
        +-- targets.append
        `-- tuple
    """
    newest_by_level: dict[int, CandidatePass] = {}
    for candidate in candidates:
        level = _peak_level_centidegrees(candidate.peak_elevation_deg)
        previous = newest_by_level.get(level)
        if previous is None or candidate.aos_utc > previous.aos_utc:
            newest_by_level[level] = candidate
    distinct_levels = sorted(newest_by_level)
    if len(distinct_levels) < 5:
        raise OrbitDatasetError(
            "selection requires at least 5 different peak-elevation levels"
        )
    lowest = distinct_levels[0] / 100.0
    highest = distinct_levels[-1] / 100.0
    spacing = (highest - lowest) / 4.0
    targets: list[float] = []
    for index in range(5):
        targets.append(lowest + spacing * index)
    return tuple(targets)


def _distinct_candidates_by_peak(
    candidates: Sequence[CandidatePass],
) -> tuple[CandidatePass, ...]:
    """Keep the newest pass at each quantized peak elevation level.

    Inputs:
        candidates: Complete visible passes available for selection.

    Returns:
        Tuple containing one candidate per distinct peak level.

    Processing flow:
        Candidate peaks -> 0.01-degree grouping -> newest acquisition per group
        -> order by peak and acquisition time

    Direct call tree (static source order):
        _distinct_candidates_by_peak
        +-- _peak_level_centidegrees
        +-- newest_by_level.get
        +-- list
        +-- newest_by_level.values
        +-- output.sort
        `-- tuple
    """
    newest_by_level: dict[int, CandidatePass] = {}
    for candidate in candidates:
        level = _peak_level_centidegrees(candidate.peak_elevation_deg)
        previous = newest_by_level.get(level)
        if previous is None or candidate.aos_utc > previous.aos_utc:
            newest_by_level[level] = candidate
    output = list(newest_by_level.values())
    output.sort(key=_candidate_sort_key)
    return tuple(output)


def select_distinct_passes(
    candidates: Sequence[CandidatePass],
    *,
    target_peak_elevations_deg: Sequence[float] | None = None,
) -> tuple[SelectedPass, ...]:
    """Select five distinct passes across the observed peak-elevation range.

    Pipeline context:
        Complete AOS-to-LOS candidate passes
                         |
                         v
          Globally optimal distinct assignment
                         |
                         v
        Five selected passes for quantization

    Inputs:
        candidates: Complete visible passes available for selection.
        target_peak_elevations_deg: Optional five target peak angles in degrees; None derives targets from the observed range.

    Returns:
        Five selected passes paired with their target peak elevations.

    Processing flow:
        Derive five evenly spaced reference points from observed low/high peaks
                         |
                         v
          Scan candidates with selection-count DP
                         |
                         v
        Compare total error, then prefer the newer AOS tuple
                         |
                         v
          Pair each target with one candidate
                         |
                         v
                 SelectedPass tuple

    Direct call tree (static source order):
        select_distinct_passes
        +-- _derived_targets_for_candidates
        +-- _distinct_candidates_by_peak
        +-- target_values.append
        +-- float
        +-- target_values.sort
        +-- tuple
        +-- list
        +-- ordered_candidates_list.sort
        +-- len
        +-- OrbitDatasetError
        +-- range
        +-- abs
        +-- _selection_aos_key
        +-- zip
        +-- selected.append
        `-- SelectedPass
    """
    if target_peak_elevations_deg is None:
        ordered_targets = _derived_targets_for_candidates(candidates)
        ordered_candidates = _distinct_candidates_by_peak(candidates)
    else:
        target_values: list[float] = []
        for target in target_peak_elevations_deg:
            target_values.append(float(target))
        target_values.sort()
        ordered_targets = tuple(target_values)
        ordered_candidates_list = list(candidates)
        ordered_candidates_list.sort(key=_candidate_sort_key)
        ordered_candidates = tuple(ordered_candidates_list)
    if len(ordered_candidates) < len(ordered_targets):
        raise OrbitDatasetError(
            f"selection requires at least {len(ordered_targets)} candidates"
        )

    best_by_count: list[
        tuple[float, tuple[CandidatePass, ...]] | None
    ] = [None] * (len(ordered_targets) + 1)
    best_by_count[0] = (0.0, ())

    for candidate in ordered_candidates:
        for selected_count in range(len(ordered_targets), 0, -1):
            previous_state = best_by_count[selected_count - 1]
            if previous_state is None:
                continue

            previous_error, previous_candidates = previous_state
            candidate_state = (
                previous_error
                + abs(
                    candidate.peak_elevation_deg
                    - ordered_targets[selected_count - 1]
                ),
                previous_candidates + (candidate,),
            )
            current_state = best_by_count[selected_count]
            candidate_key = _selection_aos_key(candidate_state)
            if current_state is None:
                best_by_count[selected_count] = candidate_state
                continue

            current_key = _selection_aos_key(current_state)
            if candidate_key < current_key:
                best_by_count[selected_count] = candidate_state

    selected_state = best_by_count[-1]
    assert selected_state is not None
    selected: list[SelectedPass] = []
    for target, candidate in zip(
        ordered_targets,
        selected_state[1],
        strict=True,
    ):
        selected.append(
            SelectedPass(
                target_peak_elevation_deg=target,
                candidate=candidate,
            )
        )
    return tuple(selected)


def floor_retrieval_cutoff(retrieval_utc: datetime) -> datetime:
    """Return the integral UTC second used as the right-open search endpoint.

    Inputs:
        retrieval_utc: UTC retrieval instant used to end the historical search.

    Returns:
        UTC retrieval instant truncated to an integral second.

    Processing flow:
        Retrieval instant -> require UTC -> discard fractional microseconds
        -> right-open historical cutoff.

    Direct call tree (static source order):
        floor_retrieval_cutoff
        +-- retrieval_utc.utcoffset
        +-- timedelta
        +-- ValueError
        `-- retrieval_utc.replace
    """
    if retrieval_utc.tzinfo is None or retrieval_utc.utcoffset() != timedelta(0):
        raise ValueError("retrieval_utc must be timezone-aware UTC")
    return retrieval_utc.replace(microsecond=0)


def select_adaptive_past_passes(
    validated_omm: ValidatedOmm,
    earth_orientation_table: iers.IERS,
    retrieval_utc: datetime,
    *,
    station: GroundStation = LINZ_GROUND_STATION,
    chunk_days: int = _DATASET_DEFAULTS["chunk_days"],
    maximum_lookback_days: int = _DATASET_DEFAULTS["maximum_lookback_days"],
) -> PastPassSelection:
    """Find the first sufficient five-pass window by expanding into the past.

    Inputs:
        validated_omm: Parsed orbital elements and the initialized SGP4 model.
        earth_orientation_table: Frozen IERS-A values used for Earth orientation.
        retrieval_utc: UTC retrieval instant used to end the historical search.
        station: Ground station geodetic coordinates and visibility mask.
        chunk_days: Maximum propagation chunk length in days.
        maximum_lookback_days: Maximum historical search window in days.

    Returns:
        PastPassSelection containing the successful search interval, candidates, and five selections.

    Processing flow:
        Retrieval instant -> integral right-open cutoff -> propagate the current
        D-day history -> filter complete boundary-safe passes -> five-level
        selection -> return immediately or expand D by one day, through D=30.

    Direct call tree (static source order):
        select_adaptive_past_passes
        +-- isinstance
        +-- ValueError
        +-- floor_retrieval_cutoff
        +-- timedelta
        +-- generate_candidate_passes
        +-- candidates_list.append
        +-- tuple
        +-- select_distinct_passes
        +-- PastPassSelection
        `-- OrbitDatasetError
    """
    if isinstance(maximum_lookback_days, bool):
        raise ValueError("maximum_lookback_days must be a positive integer")
    if not isinstance(maximum_lookback_days, int):
        raise ValueError("maximum_lookback_days must be a positive integer")
    if maximum_lookback_days < 1 or maximum_lookback_days > 30:
        raise ValueError("maximum_lookback_days must be between 1 and 30")

    cutoff = floor_retrieval_cutoff(retrieval_utc)
    lookback_days = 1
    while lookback_days <= maximum_lookback_days:
        search_start = cutoff - timedelta(days=lookback_days)
        generated_candidates = generate_candidate_passes(
            validated_omm,
            earth_orientation_table,
            search_start,
            cutoff,
            station=station,
            chunk_days=chunk_days,
        )
        candidates_list: list[CandidatePass] = []
        for candidate in generated_candidates:
            if candidate.aos_utc < search_start:
                continue
            if candidate.los_utc >= cutoff:
                continue
            candidates_list.append(candidate)
        candidates = tuple(candidates_list)
        try:
            selected = select_distinct_passes(candidates)
        except OrbitDatasetError:
            lookback_days += 1
            continue
        return PastPassSelection(
            search_start_utc=search_start,
            search_end_utc=cutoff,
            lookback_days=lookback_days,
            candidates=candidates,
            selected_passes=selected,
        )

    raise OrbitDatasetError(
        "could not select five distinct elevation levels within 30 past days"
    )


def generate_dataset_files(
    output_directory: str | Path,
    *,
    omm_source: FetchedSource,
    iers_source: FetchedSource,
    generator_git_commit: str,
    search_start_utc: datetime | None = None,
    search_end_utc: datetime | None = None,
    station: GroundStation = LINZ_GROUND_STATION,
    chunk_days: int = _DATASET_DEFAULTS["chunk_days"],
    dataset_id: str | None = None,
    maximum_lookback_days: int = _DATASET_DEFAULTS["maximum_lookback_days"],
) -> GeneratedDataset:
    """Generate one complete orbit dataset from frozen source byte streams.

    Inputs:
        output_directory: Destination directory for generated Level 1 artifacts.
        omm_source: Frozen OMM XML response and its retrieval metadata.
        iers_source: Frozen IERS-A response and its retrieval metadata.
        generator_git_commit: Optional Git commit text recorded as generator metadata.
        search_start_utc: Inclusive beginning of the propagation search, or None for adaptive search.
        search_end_utc: Exclusive end of the propagation search, or None for adaptive search.
        station: Ground station geodetic coordinates and visibility mask.
        chunk_days: Maximum propagation chunk length in days.
        dataset_id: Identity recorded in the orbit manifest and publication directory.
        maximum_lookback_days: Maximum historical search window in days.

    Returns:
        GeneratedDataset describing generated artifact paths, pass selection, and provenance.

    Processing flow:
        Frozen source bytes -> validated local OMM/IERS-A -> adaptive whole-day
        historical search -> five diverse passes -> CSV and 50-byte records ->
        provenance -> canonical dynamic-schedule manifest.

    Direct call tree (static source order):
        generate_dataset_files
        +-- ValueError
        +-- floor_retrieval_cutoff
        +-- OrbitDatasetError
        +-- Path
        +-- dataset_directory.exists
        +-- any
        +-- dataset_directory.iterdir
        +-- FileExistsError
        +-- dataset_directory.mkdir
        +-- source_directory.mkdir
        +-- write_bytes_exclusive
        +-- load_validated_omm
        +-- iers.conf.set_temp
        +-- load_frozen_iers_a
        +-- select_adaptive_past_passes
        +-- generate_candidate_passes
        +-- select_distinct_passes
        +-- <BinOp expression>.total_seconds
        +-- int
        +-- write_dataset_csvs
        +-- read_sample_rows
        +-- write_mission_record_stream
        +-- write_dataset_provenance
        +-- retrieval_cutoff.strftime
        +-- write_orbit_manifest
        +-- GeneratedDataset
        `-- len
    """
    if (search_start_utc is None) != (search_end_utc is None):
        raise ValueError(
            "search_start_utc and search_end_utc must be supplied together"
        )
    retrieval_cutoff = floor_retrieval_cutoff(omm_source.retrieved_at_utc)
    if search_start_utc is not None:
        assert search_end_utc is not None
        if search_start_utc.microsecond != 0 or search_end_utc.microsecond != 0:
            raise OrbitDatasetError("explicit search bounds must use whole seconds")
        if search_end_utc > retrieval_cutoff:
            raise OrbitDatasetError("orbit search must never include future time")
        if search_end_utc <= search_start_utc:
            raise OrbitDatasetError("search_end_utc must be after search_start_utc")

    dataset_directory = Path(output_directory)
    if dataset_directory.exists() and any(dataset_directory.iterdir()):
        raise FileExistsError(
            f"dataset output directory must be empty: {dataset_directory}"
        )
    dataset_directory.mkdir(parents=True, exist_ok=True)
    source_directory = dataset_directory / "source"
    source_directory.mkdir()
    omm_path = source_directory / "gomx1_39430.omm.xml"
    iers_path = source_directory / "iers_a_finals2000A.all"
    write_bytes_exclusive(omm_path, omm_source.content)
    write_bytes_exclusive(iers_path, iers_source.content)

    validated_omm = load_validated_omm(
        omm_path,
        omm_source.retrieved_at_utc,
    )
    with iers.conf.set_temp("auto_download", False):
        earth_orientation_table = load_frozen_iers_a(iers_path, retrieval_cutoff)
        if search_start_utc is None:
            adaptive = select_adaptive_past_passes(
                validated_omm,
                earth_orientation_table,
                omm_source.retrieved_at_utc,
                station=station,
                chunk_days=chunk_days,
                maximum_lookback_days=maximum_lookback_days,
            )
            search_start_utc = adaptive.search_start_utc
            search_end_utc = adaptive.search_end_utc
            lookback_days = adaptive.lookback_days
            candidates = adaptive.candidates
            selected_passes = adaptive.selected_passes
        else:
            assert search_end_utc is not None
            candidates = generate_candidate_passes(
                validated_omm,
                earth_orientation_table,
                search_start_utc,
                search_end_utc,
                station=station,
                chunk_days=chunk_days,
            )
            selected_passes = select_distinct_passes(candidates)
            duration_seconds = (search_end_utc - search_start_utc).total_seconds()
            lookback_days = int((duration_seconds + 86399) // 86400)

    assert search_start_utc is not None
    assert search_end_utc is not None
    passes_path, samples_path = write_dataset_csvs(
        dataset_directory,
        selected_passes,
        orbit_epoch_utc=validated_omm.epoch_utc,
    )
    sample_rows = read_sample_rows(samples_path)
    mission_records_path = dataset_directory / "mission_records.bin"
    sample_count = write_mission_record_stream(mission_records_path, sample_rows)
    provenance_path = write_dataset_provenance(
        dataset_directory,
        omm_source=omm_source,
        iers_source=iers_source,
        validated_omm=validated_omm,
        search_start_utc=search_start_utc,
        search_end_utc=search_end_utc,
        passes_path=passes_path,
        samples_path=samples_path,
        generator_git_commit=generator_git_commit,
        chunk_days=chunk_days,
        station=station,
        mission_records_path=mission_records_path,
        selected_passes=selected_passes,
        lookback_days=lookback_days,
    )
    if dataset_id is None:
        dataset_id = retrieval_cutoff.strftime("%Y%m%dT%H%M%SZ")
    orbit_manifest_path = write_orbit_manifest(
        dataset_directory,
        dataset_id=dataset_id,
        retrieval_utc=omm_source.retrieved_at_utc,
        selected_passes=selected_passes,
        sample_rows=sample_rows,
    )
    return GeneratedDataset(
        dataset_directory=dataset_directory,
        search_start_utc=search_start_utc,
        search_end_utc=search_end_utc,
        candidate_count=len(candidates),
        selected_passes=selected_passes,
        passes_path=passes_path,
        samples_path=samples_path,
        provenance_path=provenance_path,
        mission_records_path=mission_records_path,
        orbit_manifest_path=orbit_manifest_path,
        sample_count=sample_count,
        lookback_days=lookback_days,
    )
