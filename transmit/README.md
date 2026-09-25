# Transmit through Nano B

[Repository overview](../README.md) · [Receiver](../receiver/README.md) · [Hardware checks](../tests/README.md)

`transmit/main.py` prepares frames and sends them through the local Nano B, endpoint 2. Run it on Raspberry Pi 5 or Windows after completing the [Pi](../setup/raspberry-pi/README.md) or [Windows](../setup/windows/README.md) setup. A Mac or another Windows computer receives through Nano A, endpoint 1.

Both computers should use the same Git revision. Activate `sx1278-benchmark` and run every command below from the repository root. Complete [wiring and firmware setup](../firmware/README.md). The [hardware checks](../tests/README.md) provide separate commands for the first trial. Select a frequency and power authorized for your location.

## Select the sender

Find the actual port with `python -m serial.tools.list_ports -v`. Run the applicable command with that port:

```bash
python firmware/tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --profile LoRa --count 3
```

On Windows, for example:

```powershell
python firmware/tools/configure_antenna.py --device COM6 --board B --role tx --profile LoRa --count 3
```

The helper saves the sender device, B's manifest, action and profile in `transmit/config.toml`. It also selects B in `firmware/config/internal/board_control.toml`. Build and upload using the platform guide before the first transmission.

## Review the configuration

[`config.toml`](config.toml) belongs to this entry point. The top-level `action = "antenna"` selects `[antenna]`. The hardware checks select a fixed frequency. For the orbit trial in this guide, set the fields below in the existing file. Keep the other fields and their explanations:

```toml
data_source = "saved"
saved_dataset = "dataset/data/replay/gomx1-example/orbit"
start = 0
count = "3"
profile = "LoRa"
pa_dbm = 2
interval_ms = 1000
timeout_ms = 2000
```

| Fields | Responsibility |
|---|---|
| `data_source`, `saved_dataset` | Select a validated saved orbit directory or acquire fresh inputs using `dataset/config.toml` |
| `frames`, `sha256`, `orbit_dataset` | Alternative explicit frame file, its full SHA-256 and optional orbit directory; used when `saved_dataset` is empty |
| `port`, `manifest` | Local UART device and manifest matching the firmware uploaded to B |
| `start`, `count` | First frame index, starting at 0, and a positive count string or `"all"` |
| `profile`, `pa_dbm`, `reg_frf_word` | Modulation, transmit power in dBm and fixed frequency register used when no orbit plan is selected |
| `interval_ms`, `timeout_ms` | Pause after a completed frame and command/completion timeout, both in milliseconds |
| `output` | Root for a new UTC trial directory, normally `output/antenna-doppler` |

The default manifest for B is `firmware/build/receive-endpoint/manifest.json`. A nonempty `saved_dataset` rebuilds frames and frequency offsets. The sender applies those offsets; the receiver remains at nominal 437.5 MHz. The example archive contains five passes and 2,072 frames.

The alternative `saved` action reads `[saved]` and sends an explicit binary frame file at a fixed frequency:

```text
python transmit/main.py saved
```

Review `[saved]` separately, including its `port`, frame hash and manifest. It does not apply the orbit frequency plan. The role helper configures `[antenna]` for the normal trial.

## Prepare, cancel, then send three frames

On the receiving computer, follow [the receiver guide](../receiver/README.md) and wait for `RX_ARMED`. On the sender, run:

```text
python transmit/main.py
```

Inspect the prepared input, count, profile and power. Enter **n** once. Expect `CANCELLED_BEFORE_SEND`. The prepared data remain in the printed directory; cancellation occurs before UART is opened. Preparation still requires the compiled local manifest.

Run the same command again. Confirm with **y** when the settings are correct and the receiver is running. For a completed trial with three frames, the sender should report:

```text
Frame 0: TX_DONE (1/3)
Frame 1: TX_DONE (2/3)
Frame 2: TX_DONE (3/3)
[Complete] 3/3 frames transmitted.
```

These lines describe the expected output. `TX_DONE` records completion reported by the transmitting radio. Check `RX_PACKET` on the receiver, then [compare the exact bytes](../receiver/README.md#compare-the-original-logs).

`python -m transmit.main` uses the same settings. Explicit command-line flags override values for that run; save edits in `config.toml` when the default should change.

## Repeat with more frames

Start a fresh receive session for each trial. After matching all three frames, run:

```text
python transmit/main.py --count 20
```

After verifying that trial, start another receive session and send the full archive:

```text
python transmit/main.py --count all
```

With `start = 0`, this sends 2,072 frames. At a 1,000 ms pause, the full run takes more than 34 minutes once airtime and serial work are included. Keep both computers awake.

Changing count, dataset or pause does not require flashing. Changes to firmware, board configuration or compiled radio tables require rebuilding and uploading. The compiled profiles are `LoRa`, `FSK`, `GFSK`, `MSK`, `GMSK` and `OOK`; select the same profile on both computers and restart both processes.

Keep the completed trial's `output/antenna-doppler/<UTC>/` directory, including `events.jsonl`, prepared input, frequency plan and manifest snapshots. Preserve incomplete runs too. If a transmission stops, correct the cause and start a new trial; uncertain transmissions are not silently retried.
