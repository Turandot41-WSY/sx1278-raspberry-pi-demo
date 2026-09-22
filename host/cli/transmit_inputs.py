"""Prepare saved or newly acquired orbit data for independent transmission."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from host.cli import acquire
from host.dataset.ccsds_tm import build_tm_frame
from host.dataset.orbit_trace import load_frozen_orbit_dataset
from host.dataset.payload_schedule import PayloadSample
from host.radio.antenna_doppler import load_antenna_plan
from host.radio.single_transmit import SavedFrames, load_saved_frames


@dataclass(frozen=True)
class PreparedTransmission:
    """Bind immutable frame bytes to their selected source and frequency samples."""

    frames: SavedFrames
    plan: tuple[PayloadSample, ...] | None
    orbit_directory: Path | None
    dataset_id: str | None
    data_source: str
    pass_count: int | None = None


def prepare_transmit_inputs(options, frame_path: Path) -> PreparedTransmission:
    """Resolve the selected source and save validated frames before opening UART.

    Processing flow:
        Latest acquisition or selected saved input -> validate frozen dataset
        -> build unchanged frame format -> save bytes and hash -> select range.
        Legacy frame files retain their explicit hash and optional orbit binding.

    Direct call tree (static source order):
        prepare_transmit_inputs
        +-- print
        +-- acquire.fetch_latest_dataset
        +-- ValueError
        +-- load_saved_frames
        +-- options.orbit_dataset.resolve
        +-- load_antenna_plan
        +-- manifest_path.is_file
        +-- json.loads
        +-- manifest_path.read_text
        +-- PreparedTransmission
        +-- root.resolve
        +-- load_frozen_orbit_dataset
        +-- samples.extend
        +-- len
        +-- bytearray
        +-- enumerate
        +-- build_tm_frame
        +-- data.extend
        +-- frame_path.open
        +-- stream.write
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        `-- tuple
    """
    root = None
    if options.data_source == 'latest':
        print('[Input] Acquiring a new five-pass orbit dataset...', flush=True)
        root = acquire.fetch_latest_dataset()
    elif options.data_source == 'saved':
        root = options.saved_dataset
    else:
        raise ValueError('data_source must be latest or saved')

    if root is None:
        print('[Input] Loading saved frame file...', flush=True)
        if options.frames is None or not options.sha256:
            raise ValueError('saved source requires saved_dataset or both frames and sha256')
        frames = load_saved_frames(options.frames, options.sha256, options.start, options.count)
        plan = None
        orbit_directory = None
        if options.orbit_dataset is not None:
            orbit_directory = options.orbit_dataset.resolve()
            print(f'[Input] Validating orbit binding: {orbit_directory}', flush=True)
            plan = load_antenna_plan(orbit_directory, frames)
        dataset_id = None
        pass_count = None
        if orbit_directory is not None:
            manifest_path = orbit_directory / 'orbit_manifest.json'
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                dataset_id = manifest['DatasetId']
                pass_count = manifest['PassCount']
        return PreparedTransmission(frames, plan, orbit_directory, dataset_id,
                                    'saved', pass_count)

    root = root.resolve()
    print(f'[Input] Validating five-pass orbit dataset: {root}', flush=True)
    dataset = load_frozen_orbit_dataset(root)
    samples = []
    for orbit_pass in dataset.passes:
        samples.extend(orbit_pass.schedule.samples)
        print(f'[Input] {orbit_pass.pass_label}: {orbit_pass.sample_count} samples', flush=True)
    print(f'[Input] Building {len(samples)} frames (64 bytes each)...', flush=True)
    data = bytearray()
    for index, sample in enumerate(samples):
        frame = build_tm_frame(sample.mission_record, index % 16384,
                               index % 256, index % 256)
        data.extend(frame)
    with frame_path.open('xb') as stream:
        stream.write(data)
    digest = hashlib.sha256(data).hexdigest()
    frames = load_saved_frames(frame_path, digest, options.start, options.count)
    print(f'[Input] Frames saved: {frames.source}', flush=True)
    print(f'[Input] Frame SHA256: {digest}', flush=True)
    return PreparedTransmission(frames, tuple(samples), root,
                                dataset.dataset_id, options.data_source, len(dataset.passes))
