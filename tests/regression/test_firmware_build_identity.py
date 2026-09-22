"""Test deterministic firmware source identity generation."""

from pathlib import Path

import pytest

from firmware.tools.generate_build_identity import (
    build_identity,
    generate_build_identity,
)


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware"
OUTPUT = FIRMWARE / "endpoint" / "src" / "generated" / "build_identity.h"


def test_identity_is_deterministic_and_excludes_its_own_header(
    tmp_path: Path,
) -> None:
    """Verify that identity is deterministic and excludes its own header.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_identity_is_deterministic_and_excludes_its_own_header
        +-- source.parent.mkdir
        +-- source.write_text
        +-- generated.parent.mkdir
        +-- generated.write_text
        `-- build_identity
    """
    firmware = tmp_path / "firmware"
    source = firmware / "endpoint" / "src" / "example.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int example() { return 1; }\n", encoding="utf-8")
    generated = firmware / "endpoint" / "src" / "generated" / "build_identity.h"
    generated.parent.mkdir(parents=True)
    generated.write_text("first generated value\n", encoding="ascii")
    first = build_identity(firmware)
    generated.write_text("different generated value\n", encoding="ascii")
    second = build_identity(firmware)
    assert first == second

    source.write_text("int example() { return 2; }\n", encoding="utf-8")
    third = build_identity(firmware)
    assert third != first


def test_generator_emits_progmem_accessor_and_check_mode(tmp_path: Path) -> None:
    """Verify that generator emits progmem accessor and check mode.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_generator_emits_progmem_accessor_and_check_mode
        +-- source.parent.mkdir
        +-- source.write_text
        +-- generate_build_identity
        +-- output.read_text
        +-- first.hex
        +-- first.hex(...).upper
        `-- pytest.raises
    """
    firmware = tmp_path / "firmware"
    source = firmware / "endpoint" / "endpoint.ino"
    source.parent.mkdir(parents=True)
    source.write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    output = firmware / "endpoint" / "src" / "generated" / "build_identity.h"
    first = generate_build_identity(firmware, output)
    text = output.read_text(encoding="ascii")
    assert "PROGMEM" in text
    assert "read_build_identity_byte" in text
    assert first.hex().upper() not in text
    assert generate_build_identity(firmware, output, check=True) == first

    source.write_text("void setup() { }\nvoid loop() {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        generate_build_identity(firmware, output, check=True)


def test_committed_build_identity_is_current() -> None:
    """Verify that committed build identity is current.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_committed_build_identity_is_current
        +-- generate_build_identity
        `-- len
    """
    generated = generate_build_identity(FIRMWARE, OUTPUT, check=True)
    assert len(generated) == 32
