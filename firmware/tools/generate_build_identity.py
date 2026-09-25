"""Generate a non-self-referential SHA-256 identity for firmware sources.

Configuration: firmware/config/internal/build_identity.toml
Function call tree (main task paths; branch labels indicate execution conditions):
main() -> firmware.host.runtime_config.parse_configured_args() Read build_identity.toml
`-- generate_build_identity()                Generate or verify the firmware source identity
    +-- build_identity()                     Compute SHA-256 over source paths and bytes
    |   `-- source_paths()                    Collect source files in a fixed order
    `-- render_header()                        Render the identity as a header
"""

import argparse
import hashlib
from pathlib import Path

import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from firmware.host.runtime_config import parse_configured_args


def source_paths(firmware_root: Path) -> list[Path]:
    """Return canonical endpoint source inputs in byte-stable path order.

    Processing flow:
        endpoint tree -> source suffix/name gates -> relative-path sort -> inputs

    Direct call tree (static source order):
        source_paths
        +-- endpoint_root.is_dir
        +-- ValueError
        +-- endpoint_root.rglob
        +-- path.is_file
        +-- paths.append
        +-- range
        +-- len
        +-- candidate.relative_to
        +-- candidate.relative_to(...).as_posix
        +-- best.relative_to
        `-- best.relative_to(...).as_posix
    """
    endpoint_root = firmware_root / "endpoint"
    paths: list[Path] = []
    if not endpoint_root.is_dir():
        raise ValueError("firmware endpoint source directory is missing")
    for path in endpoint_root.rglob("*"):
        if not path.is_file():
            continue
        is_source = False
        if path.suffix == ".h":
            is_source = True
        if path.suffix == ".cpp":
            is_source = True
        if path.suffix == ".ino":
            is_source = True
        if not is_source:
            continue
        if path.name == "build_identity.h":
            continue
        paths.append(path)

    for index in range(len(paths)):
        best_index = index
        candidate_index = index + 1
        while candidate_index < len(paths):
            candidate = paths[candidate_index]
            best = paths[best_index]
            candidate_name = candidate.relative_to(firmware_root).as_posix()
            best_name = best.relative_to(firmware_root).as_posix()
            if candidate_name < best_name:
                best_index = candidate_index
            candidate_index += 1
        if best_index != index:
            saved = paths[index]
            paths[index] = paths[best_index]
            paths[best_index] = saved
    if len(paths) == 0:
        raise ValueError("no firmware endpoint source inputs")
    return paths


def build_identity(firmware_root: Path) -> bytes:
    """Hash every canonical endpoint source path and byte sequence.

    References:
        NIST FIPS PUB 180-4, ``Secure Hash Standard``, August 2015, section 6.2,
        SHA-256.

    Processing flow:
        ordered sources -> path/NUL/source/NUL records -> SHA-256 digest

    Direct call tree (static source order):
        build_identity
        +-- source_paths
        +-- hashlib.sha256
        +-- path.relative_to
        +-- path.relative_to(...).as_posix
        +-- digest.update
        +-- relative.encode
        +-- path.read_bytes
        `-- digest.digest
    """
    paths = source_paths(firmware_root)
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(firmware_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.digest()


def render_header(identity: bytes) -> str:
    """Render one AVR-flash-resident identity and bounded byte accessor.

            Processing flow:
                32-byte digest -> hexadecimal literals -> PROGMEM array/accessor header

    Direct call tree (static source order):
        render_header
        +-- len
        +-- ValueError
        +-- octets.append
        `-- <str literal>.join
    """
    if len(identity) != 32:
        raise ValueError("firmware identity must contain 32 bytes")
    octets: list[str] = []
    for value in identity:
        octets.append(f"0x{value:02X}U")
    initializer = ", ".join(octets)
    lines = [
        "#ifndef SX1278_GENERATED_BUILD_IDENTITY_H",
        "#define SX1278_GENERATED_BUILD_IDENTITY_H",
        "#include <stdint.h>",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "namespace sx1278 {",
        "namespace generated {",
        "static const uint8_t kFirmwareIdentitySha256[32] PROGMEM = {",
        "    " + initializer,
        "};",
        "/** Read one firmware source-identity byte from native memory or AVR flash.",
        " * Processing flow: index/output checks -> platform read -> byte result.",
        " */",
        "inline bool read_build_identity_byte(uint8_t index, uint8_t* output) {",
        "  if (output == 0) {",
        "    return false;",
        "  }",
        "  if (index >= 32U) {",
        "    return false;",
        "  }",
        "#ifdef __AVR__",
        "  *output = pgm_read_byte(&kFirmwareIdentitySha256[index]);",
        "#else",
        "  *output = kFirmwareIdentitySha256[index];",
        "#endif",
        "  return true;",
        "}",
        "}",
        "}",
        "#endif",
    ]
    return "\n".join(lines) + "\n"


def generate_build_identity(
    firmware_root: Path,
    output: Path,
    check: bool = False,
) -> bytes:
    """Write or verify the deterministic generated identity header.

    Processing flow:
        firmware tree -> identity digest -> header bytes -> write or strict check

    Direct call tree (static source order):
        generate_build_identity
        +-- build_identity
        +-- render_header
        +-- content.encode
        +-- output.is_file
        +-- ValueError
        +-- output.read_bytes
        +-- output.parent.mkdir
        `-- output.write_bytes
    """
    identity = build_identity(firmware_root)
    content = render_header(identity)
    encoded = content.encode("ascii")
    if check:
        if not output.is_file():
            raise ValueError("generated build identity is missing")
        if output.read_bytes() != encoded:
            raise ValueError("generated build identity is stale")
        return identity
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    return identity


def main(argv: list[str] | None = None) -> int:
    """Run build-identity generation from the command line.

    Processing flow:
        Configured paths -> source identity and header -> write/check report.

    Direct call tree (static source order):
        main
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- generate_build_identity
        +-- print
        `-- identity.hex
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    arguments = parse_configured_args(parser, argv, "build_identity")
    identity = generate_build_identity(
        arguments.firmware_root,
        arguments.output,
        check=arguments.check,
    )
    print("firmware identity PASS: " + identity.hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
