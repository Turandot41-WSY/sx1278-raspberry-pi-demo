"""Generate or reproduce the deterministic GOMX-1/Linz orbit dataset.

Configuration: config/main_dataset.toml [acquire]
Shared model: config/main_dataset.toml
Function call tree :
run()
+-- _parse_args(): Read configuration and command arguments
|   `-- host.common.runtime_config.parse_configured_args(: )Merge config/main_dataset.toml with command overrides
+-- [fetch] host.dataset.orbit_dataset.fetch_source():  Download OMM and IERS-A and record retrieval times
+-- [fetch] _freeze_fetched_dataset(): Create a directory named by launch time and publish the dataset
|   +-- host.dataset.orbit_dataset.generate_dataset_files(): Generate a complete dataset from raw sources
|   |   +-- load_validated_omm(): Parse OMM and construct the Satrec propagation model
|   |   +-- load_frozen_iers_a(): Load local Earth orientation data
|   |   +-- [adaptive window] select_adaptive_past_passes(): Extend the historical search window one day at a time
|   |   |   +-- generate_candidate_passes(): Find complete passes within the search window
|   |   |   |   +-- iter_utc_second_chunks(): Generate a time grid at one-second intervals
|   |   |   |   +-- host.dataset.orbit_geometry.propagate_itrs(): Propagate with SGP4 and transform TEME to ITRS
|   |   |   |   +-- host.dataset.orbit_geometry.compute_geometry_sample(): Compute range, elevation, and Doppler shift
|   |   |   |   `-- CompletePassAccumulator.consume(): Accumulate passes as elevation crosses the mask
|   |   |   `-- select_distinct_passes(): Select five distinct passes by peak elevation
|   |   +-- [fixed window] generate_candidate_passes() -> select_distinct_passes()
|   |   +-- write_dataset_csvs(): Save pass summaries and samples at one-second intervals
|   |   +-- write_mission_record_stream(): Save the stream of 50-byte records
|   |   +-- write_dataset_provenance(): Record sources, computation settings, and file hashes
|   |   `-- write_orbit_manifest(): Save the dataset manifest for subsequent transmission
|   +-- validate_level1_publication(): Reload and validate the publication contents
|   `-- _fsync_publication_tree(): Synchronize files before publication by directory rename
`-- [offline] _regenerate_offline_dataset(): Recompute from the selected dataset sources
    +-- _source_from_provenance(): Validate source bytes and reconstruct FetchedSource
    +-- host.dataset.orbit_dataset.generate_dataset_files(): Recompute using the recorded search window
    `-- compare_offline_artifacts(): Compare four derived files byte for byte
"""

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


from host.common.runtime_config import configured_path, load_settings, parse_configured_args
from host.common.canonical import fsync_directory, sha256_file
from host.dataset.orbit_dataset import (
    FetchedSource,
    fetch_source,
    generate_dataset_files,
    sha256_bytes,
)
from host.dataset.orbit_trace import OrbitTraceError, load_frozen_orbit_dataset


_DATASET_SETTINGS = load_settings("main_dataset")["acquire"]
_ORBIT_MODEL = load_settings("main_dataset")["orbit_model"]
CELESTRAK_GOMX1_OMM_URL = _ORBIT_MODEL["sources"]["omm_url"]
IERS_A_URL = _ORBIT_MODEL["sources"]["iers_a_url"]
_SOURCE_SPECS = (
    ("gomx1_39430.omm.xml", CELESTRAK_GOMX1_OMM_URL),
    ("iers_a_finals2000A.all", IERS_A_URL),
)
LEVEL1_ARTIFACT_NAMES = (
    "passes.csv",
    "samples.csv",
    "mission_records.bin",
    "orbit_manifest.json",
)
# Each fetch gets its own UTC launch-time directory (including microseconds).
# See docs/adr/0001-direct-experiment-workflow.md, Dataset identity.
DATASET_ROOT = configured_path(_DATASET_SETTINGS["output_root"])


def compare_offline_artifacts(
    rebuilt: str | Path,
    expected: str | Path,
) -> dict[str, str]:
    """Compare every reproducible Level 1 artifact byte for byte.

    Inputs:
        rebuilt: Directory containing newly reproduced artifacts.
        expected: Directory containing the frozen reference artifacts.

    Returns:
        Mapping of artifact filenames to SHA-256 digests after exact equality checks.

    Processing flow:
        Rebuilt and frozen directories -> compare four ordered artifacts ->
        reject all named mismatches -> ordered raw SHA-256 result mapping.

    Direct call tree (static source order):
        compare_offline_artifacts
        +-- Path
        +-- rebuilt_file.is_file
        +-- expected_file.is_file
        +-- mismatches.append
        +-- rebuilt_file.read_bytes
        +-- expected_file.read_bytes
        +-- len
        +-- <str literal>.join
        +-- RuntimeError
        `-- sha256_file
    """
    rebuilt_path = Path(rebuilt)
    expected_path = Path(expected)
    mismatches: list[str] = []
    for artifact_name in LEVEL1_ARTIFACT_NAMES:
        rebuilt_file = rebuilt_path / artifact_name
        expected_file = expected_path / artifact_name
        if not rebuilt_file.is_file() or not expected_file.is_file():
            mismatches.append(artifact_name)
            continue
        if rebuilt_file.read_bytes() != expected_file.read_bytes():
            mismatches.append(artifact_name)
    if len(mismatches) != 0:
        names = ", ".join(mismatches)
        raise RuntimeError(f"offline rebuild differs for artifacts: {names}")
    hashes: dict[str, str] = {}
    for artifact_name in LEVEL1_ARTIFACT_NAMES:
        hashes[artifact_name] = sha256_file(rebuilt_path / artifact_name)
    return hashes


def validate_level1_publication(dataset_directory: str | Path) -> None:
    """Fail closed unless a staged directory is a complete Level 1 dataset.

    Inputs:
        dataset_directory: Frozen or staged dataset directory to inspect.

    Returns:
        None after the staged dataset passes publication checks.

    Processing flow:
        Staged directory -> strict derived-artifact loader -> two frozen source
        files and source-provenance hashes -> publication approval or rejection.

    Direct call tree (static source order):
        validate_level1_publication
        +-- Path
        +-- load_frozen_orbit_dataset
        +-- ValueError
        +-- <BinOp expression>.is_file
        +-- json.loads
        +-- provenance_path.read_text
        +-- isinstance
        +-- provenance_value.get
        +-- sources_value.get
        +-- source_record.get
        `-- _source_from_provenance
    """
    dataset_path = Path(dataset_directory)
    try:
        load_frozen_orbit_dataset(
            dataset_path,
            require_formal_provenance=True,
        )
    except (FileNotFoundError, OrbitTraceError) as error:
        raise ValueError(f"invalid Level 1 publication: {error}") from error
    for artifact_name in LEVEL1_ARTIFACT_NAMES:
        if not (dataset_path / artifact_name).is_file():
            raise ValueError(f"missing Level 1 artifact: {artifact_name}")
    provenance_path = dataset_path / "provenance.json"
    try:
        provenance_value = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid Level 1 source provenance") from error
    if not isinstance(provenance_value, dict):
        raise ValueError("Level 1 source provenance must be an object")
    sources_value = provenance_value.get("sources")
    if not isinstance(sources_value, dict):
        raise ValueError("Level 1 source provenance is missing sources")
    source_specs = (
        ("omm", "gomx1_39430.omm.xml"),
        ("iers_a", "iers_a_finals2000A.all"),
    )
    for source_key, filename in source_specs:
        source_record = sources_value.get(source_key)
        if not isinstance(source_record, dict):
            raise ValueError("Level 1 source provenance is missing " + source_key)
        expected_filename = "source/" + filename
        if source_record.get("filename") != expected_filename:
            raise ValueError("Level 1 source provenance filename disagrees")
        try:
            _source_from_provenance(dataset_path, source_record, filename)
        except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid Level 1 source provenance") from error


def _fsync_publication_tree(dataset_directory: Path) -> None:
    """Flush staged dataset files and directories before publication.

    Inputs:
        dataset_directory: Frozen or staged dataset directory to inspect.

    Returns:
        None after staged contents and directory metadata are synchronized.

    Processing flow:
        Discover and order files -> fsync file contents -> optional source directory
        -> dataset directory metadata

    Direct call tree (static source order):
        _fsync_publication_tree
        +-- dataset_directory.rglob
        +-- path.is_file
        +-- paths.append
        +-- paths.sort
        +-- path.open
        +-- os.fsync
        +-- stream.fileno
        +-- source_directory.is_dir
        `-- fsync_directory
    """
    paths: list[Path] = []
    for path in dataset_directory.rglob("*"):
        if path.is_file():
            paths.append(path)
    paths.sort()
    for path in paths:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    source_directory = dataset_directory / "source"
    if source_directory.is_dir():
        fsync_directory(source_directory)
    fsync_directory(dataset_directory)


def _parse_args(arguments: Sequence[str] | None) -> argparse.Namespace:
    """Parse acquisition options and validate the configured search window.

    Inputs:
        arguments: Command arguments, or None to read the process command line.

    Returns:
        Validated argparse namespace.

    Processing flow:
        Fetch/offline mode -> config and command overrides -> paired search endpoints
        -> positive chunk/lookback lengths -> thirty-day limit

    Direct call tree (static source order):
        _parse_args
        +-- argparse.ArgumentParser
        +-- parser.add_mutually_exclusive_group
        +-- mode.add_argument
        +-- parser.add_argument
        +-- parse_configured_args
        `-- parser.error
    """
    parser = argparse.ArgumentParser(
        description="Freeze online sources or reproduce a frozen orbit dataset."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fetch",
        action="store_true",
        help="retrieve approved sources and atomically generate the dataset",
    )
    mode.add_argument(
        "--offline",
        type=Path,
        metavar="DATASET_DIRECTORY",
        help="reproduce frozen outputs without making network requests",
    )
    parser.add_argument("--output-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--search-start-utc", type=_parse_utc)
    parser.add_argument("--search-end-utc", type=_parse_utc)
    parser.add_argument("--chunk-days", type=int, default=_DATASET_SETTINGS["chunk_days"])
    parser.add_argument("--maximum-lookback-days", type=int, default=_DATASET_SETTINGS["maximum_lookback_days"])
    parser.add_argument("--generator-git-commit", default="")
    options = parse_configured_args(parser, arguments, "main_dataset", section="acquire")
    if (options.search_start_utc is None) != (options.search_end_utc is None):
        parser.error("search_start_utc and search_end_utc must be supplied together")
    if options.chunk_days <= 0 or options.maximum_lookback_days <= 0:
        parser.error("chunk_days and maximum_lookback_days must be positive")
    if options.maximum_lookback_days > 30:
        parser.error("maximum_lookback_days must not exceed 30")
    return options


def _report_fetched_source(filename: str, source: FetchedSource) -> None:
    """Print retrieval metadata and the digest of a downloaded source.

    Inputs:
        filename: Exact source or artifact filename.
        source: Retrieved source bytes, timestamp, URL, and response headers.

    Returns:
        None; writes one source summary to standard output.

    Processing flow:
        Source response -> last-modified fallback -> URL/time/size/hash report

    Direct call tree (static source order):
        _report_fetched_source
        +-- source.headers.get
        +-- print
        +-- source.retrieved_at_utc.isoformat
        +-- len
        `-- sha256_bytes
    """
    last_modified = source.headers.get("Last-Modified", "unavailable")
    print(
        f"{filename}: url={source.url} "
        f"retrieved_at_utc={source.retrieved_at_utc.isoformat()} "
        f"bytes={len(source.content)} sha256={sha256_bytes(source.content)} "
        f"last_modified={last_modified}"
    )


def _report_offline_source(dataset_directory: Path, filename: str) -> None:
    """Print the location and digest of an existing frozen source.

    Inputs:
        dataset_directory: Frozen or staged dataset directory to inspect.
        filename: Exact source or artifact filename.

    Returns:
        None; writes one source summary to standard output.

    Processing flow:
        Dataset source path -> exact bytes -> size and hash report

    Direct call tree (static source order):
        _report_offline_source
        +-- source_path.read_bytes
        +-- print
        +-- len
        `-- sha256_bytes
    """
    source_path = dataset_directory / "source" / filename
    content = source_path.read_bytes()
    print(
        f"{filename}: path={source_path} bytes={len(content)} "
        f"sha256={sha256_bytes(content)}"
    )


def _freeze_fetched_dataset(
    *,
    omm_source: FetchedSource,
    iers_source: FetchedSource,
    started_at_utc: datetime,
    generator_git_commit: str = "",
    dataset_root: Path = DATASET_ROOT,
    search_start_utc: datetime | None = None,
    search_end_utc: datetime | None = None,
    chunk_days: int = _DATASET_SETTINGS["chunk_days"],
    maximum_lookback_days: int = _DATASET_SETTINGS["maximum_lookback_days"],
) -> Path:
    """Publish a verified dataset in a directory named by launch time.

    Inputs:
        omm_source: Frozen OMM XML response and its retrieval metadata.
        iers_source: Frozen IERS-A response and its retrieval metadata.
        started_at_utc: Launch instant used to name the dataset publication.
        generator_git_commit: Optional Git commit text recorded as generator metadata.
        dataset_root: Parent directory for new dataset publications.
        search_start_utc: Inclusive beginning of the propagation search, or None for adaptive search.
        search_end_utc: Exclusive end of the propagation search, or None for adaptive search.
        chunk_days: Maximum propagation chunk length in days.
        maximum_lookback_days: Maximum historical search window in days.

    Returns:
        Path to the published immutable dataset directory.

    Processing flow:
        UTC dataset identity -> collision rejection -> temporary generation
        -> Level 1 validation -> fsync -> directory rename -> parent fsync

    Direct call tree (static source order):
        _freeze_fetched_dataset
        +-- started_at_utc.astimezone
        +-- started_at_utc.astimezone(...).strftime
        +-- dataset_root.mkdir
        +-- final_directory.exists
        +-- FileExistsError
        +-- tempfile.TemporaryDirectory
        +-- Path
        +-- generate_dataset_files
        +-- validate_level1_publication
        +-- _fsync_publication_tree
        +-- staged_directory.replace
        `-- fsync_directory
    """
    dataset_id = started_at_utc.astimezone(UTC).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    dataset_root.mkdir(parents=True, exist_ok=True)
    final_directory = dataset_root / dataset_id
    if final_directory.exists():
        raise FileExistsError(
            f"refusing to overwrite existing dataset: {final_directory}"
        )

    with tempfile.TemporaryDirectory(
        prefix=".gomx1-staging-",
        dir=dataset_root,
    ) as temporary_directory:
        staged_directory = Path(temporary_directory) / dataset_id
        generate_dataset_files(
            staged_directory,
            omm_source=omm_source,
            iers_source=iers_source,
            generator_git_commit=generator_git_commit,
            dataset_id=dataset_id,
            search_start_utc=search_start_utc,
            search_end_utc=search_end_utc,
            chunk_days=chunk_days,
            maximum_lookback_days=maximum_lookback_days,
        )
        validate_level1_publication(staged_directory)
        _fsync_publication_tree(staged_directory)
        staged_directory.replace(final_directory)
        fsync_directory(dataset_root)
    return final_directory


def _parse_utc(value: str) -> datetime:
    """Parse an acquisition timestamp that ends with a literal Z.

    Inputs:
        value: Candidate field or provenance object to validate.

    Returns:
        UTC datetime parsed from the command or provenance text.

    Processing flow:
        Literal Z suffix -> ISO timestamp parser with UTC offset -> datetime

    Direct call tree (static source order):
        _parse_utc
        +-- value.endswith
        +-- ValueError
        `-- datetime.fromisoformat
    """
    if not value.endswith("Z"):
        raise ValueError(f"expected UTC timestamp ending in Z: {value!r}")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _validated_frozen_file(
    path: Path,
    record: dict[str, Any],
    label: str,
) -> tuple[bytes, str]:
    """Read a frozen file only when its provenance size and digest agree.

    Inputs:
        path: Source or artifact path used by this operation.
        record: Recorded byte count and SHA-256 for the frozen file.
        label: Field or artifact name included in validation errors.

    Returns:
        Tuple of verified bytes and their SHA-256 digest.

    Processing flow:
        Recorded hash syntax -> recorded nonnegative size -> raw file bytes
        -> byte-count comparison -> SHA-256 comparison

    Direct call tree (static source order):
        _validated_frozen_file
        +-- ValueError
        +-- isinstance
        +-- len
        +-- path.read_bytes
        `-- sha256_bytes
    """
    if "sha256" not in record:
        raise ValueError(f"{label} provenance is missing sha256")
    recorded_digest = record["sha256"]
    invalid_digest = not isinstance(recorded_digest, str)
    if isinstance(recorded_digest, str):
        if len(recorded_digest) != 64:
            invalid_digest = True
        for character in recorded_digest:
            if character not in "0123456789abcdef":
                invalid_digest = True
    if invalid_digest:
        raise ValueError(f"{label} provenance sha256 must be 64 lowercase hex digits")
    if "byte_count" not in record:
        raise ValueError(f"{label} provenance is missing byte_count")
    recorded_byte_count = record["byte_count"]
    if (
        not isinstance(recorded_byte_count, int)
        or isinstance(recorded_byte_count, bool)
        or recorded_byte_count < 0
    ):
        raise ValueError(f"{label} provenance byte_count must be a nonnegative integer")

    content = path.read_bytes()
    if len(content) != recorded_byte_count:
        raise ValueError(f"{label} byte_count differs from provenance")
    actual_digest = sha256_bytes(content)
    if actual_digest != recorded_digest:
        raise ValueError(f"{label} sha256 differs from provenance")
    return content, actual_digest


def _source_from_provenance(
    dataset_directory: Path,
    source_record: dict[str, Any],
    filename: str,
) -> FetchedSource:
    """Reconstruct a fetched source from its verified frozen bytes and metadata.

    Inputs:
        dataset_directory: Frozen or staged dataset directory to inspect.
        source_record: Frozen source provenance including retrieval metadata and digest.
        filename: Exact source or artifact filename.

    Returns:
        FetchedSource containing the original frozen bytes.

    Processing flow:
        Frozen source path -> byte/hash validation -> HTTP header mapping
        -> retrieval timestamp and URL -> source object

    Direct call tree (static source order):
        _source_from_provenance
        +-- _validated_frozen_file
        +-- source_record.get
        +-- isinstance
        +-- ValueError
        +-- source_headers.items
        +-- str
        +-- FetchedSource
        `-- _parse_utc
    """
    content, _digest = _validated_frozen_file(
        dataset_directory / "source" / filename,
        source_record,
        f"source {filename}",
    )
    headers: dict[str, str] = {}
    source_headers = source_record.get("http_headers", {})
    if not isinstance(source_headers, dict):
        raise ValueError("source provenance http_headers must be an object")
    for name, value in source_headers.items():
        headers[str(name)] = str(value)
    return FetchedSource(
        url=str(source_record["url"]),
        retrieved_at_utc=_parse_utc(str(source_record["retrieved_at_utc"])),
        headers=headers,
        content=content,
    )


def _regenerate_offline_dataset(
    dataset_directory: Path,
) -> dict[str, str]:
    """Reproduce a frozen dataset and compare its derived artifacts byte for byte.

    Inputs:
        dataset_directory: Frozen or staged dataset directory to inspect.

    Returns:
        Dictionary of the reproduced artifact digests.

    Processing flow:
        Formal Level 1 validation -> reconstruct frozen sources -> verify output records
        -> temporary regeneration using recorded search -> exact artifact comparisons

    Direct call tree (static source order):
        _regenerate_offline_dataset
        +-- dataset_directory.resolve
        +-- load_frozen_orbit_dataset
        +-- json.loads
        +-- <BinOp expression>.read_text
        +-- _source_from_provenance
        +-- provenance.get
        +-- isinstance
        +-- ValueError
        +-- output_records.get
        +-- _validated_frozen_file
        +-- tempfile.TemporaryDirectory
        +-- Path
        +-- generate_dataset_files
        +-- str
        +-- _parse_utc
        +-- int
        `-- compare_offline_artifacts
    """
    dataset_path = dataset_directory.resolve(strict=True)
    frozen_dataset = load_frozen_orbit_dataset(
        dataset_path,
        require_formal_provenance=True,
    )
    provenance = json.loads(
        (dataset_path / "provenance.json").read_text(encoding="utf-8")
    )
    omm_source = _source_from_provenance(
        dataset_path,
        provenance["sources"]["omm"],
        "gomx1_39430.omm.xml",
    )
    iers_source = _source_from_provenance(
        dataset_path,
        provenance["sources"]["iers_a"],
        "iers_a_finals2000A.all",
    )
    search = provenance["search"]
    generator = provenance["generator"]
    output_records = provenance.get("outputs")
    if not isinstance(output_records, dict):
        raise ValueError("provenance outputs is missing passes.csv")
    provenance_artifacts = (
        "passes.csv",
        "samples.csv",
        "mission_records.bin",
    )
    for filename in provenance_artifacts:
        output_record = output_records.get(filename)
        if not isinstance(output_record, dict):
            raise ValueError(f"provenance outputs is missing {filename}")
        _validated_frozen_file(
            dataset_path / filename,
            output_record,
            f"output {filename}",
        )

    with tempfile.TemporaryDirectory(
        prefix=".gomx1-reproduction-",
        dir=dataset_path.parent,
    ) as temporary_directory:
        regenerated_directory = Path(temporary_directory) / dataset_path.name
        regenerated = generate_dataset_files(
            regenerated_directory,
            omm_source=omm_source,
            iers_source=iers_source,
            generator_git_commit=str(generator["git_commit"]),
            search_start_utc=_parse_utc(str(search["start_utc"])),
            search_end_utc=_parse_utc(str(search["end_utc"])),
            chunk_days=int(search["chunk_days"]),
            dataset_id=frozen_dataset.dataset_id,
        )
        return compare_offline_artifacts(
            regenerated.dataset_directory,
            dataset_path,
        )


def _fetch_and_freeze(options) -> Path:
    """Download approved sources and return the published dataset directory.

    Processing flow:
        Acquisition settings -> download frozen inputs -> generate and validate
        five passes -> publish one immutable directory -> return its exact path.

    Direct call tree (static source order):
        _fetch_and_freeze
        +-- datetime.now
        +-- print
        +-- started_at_utc.isoformat
        +-- fetch_source
        +-- _report_fetched_source
        +-- _freeze_fetched_dataset
        `-- dataset_path.resolve
    """
    started_at_utc = datetime.now(UTC)
    print(f"started_at_utc={started_at_utc.isoformat()}", flush=True)
    fetched_sources: dict[str, FetchedSource] = {}
    for filename, url in _SOURCE_SPECS:
        print(f"[Dataset] Downloading {filename}...", flush=True)
        source = fetch_source(url)
        fetched_sources[filename] = source
        _report_fetched_source(filename, source)
    print("[Dataset] Generating and validating five complete passes...", flush=True)
    dataset_path = _freeze_fetched_dataset(
        omm_source=fetched_sources["gomx1_39430.omm.xml"],
        iers_source=fetched_sources["iers_a_finals2000A.all"],
        started_at_utc=started_at_utc,
        dataset_root=options.output_root,
        search_start_utc=options.search_start_utc,
        search_end_utc=options.search_end_utc,
        chunk_days=options.chunk_days,
        maximum_lookback_days=options.maximum_lookback_days,
        generator_git_commit=options.generator_git_commit,
    )
    print(f"dataset_path={dataset_path.resolve()}", flush=True)
    print("[Dataset] Dataset saved and validated.", flush=True)
    return dataset_path.resolve()


def fetch_latest_dataset() -> Path:
    """Acquire a fresh five-pass dataset using the main dataset configuration.

    Processing flow:
        main_dataset acquire settings -> explicit online selection -> shared
        acquisition pipeline -> exact published directory, or an error.

    Direct call tree (static source order):
        fetch_latest_dataset
        +-- _parse_args
        `-- _fetch_and_freeze
    """
    options = _parse_args(['--fetch'])
    return _fetch_and_freeze(options)


def run(arguments: Sequence[str] | None = None) -> int:
    """Fetch a new timestamped dataset or reproduce an existing directory.

    Inputs:
        arguments: Command arguments, or None to read the process command line.

    Returns:
        Process exit status after fetching or reproducing the dataset.

    Processing flow:
        --fetch: launch time -> download sources -> generate -> publish directory.
        --offline: existing directory -> reconstruct -> compare artifact bytes.

    Direct call tree (static source order):
        run
        +-- _parse_args
        +-- _fetch_and_freeze
        +-- print
        +-- options.offline.resolve
        +-- _report_offline_source
        +-- _regenerate_offline_dataset
        `-- hashes.items
    """
    options = _parse_args(arguments)
    if options.fetch:
        _fetch_and_freeze(options)
        return 0

    print(f"dataset_path={options.offline.resolve(strict=True)}")
    for filename, _url in _SOURCE_SPECS:
        _report_offline_source(options.offline, filename)
    hashes = _regenerate_offline_dataset(options.offline)
    for filename, digest in hashes.items():
        print(f"reproduced {filename}: sha256={digest}")
    return 0
