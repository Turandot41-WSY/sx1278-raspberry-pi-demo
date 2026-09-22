"""Deterministic byte and scalar encodings for immutable data artifacts."""

import csv
import hashlib
import io
import json
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path


_RFC3339_UTC_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*|-[1-9][0-9]*)$")


def canonical_json_bytes(value: object, *, trailing_lf: bool = True) -> bytes:
    """Encode one value as deterministic UTF-8 JSON bytes.

    Processing flow:
        Python value
             |
             v
        Reject non-JSON finite-number violations
             |
             v
        Sort object keys and remove insignificant whitespace
             |
             v
        UTF-8 bytes + optional single trailing LF

    Direct call tree (static source order):
        canonical_json_bytes
        +-- json.dumps
        `-- json.dumps(...).encode
    """
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if trailing_lf:
        return encoded + b"\n"
    return encoded


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of bytes.

    References:
        NIST FIPS PUB 180-4, ``Secure Hash Standard``, August 2015,
        section 6.2, ``SHA-256``.

    Direct call tree (static source order):
        sha256_bytes
        +-- hashlib.sha256
        `-- hashlib.sha256(...).hexdigest
    """
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of a file's original bytes.

    References:
        NIST FIPS PUB 180-4, ``Secure Hash Standard``, August 2015,
        section 6.2, ``SHA-256``.

    Processing flow:
        File path -> bounded binary chunks -> incremental SHA-256 -> hex digest

    Direct call tree (static source order):
        sha256_file
        +-- hashlib.sha256
        +-- Path
        +-- Path(...).open
        +-- source.read
        +-- digest.update
        `-- digest.hexdigest
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if chunk == b"":
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_canonical_csv(
    path: str | Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> Path:
    """Write an immutable UTF-8 RFC 4180-style CSV with an exact header.

    References:
        RFC 4180, October 2005, section 2.

    Processing flow:
        Frozen columns + rows
                |
                v
        Validate every row has exactly the frozen columns
                |
                v
        Serialize UTF-8 CSV with LF line endings
                |
                v
        Exclusive file write, file fsync, directory fsync

    Direct call tree (static source order):
        write_canonical_csv
        +-- tuple
        +-- len
        +-- set
        +-- ValueError
        +-- io.StringIO
        +-- csv.DictWriter
        +-- writer.writeheader
        +-- enumerate
        +-- writer.writerow
        +-- dict
        +-- Path
        +-- buffer.getvalue
        +-- csv_text.encode
        `-- write_bytes_exclusive
    """
    frozen_columns = tuple(columns)
    if not frozen_columns or len(set(frozen_columns)) != len(frozen_columns):
        raise ValueError("columns must be non-empty and unique")

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=frozen_columns,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    expected = set(frozen_columns)
    for row_number, row in enumerate(rows, start=1):
        if set(row) != expected:
            raise ValueError(
                f"row {row_number} columns must exactly match the frozen header"
            )
        writer.writerow(dict(row))

    destination = Path(path)
    csv_text = buffer.getvalue()
    csv_bytes = csv_text.encode("utf-8")
    write_bytes_exclusive(destination, csv_bytes)
    return destination


def fsync_directory(path: str | Path) -> None:
    """Persist directory-entry changes for one existing directory.

    Processing flow:
        Existing directory path -> open directory descriptor -> flush entry updates -> close descriptor even on failure.

    Direct call tree (static source order):
        fsync_directory
        +-- getattr
        +-- os.open
        +-- Path
        +-- os.fsync
        `-- os.close
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    file_descriptor = os.open(Path(path), flags)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)

def write_bytes_exclusive(path: str | Path, content: bytes) -> Path:
    """Create and durably write one file without replacing an existing artifact.

    Processing flow:
        Destination + bytes
               |
               v
        Create parent and open destination exclusively
               |
               v
        Write all bytes, flush, and fsync file
               |
               v
        Fsync parent directory -> durable immutable artifact

    Direct call tree (static source order):
        write_bytes_exclusive
        +-- Path
        +-- destination.parent.mkdir
        +-- destination.open
        +-- output.write
        +-- output.flush
        +-- os.fsync
        +-- output.fileno
        `-- fsync_directory
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    fsync_directory(destination.parent)
    return destination

def format_rfc3339_utc(value: datetime) -> str:
    """Format a timezone-aware instant as canonical microsecond UTC text.

    References:
        RFC 3339, July 2002, sections 5.6 and 5.8.

    Processing flow:
        datetime -> require an original UTC offset of zero
                 -> render six fractional digits and literal Z

    Direct call tree (static source order):
        format_rfc3339_utc
        +-- value.utcoffset
        +-- timedelta
        +-- ValueError
        `-- value.strftime
    """
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("value must be timezone-aware UTC")
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_rfc3339_utc(text: str) -> datetime:
    """Parse only the project's canonical microsecond UTC timestamp form.

    References:
        RFC 3339, July 2002, sections 5.6 and 5.8.

    Processing flow:
        Text -> require the canonical lexical form
             -> parse fields -> timezone-aware UTC datetime

    Direct call tree (static source order):
        parse_rfc3339_utc
        +-- isinstance
        +-- _RFC3339_UTC_PATTERN.fullmatch
        +-- ValueError
        +-- datetime.strptime
        `-- datetime.strptime(...).replace
    """
    if not isinstance(text, str) or _RFC3339_UTC_PATTERN.fullmatch(text) is None:
        raise ValueError("timestamp must use canonical RFC3339 microsecond UTC form")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("timestamp must use canonical RFC3339 microsecond UTC form") from error


def parse_decimal(text: str) -> int:
    """Parse one canonical base-10 integer without aliases or whitespace.

    Processing flow:
        Text -> reject aliases, whitespace, and negative zero -> integer

    Direct call tree (static source order):
        parse_decimal
        +-- isinstance
        +-- _DECIMAL_PATTERN.fullmatch
        +-- ValueError
        `-- int
    """
    if not isinstance(text, str) or _DECIMAL_PATTERN.fullmatch(text) is None:
        raise ValueError("integer must use canonical decimal notation")
    return int(text, 10)


def format_float(value: float) -> str:
    """Format one finite binary float as stable minimal decimal text.

    References:
        Python 3.12 language reference, ``repr`` shortest-round-trip float conversion.

    Processing flow:
        Numeric value -> reject bool/type/non-finite values
                      -> normalize signed zero and integral values
                      -> shortest round-trip decimal text

    Direct call tree (static source order):
        format_float
        +-- isinstance
        +-- TypeError
        +-- float
        +-- math.isfinite
        +-- ValueError
        +-- converted.is_integer
        +-- str
        +-- int
        `-- repr
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("value must be a float")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("value must be finite")
    if converted == 0.0:
        return "0"
    if converted.is_integer():
        return str(int(converted))
    return repr(converted)
