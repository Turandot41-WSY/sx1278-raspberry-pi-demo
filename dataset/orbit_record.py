"""Packing rules for the benchmark's fixed mission record."""

import struct
from dataclasses import dataclass


_MISSION_RECORD = struct.Struct(">IiiiiiiIiiBBH6s")


@dataclass(frozen=True, slots=True)
class MissionRecord:
    """Hold one already-quantized orbital trace sample.

    Keeping the values in a named structure makes the 50-byte
    wire layout readable and reproducible. Each attribute maps directly to
    one fixed-width field; unit conversion is deliberately done elsewhere.
    """

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


def validation_pattern(sample_id: int) -> bytes:
    """Build a six-byte diagnostic pattern from a 16-bit sample ID.

    Processing flow:
        16-bit trace sample ID
                  |
                  v
           Validate uint16 range
                  |
                  v
        Derive XOR and byte-swapped words
                  |
                  v
        Pack three big-endian uint16 words
                  |
                  v
           Six-byte diagnostic pattern

    Direct call tree (static source order):
        validation_pattern
        +-- ValueError
        `-- struct.pack
    """
    if not 0 <= sample_id <= 0xFFFF:
        raise ValueError("sample_id must fit in uint16")

    swapped = ((sample_id & 0xFF) << 8) | (sample_id >> 8)
    return struct.pack(">HHH", sample_id, sample_id ^ 0xA5A5, swapped)


def pack_mission_record(record: MissionRecord) -> bytes:
    """Pack one mission record into the frozen 50-byte wire format.

    Processing flow:
        Quantized MissionRecord fields
                    |
                    v
        Build the six-byte validation pattern
                    |
                    v
        Pack the frozen big-endian struct layout
                    |
             +------+------+
             |             |
             v             v
        50-byte record  struct range error
                               |
                               v
                         clear ValueError

    Direct call tree (static source order):
        pack_mission_record
        +-- _MISSION_RECORD.pack
        +-- validation_pattern
        `-- ValueError
    """
    try:
        return _MISSION_RECORD.pack(
            record.trace_time_ms,
            record.position_x_m,
            record.position_y_m,
            record.position_z_m,
            record.velocity_x_mmps,
            record.velocity_y_mmps,
            record.velocity_z_mmps,
            record.slant_range_m,
            record.range_rate_mmps,
            record.doppler_millihz,
            record.mission_state,
            record.workload,
            record.trace_sample_id,
            validation_pattern(record.trace_sample_id),
        )
    except struct.error as error:
        raise ValueError(f"mission record field out of range: {error}") from error


def unpack_mission_record(data: bytes) -> MissionRecord:
    """Restore one mission record from exactly 50 received bytes.

    Processing flow:
        Received mission-record bytes
                    |
                    v
           Require exactly 50 bytes
                    |
                    v
          Unpack the big-endian struct
                    |
                    v
          Map fields into MissionRecord
                    |
                    v
                MissionRecord

    Direct call tree (static source order):
        unpack_mission_record
        +-- len
        +-- ValueError
        +-- _MISSION_RECORD.unpack
        `-- MissionRecord
    """
    if len(data) != _MISSION_RECORD.size:
        raise ValueError(
            f"mission record must be exactly {_MISSION_RECORD.size} bytes"
        )

    (
        trace_time_ms,
        position_x_m,
        position_y_m,
        position_z_m,
        velocity_x_mmps,
        velocity_y_mmps,
        velocity_z_mmps,
        slant_range_m,
        range_rate_mmps,
        doppler_millihz,
        mission_state,
        workload,
        trace_sample_id,
        _diagnostic_pattern,
    ) = _MISSION_RECORD.unpack(data)

    return MissionRecord(
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
        mission_state=mission_state,
        workload=workload,
        trace_sample_id=trace_sample_id,
    )
