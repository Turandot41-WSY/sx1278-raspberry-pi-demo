"""Capture radio packets on a local Nano independently of the sending computer.

Call tree:
run -> validate settings/build -> preserve configuration -> optional exact-session display -> open_nano_port
    -> configure_transmitter [shared identity/profile/PA setup; no START_TX]
    -> receive_window [ARM_RX -> RX_ARMED -> RX_PACKET/RX_TIMEOUT]
    -> record exact packet bytes and host time -> close UART, evidence and display
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time

from host.common.runtime_config import PROJECT_ROOT, parse_configured_args
from host.radio.profile_truth import load_profile_truth
from host.radio.serial_transport import EndpointTransport, SystemClock, open_nano_port
from host.radio.single_transmit import TransmitEvidence, configure_transmitter
from host.radio.single_receive import receive_window
from host.cli.receive_display import start_for_capture


def run(arguments=None) -> int:
    """Configure the local radio and save each independent receive observation.

    The firmware requires profile and PA setup before ARM_RX, so the same setup
    function used by the transmitter is reused. SET_PA only configures registers;
    this path never issues LOAD_TX or START_TX. The radio uses 437.5 MHz as fixed
    by the existing firmware. These observations are diagnostic capture evidence.

    Processing flow:
        Validate settings and build -> snapshot configuration -> optional display -> settle UART
        -> verify identity/registers -> repeat receive windows -> summarize/close.
        Ctrl+C ends capture; a protocol failure records INCOMPLETE and stops.

    Direct call tree (static source order):
        run
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- options.device.startswith
        +-- parser.error
        +-- options.manifest.read_text
        +-- json.loads
        +-- manifest.get
        +-- load_profile_truth
        +-- profile_ids.append
        +-- datetime.now
        +-- datetime.now(...).strftime
        +-- directory.mkdir
        +-- <BinOp expression>.write_text
        +-- <BinOp expression>.write_bytes
        +-- source.read_bytes
        +-- TransmitEvidence
        +-- SystemClock
        +-- secrets.randbelow
        +-- print
        +-- evidence.record
        +-- start_for_capture
        +-- open_nano_port
        +-- clock.sleep_ms
        +-- port.reset_input_buffer
        +-- EndpointTransport
        +-- configure_transmitter
        +-- ValueError
        +-- receive_window
        +-- observation.pop
        +-- time.time_ns
        +-- repr
        +-- port.close
        +-- evidence.close
        `-- display.close
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", default="LoRa")
    parser.add_argument("--rx-window-ms", type=int, default=5000)
    parser.add_argument("--timeout-ms", type=int, default=2000)
    parser.add_argument("--boot-settle-ms", type=int, default=2500)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--display", action=argparse.BooleanOptionalAction, default=False)
    options = parse_configured_args(parser, arguments, "main_receive", section="listen")
    if options.device.startswith("tcp://"):
        parser.error("listen requires a local UART, for example COM4")
    if not 1 <= options.rx_window_ms <= 65535:
        parser.error("rx_window_ms must be between 1 and 65535")
    if options.timeout_ms <= 0 or options.boot_settle_ms < 0:
        parser.error("timeout must be positive and boot settling nonnegative")
    if not 0 <= options.max_windows <= 0x100000000:
        parser.error("max_windows must be zero or a positive uint32 range length")
    manifest_text = options.manifest.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    if manifest.get("compiled") is not True:
        parser.error("manifest must describe the completed build flashed on this receiver")
    truth = load_profile_truth(PROJECT_ROOT / "config")
    profile_ids = []
    for profile in truth.profiles:
        profile_ids.append(profile.profile_id)
    if options.profile not in profile_ids:
        parser.error("profile must match a ProfileId in config/profiles.csv")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    directory = options.output / stamp
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "firmware_manifest.json").write_text(manifest_text, encoding="utf-8")
    for name in ("profiles.csv", "pa_settings.csv", "profile_registers.csv"):
        source = PROJECT_ROOT / "config" / name
        (directory / name).write_bytes(source.read_bytes())
    evidence = TransmitEvidence(directory / "events.jsonl")
    clock = SystemClock()
    run_token = secrets.randbelow(0xFFFFFFFF) + 1
    port = None
    windows = 0
    packets = 0
    timeouts = 0
    status = "COMPLETED"
    exit_code = 0
    display = None
    print(f"Evidence: {directory}", flush=True)
    try:
        evidence.record("run_start", data_origin="physical_serial", purpose="diagnostic_capture",
                        device=options.device, profile=options.profile, run_token=run_token,
                        rx_window_ms=options.rx_window_ms, timeout_ms=options.timeout_ms,
                        boot_settle_ms=options.boot_settle_ms, max_windows=options.max_windows,
                        nominal_reg_frf_word=0x6D6000)
        if options.display:
            display = start_for_capture(options.settings, directory)
        port = open_nano_port(options.device)
        clock.sleep_ms(options.boot_settle_ms)
        port.reset_input_buffer()
        transport = EndpointTransport(port, manifest["endpoint_id"], evidence, clock)
        configure_transmitter(transport, truth, manifest, options.profile, 2, options.timeout_ms)
        evidence.record("configured")
        while options.max_windows == 0 or windows < options.max_windows:
            if windows > 0xFFFFFFFF:
                raise ValueError("receive window index exhausted")
            observation = receive_window(transport, run_token, windows,
                                         options.rx_window_ms, options.timeout_ms, evidence)
            event = observation.pop("event")
            evidence.record(event, host_received_utc_ns=time.time_ns(), **observation)
            windows += 1
            if event == "rx_packet":
                packets += 1
                print(f"RX_PACKET: length={observation['received_length']} "
                      f"phy_crc_ok={observation['phy_crc_ok']} "
                      f"hex={observation['packet_hex']}", flush=True)
            else:
                timeouts += 1
                print("RX_TIMEOUT: empty window; arming the next window", flush=True)
    except KeyboardInterrupt:
        status = "STOPPED_BY_USER"
    except Exception as error:
        status = "INCOMPLETE"
        exit_code = 1
        evidence.record("error", error=repr(error), retry_performed=False)
        print(f"Stopped: {error}", flush=True)
    finally:
        try:
            if port is not None:
                port.close()
        finally:
            evidence.record("summary", status=status, completed_windows=windows,
                            rx_packets=packets, rx_timeouts=timeouts)
            evidence.close()
            if display is not None:
                display.close()
    return exit_code
