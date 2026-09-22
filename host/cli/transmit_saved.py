"""Prepare selected data and run the Nano RF transmission experiment.

Configuration: config/main_transmit.toml [antenna] or legacy [saved]
Instructions: README.md
Call tree:
run() - run the saved-frame experiment
+-- prepare_transmit_inputs() - acquire or load data, verify bytes and choose frame range
+-- configure_transmitter() - verify/configure the real endpoint
`-- transmit_frame() - LOAD_TX, START_TX and TX_DONE
    `-- EndpointTransport - production wire codec and serial evidence
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets

from host.cli.transmit_inputs import prepare_transmit_inputs

from host.radio.profile_truth import load_profile_truth
from host.common.runtime_config import PROJECT_ROOT, parse_configured_args
from host.radio.serial_transport import EndpointTransport, SystemClock, open_nano_port
from host.radio.single_transmit import (
    TransmitEvidence, configure_transmitter, transmit_frame,
)


def confirm_transmission(prepared, options) -> bool:
    """Ask the operator to approve prepared data before opening the transmitter.

    Processing flow:
        Show the selected source and frame range -> read one explicit answer
        -> approve y/yes or cancel on any other answer, EOF, or interruption.

    Direct call tree (static source order):
        confirm_transmission
        +-- print
        +-- input
        +-- answer.strip
        `-- answer.strip(...).lower
    """
    frames = prepared.frames
    print(f"[Ready] Data source: {prepared.data_source}", flush=True)
    if prepared.orbit_directory is not None:
        print(f"[Ready] Dataset: {prepared.orbit_directory}", flush=True)
    if prepared.pass_count is not None:
        print(f"[Ready] Passes in dataset: {prepared.pass_count}", flush=True)
    print(f"[Ready] Frames: {frames.count}; start index: {frames.start}; profile: {options.profile}; power: {options.pa_dbm} dBm", flush=True)
    print(f"[Ready] Prepared frame file: {frames.source}", flush=True)
    try:
        answer = input('Data is ready. Start transmission? [y/N] ')
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ('y', 'yes')


def run(arguments=None, *, section="saved") -> int:
    """Prepare the selected data source and transmit frames with recorded evidence.

    Processing flow:
        Validate config -> acquire or load data -> prepare and preserve frames
        -> request operator confirmation -> open production serial link
        -> verify/configure endpoint -> transmit selected frames -> close and summarize.

    Direct call tree (static source order):
        run
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- parser.error
        +-- options.port.startswith
        +-- print
        +-- options.manifest.read_text
        +-- json.loads
        +-- manifest.get
        +-- load_profile_truth
        +-- datetime.now
        +-- datetime.now(...).strftime
        +-- directory.mkdir
        +-- prepare_transmit_inputs
        +-- frame_snapshot.exists
        +-- frame_snapshot.write_bytes
        +-- json.dumps
        +-- manifest_snapshot.write_text
        +-- source_table.read_bytes
        +-- destination_table.write_bytes
        +-- range
        +-- frequency_rows.append
        +-- <BinOp expression>.write_text
        +-- orbit_manifest.exists
        +-- <BinOp expression>.write_bytes
        +-- orbit_manifest.read_bytes
        +-- TransmitEvidence
        +-- secrets.randbelow
        +-- SystemClock
        +-- str
        +-- evidence.record
        +-- confirm_transmission
        +-- open_nano_port
        +-- clock.sleep_ms
        +-- port.reset_input_buffer
        +-- EndpointTransport
        +-- configure_transmitter
        +-- frames.frame
        +-- frame.hex
        +-- transmit_frame
        +-- repr
        +-- port.close
        `-- evidence.close
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--data-source", choices=("saved", "latest"), default="saved")
    parser.add_argument("--saved-dataset", type=Path)
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", default="1")
    parser.add_argument("--profile", default="LoRa")
    parser.add_argument("--pa-dbm", type=int, default=2)
    parser.add_argument("--reg-frf-word", type=int, default=7168000)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--timeout-ms", type=int, default=2000)
    parser.add_argument("--orbit-dataset", type=Path)
    configuration_name = "main_transmit"
    configuration_section = section
    options = parse_configured_args(
        parser, arguments, configuration_name, section=configuration_section
    )
    if options.interval_ms < 0 or options.timeout_ms <= 0:
        parser.error("interval must be nonnegative and timeout must be positive")
    if not 0 <= options.reg_frf_word <= 0xFFFFFF:
        parser.error("FRF must fit unsigned 24 bits")
    if options.port.startswith("tcp://"):
        parser.error("antenna/saved transmission requires a local UART")
    print("[Prepare] Checking transmitter settings and firmware manifest...", flush=True)
    manifest_text = options.manifest.read_text()
    manifest = json.loads(manifest_text)
    if manifest.get("compiled") is not True:
        parser.error("firmware manifest is not a completed build; run the production builder first")
    radio_table_directory = PROJECT_ROOT / "config"
    truth = load_profile_truth(radio_table_directory)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    directory = options.output / stamp
    directory.mkdir(parents=True, exist_ok=False)
    frame_snapshot = directory / "input_frames.bin"
    try:
        prepared = prepare_transmit_inputs(options, frame_snapshot)
    except (Exception, KeyboardInterrupt) as error:
        if options.data_source == 'saved' and options.saved_dataset is None:
            raise
        print(f"Stopped before transmission: {error}. No frames transmitted.", flush=True)
        return 1
    frames = prepared.frames
    plan = prepared.plan
    if not frame_snapshot.exists():
        frame_snapshot.write_bytes(frames.data)
    manifest_snapshot = directory / "firmware_manifest.json"
    manifest_json = json.dumps(manifest, indent=2)
    manifest_snapshot.write_text(manifest_json + "\n")
    for name in ("profiles.csv", "pa_settings.csv", "profile_registers.csv"):
        source_table = radio_table_directory / name
        destination_table = directory / name
        table_bytes = source_table.read_bytes()
        destination_table.write_bytes(table_bytes)
    if plan is not None and prepared.orbit_directory is not None:
        frequency_rows = []
        for index in range(frames.start, frames.start + frames.count):
            sample = plan[index]
            frequency_rows.append({"frame_index": index, "reg_frf_word": sample.reg_frf_word,
                "requested_cfo_hz": sample.requested_cfo_hz,
                "programmed_cfo_hz": sample.programmed_cfo_hz})
        (directory / "frequency_plan.json").write_text(json.dumps(frequency_rows, indent=2) + "\n")
        orbit_manifest = prepared.orbit_directory / "orbit_manifest.json"
        if orbit_manifest.exists():
            (directory / "orbit_manifest.json").write_bytes(orbit_manifest.read_bytes())
    evidence = TransmitEvidence(directory / "events.jsonl")
    token = secrets.randbelow(0xFFFFFFFF) + 1
    completed = 0
    port = None
    clock = SystemClock()
    print(f"Evidence: {directory}", flush=True)
    experiment_kind = "saved_fixed_frequency"
    orbit_directory = None
    if plan is not None:
        experiment_kind = "antenna_doppler_diagnostic"
        orbit_directory = str(prepared.orbit_directory)
    try:
        evidence.record("run_start", source=str(frames.source), sha256=frames.sha256,
                        start=frames.start, count=frames.count, run_token=token,
                        port=options.port, profile=options.profile, pa_dbm=options.pa_dbm,
                        reg_frf_word=options.reg_frf_word, interval_ms=options.interval_ms,
                        timeout_ms=options.timeout_ms, data_origin="physical_serial",
                        experiment_kind=experiment_kind,
                        orbit_dataset=orbit_directory, data_source=prepared.data_source,
                        dataset_id=prepared.dataset_id,
                        receiver=None, receive_coordination="independent")
        accepted = confirm_transmission(prepared, options)
        evidence.record("send_confirmation", accepted=accepted)
        if not accepted:
            evidence.record("summary", status="CANCELLED_BEFORE_SEND", tx_done=0,
                            requested=frames.count)
            print(f"Cancelled. Prepared data retained at {directory}. No frames transmitted.", flush=True)
            return 0
        print(f"[Radio] Opening transmitter: {options.port}", flush=True)
        port = open_nano_port(options.port)
        # Opening a Nano serial port resets its bootloader; wait before binary HELLO.
        clock.sleep_ms(2500)
        port.reset_input_buffer()
        transport = EndpointTransport(port, manifest["endpoint_id"], evidence, clock)
        print(f"[Radio] Verifying firmware and applying {options.profile} profile...", flush=True)
        configure_transmitter(transport, truth, manifest, options.profile,
                              options.pa_dbm, options.timeout_ms)
        evidence.record("configured")
        first_frame_index = frames.start
        stop_frame_index = frames.start + frames.count
        print(f"[Transmit] Sending {frames.count} frames from index {frames.start}...", flush=True)
        for index in range(first_frame_index, stop_frame_index):
            frame = frames.frame(index)
            word = options.reg_frf_word
            requested_cfo_hz = None
            programmed_cfo_hz = None
            if plan is not None:
                sample = plan[index]
                word = sample.reg_frf_word
                requested_cfo_hz = sample.requested_cfo_hz
                programmed_cfo_hz = sample.programmed_cfo_hz
            evidence.record("frame_requested", frame_index=index, frame_hex=frame.hex(),
                            reg_frf_word=word, requested_cfo_hz=requested_cfo_hz,
                            programmed_cfo_hz=programmed_cfo_hz)
            transmit_frame(transport, frame, index, token, word, options.timeout_ms)
            completed += 1
            evidence.record("tx_done", frame_index=index)
            print(f"Frame {index}: TX_DONE ({completed}/{frames.count})", flush=True)
            if completed < frames.count:
                clock.sleep_ms(options.interval_ms)
        evidence.record("summary", status="COMPLETED", tx_done=completed, requested=frames.count)
        print(f"[Complete] {completed}/{frames.count} frames transmitted. Evidence: {directory}", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        evidence.record("summary", status="INCOMPLETE", tx_done=completed,
                        requested=frames.count, error=repr(error), retry_performed=False)
        print(f"Stopped: {error}. Recorded TX_DONE: {completed}; no automatic retry.", flush=True)
        return 1
    finally:
        if port is not None:
            port.close()
        evidence.close()
