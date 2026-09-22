"""Tests for the benchmark's CCSDS Space Packet and TM frame layers."""

import pytest

from host.dataset import ccsds_tm

from host.dataset import orbit_record


def _golden_record_bytes() -> bytes:
    """Serialize the golden mission fields into their expected binary record.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: bytes.

    Direct call tree (static source order):
        _golden_record_bytes
        +-- orbit_record.MissionRecord
        `-- orbit_record.pack_mission_record
    """
    record = orbit_record.MissionRecord(
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
    return orbit_record.pack_mission_record(record)


def _golden_space_packet_bytes() -> bytes:
    """Wrap the golden mission record in a Space Packet with a fixed sequence count.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: bytes.

    Direct call tree (static source order):
        _golden_space_packet_bytes
        +-- ccsds_tm.pack_space_packet
        `-- _golden_record_bytes
    """
    return ccsds_tm.pack_space_packet(
        _golden_record_bytes(),
        sequence_count=0x1234,
    )


def test_pack_space_packet_adds_frozen_six_byte_primary_header() -> None:
    """Verify that pack space packet adds frozen six byte primary header.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_space_packet_adds_frozen_six_byte_primary_header
        +-- _golden_record_bytes
        +-- ccsds_tm.pack_space_packet
        +-- len
        `-- packet[...].hex
    """
    record = _golden_record_bytes()

    packet = ccsds_tm.pack_space_packet(record, sequence_count=0x1234)

    assert len(packet) == 56
    assert packet[:6].hex(" ") == "01 27 d2 34 00 31"
    assert packet[6:] == record


def test_pack_space_packet_requires_exactly_50_record_bytes() -> None:
    """Verify that pack space packet requires exactly 50 record bytes.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_space_packet_requires_exactly_50_record_bytes
        +-- pytest.raises
        +-- ccsds_tm.pack_space_packet
        `-- bytes
    """
    with pytest.raises(ValueError, match="50 bytes"):
        ccsds_tm.pack_space_packet(bytes(49), sequence_count=0)


def test_pack_space_packet_rejects_out_of_range_sequence_count() -> None:
    """Verify that pack space packet rejects out of range sequence count.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_space_packet_rejects_out_of_range_sequence_count
        +-- pytest.raises
        +-- ccsds_tm.pack_space_packet
        `-- _golden_record_bytes
    """
    with pytest.raises(ValueError, match="sequence_count"):
        ccsds_tm.pack_space_packet(
            _golden_record_bytes(),
            sequence_count=0x4000,
        )


def test_pack_space_packet_rejects_out_of_range_apid() -> None:
    """Verify that pack space packet rejects out of range apid.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_space_packet_rejects_out_of_range_apid
        +-- pytest.raises
        +-- ccsds_tm.pack_space_packet
        `-- _golden_record_bytes
    """
    with pytest.raises(ValueError, match="apid"):
        ccsds_tm.pack_space_packet(
            _golden_record_bytes(),
            sequence_count=0,
            apid=0x800,
        )


def test_pack_tm_protected_data_adds_frozen_six_byte_primary_header() -> None:
    """Verify that pack tm protected data adds frozen six byte primary header.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_adds_frozen_six_byte_primary_header
        +-- _golden_space_packet_bytes
        +-- ccsds_tm.pack_tm_protected_data
        +-- len
        `-- protected[...].hex
    """
    packet = _golden_space_packet_bytes()

    protected = ccsds_tm.pack_tm_protected_data(
        packet,
        master_channel_count=0x12,
        virtual_channel_count=0x34,
    )

    assert len(protected) == 62
    assert protected[:6].hex(" ") == "27 80 12 34 18 00"
    assert protected[6:] == packet


def test_pack_tm_protected_data_requires_exactly_56_packet_bytes() -> None:
    """Verify that pack tm protected data requires exactly 56 packet bytes.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_requires_exactly_56_packet_bytes
        +-- pytest.raises
        +-- ccsds_tm.pack_tm_protected_data
        `-- bytes
    """
    with pytest.raises(ValueError, match="56 bytes"):
        ccsds_tm.pack_tm_protected_data(
            bytes(55),
            master_channel_count=0,
            virtual_channel_count=0,
        )


def test_pack_tm_protected_data_rejects_out_of_range_spacecraft_id() -> None:
    """Verify that pack tm protected data rejects out of range spacecraft id.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_rejects_out_of_range_spacecraft_id
        +-- pytest.raises
        +-- ccsds_tm.pack_tm_protected_data
        `-- _golden_space_packet_bytes
    """
    with pytest.raises(ValueError, match="spacecraft_id"):
        ccsds_tm.pack_tm_protected_data(
            _golden_space_packet_bytes(),
            master_channel_count=0,
            virtual_channel_count=0,
            spacecraft_id=0x400,
        )


def test_pack_tm_protected_data_rejects_out_of_range_virtual_channel_id() -> None:
    """Verify that pack tm protected data rejects out of range virtual channel id.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_rejects_out_of_range_virtual_channel_id
        +-- pytest.raises
        +-- ccsds_tm.pack_tm_protected_data
        `-- _golden_space_packet_bytes
    """
    with pytest.raises(ValueError, match="virtual_channel_id"):
        ccsds_tm.pack_tm_protected_data(
            _golden_space_packet_bytes(),
            master_channel_count=0,
            virtual_channel_count=0,
            virtual_channel_id=0x8,
        )


def test_pack_tm_protected_data_rejects_out_of_range_master_count() -> None:
    """Verify that pack tm protected data rejects out of range master count.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_rejects_out_of_range_master_count
        +-- pytest.raises
        +-- ccsds_tm.pack_tm_protected_data
        `-- _golden_space_packet_bytes
    """
    with pytest.raises(ValueError, match="master_channel_count"):
        ccsds_tm.pack_tm_protected_data(
            _golden_space_packet_bytes(),
            master_channel_count=0x100,
            virtual_channel_count=0,
        )


def test_pack_tm_protected_data_rejects_out_of_range_virtual_count() -> None:
    """Verify that pack tm protected data rejects out of range virtual count.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pack_tm_protected_data_rejects_out_of_range_virtual_count
        +-- pytest.raises
        +-- ccsds_tm.pack_tm_protected_data
        `-- _golden_space_packet_bytes
    """
    with pytest.raises(ValueError, match="virtual_channel_count"):
        ccsds_tm.pack_tm_protected_data(
            _golden_space_packet_bytes(),
            master_channel_count=0,
            virtual_channel_count=0x100,
        )


def test_fecf_matches_crc_ccitt_false_check_value() -> None:
    """Verify that fecf matches crc ccitt false check value.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_fecf_matches_crc_ccitt_false_check_value
        +-- ccsds_tm.fecf_ccsds
        `-- bytes.fromhex
    """
    assert ccsds_tm.fecf_ccsds(b"123456789") == bytes.fromhex("29 b1")


def test_build_tm_frame_matches_frozen_64_byte_vector() -> None:
    """Verify that build tm frame matches frozen 64 byte vector.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_build_tm_frame_matches_frozen_64_byte_vector
        +-- ccsds_tm.build_tm_frame
        +-- _golden_record_bytes
        +-- len
        +-- frame.hex
        `-- bytes.fromhex
    """
    frame = ccsds_tm.build_tm_frame(
        _golden_record_bytes(),
        sequence_count=0x1234,
        master_channel_count=0x12,
        virtual_channel_count=0x34,
    )

    assert len(frame) == 64
    assert frame.hex(" ") == (
        "27 80 12 34 18 00 01 27 d2 34 00 31 00 01 e2 40 "
        "00 3e 8f a0 ff ed b0 80 00 50 df 20 ff ed 29 79 "
        "00 23 ca ce ff cb 40 eb 00 0f 12 06 ff 98 68 78 "
        "00 97 14 b2 02 07 12 34 12 34 b7 91 34 12 78 22"
    )
    assert frame[-2:] == bytes.fromhex("78 22")


def test_validate_tm_frame_accepts_the_golden_frame() -> None:
    """Verify that validate tm frame accepts the golden frame.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_validate_tm_frame_accepts_the_golden_frame
        +-- ccsds_tm.build_tm_frame
        +-- _golden_record_bytes
        `-- ccsds_tm.validate_tm_frame
    """
    frame = ccsds_tm.build_tm_frame(
        _golden_record_bytes(),
        sequence_count=0x1234,
        master_channel_count=0x12,
        virtual_channel_count=0x34,
    )

    result = ccsds_tm.validate_tm_frame(frame)

    assert result.length_ok is True
    assert result.fecf_ok is True
    assert result.valid is True


def test_validate_tm_frame_detects_a_changed_protected_byte() -> None:
    """Verify that validate tm frame detects a changed protected byte.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_validate_tm_frame_detects_a_changed_protected_byte
        +-- bytearray
        +-- ccsds_tm.build_tm_frame
        +-- _golden_record_bytes
        +-- ccsds_tm.validate_tm_frame
        `-- bytes
    """
    frame = bytearray(
        ccsds_tm.build_tm_frame(
            _golden_record_bytes(),
            sequence_count=0x1234,
            master_channel_count=0x12,
            virtual_channel_count=0x34,
        )
    )
    frame[20] ^= 0x01

    result = ccsds_tm.validate_tm_frame(bytes(frame))

    assert result.length_ok is True
    assert result.fecf_ok is False
    assert result.valid is False


def test_validate_tm_frame_does_not_check_fecf_at_the_wrong_length() -> None:
    """Verify that validate tm frame does not check fecf at the wrong length.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_validate_tm_frame_does_not_check_fecf_at_the_wrong_length
        +-- ccsds_tm.validate_tm_frame
        `-- bytes
    """
    result = ccsds_tm.validate_tm_frame(bytes(63))

    assert result.length_ok is False
    assert result.fecf_ok is None
    assert result.valid is False


def test_decode_tm_and_space_headers_returns_all_three_counters() -> None:
    """Verify that decode tm and space headers returns all three counters.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_decode_tm_and_space_headers_returns_all_three_counters
        +-- ccsds_tm.build_tm_frame
        +-- _golden_record_bytes
        `-- ccsds_tm.decode_tm_and_space_headers
    """
    frame = ccsds_tm.build_tm_frame(
        _golden_record_bytes(),
        sequence_count=0x1234,
        master_channel_count=0x12,
        virtual_channel_count=0x34,
    )

    counters = ccsds_tm.decode_tm_and_space_headers(frame)

    assert counters.master_channel_count == 0x12
    assert counters.virtual_channel_count == 0x34
    assert counters.packet_sequence_count == 0x1234


def test_decode_tm_and_space_headers_rejects_length_and_fixed_fields() -> None:
    """Verify that decode tm and space headers rejects length and fixed fields.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_decode_tm_and_space_headers_rejects_length_and_fixed_fields
        +-- pytest.raises
        +-- ccsds_tm.decode_tm_and_space_headers
        +-- bytes
        +-- bytearray
        +-- ccsds_tm.build_tm_frame
        `-- _golden_record_bytes
    """
    with pytest.raises(ValueError, match="64 bytes"):
        ccsds_tm.decode_tm_and_space_headers(bytes(63))

    frame = bytearray(
        ccsds_tm.build_tm_frame(
            _golden_record_bytes(),
            sequence_count=0,
            master_channel_count=0,
            virtual_channel_count=0,
        )
    )
    frame[4] = 0
    frame[5] = 0
    with pytest.raises(ValueError, match="fixed header"):
        ccsds_tm.decode_tm_and_space_headers(bytes(frame))

    frame = bytearray(
        ccsds_tm.build_tm_frame(
            _golden_record_bytes(),
            sequence_count=0,
            master_channel_count=0,
            virtual_channel_count=0,
        )
    )
    frame[10] = 0
    frame[11] = 48
    with pytest.raises(ValueError, match="fixed header"):
        ccsds_tm.decode_tm_and_space_headers(bytes(frame))
