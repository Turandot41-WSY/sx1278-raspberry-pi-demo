"""Strict read-only loading of frozen Level 1 orbit datasets."""

import csv
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from firmware.host.runtime_config import load_settings

from firmware.host.canonical import (
    canonical_json_bytes,
    parse_decimal,
    parse_rfc3339_utc,
    sha256_bytes,
    sha256_file,
)
from dataset.orbit_dataset import (
    PASS_CSV_FIELDS,
    SAMPLE_CSV_FIELDS,
    OrbitDatasetError,
    load_validated_omm,
    orbit_schedule_hash_row,
    quantize_peak_elevation_level,
    quantized_row_to_mission_record,
)
from dataset.orbit_geometry import (
    LINZ_GROUND_STATION,
    NOMINAL_CARRIER_HZ,
    SPEED_OF_LIGHT_MPS,
    SX1278_FSTEP_HZ,
    SX1278_NOMINAL_FRF_WORD,
)
from dataset.orbit_record import pack_mission_record, unpack_mission_record
from dataset.payload_schedule import PayloadSample, PayloadSchedule


LEVEL1_ARTIFACT_NAMES = (
    "provenance.json",
    "passes.csv",
    "samples.csv",
    "mission_records.bin",
)
_MANIFEST_FIELDS = (
    "SchemaVersion",
    "DatasetId",
    "RetrievalUtc",
    "PassCount",
    "SampleCount",
    "PassSchedules",
    "Artifacts",
)
_PASS_SCHEDULE_FIELDS = (
    "PassId",
    "PassLabel",
    "TargetPeakElevationDeg",
    "ActualPeakElevationDeg",
    "SampleCount",
    "FirstTraceSampleId",
    "LastTraceSampleId",
    "ByteOffset",
    "ByteCount",
    "ScheduleSha256",
)
_ARTIFACT_FIELDS = ("ByteCount", "Sha256")
_FORMAL_PROVENANCE_FIELDS = (
    "generator",
    "orbit",
    "outputs",
    "rf",
    "schema_version",
    "search",
    "sources",
    "station",
)
_GENERATOR_FIELDS = (
    "git_commit",
    "gravity_model",
    "schema_version",
    "software_versions",
)
_SOFTWARE_VERSION_FIELDS = ("astropy", "numpy", "python", "sgp4")
_ORBIT_PROVENANCE_FIELDS = ("epoch_age_seconds", "epoch_utc", "omm_fields")
_OUTPUT_PROVENANCE_FIELDS = (
    "passes.csv",
    "samples.csv",
    "mission_records.bin",
)
_FILE_PROVENANCE_FIELDS = ("byte_count", "sha256")
_RF_PROVENANCE_FIELDS = (
    "nominal_carrier_hz",
    "speed_of_light_mps",
    "sx1278_fstep_hz",
    "sx1278_nominal_frf_word",
)
_SEARCH_PROVENANCE_FIELDS = (
    "actual_peak_elevations_deg",
    "chunk_days",
    "dynamic_selection_anchors_deg",
    "end_utc",
    "lookback_days",
    "selection_rule",
    "start_utc",
    "step_seconds",
)
_SOURCE_PROVENANCE_FIELDS = (
    "byte_count",
    "filename",
    "http_headers",
    "retrieved_at_utc",
    "sha256",
    "url",
)
_STATION_PROVENANCE_FIELDS = (
    "elevation_mask_deg",
    "height_m",
    "latitude_deg",
    "longitude_deg",
    "reference_frame",
)
_ORBIT_MODEL = load_settings("main_dataset")["orbit_model"]
_APPROVED_OMM_URL = _ORBIT_MODEL["sources"]["omm_url"]
_APPROVED_IERS_A_URL = _ORBIT_MODEL["sources"]["iers_a_url"]
_SELECTION_RULE = (
    "five distinct complete passes spanning the actual candidate low-to-high "
    "peak-elevation range; dynamic anchors are derived from that range and "
    "ties use the newer AOS tuple"
)


class OrbitTraceError(ValueError):
    """Reject a frozen Level 1 dataset with inconsistent bytes or identity."""


@dataclass(frozen=True)
class FrozenOrbitSample:
    """Hold one checked orbit sample with both global and pass-local identity."""

    pass_id: int
    trace_sample_id: int
    pass_sample_index: int
    requested_cfo_hz: float
    programmed_cfo_hz: float
    reg_frf_word: int
    mission_record: bytes


@dataclass(frozen=True)
class FrozenOrbitPass:
    """Hold one checked pass and its dynamic payload schedule."""

    pass_id: int
    pass_label: str
    sample_count: int
    schedule: PayloadSchedule


@dataclass(frozen=True)
class FrozenOrbitDataset:
    """Hold one fully verified five-pass Level 1 orbit dataset."""

    dataset_id: str
    root: Path
    passes: tuple[FrozenOrbitPass, ...]
    sample_count: int
    manifest_sha256: str

    def schedule_for_pass(self, pass_id: int) -> PayloadSchedule:
        """Return the sole schedule identified by a checked pass ID.

        Inputs:
            pass_id: Identifier of the selected pass schedule.

        Returns:
            PayloadSchedule for the unique matching pass.

        Processing flow:
            Pass ID -> scan five immutable pass records -> exactly one match ->
            dynamic payload schedule, otherwise a fail-closed identity error.

        Direct call tree (static source order):
            schedule_for_pass
            `-- OrbitTraceError
        """
        match: PayloadSchedule | None = None
        for orbit_pass in self.passes:
            if orbit_pass.pass_id == pass_id:
                if match is not None:
                    raise OrbitTraceError(f"unknown or duplicate pass id: {pass_id}")
                match = orbit_pass.schedule
        if match is None:
            raise OrbitTraceError(f"unknown or duplicate pass id: {pass_id}")
        return match


def _require_exact_fields(
    value: object,
    expected_fields: Sequence[str],
    label: str,
) -> dict[str, object]:
    """Require a JSON object to contain exactly the expected field names.

    Inputs:
        value: Candidate field or provenance object to validate.
        expected_fields: Complete allowed field-name set.
        label: Field or artifact name included in validation errors.

    Returns:
        The original checked dictionary.

    Processing flow:
        Object type -> compare actual and expected field sets -> checked mapping

    Direct call tree (static source order):
        _require_exact_fields
        +-- isinstance
        +-- OrbitTraceError
        `-- set
    """
    if not isinstance(value, dict):
        raise OrbitTraceError(f"{label} must be an object")
    actual_fields = set(value)
    expected = set(expected_fields)
    if actual_fields != expected:
        raise OrbitTraceError(f"{label} fields do not match the frozen contract")
    return value


def _require_integer(
    value: object,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    """Require a integer distinct from Boolean values within inclusive bounds.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.
        minimum: Inclusive lower numeric bound.
        maximum: Inclusive upper numeric bound.

    Returns:
        Validated integer.

    Processing flow:
        Numeric type -> exclude Boolean -> inclusive lower/upper bounds

    Direct call tree (static source order):
        _require_integer
        +-- isinstance
        `-- OrbitTraceError
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise OrbitTraceError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise OrbitTraceError(f"{label} is outside its allowed range")
    return value


def _require_number(
    value: object,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    """Require a finite numeric value within inclusive bounds.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.
        minimum: Inclusive lower numeric bound.
        maximum: Inclusive upper numeric bound.

    Returns:
        Validated finite floating point value.

    Processing flow:
        Numeric type -> exclude Boolean -> float conversion -> finite and range checks

    Direct call tree (static source order):
        _require_number
        +-- isinstance
        +-- OrbitTraceError
        +-- float
        `-- math.isfinite
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrbitTraceError(f"{label} must be a number")
    converted = float(value)
    if not math.isfinite(converted):
        raise OrbitTraceError(f"{label} must be finite")
    if converted < minimum or converted > maximum:
        raise OrbitTraceError(f"{label} is outside its allowed range")
    return converted


def _require_hash(value: object, label: str) -> str:
    """Require the canonical lowercase hexadecimal form of a SHA-256 digest.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.

    Returns:
        Validated digest text.

    Processing flow:
        Text type and 64-character width -> inspect hexadecimal characters -> digest

    Direct call tree (static source order):
        _require_hash
        +-- isinstance
        +-- len
        `-- OrbitTraceError
    """
    if not isinstance(value, str) or len(value) != 64:
        raise OrbitTraceError(f"{label} must be a lowercase SHA-256 hash")
    for character in value:
        if character not in "0123456789abcdef":
            raise OrbitTraceError(f"{label} must be a lowercase SHA-256 hash")
    return value


def _read_exact_csv(
    path: Path,
    fields: Sequence[str],
    label: str,
) -> tuple[dict[str, str], ...]:
    """Read complete CSV rows using the frozen header and exact LF encoding.

    Inputs:
        path: Source or artifact path used by this operation.
        fields: Exact CSV column names and order.
        label: Field or artifact name included in validation errors.

    Returns:
        Tuple of dictionaries containing every required CSV field.

    Processing flow:
        Raw bytes -> UTF-8 and LF checks -> exact header -> complete row fields

    Direct call tree (static source order):
        _read_exact_csv
        +-- path.read_bytes
        +-- raw.endswith
        +-- OrbitTraceError
        +-- raw.decode
        +-- path.open
        +-- csv.DictReader
        +-- tuple
        +-- row.get
        `-- rows.append
    """
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise OrbitTraceError(f"{label} must use exact LF line endings")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OrbitTraceError(f"{label} must be UTF-8") from error
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or tuple(reader.fieldnames) != tuple(fields):
            raise OrbitTraceError(f"{label} columns changed")
        for row in reader:
            if None in row:
                raise OrbitTraceError(f"{label} row has extra columns")
            checked: dict[str, str] = {}
            for field_name in fields:
                field_value = row.get(field_name)
                if field_value is None or field_value == "":
                    raise OrbitTraceError(f"{label} row has a missing value")
                checked[field_name] = field_value
            rows.append(checked)
    return tuple(rows)


def _parse_row_integer(row: Mapping[str, str], field_name: str) -> int:
    """Decode a canonical decimal field from a frozen CSV row.

    Inputs:
        row: Sample CSV fields before conversion to typed values.
        field_name: Name of the required CSV field.

    Returns:
        Parsed integer field value.

    Processing flow:
        Required CSV field -> canonical decimal parser -> labelled validation error or integer

    Direct call tree (static source order):
        _parse_row_integer
        +-- parse_decimal
        `-- OrbitTraceError
    """
    try:
        return parse_decimal(row[field_name])
    except (KeyError, ValueError) as error:
        raise OrbitTraceError(f"{field_name} is not canonical decimal") from error


def _parse_row_float(row: Mapping[str, str], field_name: str) -> float:
    """Decode a finite numeric field from a frozen CSV row.

    Inputs:
        row: Sample CSV fields before conversion to typed values.
        field_name: Name of the required CSV field.

    Returns:
        Parsed finite field value.

    Processing flow:
        Required unpadded text -> floating point conversion -> finite-value check

    Direct call tree (static source order):
        _parse_row_float
        +-- OrbitTraceError
        +-- text.strip
        +-- float
        `-- math.isfinite
    """
    try:
        text = row[field_name]
    except KeyError as error:
        raise OrbitTraceError(f"{field_name} is missing") from error
    if text == "" or text != text.strip():
        raise OrbitTraceError(f"{field_name} must be a finite number")
    try:
        value = float(text)
    except ValueError as error:
        raise OrbitTraceError(f"{field_name} must be a finite number") from error
    if not math.isfinite(value):
        raise OrbitTraceError(f"{field_name} must be a finite number")
    return value


def _parse_sample_timestamp(text: str) -> datetime:
    """Parse a sample timestamp at an integral UTC second.

    Inputs:
        text: Timestamp text from a sample row.

    Returns:
        UTC datetime without fractional seconds.

    Processing flow:
        Exact second-resolution timestamp syntax -> datetime -> UTC timezone

    Direct call tree (static source order):
        _parse_sample_timestamp
        +-- datetime.strptime
        +-- OrbitTraceError
        `-- parsed.replace
    """
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise OrbitTraceError(
            "sample timestamp must be an integral UTC second"
        ) from error
    return parsed.replace(tzinfo=UTC)


def _validate_manifest_shape(manifest: object) -> dict[str, object]:
    """Validate the structure and numeric limits of the Level 1 manifest.

    Inputs:
        manifest: Parsed orbit manifest to validate or compare against.

    Returns:
        Validated manifest dictionary.

    Processing flow:
        Exact manifest fields -> version/identity/counts -> five schedule entries
        -> artifact field sets, byte counts, and hashes

    Direct call tree (static source order):
        _validate_manifest_shape
        +-- _require_exact_fields
        +-- OrbitTraceError
        +-- isinstance
        +-- parse_rfc3339_utc
        +-- _require_integer
        +-- len
        +-- range
        +-- _require_number
        `-- _require_hash
    """
    root = _require_exact_fields(manifest, _MANIFEST_FIELDS, "orbit manifest")
    if root["SchemaVersion"] != 1:
        raise OrbitTraceError("orbit manifest SchemaVersion must be 1")
    dataset_id = root["DatasetId"]
    if not isinstance(dataset_id, str) or dataset_id == "":
        raise OrbitTraceError("orbit manifest DatasetId must be non-empty text")
    retrieval = root["RetrievalUtc"]
    if not isinstance(retrieval, str):
        raise OrbitTraceError("orbit manifest RetrievalUtc must be text")
    try:
        parse_rfc3339_utc(retrieval)
    except ValueError as error:
        raise OrbitTraceError("orbit manifest RetrievalUtc is not canonical") from error
    if root["PassCount"] != 5:
        raise OrbitTraceError("orbit manifest must index five passes")
    _require_integer(root["SampleCount"], "SampleCount", 0, 65536)

    schedules = root["PassSchedules"]
    if not isinstance(schedules, list) or len(schedules) != 5:
        raise OrbitTraceError("orbit manifest must index five passes")
    for entry_index in range(5):
        entry = _require_exact_fields(
            schedules[entry_index],
            _PASS_SCHEDULE_FIELDS,
            "pass schedule",
        )
        _require_integer(entry["PassId"], "PassId", 0, 4)
        label = entry["PassLabel"]
        if not isinstance(label, str):
            raise OrbitTraceError("PassLabel must be text")
        _require_number(
            entry["TargetPeakElevationDeg"],
            "TargetPeakElevationDeg",
            10.0,
            90.0,
        )
        _require_number(
            entry["ActualPeakElevationDeg"],
            "ActualPeakElevationDeg",
            10.0,
            90.0,
        )
        _require_integer(entry["SampleCount"], "SampleCount", 1, 65536)
        _require_integer(entry["FirstTraceSampleId"], "FirstTraceSampleId", 0, 65535)
        _require_integer(entry["LastTraceSampleId"], "LastTraceSampleId", 0, 65535)
        _require_integer(entry["ByteOffset"], "ByteOffset", 0, 3276800)
        _require_integer(entry["ByteCount"], "ByteCount", 50, 3276800)
        _require_hash(entry["ScheduleSha256"], "ScheduleSha256")

    artifacts = _require_exact_fields(
        root["Artifacts"],
        LEVEL1_ARTIFACT_NAMES,
        "artifact index",
    )
    for artifact_name in LEVEL1_ARTIFACT_NAMES:
        artifact = _require_exact_fields(
            artifacts[artifact_name],
            _ARTIFACT_FIELDS,
            f"artifact {artifact_name}",
        )
        _require_integer(artifact["ByteCount"], "ByteCount", 0, 18446744073709551615)
        _require_hash(artifact["Sha256"], "Sha256")
    return root


def verify_level1_artifact_hashes(
    root: str | Path,
    entries: Mapping[str, object],
) -> None:
    """Verify the exact Level 1 artifact set, byte counts, and raw hashes.

    Inputs:
        root: Frozen Level 1 dataset directory.
        entries: Manifest artifact map or ordered pass schedule entries.

    Returns:
        None after every required artifact matches its descriptor.

    Processing flow:
        Manifest artifact map -> exact four names -> original file byte count ->
        raw SHA-256 comparison -> success only when every artifact agrees.

    Direct call tree (static source order):
        verify_level1_artifact_hashes
        +-- _require_exact_fields
        +-- Path
        +-- artifact_path.is_file
        +-- OrbitTraceError
        +-- _require_integer
        +-- artifact_path.stat
        +-- _require_hash
        `-- sha256_file
    """
    checked_entries = _require_exact_fields(
        entries,
        LEVEL1_ARTIFACT_NAMES,
        "artifact index",
    )
    root_path = Path(root)
    for artifact_name in LEVEL1_ARTIFACT_NAMES:
        artifact = _require_exact_fields(
            checked_entries[artifact_name],
            _ARTIFACT_FIELDS,
            f"artifact {artifact_name}",
        )
        artifact_path = root_path / artifact_name
        if not artifact_path.is_file():
            raise OrbitTraceError(f"{artifact_name}: artifact is missing")
        expected_count = _require_integer(
            artifact["ByteCount"],
            "ByteCount",
            0,
            18446744073709551615,
        )
        if artifact_path.stat().st_size != expected_count:
            raise OrbitTraceError(f"{artifact_name}: byte count mismatch")
        expected_hash = _require_hash(artifact["Sha256"], "Sha256")
        if sha256_file(artifact_path) != expected_hash:
            raise OrbitTraceError(f"{artifact_name}: hash mismatch")


def _require_text(value: object, label: str) -> str:
    """Require nonempty text without leading or trailing whitespace.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.

    Returns:
        Validated text.

    Processing flow:
        Text type -> nonempty content -> exact trimmed form

    Direct call tree (static source order):
        _require_text
        +-- isinstance
        +-- value.strip
        `-- OrbitTraceError
    """
    if not isinstance(value, str) or value == "" or value != value.strip():
        raise OrbitTraceError(f"{label} must be non-empty text")
    return value


def _parse_provenance_utc(value: object, label: str) -> datetime:
    """Parse canonical UTC provenance text with a literal Z suffix.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.

    Returns:
        Validated UTC datetime.

    Processing flow:
        Nonempty text -> literal Z -> UTC datetime -> canonical precision round trip

    Direct call tree (static source order):
        _parse_provenance_utc
        +-- _require_text
        +-- text.endswith
        +-- OrbitTraceError
        +-- datetime.fromisoformat
        +-- parsed.utcoffset
        +-- timedelta
        +-- parsed.isoformat
        `-- parsed.isoformat(...).replace
    """
    text = _require_text(value, label)
    if not text.endswith("Z"):
        raise OrbitTraceError(f"{label} must use UTC with a literal Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise OrbitTraceError(f"{label} is not a UTC timestamp") from error
    if parsed.utcoffset() != timedelta(0):
        raise OrbitTraceError(f"{label} must use UTC")
    timespec = "seconds"
    if parsed.microsecond != 0:
        timespec = "microseconds"
    expected = parsed.isoformat(timespec=timespec).replace("+00:00", "Z")
    if text != expected:
        raise OrbitTraceError(f"{label} is not canonical")
    return parsed


def _require_string_mapping(value: object, label: str) -> dict[str, str]:
    """Copy a mapping only when every key and value is text.

    Inputs:
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.

    Returns:
        Dictionary of string keys and values.

    Processing flow:
        Dictionary type -> inspect all key/value pairs -> checked copy

    Direct call tree (static source order):
        _require_string_mapping
        +-- isinstance
        +-- OrbitTraceError
        `-- value.items
    """
    if not isinstance(value, dict):
        raise OrbitTraceError(f"{label} must be an object")
    checked: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise OrbitTraceError(f"{label} keys and values must be text")
        checked[key] = item
    return checked


def _read_formal_provenance(root: Path) -> dict[str, object]:
    """Load the exact deterministic JSON bytes used for formal provenance.

            Inputs:
                root: Frozen Level 1 dataset directory.

            Returns:
                Validated top-level provenance dictionary.

            Processing flow:
                Provenance bytes -> UTF-8 JSON -> indented/sorted serialization round trip
                -> exact formal provenance fields

    Direct call tree (static source order):
        _read_formal_provenance
        +-- path.read_bytes
        +-- json.loads
        +-- OrbitTraceError
        +-- <BinOp expression>.encode
        +-- json.dumps
        `-- _require_exact_fields
    """
    path = root / "provenance.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OrbitTraceError("formal provenance is not valid UTF-8 JSON") from error
    try:
        expected = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise OrbitTraceError("formal provenance is not deterministic JSON") from error
    if raw != expected:
        raise OrbitTraceError("formal provenance is not deterministic JSON")
    return _require_exact_fields(
        value,
        _FORMAL_PROVENANCE_FIELDS,
        "formal provenance",
    )


def _verify_formal_file_record(
    root: Path,
    filename: str,
    value: object,
    label: str,
) -> dict[str, object]:
    """Match a generated artifact to its recorded byte count and digest.

    Inputs:
        root: Frozen Level 1 dataset directory.
        filename: Exact source or artifact filename.
        value: Candidate field or provenance object to validate.
        label: Field or artifact name included in validation errors.

    Returns:
        Validated file provenance record.

    Processing flow:
        Exact file record -> existing artifact -> positive byte count -> SHA-256 match

    Direct call tree (static source order):
        _verify_formal_file_record
        +-- _require_exact_fields
        +-- path.is_file
        +-- OrbitTraceError
        +-- _require_integer
        +-- path.stat
        +-- _require_hash
        `-- sha256_file
    """
    record = _require_exact_fields(value, _FILE_PROVENANCE_FIELDS, label)
    path = root / filename
    if not path.is_file():
        raise OrbitTraceError(f"{label} file is missing")
    expected_count = _require_integer(
        record["byte_count"],
        f"{label} byte_count",
        1,
        18446744073709551615,
    )
    if path.stat().st_size != expected_count:
        raise OrbitTraceError(f"{label} byte count disagrees")
    expected_hash = _require_hash(record["sha256"], f"{label} sha256")
    if sha256_file(path) != expected_hash:
        raise OrbitTraceError(f"{label} hash disagrees")
    return record


def _verify_formal_source(
    root: Path,
    value: object,
    *,
    key: str,
    filename: str,
    approved_url: str,
) -> tuple[dict[str, object], datetime]:
    """Match a frozen source to its approved URL, identity, and exact bytes.

    Inputs:
        root: Frozen Level 1 dataset directory.
        value: Candidate field or provenance object to validate.
        key: Provenance source key identifying OMM or IERS-A.
        filename: Exact source or artifact filename.
        approved_url: Required retrieval URL for this source.

    Returns:
        Validated source record and its retrieval UTC datetime.

    Processing flow:
        Source fields -> approved filename/URL -> headers/retrieval timestamp
        -> source existence -> byte count and SHA-256 comparison

    Direct call tree (static source order):
        _verify_formal_source
        +-- _require_exact_fields
        +-- OrbitTraceError
        +-- _require_string_mapping
        +-- _parse_provenance_utc
        +-- path.is_file
        +-- _require_integer
        +-- path.stat
        +-- _require_hash
        `-- sha256_file
    """
    label = f"formal provenance source {key}"
    record = _require_exact_fields(value, _SOURCE_PROVENANCE_FIELDS, label)
    expected_filename = "source/" + filename
    if record["filename"] != expected_filename:
        raise OrbitTraceError(f"{label} filename disagrees")
    if record["url"] != approved_url:
        if key == "omm":
            raise OrbitTraceError("formal provenance must use the approved OMM URL")
        raise OrbitTraceError("formal provenance must use the approved IERS-A URL")
    _require_string_mapping(record["http_headers"], f"{label} http_headers")
    retrieved = _parse_provenance_utc(
        record["retrieved_at_utc"],
        f"{label} retrieved_at_utc",
    )
    path = root / expected_filename
    if not path.is_file():
        raise OrbitTraceError(f"{label} file is missing")
    byte_count = _require_integer(
        record["byte_count"],
        f"{label} byte_count",
        1,
        18446744073709551615,
    )
    if path.stat().st_size != byte_count:
        raise OrbitTraceError(f"{label} byte count disagrees")
    digest = _require_hash(record["sha256"], f"{label} sha256")
    if sha256_file(path) != digest:
        raise OrbitTraceError(f"{label} hash disagrees")
    return record, retrieved


def _verify_generator_provenance(value: object) -> None:
    """Check the recorded gravity model, optional commit, and software versions.

    Inputs:
        value: Candidate field or provenance object to validate.

    Returns:
        None; raises OrbitTraceError when generator provenance differs.

    Processing flow:
        Generator fields -> WGS-72/version -> empty or full commit digest
        -> required software version strings

    Direct call tree (static source order):
        _verify_generator_provenance
        +-- _require_exact_fields
        +-- OrbitTraceError
        +-- isinstance
        +-- len
        `-- _require_text
    """
    generator = _require_exact_fields(
        value,
        _GENERATOR_FIELDS,
        "formal provenance generator",
    )
    if generator["gravity_model"] != "WGS-72":
        raise OrbitTraceError("formal provenance gravity model must be WGS-72")
    if generator["schema_version"] != 1:
        raise OrbitTraceError("formal provenance generator schema_version must be 1")
    # Git is optional metadata; source bytes and artifact hashes remain checked.
    git_commit = generator["git_commit"]
    if not isinstance(git_commit, str):
        raise OrbitTraceError("formal provenance Git commit must be text")
    if git_commit != "" and len(git_commit) != 40:
        raise OrbitTraceError("formal provenance Git commit must be empty or a full SHA")
    for character in git_commit:
        if character not in "0123456789abcdef":
            raise OrbitTraceError("formal provenance Git commit must be a full SHA")
    versions = _require_exact_fields(
        generator["software_versions"],
        _SOFTWARE_VERSION_FIELDS,
        "formal provenance software_versions",
    )
    for name in _SOFTWARE_VERSION_FIELDS:
        _require_text(versions[name], f"formal provenance software version {name}")


def _verify_rf_and_station_provenance(provenance: Mapping[str, object]) -> None:
    """Compare recorded RF constants and Linz station coordinates with runtime truth.

    Inputs:
        provenance: Recorded RF and station provenance.

    Returns:
        None; raises OrbitTraceError for any physical model mismatch.

    Processing flow:
        RF field set -> compare carrier/frequency constants -> station field set
        -> compare location, elevation mask, and coordinate-frame label

    Direct call tree (static source order):
        _verify_rf_and_station_provenance
        +-- _require_exact_fields
        +-- expected_rf.items
        +-- OrbitTraceError
        `-- expected_station.items
    """
    rf = _require_exact_fields(
        provenance["rf"],
        _RF_PROVENANCE_FIELDS,
        "formal provenance rf",
    )
    expected_rf = {
        "nominal_carrier_hz": NOMINAL_CARRIER_HZ,
        "speed_of_light_mps": SPEED_OF_LIGHT_MPS,
        "sx1278_fstep_hz": SX1278_FSTEP_HZ,
        "sx1278_nominal_frf_word": SX1278_NOMINAL_FRF_WORD,
    }
    for field, expected in expected_rf.items():
        if rf[field] != expected:
            raise OrbitTraceError(f"formal provenance RF field {field} disagrees")

    station = _require_exact_fields(
        provenance["station"],
        _STATION_PROVENANCE_FIELDS,
        "formal provenance station",
    )
    expected_station: dict[str, object] = {
        "elevation_mask_deg": LINZ_GROUND_STATION.elevation_mask_deg,
        "height_m": LINZ_GROUND_STATION.height_m,
        "latitude_deg": LINZ_GROUND_STATION.latitude_deg,
        "longitude_deg": LINZ_GROUND_STATION.longitude_deg,
        "reference_frame": "WGS-84 geodetic / ITRS ECEF",
    }
    for field, expected in expected_station.items():
        if station[field] != expected:
            raise OrbitTraceError(f"formal provenance Linz station field {field} disagrees")


def _verify_search_provenance(
    root: Path,
    value: object,
    manifest: Mapping[str, object],
    retrieval_utc: datetime,
) -> None:
    """Check that recorded passes fit the declared historical search and sample grid.

    Inputs:
        root: Frozen Level 1 dataset directory.
        value: Candidate field or provenance object to validate.
        manifest: Parsed orbit manifest to validate or compare against.
        retrieval_utc: UTC retrieval instant used to end the historical search.

    Returns:
        None; raises OrbitTraceError when search or pass evidence disagrees.

    Processing flow:
        Search limits and selection rule -> retrieval cutoff and lookback interval
        -> five anchor/peak pairs -> AOS/LOS bounds -> integral-second sample counts

    Direct call tree (static source order):
        _verify_search_provenance
        +-- _require_exact_fields
        +-- _require_integer
        +-- OrbitTraceError
        +-- _parse_provenance_utc
        +-- retrieval_utc.replace
        +-- timedelta
        +-- isinstance
        +-- len
        +-- _require_number
        +-- float
        +-- _read_exact_csv
        +-- _parse_sample_timestamp
        +-- aos.replace
        +-- los.replace
        +-- _parse_row_integer
        +-- int
        `-- <BinOp expression>.total_seconds
    """
    search = _require_exact_fields(
        value,
        _SEARCH_PROVENANCE_FIELDS,
        "formal provenance search",
    )
    lookback_days = _require_integer(
        search["lookback_days"],
        "formal provenance lookback_days",
        1,
        30,
    )
    _require_integer(
        search["chunk_days"],
        "formal provenance chunk_days",
        1,
        30,
    )
    if search["step_seconds"] != 1:
        raise OrbitTraceError("formal provenance search must use a 1 Hz grid")
    if search["selection_rule"] != _SELECTION_RULE:
        raise OrbitTraceError("formal provenance selection rule disagrees")

    search_start = _parse_provenance_utc(
        search["start_utc"],
        "formal provenance search start_utc",
    )
    search_end = _parse_provenance_utc(
        search["end_utc"],
        "formal provenance search end_utc",
    )
    retrieval_cutoff = retrieval_utc.replace(microsecond=0)
    if search_end != retrieval_cutoff:
        raise OrbitTraceError("formal provenance search end is not retrieval cutoff")
    if search_start != search_end - timedelta(days=lookback_days):
        raise OrbitTraceError("formal provenance lookback window disagrees")

    anchors = search["dynamic_selection_anchors_deg"]
    peaks = search["actual_peak_elevations_deg"]
    if not isinstance(anchors, list) or len(anchors) != 5:
        raise OrbitTraceError("formal provenance must contain five dynamic anchors")
    if not isinstance(peaks, list) or len(peaks) != 5:
        raise OrbitTraceError("formal provenance must contain five actual peaks")
    entries = manifest["PassSchedules"]
    if not isinstance(entries, list) or len(entries) != 5:
        raise OrbitTraceError("orbit manifest must index five passes")
    index = 0
    while index < 5:
        anchor = _require_number(
            anchors[index],
            "formal provenance dynamic anchor",
            10.0,
            90.0,
        )
        peak = _require_number(
            peaks[index],
            "formal provenance actual peak",
            10.0,
            90.0,
        )
        entry = entries[index]
        if not isinstance(entry, dict):
            raise OrbitTraceError("pass schedule must be an object")
        if anchor != float(entry["TargetPeakElevationDeg"]):
            raise OrbitTraceError("formal provenance dynamic anchor disagrees")
        if peak != float(entry["ActualPeakElevationDeg"]):
            raise OrbitTraceError("formal provenance actual peak disagrees")
        index += 1

    pass_rows = _read_exact_csv(root / "passes.csv", PASS_CSV_FIELDS, "passes.csv")
    for row in pass_rows:
        aos = _parse_provenance_utc(row["aos_utc"], "passes.csv aos_utc")
        los = _parse_provenance_utc(row["los_utc"], "passes.csv los_utc")
        first = _parse_sample_timestamp(row["first_sample_utc"])
        last = _parse_sample_timestamp(row["last_sample_utc"])
        if aos < search_start or los >= search_end:
            raise OrbitTraceError("formal provenance pass is outside the past window")
        if aos >= los:
            raise OrbitTraceError("formal provenance pass boundaries are reversed")
        expected_first = aos.replace(microsecond=0)
        if aos.microsecond != 0:
            expected_first += timedelta(seconds=1)
        expected_last = los.replace(microsecond=0)
        if first != expected_first or last != expected_last:
            raise OrbitTraceError("formal provenance AOS/LOS 1 Hz boundary disagrees")
        sample_count = _parse_row_integer(row, "sample_count")
        expected_count = int((last - first).total_seconds()) + 1
        if sample_count != expected_count:
            raise OrbitTraceError("formal provenance pass sample count disagrees")


def validate_formal_level1_provenance(
    root: str | Path,
    manifest: Mapping[str, object],
) -> None:
    """Validate the complete source and past-search record for measured data.

    References:
        CCSDS 502.0-B-3, Issue 3 (April 2023), Sections 4.1--4.2 and 8.9.14 for the OMM
        identity fields.

    Inputs:
        root: Frozen Level 1 dataset directory.
        manifest: Parsed orbit manifest to validate or compare against.

    Returns:
        None after the complete formal provenance contract passes.

    Processing flow:
        Hashed provenance -> closed generator/source/output records -> parse the
        frozen GOMX-1 OMM and apply its 0--72 h source-age gate -> verify the
        retrieval-anchored 1--30 day past window, five pass boundaries, Linz
        station, RF constants, and manifest linkage -> measured-data approval.

    Direct call tree (static source order):
        validate_formal_level1_provenance
        +-- Path
        +-- _read_formal_provenance
        +-- OrbitTraceError
        +-- _verify_generator_provenance
        +-- _verify_rf_and_station_provenance
        +-- _require_exact_fields
        +-- _verify_formal_source
        +-- parse_rfc3339_utc
        +-- str
        +-- load_validated_omm
        +-- _parse_provenance_utc
        +-- _require_string_mapping
        +-- _require_number
        +-- float
        +-- <BinOp expression>.total_seconds
        +-- isinstance
        +-- _verify_formal_file_record
        `-- _verify_search_provenance
    """
    root_path = Path(root)
    provenance = _read_formal_provenance(root_path)
    if provenance["schema_version"] != 1:
        raise OrbitTraceError("formal provenance schema_version must be 1")
    _verify_generator_provenance(provenance["generator"])
    _verify_rf_and_station_provenance(provenance)

    sources = _require_exact_fields(
        provenance["sources"],
        ("iers_a", "omm"),
        "formal provenance sources",
    )
    _, omm_retrieval = _verify_formal_source(
        root_path,
        sources["omm"],
        key="omm",
        filename="gomx1_39430.omm.xml",
        approved_url=_APPROVED_OMM_URL,
    )
    _verify_formal_source(
        root_path,
        sources["iers_a"],
        key="iers_a",
        filename="iers_a_finals2000A.all",
        approved_url=_APPROVED_IERS_A_URL,
    )
    try:
        manifest_retrieval = parse_rfc3339_utc(str(manifest["RetrievalUtc"]))
    except (KeyError, ValueError) as error:
        raise OrbitTraceError("orbit manifest retrieval is invalid") from error
    if omm_retrieval != manifest_retrieval:
        raise OrbitTraceError("formal provenance and manifest retrieval disagree")
    # DatasetId names the launch, independently of network completion time.
    # Legacy dataset IDs remain readable; see ADR-0001, Dataset identity.

    orbit = _require_exact_fields(
        provenance["orbit"],
        _ORBIT_PROVENANCE_FIELDS,
        "formal provenance orbit",
    )
    omm_path = root_path / "source" / "gomx1_39430.omm.xml"
    try:
        validated_omm = load_validated_omm(omm_path, omm_retrieval)
    except (OrbitDatasetError, ValueError) as error:
        raise OrbitTraceError(f"formal provenance OMM is invalid: {error}") from error
    epoch = _parse_provenance_utc(
        orbit["epoch_utc"],
        "formal provenance orbit epoch_utc",
    )
    if epoch != validated_omm.epoch_utc:
        raise OrbitTraceError("formal provenance OMM epoch disagrees")
    fields = _require_string_mapping(
        orbit["omm_fields"],
        "formal provenance OMM fields",
    )
    if fields != validated_omm.fields:
        raise OrbitTraceError("formal provenance GOMX-1 OMM fields disagree")
    epoch_age = _require_number(
        orbit["epoch_age_seconds"],
        "formal provenance OMM epoch age",
        0.0,
        float(_ORBIT_MODEL["sources"]["maximum_omm_age_hours"]) * 3600.0,
    )
    actual_age = (omm_retrieval - validated_omm.epoch_utc).total_seconds()
    if epoch_age != actual_age:
        raise OrbitTraceError("formal provenance OMM epoch age disagrees")

    outputs = _require_exact_fields(
        provenance["outputs"],
        _OUTPUT_PROVENANCE_FIELDS,
        "formal provenance outputs",
    )
    manifest_artifacts = manifest["Artifacts"]
    if not isinstance(manifest_artifacts, dict):
        raise OrbitTraceError("orbit manifest artifact index must be an object")
    for filename in _OUTPUT_PROVENANCE_FIELDS:
        output_record = _verify_formal_file_record(
            root_path,
            filename,
            outputs[filename],
            f"output provenance {filename}",
        )
        manifest_record = manifest_artifacts[filename]
        if not isinstance(manifest_record, dict):
            raise OrbitTraceError("orbit manifest artifact record must be an object")
        if output_record["byte_count"] != manifest_record["ByteCount"]:
            raise OrbitTraceError("output provenance byte count disagrees with manifest")
        if output_record["sha256"] != manifest_record["Sha256"]:
            raise OrbitTraceError("output provenance hash disagrees with manifest")

    _verify_search_provenance(
        root_path,
        provenance["search"],
        manifest,
        omm_retrieval,
    )


def read_samples_with_exact_header(path: str | Path) -> tuple[dict[str, str], ...]:
    """Read samples.csv only with its frozen snake_case columns and LF bytes.

    Inputs:
        path: Source or artifact path used by this operation.

    Returns:
        Tuple of complete sample dictionaries with the frozen columns.

    Processing flow:
        Raw CSV -> UTF-8/LF validation -> exact snake_case header -> complete
        nonblank rows -> immutable tuple.

    Direct call tree (static source order):
        read_samples_with_exact_header
        +-- _read_exact_csv
        `-- Path
    """
    return _read_exact_csv(Path(path), SAMPLE_CSV_FIELDS, "samples.csv")


def split_exact_records(path: str | Path, width: int = 50) -> tuple[bytes, ...]:
    """Split and validate a mission-record stream with no partial record.

    Inputs:
        path: Source or artifact path used by this operation.
        width: Required mission record width in bytes.

    Returns:
        Tuple of validated records of the required width.

    Processing flow:
        Binary artifact -> exact width divisibility -> record slices -> shared
        mission-record unpack validation -> immutable record tuple.

    Direct call tree (static source order):
        split_exact_records
        +-- isinstance
        +-- OrbitTraceError
        +-- Path
        +-- Path(...).read_bytes
        +-- len
        +-- unpack_mission_record
        +-- records.append
        `-- tuple
    """
    if isinstance(width, bool) or not isinstance(width, int) or width != 50:
        raise OrbitTraceError("mission record width must be exactly 50")
    raw = Path(path).read_bytes()
    if len(raw) % width != 0:
        raise OrbitTraceError("mission record stream has a partial record")
    records: list[bytes] = []
    offset = 0
    while offset < len(raw):
        record = raw[offset : offset + width]
        try:
            unpack_mission_record(record)
        except ValueError as error:
            raise OrbitTraceError("mission record is invalid") from error
        records.append(record)
        offset += width
    return tuple(records)


def _values_close(left: float, right: float) -> bool:
    """Compare reconstructed decimal quantities at the CSV serialization tolerance.

    Inputs:
        left: First reconstructed numeric value.
        right: Second reconstructed numeric value.

    Returns:
        True when the absolute difference is at most 5e-12.

    Processing flow:
        Absolute difference -> project tolerance of 5e-12 -> comparison result

    Direct call tree (static source order):
        _values_close
        `-- abs
    """
    return abs(left - right) <= 0.000000000005


def _validate_dynamic_anchors(
    entries: Sequence[Mapping[str, object]],
    actual_peaks: Sequence[float],
) -> None:
    """Verify five distinct peak levels and equally spaced selection anchors.

    Inputs:
        entries: Manifest artifact map or ordered pass schedule entries.
        actual_peaks: Observed peak elevations in degrees, ordered by selected pass.

    Returns:
        None; raises OrbitTraceError if dynamic anchors are inconsistent.

    Processing flow:
        Anchor bounds -> increasing quantized peaks -> observed range endpoints
        -> five equal anchor intervals within serialization tolerance

    Direct call tree (static source order):
        _validate_dynamic_anchors
        +-- anchors.append
        +-- _require_number
        +-- quantize_peak_elevation_level
        +-- len
        +-- OrbitTraceError
        +-- peak_levels.append
        +-- min
        +-- max
        +-- _values_close
        `-- range
    """
    anchors: list[float] = []
    peak_levels: list[float] = []
    for entry in entries:
        anchors.append(_require_number(entry["TargetPeakElevationDeg"], "TargetPeakElevationDeg", 10.0, 90.0))
    for actual_peak in actual_peaks:
        level = quantize_peak_elevation_level(actual_peak)
        if len(peak_levels) != 0:
            if level <= peak_levels[-1]:
                raise OrbitTraceError(
                    "actual peak levels must be distinct and ordered P1 through P5"
                )
        peak_levels.append(level)
    lowest_level = quantize_peak_elevation_level(min(actual_peaks))
    highest_level = quantize_peak_elevation_level(max(actual_peaks))
    if not _values_close(anchors[0], lowest_level):
        raise OrbitTraceError("first dynamic elevation anchor does not cover the low end")
    if not _values_close(anchors[-1], highest_level):
        raise OrbitTraceError("last dynamic elevation anchor does not cover the high end")
    spacing = (anchors[-1] - anchors[0]) / 4.0
    for index in range(5):
        expected = anchors[0] + spacing * index
        if not _values_close(anchors[index], expected):
            raise OrbitTraceError("dynamic elevation anchors are not range quantiles")


def rebuild_and_verify_pass_schedules(
    rows: Sequence[Mapping[str, str]],
    records: Sequence[bytes],
    manifest: Mapping[str, object],
    pass_rows: Sequence[Mapping[str, str]],
) -> tuple[FrozenOrbitPass, ...]:
    """Rebuild all dynamic schedules and verify identities, timing, and hashes.

    Inputs:
        rows: Ordered sample rows from the frozen CSV.
        records: Validated binary mission records in trace order.
        manifest: Parsed orbit manifest to validate or compare against.
        pass_rows: Pass-summary CSV rows corresponding to the manifest schedules.

    Returns:
        Tuple of reconstructed pass traces with verified payload schedules.

    Processing flow:
        Five manifest/pass entries + sample rows + 50-byte records -> validate
        pass identity/offsets -> enforce 1 Hz and both ID domains -> compare CSV
        mission fields -> recompute schedule hashes -> immutable five-pass tuple.

    Direct call tree (static source order):
        rebuild_and_verify_pass_schedules
        +-- isinstance
        +-- len
        +-- OrbitTraceError
        +-- _require_exact_fields
        +-- _parse_row_integer
        +-- selected_rows.append
        +-- _require_integer
        +-- _parse_row_float
        +-- _require_number
        +-- _values_close
        +-- actual_peaks.append
        +-- bytearray
        +-- _parse_sample_timestamp
        +-- timedelta
        +-- quantized_row_to_mission_record
        +-- pack_mission_record
        +-- orbit_schedule_hash_row
        +-- hash_stream.extend
        +-- payload_samples.append
        +-- PayloadSample
        +-- sha256_bytes
        +-- bytes
        +-- output.append
        +-- FrozenOrbitPass
        +-- PayloadSchedule
        +-- tuple
        `-- _validate_dynamic_anchors
    """
    entries_object = manifest["PassSchedules"]
    if not isinstance(entries_object, list) or len(entries_object) != 5:
        raise OrbitTraceError("orbit manifest must index five passes")
    if len(pass_rows) != 5:
        raise OrbitTraceError("passes.csv must contain five rows")

    output: list[FrozenOrbitPass] = []
    actual_peaks: list[float] = []
    global_cursor = 0
    pass_id = 0
    for entry_object in entries_object:
        entry = _require_exact_fields(
            entry_object,
            _PASS_SCHEDULE_FIELDS,
            "pass schedule",
        )
        pass_row = pass_rows[pass_id]
        if _parse_row_integer(pass_row, "pass_id") != pass_id:
            raise OrbitTraceError("passes.csv pass IDs must be ordered 0 through 4")
        label = f"P{pass_id + 1}"
        if entry["PassId"] != pass_id or entry["PassLabel"] != label:
            raise OrbitTraceError("pass manifest identity disagrees")

        selected_rows: list[Mapping[str, str]] = []
        for row in rows:
            row_pass_id = _parse_row_integer(row, "pass_id")
            if row_pass_id == pass_id:
                selected_rows.append(row)
        count = len(selected_rows)
        if count == 0:
            raise OrbitTraceError("a frozen pass cannot be empty")
        manifest_count = _require_integer(entry["SampleCount"], "SampleCount", 1, 65536)
        csv_count = _parse_row_integer(pass_row, "sample_count")
        if manifest_count != count or csv_count != count:
            raise OrbitTraceError("pass sample counts disagree")
        if entry["ByteOffset"] != global_cursor * 50:
            raise OrbitTraceError("pass manifest byte offset disagrees")
        if entry["ByteCount"] != count * 50:
            raise OrbitTraceError("pass manifest byte count disagrees")
        if entry["FirstTraceSampleId"] != global_cursor:
            raise OrbitTraceError("pass first TraceSampleId disagrees")
        if entry["LastTraceSampleId"] != global_cursor + count - 1:
            raise OrbitTraceError("pass last TraceSampleId disagrees")

        target_peak = _parse_row_float(pass_row, "target_peak_elevation_deg")
        actual_peak = _parse_row_float(pass_row, "actual_peak_elevation_deg")
        manifest_target = _require_number(entry["TargetPeakElevationDeg"], "TargetPeakElevationDeg", 10.0, 90.0)
        manifest_actual = _require_number(entry["ActualPeakElevationDeg"], "ActualPeakElevationDeg", 10.0, 90.0)
        if not _values_close(target_peak, manifest_target):
            raise OrbitTraceError("dynamic elevation anchor disagrees with passes.csv")
        if not _values_close(actual_peak, manifest_actual):
            raise OrbitTraceError("actual peak elevation disagrees with passes.csv")
        actual_peaks.append(actual_peak)

        payload_samples: list[PayloadSample] = []
        hash_stream = bytearray()
        previous_timestamp: datetime | None = None
        maximum_saved_elevation = -90.0
        local_index = 0
        for row in selected_rows:
            trace_id = _parse_row_integer(row, "trace_sample_id")
            if trace_id != global_cursor + local_index:
                raise OrbitTraceError("TraceSampleId is not dataset-global")
            parsed_local_index = _parse_row_integer(row, "pass_sample_index")
            if parsed_local_index != local_index:
                raise OrbitTraceError("PassSampleIndex is not pass-local")
            trace_time_ms = _parse_row_integer(row, "trace_time_ms")
            if trace_time_ms != local_index * 1000:
                raise OrbitTraceError("trace_time_ms is not pass-local 1 Hz time")

            timestamp = _parse_sample_timestamp(row["timestamp_utc"])
            if previous_timestamp is not None:
                if timestamp - previous_timestamp != timedelta(seconds=1):
                    raise OrbitTraceError("pass samples are not on a 1 Hz grid")
            previous_timestamp = timestamp
            elevation = _parse_row_float(row, "elevation_deg")
            if elevation < 10.0 or elevation > 90.0:
                raise OrbitTraceError("saved elevation is outside 10 to 90 degrees")
            if elevation > maximum_saved_elevation:
                maximum_saved_elevation = elevation
            row_target = _parse_row_float(row, "target_peak_elevation_deg")
            row_actual = _parse_row_float(row, "actual_peak_elevation_deg")
            if not _values_close(row_target, manifest_target):
                raise OrbitTraceError("sample dynamic elevation anchor disagrees")
            if not _values_close(row_actual, manifest_actual):
                raise OrbitTraceError("sample actual peak elevation disagrees")

            record = records[trace_id]
            try:
                expected_record = quantized_row_to_mission_record(row)
                expected_bytes = pack_mission_record(expected_record)
            except (OrbitDatasetError, ValueError) as error:
                raise OrbitTraceError("sample mission record fields are invalid") from error
            if record != expected_bytes:
                raise OrbitTraceError("mission record disagrees with samples.csv")

            requested = _parse_row_float(row, "doppler_hz")
            programmed = _parse_row_float(row, "programmed_doppler_hz")
            reg_frf_word = _parse_row_integer(row, "reg_frf_word")
            if reg_frf_word < 0 or reg_frf_word > 16777215:
                raise OrbitTraceError("RegFrfWord must fit uint24")
            packed_hash_row = orbit_schedule_hash_row(
                trace_id,
                local_index,
                requested,
                programmed,
                reg_frf_word,
                record,
            )
            hash_stream.extend(packed_hash_row)
            payload_samples.append(
                PayloadSample(
                    trace_sample_id=trace_id,
                    pass_sample_index=local_index,
                    requested_cfo_hz=requested,
                    programmed_cfo_hz=programmed,
                    reg_frf_word=reg_frf_word,
                    mission_record=record,
                )
            )
            local_index += 1
        if not _values_close(maximum_saved_elevation, manifest_actual):
            raise OrbitTraceError("actual peak does not equal saved sample maximum")
        digest = sha256_bytes(bytes(hash_stream))
        if digest != entry["ScheduleSha256"]:
            raise OrbitTraceError("pass schedule hash mismatch")
        output.append(
            FrozenOrbitPass(
                pass_id=pass_id,
                pass_label=label,
                sample_count=count,
                schedule=PayloadSchedule(
                    schedule_id=f"{manifest['DatasetId']}:{label}",
                    samples=tuple(payload_samples),
                    schedule_sha256=digest,
                ),
            )
        )
        global_cursor += count
        pass_id += 1

    if global_cursor != len(rows) or global_cursor != len(records):
        raise OrbitTraceError("orbit rows include unknown or duplicate passes")
    _validate_dynamic_anchors(entries_object, actual_peaks)
    return tuple(output)


def load_frozen_orbit_dataset(
    root: str | Path,
    *,
    require_formal_provenance: bool = False,
) -> FrozenOrbitDataset:
    """Load a Level 1 orbit dataset only after complete fail-closed validation.

    Inputs:
        root: Frozen Level 1 dataset directory.
        require_formal_provenance: Whether to require the measured-data source and historical-search contract.

    Returns:
        FrozenOrbitDataset whose artifacts and schedules have all passed validation.

    Processing flow:
        Dataset path -> canonical manifest and closed shape -> raw artifact hashes
        -> optional measured-data source/provenance gate -> exact snake_case CSVs
        and 50-byte records -> dynamic schedule rebuild -> count/hash/identity
        agreement -> immutable FrozenOrbitDataset.

    Direct call tree (static source order):
        load_frozen_orbit_dataset
        +-- isinstance
        +-- TypeError
        +-- Path
        +-- manifest_path.read_bytes
        +-- json.loads
        +-- OrbitTraceError
        +-- canonical_json_bytes
        +-- _validate_manifest_shape
        +-- verify_level1_artifact_hashes
        +-- validate_formal_level1_provenance
        +-- _read_exact_csv
        +-- read_samples_with_exact_header
        +-- split_exact_records
        +-- _require_integer
        +-- len
        +-- rebuild_and_verify_pass_schedules
        +-- FrozenOrbitDataset
        `-- sha256_bytes
    """
    if not isinstance(require_formal_provenance, bool):
        raise TypeError("require_formal_provenance must be bool")
    root_path = Path(root)
    manifest_path = root_path / "orbit_manifest.json"
    raw_manifest = manifest_path.read_bytes()
    try:
        parsed_manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OrbitTraceError("orbit manifest is not valid UTF-8 JSON") from error
    try:
        expected_bytes = canonical_json_bytes(parsed_manifest)
    except (TypeError, ValueError) as error:
        raise OrbitTraceError("orbit manifest is not canonical JSON") from error
    if raw_manifest != expected_bytes:
        raise OrbitTraceError("orbit manifest is not canonical JSON")
    manifest = _validate_manifest_shape(parsed_manifest)
    artifacts_object = manifest["Artifacts"]
    if not isinstance(artifacts_object, dict):
        raise OrbitTraceError("artifact index must be an object")
    verify_level1_artifact_hashes(root_path, artifacts_object)
    if require_formal_provenance:
        validate_formal_level1_provenance(root_path, manifest)

    pass_rows = _read_exact_csv(root_path / "passes.csv", PASS_CSV_FIELDS, "passes.csv")
    sample_rows = read_samples_with_exact_header(root_path / "samples.csv")
    records = split_exact_records(root_path / "mission_records.bin")
    manifest_count = _require_integer(manifest["SampleCount"], "SampleCount", 0, 65536)
    if len(sample_rows) != len(records) or len(sample_rows) != manifest_count:
        raise OrbitTraceError("Level 1 sample counts disagree")
    passes = rebuild_and_verify_pass_schedules(
        sample_rows,
        records,
        manifest,
        pass_rows,
    )
    dataset_id = manifest["DatasetId"]
    if not isinstance(dataset_id, str):
        raise OrbitTraceError("DatasetId must be text")
    return FrozenOrbitDataset(
        dataset_id=dataset_id,
        root=root_path,
        passes=passes,
        sample_count=len(sample_rows),
        manifest_sha256=sha256_bytes(raw_manifest),
    )
