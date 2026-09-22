"""Common immutable payload schedule types for static and orbit traces."""

from dataclasses import dataclass

from host.common.canonical import sha256_bytes
from host.dataset.orbit_record import MissionRecord, pack_mission_record


STATIC_ZERO_CFO_SHA256 = (
    "482359ebd73182c810660451b1de7027903322c373f9c1f3c06f5173d113377e"
)
STATIC_ZERO_CFO_SAMPLE_COUNT = 500
NOMINAL_REG_FRF_WORD = 0x6D6000


@dataclass(frozen=True)
class PayloadSample:
    """Hold one mission record together with its external RF control values."""

    trace_sample_id: int
    pass_sample_index: int
    requested_cfo_hz: float
    programmed_cfo_hz: float
    reg_frf_word: int
    mission_record: bytes


@dataclass(frozen=True)
class PayloadSchedule:
    """Hold one ordered immutable sequence of payload and CFO samples."""

    schedule_id: str
    samples: tuple[PayloadSample, ...]
    schedule_sha256: str

    def prefix(self, count: int) -> "PayloadSchedule":
        """Return a named leading subset with a mission-record stream hash.

        Processing flow:
            Prefix count -> integer/range validation -> leading samples -> exact
            mission-record byte stream -> derived schedule identity and hash.

        Direct call tree (static source order):
            prefix
            +-- isinstance
            +-- ValueError
            +-- len
            +-- bytearray
            +-- stream.extend
            +-- sha256_bytes
            +-- bytes
            `-- PayloadSchedule
        """
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("schedule prefix count must be an integer")
        if count <= 0 or count > len(self.samples):
            raise ValueError("schedule prefix count is out of range")
        chosen = self.samples[:count]
        stream = bytearray()
        for sample in chosen:
            stream.extend(sample.mission_record)
        digest = sha256_bytes(bytes(stream))
        return PayloadSchedule(
            schedule_id=f"{self.schedule_id}:prefix:{count}",
            samples=chosen,
            schedule_sha256=digest,
        )


def build_static_zero_cfo_schedule() -> PayloadSchedule:
    """Build the approved 500-record static schedule with CFO fixed at zero.

    Processing flow:
        Sample IDs 0..499 -> zero geometry and CFO MissionRecord values -> shared
        50-byte packer -> 25,000-byte approved stream -> frozen hash verification
        -> immutable static schedule.

    Direct call tree (static source order):
        build_static_zero_cfo_schedule
        +-- bytearray
        +-- MissionRecord
        +-- pack_mission_record
        +-- PayloadSample
        +-- samples.append
        +-- stream.extend
        +-- sha256_bytes
        +-- bytes
        +-- RuntimeError
        +-- PayloadSchedule
        `-- tuple
    """
    samples: list[PayloadSample] = []
    stream = bytearray()
    index = 0
    while index < STATIC_ZERO_CFO_SAMPLE_COUNT:
        record = MissionRecord(
            trace_time_ms=index * 1000,
            position_x_m=0,
            position_y_m=0,
            position_z_m=0,
            velocity_x_mmps=0,
            velocity_y_mmps=0,
            velocity_z_mmps=0,
            slant_range_m=0,
            range_rate_mmps=0,
            doppler_millihz=0,
            mission_state=0,
            workload=0,
            trace_sample_id=index,
        )
        packed_record = pack_mission_record(record)
        sample = PayloadSample(
            trace_sample_id=index,
            pass_sample_index=index,
            requested_cfo_hz=0.0,
            programmed_cfo_hz=0.0,
            reg_frf_word=NOMINAL_REG_FRF_WORD,
            mission_record=packed_record,
        )
        samples.append(sample)
        stream.extend(packed_record)
        index += 1
    digest = sha256_bytes(bytes(stream))
    if digest != STATIC_ZERO_CFO_SHA256:
        raise RuntimeError("static_zero_cfo_v1 hash does not match approved design")
    return PayloadSchedule(
        schedule_id="static_zero_cfo_v1",
        samples=tuple(samples),
        schedule_sha256=digest,
    )
