"""Enforce the frozen Arduino Nano firmware resource budget.

Configuration: config/internal/avr_size.toml
Function call tree (main task paths; branch labels indicate execution conditions):
main() -> host.common.runtime_config.parse_configured_args() Read avr_size.toml
+-- _validate_map()                          Check the ELF file against the linker map
+-- _validate_tool_version()                  Check the avr-size version
+-- _measure_elf_sections()                   Read ELF section sizes
+-- _validate_section_binding()              Compare ELF sections with map records
+-- subprocess.run()                         Run avr-size to measure Flash and RAM usage
+-- parse_avr_size()                         Parse Flash and RAM usage
`-- enforce_limits()                        Check firmware usage against the Nano resource budget
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from host.common.runtime_config import parse_configured_args
from typing import Sequence


EXPECTED_AVR_SIZE_VERSION = "GNU size (GNU Binutils) 2.26.20160125"

# Project choice: require code, initialized data and zero-initialized data
# sections before checking the Flash and static RAM budgets.
REQUIRED_SECTION_NAMES = (".text", ".data", ".bss")


@dataclass(frozen=True)
class ResourceUsage:
    """Store flash and static-RAM measurements reported by avr-size."""

    flash_bytes: int
    static_ram_bytes: int


def _parse_measurement(text: str, label: str) -> int:
    """Parse one uniquely labelled non-negative byte measurement.

    Processing flow:
        avr-size lines -> unique labelled line -> validated integer bytes

    Direct call tree (static source order):
        _parse_measurement
        +-- text.splitlines
        +-- line.strip
        +-- stripped_line.startswith
        +-- labelled_lines.append
        +-- len
        +-- ValueError
        +-- re.escape
        +-- re.fullmatch
        +-- measurement_match.group
        `-- int
    """
    labelled_lines: list[str] = []
    label_prefix = label + ":"
    lines = text.splitlines()
    for line in lines:
        stripped_line = line.strip()
        line_has_label = stripped_line.startswith(label_prefix)
        if line_has_label:
            labelled_lines.append(stripped_line)
    if len(labelled_lines) != 1:
        raise ValueError(f"expected exactly one {label} measurement")
    escaped_label = re.escape(label)
    measurement_pattern = escaped_label + r":\s*([^\s]+)\s+bytes(?:\s+.*)?"
    measurement_line = labelled_lines[0]
    measurement_match = re.fullmatch(measurement_pattern, measurement_line)
    measurement_line_is_invalid = measurement_match is None
    if measurement_line_is_invalid:
        raise ValueError(f"invalid {label} byte measurement")

    measurement_text = measurement_match.group(1)
    integer_match = re.fullmatch(r"[0-9]+", measurement_text)
    measurement_is_not_integer = integer_match is None
    if measurement_is_not_integer:
        raise ValueError(f"invalid {label} byte measurement")
    return int(measurement_text)


def parse_avr_size(text: str) -> ResourceUsage:
    """Parse GNU avr-size Berkeley-style program and data measurements.

    References:
        Arduino AVR Boards AVR GCC toolchain
        ``7.3.0-atmel3.6.1-arduino7``, GNU size help locator
        ``-C/--mcu=<avrmcu>``; that MCU-aware report labels the two totals
        ``Program`` and ``Data``.

    Processing flow:
        command output -> Program/Data validation -> immutable resource usage

    Direct call tree (static source order):
        parse_avr_size
        +-- _parse_measurement
        `-- ResourceUsage
    """
    flash_bytes = _parse_measurement(text, "Program")
    static_ram_bytes = _parse_measurement(text, "Data")
    return ResourceUsage(
        flash_bytes=flash_bytes,
        static_ram_bytes=static_ram_bytes,
    )


def enforce_limits(
    usage: ResourceUsage,
    flash_limit: int = 28672,
    static_ram_limit: int = 1536,
) -> ResourceUsage:
    """Reject firmware measurements above the frozen Nano resource limits.

    Processing flow:
        measured bytes -> configured boundary checks -> accepted usage or error

    Direct call tree (static source order):
        enforce_limits
        `-- ValueError
    """
    flash_limit_is_negative = flash_limit < 0
    if flash_limit_is_negative:
        raise ValueError("flash limit must be non-negative")
    static_ram_limit_is_negative = static_ram_limit < 0
    if static_ram_limit_is_negative:
        raise ValueError("static RAM limit must be non-negative")

    flash_usage_is_negative = usage.flash_bytes < 0
    if flash_usage_is_negative:
        raise ValueError("flash usage must be non-negative")
    static_ram_usage_is_negative = usage.static_ram_bytes < 0
    if static_ram_usage_is_negative:
        raise ValueError("static RAM usage must be non-negative")

    flash_limit_is_exceeded = usage.flash_bytes > flash_limit
    if flash_limit_is_exceeded:
        raise ValueError(
            f"flash usage {usage.flash_bytes} exceeds limit {flash_limit}"
        )
    static_ram_limit_is_exceeded = usage.static_ram_bytes > static_ram_limit
    if static_ram_limit_is_exceeded:
        raise ValueError(
            "static RAM usage "
            f"{usage.static_ram_bytes} exceeds limit {static_ram_limit}"
        )
    return usage


def _parse_map_output(text: str) -> str:
    """Parse the single GNU ld OUTPUT path from one linker map.

    References:
        Arduino AVR Boards toolchain GNU Binutils ``2.26.20160125``, GNU ld
        map file output and ``Linker Scripts`` documentation locator.

    Processing flow:
        map lines -> one OUTPUT line -> quoted or unquoted output path

    Direct call tree (static source order):
        _parse_map_output
        +-- text.splitlines
        +-- line.strip
        +-- stripped_line.startswith
        +-- output_lines.append
        +-- len
        +-- ValueError
        +-- output_line.endswith
        +-- untrimmed_output_body.strip
        +-- output_body.startswith
        `-- output_body.find
    """
    output_lines: list[str] = []
    lines = text.splitlines()
    for line in lines:
        stripped_line = line.strip()
        line_is_output = stripped_line.startswith("OUTPUT(")
        if line_is_output:
            output_lines.append(stripped_line)

    if len(output_lines) != 1:
        raise ValueError("map file must contain exactly one GNU ld OUTPUT line")

    output_line = output_lines[0]
    line_has_closing_parenthesis = output_line.endswith(")")
    if not line_has_closing_parenthesis:
        raise ValueError("map file contains an invalid GNU ld OUTPUT line")

    output_prefix = "OUTPUT("
    body_start = len(output_prefix)
    body_end = len(output_line) - 1
    untrimmed_output_body = output_line[body_start:body_end]
    output_body = untrimmed_output_body.strip()
    if output_body == "":
        raise ValueError("map file contains an empty GNU ld OUTPUT line")

    path_is_quoted = output_body.startswith('"')
    if path_is_quoted:
        closing_quote = output_body.find('"', 1)
        if closing_quote < 0:
            raise ValueError("map file contains an unterminated OUTPUT path")
        output_path = output_body[1:closing_quote]
    else:
        first_space = output_body.find(" ")
        if first_space < 0:
            output_path = output_body
        else:
            output_path = output_body[:first_space]

    if output_path == "":
        raise ValueError("map file contains an empty OUTPUT path")
    return output_path


def _parse_hexadecimal(text: str, field: str) -> int:
    """Parse one GNU tool hexadecimal address or size without aliases.

    Processing flow:
        GNU address or size text -> require a hexadecimal field beginning with 0x
        -> convert the accepted field to its integer value; reject other spellings.

    Direct call tree (static source order):
        _parse_hexadecimal
        +-- re.fullmatch
        +-- ValueError
        `-- int
    """
    hexadecimal_match = re.fullmatch(r"0x[0-9a-fA-F]+", text)
    text_is_not_hexadecimal = hexadecimal_match is None
    if text_is_not_hexadecimal:
        raise ValueError(f"{field} must be hexadecimal")
    return int(text, 16)


def _parse_map_sections(text: str) -> dict[str, tuple[int, int]]:
    """Parse top-level .text, .data, and .bss extents from a GNU ld map.

    References:
        Arduino AVR Boards toolchain GNU Binutils ``2.26.20160125``, GNU ld
        map file ``Output Section Description`` format.

    Processing flow:
        map lines -> top-level required section rows -> address/size extents

    Direct call tree (static source order):
        _parse_map_sections
        +-- text.splitlines
        +-- line.startswith
        +-- line.split
        +-- len
        +-- ValueError
        `-- _parse_hexadecimal
    """
    sections: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    for line in lines:
        line_is_top_level_section = line.startswith(".")
        if not line_is_top_level_section:
            continue
        fields = line.split()
        if len(fields) < 3:
            continue
        section_name = fields[0]
        section_is_required = section_name in REQUIRED_SECTION_NAMES
        if not section_is_required:
            continue
        section_is_duplicated = section_name in sections
        if section_is_duplicated:
            raise ValueError(f"map file repeats top-level section {section_name}")
        address = _parse_hexadecimal(fields[1], section_name + " map address")
        size = _parse_hexadecimal(fields[2], section_name + " map size")
        sections[section_name] = (address, size)

    for section_name in REQUIRED_SECTION_NAMES:
        section_is_missing = section_name not in sections
        if section_is_missing:
            raise ValueError(f"map file is missing required section {section_name}")
    return sections


def _parse_elf_sections(text: str) -> dict[str, tuple[int, int]]:
    """Parse required section extents from GNU size SysV output.

    References:
        Arduino AVR Boards AVR GCC toolchain
        ``7.3.0-atmel3.6.1-arduino7``, GNU size option locators
        ``-A/--format=sysv`` and ``--radix=16``.

    Processing flow:
        avr-size rows -> required section rows -> address/size extents

    Direct call tree (static source order):
        _parse_elf_sections
        +-- text.splitlines
        +-- line.split
        +-- len
        +-- ValueError
        `-- _parse_hexadecimal
    """
    sections: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    for line in lines:
        fields = line.split()
        if len(fields) != 3:
            continue
        section_name = fields[0]
        section_is_required = section_name in REQUIRED_SECTION_NAMES
        if not section_is_required:
            continue
        section_is_duplicated = section_name in sections
        if section_is_duplicated:
            raise ValueError(f"ELF report repeats section {section_name}")
        size = _parse_hexadecimal(fields[1], section_name + " ELF size")
        address = _parse_hexadecimal(fields[2], section_name + " ELF address")
        sections[section_name] = (address, size)

    for section_name in REQUIRED_SECTION_NAMES:
        section_is_missing = section_name not in sections
        if section_is_missing:
            raise ValueError(f"ELF report is missing required section {section_name}")
    return sections


def _validate_map(path: Path, elf_path: Path) -> dict[str, tuple[int, int]]:
    """Validate that one linker map belongs to the measured ELF.

    References:
        Arduino AVR Boards toolchain GNU Binutils ``2.26.20160125``, GNU ld map file
        output and ``Linker Scripts`` documentation locator.

    Processing flow:
        map path -> required section extents -> OUTPUT path -> resolved ELF path

    Direct call tree (static source order):
        _validate_map
        +-- path.is_file
        +-- ValueError
        +-- path.read_text
        +-- _parse_map_sections
        +-- _parse_map_output
        +-- Path
        +-- output_path.is_absolute
        +-- output_path.resolve
        `-- elf_path.resolve
    """
    map_file_exists = path.is_file()
    if not map_file_exists:
        raise ValueError(f"map file does not exist: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    memory_configuration_is_missing = "Memory Configuration" not in text
    if memory_configuration_is_missing:
        raise ValueError("map file is missing Memory Configuration")
    map_sections = _parse_map_sections(text)

    output_text = _parse_map_output(text)
    output_path = Path(output_text)
    output_path_is_absolute = output_path.is_absolute()
    if not output_path_is_absolute:
        output_path = path.parent / output_path
    resolved_output_path = output_path.resolve()
    resolved_elf_path = elf_path.resolve()
    paths_are_different = resolved_output_path != resolved_elf_path
    if paths_are_different:
        raise ValueError(
            "map OUTPUT does not match ELF: "
            f"{resolved_output_path} != {resolved_elf_path}"
        )
    return map_sections


def _measure_elf_sections(
    executable: str,
    elf_path: Path,
) -> dict[str, tuple[int, int]]:
    """Measure ELF section addresses and sizes with the frozen GNU size tool.

    References:
        Arduino AVR Boards AVR GCC toolchain
        ``7.3.0-atmel3.6.1-arduino7``, GNU size option locators
        ``-A/--format=sysv`` and ``--radix=16``.

    Processing flow:
        frozen avr-size + ELF -> hexadecimal SysV report -> section extents

    Direct call tree (static source order):
        _measure_elf_sections
        +-- subprocess.run
        +-- str
        `-- _parse_elf_sections
    """
    completed = subprocess.run(
        [executable, "-A", "--radix=16", str(elf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _parse_elf_sections(completed.stdout)


def _validate_section_binding(
    map_sections: dict[str, tuple[int, int]],
    elf_sections: dict[str, tuple[int, int]],
) -> None:
    """Reject a map whose required section extents differ from the ELF.

    Processing flow:
        map extents + ELF extents -> per-section equality -> bound evidence

    Direct call tree (static source order):
        _validate_section_binding
        `-- ValueError
    """
    for section_name in REQUIRED_SECTION_NAMES:
        map_extent = map_sections[section_name]
        elf_extent = elf_sections[section_name]
        extents_are_different = map_extent != elf_extent
        if extents_are_different:
            raise ValueError(
                f"{section_name} map address/size {map_extent} "
                f"differs from ELF address/size {elf_extent}"
            )


def _validate_tool_version(executable: str) -> str:
    """Verify the exact GNU size version frozen by the firmware build contract.

    References:
        Arduino AVR Boards AVR GCC toolchain ``7.3.0-atmel3.6.1-arduino7`` bundles GNU
        Binutils ``2.26.20160125``.

    Processing flow:
        executable -> --version process -> first line -> exact-version decision

    Direct call tree (static source order):
        _validate_tool_version
        +-- subprocess.run
        +-- completed.stdout.splitlines
        +-- len
        `-- ValueError
    """
    completed = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    version_lines = completed.stdout.splitlines()
    if len(version_lines) == 0:
        raise ValueError("avr-size version output is empty")
    first_line = version_lines[0]
    version_is_wrong = first_line != EXPECTED_AVR_SIZE_VERSION
    if version_is_wrong:
        raise ValueError(
            "avr-size version mismatch: "
            f"expected {EXPECTED_AVR_SIZE_VERSION}, got {first_line}"
        )
    return first_line


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 identity of one evidence file.

    Processing flow:
        file path -> fixed-size byte chunks -> SHA-256 hexadecimal identity

    Direct call tree (static source order):
        _sha256_file
        +-- hashlib.sha256
        +-- path.open
        +-- stream.read
        +-- digest.update
        `-- digest.hexdigest
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(65536)
            end_of_file = chunk == b""
            if end_of_file:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Run avr-size and enforce the project flash and static-RAM gate.

    References:
        Arduino AVR Boards AVR GCC toolchain ``7.3.0-atmel3.6.1-arduino7`` GNU size
        option locator ``-C/--mcu=atmega328p``.

    Processing flow:
        CLI paths -> ELF/map binding -> tool-version gate -> size measurement
        -> limit enforcement -> evidence hashes -> bound report

    Direct call tree (static source order):
        main
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- arguments.elf.is_file
        +-- ValueError
        +-- _validate_map
        +-- _validate_tool_version
        +-- _measure_elf_sections
        +-- _validate_section_binding
        +-- subprocess.run
        +-- str
        +-- parse_avr_size
        +-- enforce_limits
        +-- _sha256_file
        `-- print
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avr-size", required=True)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--map", required=True, dest="map_path", type=Path)
    arguments = parse_configured_args(parser, argv, "avr_size")

    elf_file_exists = arguments.elf.is_file()
    if not elf_file_exists:
        raise ValueError(f"ELF file does not exist: {arguments.elf}")
    map_sections = _validate_map(arguments.map_path, arguments.elf)
    tool_version = _validate_tool_version(arguments.avr_size)
    elf_sections = _measure_elf_sections(arguments.avr_size, arguments.elf)
    _validate_section_binding(map_sections, elf_sections)
    completed = subprocess.run(
        [
            arguments.avr_size,
            "-C",
            "--mcu=atmega328p",
            str(arguments.elf),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed_usage = parse_avr_size(completed.stdout)
    usage = enforce_limits(parsed_usage)
    elf_sha256 = _sha256_file(arguments.elf)
    map_sha256 = _sha256_file(arguments.map_path)
    print(
        "AVR resource gate: PASS "
        f"flash={usage.flash_bytes}/28672 bytes "
        f"static_ram={usage.static_ram_bytes}/1536 bytes "
        f"elf_sha256={elf_sha256} "
        f"map_sha256={map_sha256} "
        f"tool_version={tool_version}"
    )
    return 0


if __name__ == "__main__":
    command_exit_code = main()
    raise SystemExit(command_exit_code)
