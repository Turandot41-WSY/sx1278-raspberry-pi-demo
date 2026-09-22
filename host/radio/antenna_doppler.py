"""Bind antenna diagnostic frames to validated frozen orbit frequency samples."""

from host.dataset.orbit_trace import load_frozen_orbit_dataset
from host.dataset.ccsds_tm import build_tm_frame


def load_antenna_plan(root, frames):
    """Match saved frame bytes to every frozen orbit sample before opening UART.

    Processing flow:
        Validated orbit artifacts -> flatten ordered samples -> reconstruct frame
        bytes -> reject mismatches -> return corresponding frequency samples.

    Direct call tree (static source order):
        load_antenna_plan
        +-- load_frozen_orbit_dataset
        +-- samples.extend
        +-- len
        +-- ValueError
        +-- enumerate
        +-- build_tm_frame
        `-- tuple
    """
    dataset = load_frozen_orbit_dataset(root)
    samples = []
    for orbit_pass in dataset.passes:
        samples.extend(orbit_pass.schedule.samples)
    if len(samples) * 64 != len(frames.data):
        raise ValueError("orbit sample count differs from saved frame count")
    for index, sample in enumerate(samples):
        # Reuse the project's frame builder and standalone sequence convention.
        expected = build_tm_frame(sample.mission_record, index % 16384,
                                  index % 256, index % 256)
        actual = frames.data[index * 64:(index + 1) * 64]
        if actual != expected:
            raise ValueError(f"orbit frame differs from saved bytes at index {index}")
    return tuple(samples)
