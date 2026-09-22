"""Tests for the 50-byte benchmark mission record."""

import pytest

from host.dataset import orbit_record


def _golden_record() -> orbit_record.MissionRecord:
    """Construct the mission record used by golden binary serialization checks.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: orbit_record.MissionRecord.

    Direct call tree (static source order):
        _golden_record
        `-- orbit_record.MissionRecord
    """
    return orbit_record.MissionRecord(
        trace_time_ms=123_456,
        position_x_m=4_100_000,
        position_y_m=-1_200_000,
        position_z_m=5_300_000,
        velocity_x_mmps=-1_234_567,
        velocity_y_mmps=2_345_678,
        velocity_z_mmps=-3_456_789,
        slant_range_m=987_654,
        range_rate_mmps=-6_789_000,
        doppler_millihz=9_901_234,
        mission_state=2,
        workload=7,
        trace_sample_id=0x1234,
    )


def test_validation_pattern_exposes_value_xor_and_byte_order() -> None:
    """Verify that validation pattern exposes value xor and byte order.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_validation_pattern_exposes_value_xor_and_byte_order
        +-- orbit_record.validation_pattern
        `-- pattern.hex
    """
    pattern = orbit_record.validation_pattern(0x1234)

    assert pattern.hex(" ") == "12 34 b7 91 34 12"


def test_validation_pattern_rejects_out_of_range_sample_id() -> None:
    """Verify that validation pattern rejects out of range sample id.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_validation_pattern_rejects_out_of_range_sample_id
        +-- pytest.raises
        `-- orbit_record.validation_pattern
    """
    with pytest.raises(ValueError, match="uint16"):
        orbit_record.validation_pattern(0x1_0000)


def test_pack_mission_record_matches_frozen_50_byte_layout() -> None:
    """Verify that pack mission record matches frozen 50 byte layout.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_mission_record_matches_frozen_50_byte_layout
        +-- _golden_record
        +-- orbit_record.pack_mission_record
        +-- len
        `-- packed.hex
    """
    record = _golden_record()

    packed = orbit_record.pack_mission_record(record)

    assert len(packed) == 50
    assert packed.hex(" ") == (
        "00 01 e2 40 00 3e 8f a0 ff ed b0 80 00 50 df 20 "
        "ff ed 29 79 00 23 ca ce ff cb 40 eb 00 0f 12 06 "
        "ff 98 68 78 00 97 14 b2 02 07 12 34 12 34 b7 91 "
        "34 12"
    )


def test_unpack_mission_record_round_trips_all_fields() -> None:
    """Verify that unpack mission record round trips all fields.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_unpack_mission_record_round_trips_all_fields
        +-- _golden_record
        +-- orbit_record.unpack_mission_record
        `-- orbit_record.pack_mission_record
    """
    original = _golden_record()

    restored = orbit_record.unpack_mission_record(
        orbit_record.pack_mission_record(original)
    )

    assert restored == original


def test_unpack_mission_record_requires_exactly_50_bytes() -> None:
    """Verify that unpack mission record requires exactly 50 bytes.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_unpack_mission_record_requires_exactly_50_bytes
        +-- pytest.raises
        +-- orbit_record.unpack_mission_record
        `-- bytes
    """
    with pytest.raises(ValueError, match="50 bytes"):
        orbit_record.unpack_mission_record(bytes(49))
