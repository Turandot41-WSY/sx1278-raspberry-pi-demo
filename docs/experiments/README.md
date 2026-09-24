# Antenna transmission and reception

[Repository overview](../../README.md) · [Setup guides](../setup/README.md) · [Troubleshooting](../troubleshooting/README.md)

Complete the hardware and platform setup first. Use Nano B (endpoint 2) at the sender and Nano A (endpoint 1) at the receiver. This convention applies to every combination:

| Sender | Receiver | Guides |
|---|---|---|
| Raspberry Pi 5 | Mac | [Pi setup](../setup/raspberry-pi/README.md) + [Mac setup](../setup/macos/README.md) |
| Raspberry Pi 5 | Windows | [Pi setup](../setup/raspberry-pi/README.md) + [Windows setup](../setup/windows/README.md) |
| Windows | Mac | [Windows setup](../setup/windows/README.md) + [Mac setup](../setup/macos/README.md) |
| Windows | Another Windows PC | [Windows setup](../setup/windows/README.md) separately on both computers |

Both machines use the same repository revision and the `sx1278-benchmark` environment. Use the antenna wiring and regulated supply in the hardware guide and a frequency/power authorized for your location.

## 1. Select the local role on each computer

Activate the environment in the repository root and inspect the actual port:

```text
conda activate sx1278-benchmark
python -m serial.tools.list_ports -v
git rev-parse HEAD
```

Run only the applicable role command on each machine. Replace example ports with those actually listed.

**Pi transmitter, Nano B:**

```bash
python tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --profile LoRa --count 3
```

**Windows transmitter, Nano B:**

```powershell
python tools/configure_antenna.py --device COM6 --board B --role tx --profile LoRa --count 3
```

**Mac receiver, Nano A:**

```bash
python tools/configure_antenna.py --device /dev/cu.usbserial-110 --board A --role rx --profile LoRa
```

**Windows receiver, Nano A:**

```powershell
python tools/configure_antenna.py --device COM4 --board A --role rx --profile LoRa
```

The two Windows computers may independently use the same COM number. Each command refers to the attached board on that computer. The helper saves the port, identity, role and profile; it does not build or flash. Follow the setup guide to build and upload before continuing.

## 2. Inspect the experiment configuration

On the sender, `config/main_transmit.toml` has `action = "antenna"`. Inspect these fields in `[antenna]`; retain the full file rather than replacing it with this excerpt:

```toml
data_source = "saved"                            # Validated local archive.
saved_dataset = "data/replay/gomx1-example/orbit" # Complete dataset directory.
start = 0                                       # First frame index.
count = "3"                                     # Later "20" or "all".
profile = "LoRa"                                # Same profile at both ends.
pa_dbm = 2                                      # Transmit power in dBm.
interval_ms = 1000                              # Pause after each frame, ms.
timeout_ms = 2000                               # Serial completion timeout, ms.
```

`port` is the sender's actual local port. `manifest` is `firmware/build/receive-endpoint/manifest.json` for B. A nonempty `saved_dataset` rebuilds the frames and frequency offsets; the `frames`, `sha256` and `orbit_dataset` fields provide the alternative explicit file input and can retain their defaults for this trial.

On the receiver, `config/main_receive.toml` has `action = "listen"`, A's actual `device`, `manifest = "firmware/build/single-endpoint/manifest.json"` and `profile = "LoRa"`. Keep `rx_window_ms = 5000`, `max_windows = 0` and `boot_settle_ms = 2500`. Zero maximum windows means listen until Ctrl+C.

Each manifest must describe the firmware actually uploaded to that board. A new build alone does not alter an installed Nano image.

## 3. Start reception first — Mac or Windows

```text
python main_receive.py
```

Wait for `RX_ARMED`. Empty windows print `RX_TIMEOUT` and arm the next window while the sender is idle. Leave this terminal running. The receiver stays at the nominal 437.5 MHz frequency and prints actual packet length, PHY CRC status and hexadecimal bytes. Its JSONL log also retains raw metrics, timestamps and serial messages.

## 4. Prepare and cancel once — Pi or Windows

On the sender:

```text
python main_transmit.py
```

Inspect the selected input, count, profile and power. At the confirmation prompt enter **n**. Expect `CANCELLED_BEFORE_SEND`: data preparation was performed before opening UART. Prepared files remain in the printed directory. This step still requires the compiled local manifest.

## 5. Send three frames — Pi or Windows

Keep the receiver running and repeat:

```text
python main_transmit.py
```

Enter **y** when the prepared input is correct. Expected sender progression:

```text
Frame 0: TX_DONE (1/3)
Frame 1: TX_DONE (2/3)
Frame 2: TX_DONE (3/3)
[Complete] 3/3 frames transmitted.
```

Look for three `RX_PACKET` lines on the receiver with `length=64` and `phy_crc_ok=1`. Stop reception with **Ctrl+C** after collecting the trial. `TX_DONE` establishes transmitter completion; successful reception requires matching packet bytes.

## 6. Compare the original logs

Keep the exact directories printed by this trial:

| Computer | Evidence |
|---|---|
| Sender | `output/antenna-doppler/<UTC>/events.jsonl`, input frames, frequency plan and manifests |
| Receiver | `output/receive/<UTC>/events.jsonl`, firmware manifest and radio table snapshots |

Copy the **completed sender trial's** `events.jsonl` to the receiver as `tx-events.jsonl`, using a USB drive or file transfer. Do not select the cancelled preparation trial. Replace `YOUR_RX_RUN` with the receiver directory printed for this trial:

```text
python tools/verify_reception.py --tx tx-events.jsonl --rx output/receive/YOUR_RX_RUN/events.jsonl
```

Expected result for a successful three-frame trial:

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

This is an expected result, not a hardware measurement. The tool requires a completed TX session and equal profiles, then compares payload bytes and multiplicities among CRC-valid RX packets. Missing frames return exit code 1; invalid input returns 2. Extra and rejected packets are reported separately.

Use a fresh receive session for each trial. Independent receive windows have no shared attempt identifier with the sender. Matching bytes cannot distinguish another transmitter replaying the same frozen payload. These logs support a functional demonstration rather than a synchronized packet error rate experiment.

## 7. Increase the count

Start a fresh receiver session before each trial. On either sender, a CLI override applies only to that run:

```text
python main_transmit.py --count 20
```

After verifying the 20-frame trial, start another receive session and send the full archive:

```text
python main_transmit.py --count all
```

At `start = 0`, the archive has 2,072 frames. The full run takes more than 34 minutes with a 1,000 ms pause because airtime and serial work add time. Keep both computers awake.

To save a new default, edit `[antenna].count` or use the role helper with `--count 20` or `--count all`. Changing count, dataset selection or pause does not require flashing. Changing firmware, board configuration or compiled tables requires rebuilding and uploading.

Other compiled profiles are `FSK`, `GFSK`, `MSK`, `GMSK` and `OOK`. Select the same profile and restart both hosts. Begin with LoRa; this guide does not claim physical results for all platform/profile combinations.

## 8. Repeat and preserve evidence

After reboot, activate the environment, return to the repository and check port names. Start reception before confirming transmission. Successful firmware uploads persist across power cycles.

The bundled archive works offline. See [Dataset preparation](../datasets/README.md) for fresh input. Only the sender needs the dataset to transmit; the receiver captures raw frames and uses the transferred TX log for comparison.

Keep the source revision, original logs and input/configuration snapshots. On failure, retain the incomplete evidence and consult [Troubleshooting](../troubleshooting/README.md). The sender does not silently retry uncertain transmissions.
