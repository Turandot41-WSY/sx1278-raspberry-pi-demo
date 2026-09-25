"""Packing rules for the benchmark's CCSDS telemetry layers."""

import struct
from dataclasses import dataclass


# Bit positions in the comments below use Python's integer convention (LSB=0).
# CCSDS diagrams instead number the first-transmitted, most-significant bit as 0.

# The first Space Packet header word is one 16-bit unsigned integer:
#   bits 15..13: version = 0b000
#   bit  12:     packet type = 0 (telemetry)
#   bit  11:     secondary-header flag = 0 (not present)
#   bits 10..0:  APID = 0x127 (local laboratory identifier, not SANA-assigned)
# Therefore the complete word is 0b000_0_0_00100100111 = 0x0127 (bytes 01 27).
LAB_APID = 0x127
_MISSION_RECORD_LENGTH = 50
_SPACE_PACKET_LENGTH = 56
_TM_FRAME_LENGTH = 64

# TM frame identification is one 16-bit word:
#   bits 15..14: version = 0b00
#   bits 13..4:  spacecraft ID = 0x278 (local laboratory identifier)
#   bits 3..1:   virtual channel ID = 0
#   bit  0:      operational control field flag = 0 (not present)
# Therefore the complete word is 0x2780 (bytes 27 80).
LAB_SCID = 0x278
LAB_VCID = 0

# Secondary header = 0, synchronization = 0, packet order = 0,
# segment length ID = 0b11, and first header pointer = 0.
_TM_DATA_FIELD_STATUS = 0x1800

# Python struct format ">HHH" (not CCSDS notation): big-endian, followed by
# three 16-bit unsigned integers. They implement the Packet Primary Header in
# CCSDS 133.0-B-2, Space Packet Protocol, section 4.1.3:
#   H: version + Packet Identification Field (sections 4.1.3.2-4.1.3.3)
#   H: Packet Sequence Control Field (section 4.1.3.4)
#   H: Packet Data Length (section 4.1.3.5)
_SPACE_PACKET_PRIMARY_HEADER = struct.Struct(">HHH")

# Python struct format ">HBBH" (not CCSDS notation): ">" selects big-endian;
# H is a 2-byte unsigned integer and B is a 1-byte unsigned integer. The four
# values implement the six-octet Transfer Frame Primary Header specified by
# CCSDS 132.0-B-3, TM Space Data Link Protocol, section 4.1.2:
#   H: Master Channel Identifier, VCID, and OCF flag (sections 4.1.2.2-4.1.2.4)
#   B: Master Channel Frame Count (section 4.1.2.5)
#   B: Virtual Channel Frame Count (section 4.1.2.6)
#   H: Transfer Frame Data Field Status (section 4.1.2.7)
_TM_PRIMARY_HEADER = struct.Struct(">HBBH")


@dataclass(frozen=True)
class FrameValidationResult:
    """Describe whether a received TM frame can be trusted."""

    length_ok: bool
    fecf_ok: bool | None

    @property
    def valid(self) -> bool:
        """Return true only when both the frame length and FECF are valid.

        References:
            CCSDS 132.0-B-3, TM Space Data Link Protocol, Section 4.1.6.

        Processing flow:
            Stored length result + stored FECF result -> strict conjunction.

        Direct call tree (static source order):
            valid
            `-- [no direct function calls; local state/return only]
        """
        return self.length_ok and self.fecf_ok is True


@dataclass(frozen=True)
class FrameCounters:
    """Hold the three air-interface counters decoded from one fixed frame."""

    master_channel_count: int
    virtual_channel_count: int
    packet_sequence_count: int


def decode_tm_and_space_headers(frame: bytes) -> FrameCounters:
    """Decode all three counters only from the project's fixed 64-byte frame.

    References:
        CCSDS 132.0-B-3, TM Space Data Link Protocol, Sections 4.1.2.2-- 4.1.2.7; CCSDS
        133.0-B-2, Space Packet Protocol, Sections 4.1.3.2--4.1.3.5.

    Processing flow:
        Frame bytes -> exact length -> TM and Space Packet header unpack
        -> fixed identity/status/length checks -> three counter values.

    Direct call tree (static source order):
        decode_tm_and_space_headers
        +-- len
        +-- ValueError
        +-- _TM_PRIMARY_HEADER.unpack
        +-- _SPACE_PACKET_PRIMARY_HEADER.unpack
        `-- FrameCounters
    """
    if len(frame) != _TM_FRAME_LENGTH:
        raise ValueError("frame must be exactly 64 bytes")
    frame_id, master_count, virtual_count, status = _TM_PRIMARY_HEADER.unpack(
        frame[:6]
    )
    packet_id, sequence_control, packet_data_length = (
        _SPACE_PACKET_PRIMARY_HEADER.unpack(frame[6:12])
    )
    expected_frame_id = (LAB_SCID << 4) | (LAB_VCID << 1)
    sequence_flags = sequence_control >> 14
    if frame_id != expected_frame_id:
        raise ValueError("frame fixed header fields are invalid")
    if status != _TM_DATA_FIELD_STATUS:
        raise ValueError("frame fixed header fields are invalid")
    if packet_id != LAB_APID:
        raise ValueError("frame fixed header fields are invalid")
    if sequence_flags != 0b11 or packet_data_length != 49:
        raise ValueError("frame fixed header fields are invalid")
    return FrameCounters(
        master_channel_count=master_count,
        virtual_channel_count=virtual_count,
        packet_sequence_count=sequence_control & 0x3FFF,
    )

def pack_space_packet(
    record: bytes,
    sequence_count: int,
    apid: int = LAB_APID,
) -> bytes:
    """Add a six-byte CCSDS primary header to one 50-byte mission record.

    References:
        CCSDS 133.0-B-2, Space Packet Protocol, section 4.1.3, "Packet
        Primary Header"; field definitions are in sections 4.1.3.2-4.1.3.5.

    Processing flow:
        50-byte mission record, sequence count, and APID
                            |
                            v
              Validate length and field widths
                            |
                            v
           Derive packet ID, sequence control, and length
                            |
                            v
              Pack the six-byte primary header
                            |
                            v
               Header + unchanged mission record

    Direct call tree (static source order):
        pack_space_packet
        +-- len
        +-- ValueError
        `-- _SPACE_PACKET_PRIMARY_HEADER.pack
    """
    if len(record) != _MISSION_RECORD_LENGTH:
        raise ValueError("record must be exactly 50 bytes")
    if not 0 <= sequence_count <= 0x3FFF:
        raise ValueError("sequence_count must fit in 14 bits")
    if not 0 <= apid <= 0x7FF:
        raise ValueError("apid must fit in 11 bits")

    # Version, packet type, and secondary-header flag are all zero.
    packet_id = apid
    # Sequence flags 0b11 identify one complete, unsegmented user-data field.
    sequence_control = (0b11 << 14) | sequence_count
    # CCSDS encodes this field as (number of data bytes - 1).
    packet_data_length = len(record) - 1

    header = _SPACE_PACKET_PRIMARY_HEADER.pack(
        packet_id,
        sequence_control,
        packet_data_length,
    )
    return header + record


def pack_tm_protected_data(
    packet: bytes,
    master_channel_count: int,
    virtual_channel_count: int,
    spacecraft_id: int = LAB_SCID,
    virtual_channel_id: int = LAB_VCID,
) -> bytes:
    """Add a six-byte TM primary header to one 56-byte Space Packet.

    References:
        CCSDS 132.0-B-3, TM Space Data Link Protocol, section 4.1.2,
        "Transfer Frame Primary Header"; field definitions are in sections
        4.1.2.2-4.1.2.7.

    Processing flow:
        56-byte Space Packet, counters, SCID, and VCID
                            |
                            v
              Validate length and field widths
                            |
                            v
           Derive the TM frame identification word
                            |
                            v
              Pack the six-byte primary header
                            |
                            v
                Header + unchanged Space Packet

    Direct call tree (static source order):
        pack_tm_protected_data
        +-- len
        +-- ValueError
        `-- _TM_PRIMARY_HEADER.pack
    """
    if len(packet) != _SPACE_PACKET_LENGTH:
        raise ValueError("packet must be exactly 56 bytes")
    if not 0 <= spacecraft_id <= 0x3FF:
        raise ValueError("spacecraft_id must fit in 10 bits")
    if not 0 <= virtual_channel_id <= 0x7:
        raise ValueError("virtual_channel_id must fit in 3 bits")
    if not 0 <= master_channel_count <= 0xFF:
        raise ValueError("master_channel_count must fit in 8 bits")
    if not 0 <= virtual_channel_count <= 0xFF:
        raise ValueError("virtual_channel_count must fit in 8 bits")

    frame_id = (spacecraft_id << 4) | (virtual_channel_id << 1)
    header = _TM_PRIMARY_HEADER.pack(
        frame_id,
        master_channel_count,
        virtual_channel_count,
        _TM_DATA_FIELD_STATUS,
    )
    return header + packet


def fecf_ccsds(data: bytes) -> bytes:
    """Compute the two-byte FECF for TM frame bytes that precede the FECF.

    References:
        CCSDS 132.0-B-3, TM Space Data Link Protocol, section 4.1.6,
        "Frame Error Control Field"; the CRC encoding procedure and generator
        polynomial x^16 + x^12 + x^5 + 1 are specified in section 4.1.6.2.

    Processing flow:
        TM bytes preceding the FECF
                    |
                    v
           Initialize remainder to 0xFFFF
                    |
                    v
           Process each byte MSB first
                    |
                    v
        Shift/XOR each bit with polynomial 0x1021
                    |
                    v
           Encode the 16-bit remainder big-endian
                    |
                    v
                   Two-byte FECF

    Direct call tree (static source order):
        fecf_ccsds
        +-- range
        `-- remainder.to_bytes
    """
    remainder = 0xFFFF

    for octet in data:
        remainder ^= octet << 8
        for _ in range(8):
            if remainder & 0x8000:
                remainder = ((remainder << 1) ^ 0x1021) & 0xFFFF
            else:
                remainder = (remainder << 1) & 0xFFFF

    return remainder.to_bytes(2, "big")

def build_tm_frame(
    record: bytes,
    sequence_count: int,
    master_channel_count: int,
    virtual_channel_count: int,
    apid: int = LAB_APID,
    spacecraft_id: int = LAB_SCID,
    virtual_channel_id: int = LAB_VCID,
) -> bytes:
    """Build one complete 64-byte TM transfer frame from a mission record.

    References:
        CCSDS 133.0-B-2, Space Packet Protocol, section 4.1.3; CCSDS 132.0-B-3, TM Space
        Data Link Protocol, sections 4.1.2 and 4.1.6.

    Processing flow:
        50-byte mission record
                  |
                  v
           Add Space Packet header
                  |
                  v
           Add TM primary header
                  |
                  v
           Compute FECF over 62 bytes
                  |
                  v
           Append the two-byte FECF
                  |
                  v
           64-byte TM transfer frame

    Direct call tree (static source order):
        build_tm_frame
        +-- pack_space_packet
        +-- pack_tm_protected_data
        `-- fecf_ccsds
    """
    packet = pack_space_packet(
        record,
        sequence_count=sequence_count,
        apid=apid,
    )
    protected_data = pack_tm_protected_data(
        packet,
        master_channel_count=master_channel_count,
        virtual_channel_count=virtual_channel_count,
        spacecraft_id=spacecraft_id,
        virtual_channel_id=virtual_channel_id,
    )
    return protected_data + fecf_ccsds(protected_data)

def validate_tm_frame(frame: bytes) -> FrameValidationResult:
    """Check the fixed frame length and, when possible, its transmitted FECF.

    References:
        CCSDS 132.0-B-3, TM Space Data Link Protocol, section 4.1.6, "Frame Error
        Control Field.".

    Processing flow:
        Candidate TM frame
                 |
                 v
           Check 64-byte length
                 |
            +----+----+
            |         |
            v         v
        Wrong length  Split protected bytes and received FECF
            |                   |
            v                   v
        fecf_ok=None       Recalculate and compare FECF
            |                   |
            +---------+---------+
                      |
                      v
              FrameValidationResult

    Direct call tree (static source order):
        validate_tm_frame
        +-- len
        +-- FrameValidationResult
        `-- fecf_ccsds
    """
    if len(frame) != _TM_FRAME_LENGTH:
        return FrameValidationResult(length_ok=False, fecf_ok=None)

    received_fecf = frame[-2:]
    calculated_fecf = fecf_ccsds(frame[:-2])
    return FrameValidationResult(
        length_ok=True,
        fecf_ok=received_fecf == calculated_fecf,
    )
