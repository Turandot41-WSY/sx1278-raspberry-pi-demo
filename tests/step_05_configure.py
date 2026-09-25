"""Verify HELLO identity and radio register readbacks through the production endpoint setup."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Configure one connected board and preserve its identity and register evidence.

    Processing flow:
        Validate explicit settings and the compiled manifest -> snapshot inputs
        -> open and settle UART -> call production endpoint setup
        -> record the result and close the port and evidence file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True,
                        help="Local USB serial port, for example COM4 or /dev/ttyUSB0")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Manifest JSON from the production build uploaded to this board")
    parser.add_argument("--profile", default="LoRa",
                        choices=("LoRa", "FSK", "GFSK", "MSK", "GMSK", "OOK"),
                        help="Profile whose registers will be applied and checked; default: LoRa")
    parser.add_argument("--pa-dbm", type=int, default=2,
                        help="Power configuration in dBm from firmware/config/pa_settings.csv; default: 2")
    parser.add_argument("--timeout-ms", type=int, default=2000,
                        help="Positive serial response timeout in milliseconds; default: 2000")
    parser.add_argument("--boot-settle-ms", type=int, default=2500,
                        help="Nonnegative wait after opening UART in milliseconds; default: 2500")
    parser.add_argument("--output", type=Path, default=ROOT / "output/hardware-configure",
                        help="Evidence root; a new UTC directory is created for each run")
    options = parser.parse_args(arguments)
    if not options.device.strip() or "://" in options.device:
        parser.error("device must name a local USB serial port")
    if options.timeout_ms <= 0 or options.boot_settle_ms < 0:
        parser.error("timeout must be positive and boot settling must be nonnegative")

    from firmware.host.endpoint import SerialEvidence, configure_endpoint
    from firmware.host.profile_truth import load_profile_truth
    from firmware.host.serial_transport import EndpointTransport, SystemClock, open_nano_port

    try:
        manifest_text = options.manifest.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        if manifest.get("compiled") is not True:
            raise ValueError("manifest must describe the completed build uploaded to this board")
        endpoint_id = manifest["endpoint_id"]
        table_directory = ROOT / "firmware/config"
        truth = load_profile_truth(table_directory)
        power_exists = False
        for setting in truth.pa_settings:
            if setting.pa_command_dbm == options.pa_dbm:
                power_exists = True
        if not power_exists:
            raise ValueError("pa-dbm must match a command value in firmware/config/pa_settings.csv")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    directory = options.output / stamp
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "firmware_manifest.json").write_text(manifest_text, encoding="utf-8")
    for name in ("profiles.csv", "pa_settings.csv", "profile_registers.csv"):
        source = table_directory / name
        (directory / name).write_bytes(source.read_bytes())
    evidence = SerialEvidence(directory / "events.jsonl")
    clock = SystemClock()
    port = None
    status = "COMPLETED"
    exit_code = 0
    print(f"Evidence: {directory}", flush=True)
    try:
        evidence.record("run_start", data_origin="physical_serial",
                        purpose="hardware_configuration_check", device=options.device,
                        profile=options.profile, pa_dbm=options.pa_dbm,
                        timeout_ms=options.timeout_ms, boot_settle_ms=options.boot_settle_ms)
        port = open_nano_port(options.device)
        clock.sleep_ms(options.boot_settle_ms)
        port.reset_input_buffer()
        transport = EndpointTransport(port, endpoint_id, evidence, clock)
        configure_endpoint(transport, truth, manifest, options.profile,
                           options.pa_dbm, options.timeout_ms)
        evidence.record("configured")
        print("HELLO identity, profile readback and PA readback passed.", flush=True)
    except (Exception, KeyboardInterrupt) as error:
        status = "INCOMPLETE"
        exit_code = 1
        evidence.record("error", error=repr(error), retry_performed=False)
        print(f"Configuration check stopped: {error}", file=sys.stderr, flush=True)
    finally:
        try:
            if port is not None:
                port.close()
        finally:
            evidence.record("summary", status=status)
            evidence.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
