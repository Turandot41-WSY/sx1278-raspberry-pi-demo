# Receive through Nano A

[Repository overview](../README.md) · [Transmit](../transmit/README.md) · [Hardware checks](../tests/README.md)

`receiver/main.py` listens through the local Nano A, endpoint 1, prints received packets, saves their bytes and radio status, and serves the local browser display. Run it on macOS or Windows after completing the [macOS](../setup/macos/README.md) or [Windows](../setup/windows/README.md) setup. The sender uses Nano B on Raspberry Pi 5 or another Windows computer.

Activate `sx1278-benchmark` and run from the repository root. Record the source revision with `git rev-parse HEAD` on both computers.

## Select the receiver

Find the actual port with `python -m serial.tools.list_ports -v`. On macOS, replace the example port:

```bash
python firmware/tools/configure_antenna.py --device /dev/cu.usbserial-110 --board A --role rx --profile LoRa
```

On Windows, for example:

```powershell
python firmware/tools/configure_antenna.py --device COM4 --board A --role rx --profile LoRa
```

This writes the local device, A's manifest and selected profile into `receiver/config.toml`, and selects A in `firmware/config/internal/board_control.toml`. Build and upload using the platform guide before starting reception.

## Review the configuration

[`config.toml`](config.toml) owns the receiver settings. Its only action is `listen`, selected by the top-level `action`.

| `[listen]` field | Meaning |
|---|---|
| `device` | Actual local serial port, such as `/dev/cu.usbserial-110` or `COM4` |
| `manifest` | `firmware/build/single-endpoint/manifest.json` matching the firmware uploaded to A |
| `output` | Root for a new UTC receive directory, normally `output/receive` |
| `profile` | Same compiled modulation as the transmitter; use `LoRa` for the first trial |
| `rx_window_ms` | Receive window length in milliseconds; default 5000 |
| `timeout_ms` | Additional wait for UART responses in milliseconds; default 2000 |
| `boot_settle_ms` | Wait after opening UART, in milliseconds, because the Nano may reset; default 2500 |
| `max_windows` | Completed receive windows; 0 continues until Ctrl+C |

The receiver stays at nominal 437.5 MHz. Window count is independent of transmitted frame count. Each window ends after a packet or timeout, then another opens while listening continues.

## Listen before starting the sender

```text
python receiver/main.py
```

`python -m receiver.main` uses the same settings. Wait for `RX_ARMED` before confirming transmission on the sender. Empty `RX_TIMEOUT` windows are expected while the sender is idle. A received packet prints its actual length, PHY CRC status and hexadecimal bytes; the JSONL log preserves raw metrics, timestamps and serial messages.

For the initial trial, look for three `RX_PACKET` lines with `length=64` and `phy_crc_ok=1`. Stop with **Ctrl+C** after the sender completes. Keep the directory printed for this session. Its `events.jsonl`, firmware manifest and radio table snapshots belong to the trial.

## Browser demonstration

The same `python receiver/main.py` command starts the approved display at
[http://127.0.0.1:8878/monitor](http://127.0.0.1:8878/monitor). Open it on the receiving
computer before starting transmission. The page shows the regional ground track,
ground station, latest received ECEF telemetry, slant range and model Doppler.
All logos and map assets are local; no Internet, Node.js, additional Python
packages or separate web process is needed. The server listens only on this computer.

For repeated demonstrations:

1. Leave `max_windows = 0` in `receiver/config.toml` so reception continues while the sender is idle.
2. Open the page and wait for **Ready for new transmission**.
3. Start the sender. Valid frames from the bundled five passes build five tracks; a pass with no valid received frames cannot appear.
4. After the sender finishes, keep the receiver running. The last tracks remain visible.
5. Reload the page (Cmd+R on Mac; Ctrl+R on Windows), wait for **Ready for new transmission**, then start the sender again.

Reloading clears only this browser presentation: map tracks, both curves, latest
values and visible counters. It does not restart the Nano, stop capture or delete
`events.jsonl`. The new page starts at its first successful telemetry snapshot and
shows packets received after that point. Reloading during transmission therefore
shows only the remaining packets. Each browser tab has its own starting point.
Without a reload, another transmission adds another set of tracks.

The bundled local reference is GOMX-1 / NORAD 39430. Received bytes must match the
reference exactly to assign a known pass. This is a ground replay demonstration;
model Doppler is not measured CFO. Valid/rejected counters describe received
packets in the current presentation, not the total number sent or a loss rate.

Optional overrides (existing configuration files work unchanged):

```text
python receiver/main.py --no-display
python receiver/main.py --display-port 8879
python receiver/main.py --reference-dataset dataset/data/orbit/YOUR_DATASET
```

These options can also be added as `display` (boolean, default true),
`display_port` (integer 1–65535, default 8878) and `reference_dataset` (path to the
matching frozen orbit directory) inside `[listen]` in `receiver/config.toml`.
Use `--no-display` for terminal capture alone. If the HTTP port is occupied, stop
the older receiver or choose another port before retrying. Ctrl+C closes reception
and its page service; closing or reloading the browser does not stop reception.

For a payload comparison, continue to use a separate capture per trial as described
below. A browser reload is not a new evidence file or a trial boundary in the log.

## Compare the original logs

Copy `events.jsonl` from the **completed sender trial** to the receiving computer as `tx-events.jsonl`. A USB drive or ordinary file transfer is sufficient. Select the completed transmission, since the cancelled preparation run has its own directory.

Replace `YOUR_RX_RUN` with the receiver directory printed for the same trial:

```text
python receiver/verify.py --tx tx-events.jsonl --rx output/receive/YOUR_RX_RUN/events.jsonl
```

The expected result when all three frames match is:

```json
{
  "requested": 3,
  "tx_done": 3,
  "matched": 3,
  "missing": 0,
  "extra_packets": 0,
  "rejected_packets": 0,
  "passed": true
}
```

The verifier requires a completed TX session and equal profiles. It compares exact payload bytes and multiplicities among packets with successful PHY CRC. Missing frames return exit code 1; invalid input returns 2. Extra and rejected packets are reported separately. A `TX_DONE` count alone does not establish successful reception.

Use a fresh receive session for each trial. The independent receive windows have no shared attempt identifier with the sender, and another transmitter replaying identical bytes cannot be distinguished by this comparison. These logs establish whether the expected payload bytes arrived within the captured session.

## When reception fails

| Symptom | Check |
|---|---|
| Serial port cannot open | Actual port, USB data cable and whether another process owns the Nano |
| HELLO identity mismatch | Board A selection, installed firmware and its matching local manifest; rebuild and upload the intended image |
| Register or SX1278 version check fails | Regulated supply, shared ground, level translation, NSS, RESET and SPI wiring |
| `TX_DONE` but only `RX_TIMEOUT` | Start reception first; verify equal profiles, antennas, power, frequency and the selected physical boards |
| Fewer matching frames | Keep both logs, inspect reported rejected and extra packets, correct the cause and start a new trial |

See [firmware troubleshooting](../firmware/README.md#troubleshooting) for bootloader and build problems. Keep both original evidence directories and the source revision alongside the comparison result.
