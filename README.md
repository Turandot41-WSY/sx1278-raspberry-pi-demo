# SX1278 antenna transmission and reception

A reproducible radio experiment using Arduino Nano and Ra-02/SX1278 assemblies. Send saved telemetry from **Raspberry Pi 5 or Windows**, receive on **macOS or another Windows computer**, and verify the received bytes from terminal logs.

| Folder | Content | Documentation |
|---|---|---|
| [`docs/setup/`](docs/setup/) | Installation, environment, serial communication and flashing for each operating system | [Pi](docs/setup/raspberry-pi/README.md) · [macOS](docs/setup/macos/README.md) · [Windows](docs/setup/windows/README.md) |
| [`docs/hardware/`](docs/hardware/) | Required hardware, power, Nano–Ra-02 wiring and board identity | [Hardware guide](docs/hardware/README.md) |
| [`docs/experiments/`](docs/experiments/) | Three-frame trial, log comparison, 20 frames and full archive | [Experiment guide](docs/experiments/README.md) |
| [`host/`](host/) | Frame preparation, UART protocol, transmission and reception | [Code architecture](docs/architecture/README.md) |
| [`firmware/`](firmware/) | Nano firmware, SX1278 driver and build/upload tools | [Firmware README](firmware/README.md) |
| [`config/`](config/) | English operator settings and compiled radio tables | [Configuration README](config/README.md) |
| [`data/replay/`](data/replay/) | Frozen public inputs and 2,072 example frames | [Dataset guide](docs/datasets/README.md) |
| [`docs/architecture/`](docs/architecture/) | Interactive architecture HTML and source map | [Architecture guide](docs/architecture/README.md) |
| [`tests/`](tests/) | Software checks using simulated endpoints | [Verification record](docs/validation.md) |

## Architecture

Each computer controls its own Nano through USB. The Nano operates an SX1278 radio through SPI, and the two assemblies exchange frames through antennas.

```text
Sender computer                         Receiver computer
Raspberry Pi 5 / Windows                 macOS / Windows
main_transmit.py                        main_receive.py
       | USB UART, 115200                       ^ USB UART, 115200
       v                                        |
Nano B, endpoint 2                       Nano A, endpoint 1
       | SPI                                    ^ SPI
       v                                        |
Ra-02 / SX1278 + antenna  -- RF frames --> antenna + Ra-02 / SX1278
       |                                        |
TX events.jsonl                         RX events.jsonl
       +------------ verify_reception.py -------+
```

**Transmitter.** The host validates the archived orbit data, prepares frames and the frequency plan, asks for confirmation, verifies Nano identity, then requests each transmission. `TX_DONE` records completion reported by the transmitting radio.

**Radio link.** The first trial uses LoRa at nominal 437.5 MHz, 2 dBm and a 1,000 ms pause after each completed frame. The sender applies the selected orbit frequency offsets; the receiver remains at nominal frequency. Use frequency and power authorized for your location. Radio operation uses local USB connections and requires no network between the computers.

**Receiver.** The host configures Nano A, repeatedly opens receive windows and preserves `RX_PACKET` bytes, CRC status and raw radio metrics. `tools/verify_reception.py` compares the completed TX requests with received bytes. Operation is through the terminal; the architecture HTML is offline code documentation.

A and B identify the physical boards. Both use the same firmware and support TX and RX commands. This guide consistently uses **B to send** and **A to receive** across all platforms.

## Supported experiment combinations

| Transmitter | Receiver | Setup to follow |
|---|---|---|
| Raspberry Pi 5 | Mac | [Pi TX](docs/setup/raspberry-pi/README.md) + [Mac RX](docs/setup/macos/README.md) |
| Raspberry Pi 5 | Windows | [Pi TX](docs/setup/raspberry-pi/README.md) + [Windows RX](docs/setup/windows/README.md) |
| Windows | Mac | [Windows TX](docs/setup/windows/README.md) + [Mac RX](docs/setup/macos/README.md) |
| Windows | Another Windows PC | [Windows setup on both computers](docs/setup/windows/README.md) |

For Windows → Windows, configure the actual COM port separately on each computer. The setup guides specify Python 3.12, Arduino CLI 1.5.1 and AVR Boards 1.8.8. Platform instructions and software checks do not establish physical success for every pair; save your actual trial logs.

## Telemetry format

The RF payload is a **64-byte binary frame**, using the layout implemented in [`ccsds_tm.py`](host/dataset/ccsds_tm.py) and [`orbit_record.py`](host/dataset/orbit_record.py). Multi-byte integers use big-endian order. Hexadecimal text in the receive log represents those bytes; JSONL is the host evidence format.

| Frame byte offset | Length | Content |
|---|---|---|
| 0–5 | 6 bytes | TM primary header and frame counters |
| 6–11 | 6 bytes | Space Packet primary header and packet sequence count |
| 12–61 | 50 bytes | Project mission record below |
| 62–63 | 2 bytes | Frame Error Control Field (FECF) |

Offsets below are relative to the start of the mission record:

| Offset | Field | Type | Unit / meaning |
|---|---|---|---|
| 0 | `trace_time_ms` | uint32 | Milliseconds from the first sample of the selected pass; not Unix time |
| 4, 8, 12 | `position_x_m`, `position_y_m`, `position_z_m` | 3 × int32 | Terrestrial position components in metres |
| 16, 20, 24 | `velocity_x_mmps`, `velocity_y_mmps`, `velocity_z_mmps` | 3 × int32 | Terrestrial velocity components in millimetres per second |
| 28 | `slant_range_m` | uint32 | Satellite-to-station slant range in metres |
| 32 | `range_rate_mmps` | int32 | Range rate in millimetres per second |
| 36 | `doppler_millihz` | int32 | Model Doppler in millihertz |
| 40 | `mission_state` | uint8 | Project mission state value; the orbit generator sets 0 |
| 41 | `workload` | uint8 | Project workload value; the orbit generator sets 0 |
| 42 | `trace_sample_id` | uint16 | Sample identifier within the frozen dataset |
| 44–49 | Diagnostic pattern | 6 bytes | Sample ID, its XOR with `0xA5A5`, and its byte-swapped value |

The bundled dataset contains five propagated GOMX-1 passes. Its values are calculated orbit telemetry, not an actual satellite downlink. [Source data and attribution](data/replay/gomx1-example/README.md) remain with the archive.

## Repository structure

```text
sx1278-raspberry-pi-demo/
├── README.md                    overview, architecture, telemetry and navigation
├── main_transmit.py             antenna/saved transmission entry
├── main_receive.py              local radio reception entry
├── main_dataset.py              optional orbit input acquisition
├── environment.yml              single Conda environment, Python 3.12
├── requirements.txt             authoritative Python dependency snapshot
├── host/                        Python data, configuration and radio modules
├── firmware/                    Nano source and maintenance tools
├── config/                      one operator TOML per main entry
├── data/replay/gomx1-example/    frozen public inputs and example frames
├── tools/                       role configuration and exact log comparison
├── tests/                       software tests and simulated endpoints
└── docs/
    ├── setup/
    │   ├── raspberry-pi/README.md
    │   ├── macos/README.md
    │   └── windows/README.md
    ├── hardware/README.md       wiring, power and board identities
    ├── experiments/README.md    run, compare and repeat
    ├── datasets/README.md       optional fresh input acquisition
    ├── architecture/            HTML, JSON and code reading guide
    ├── troubleshooting/README.md
    └── validation.md            tested scope and physical limitations
```

`firmware/build/`, `data/orbit/` and `output/` are created locally and excluded from Git. Build and upload locally so the manifest corresponds to the firmware installed on that board.

## Getting started

1. Assemble both boards using the [hardware guide](docs/hardware/README.md).
2. Follow the sender's [Pi](docs/setup/raspberry-pi/README.md) or [Windows](docs/setup/windows/README.md) setup from zero.
3. Follow the receiver's [Mac](docs/setup/macos/README.md) or [Windows](docs/setup/windows/README.md) setup from zero.
4. Run the [three-frame antenna experiment](docs/experiments/README.md). Start reception first, prepare/cancel once, then confirm the sender.
5. Compare the original logs before increasing the count to 20 or `all`.

After setup, the basic commands are:

```text
# Receiver terminal on Mac or Windows:
python main_receive.py

# Sender terminal on Pi or Windows:
python main_transmit.py
```

The [experiment guide](docs/experiments/README.md) provides the exact role commands, configuration fields, expected output, transfer of evidence and verification command for every combination.

## End-to-end checks

In order:

1. Both hosts use the same Git revision and pass `python -m pip check` and `python -m pytest -q`.
2. Both Nano builds and uploads finish with flash verification; the selected manifests match B/2 and A/1.
3. The receiver reports `RX_ARMED`; empty `RX_TIMEOUT` windows are expected before transmission.
4. The sender reports `TX_DONE` for all three requested frames.
5. The receiver records packets of length 64 with successful PHY CRC.
6. The log comparison reports `requested = tx_done = matched = 3`, `missing = 0` and `passed = true`.
7. Both original evidence directories and the code revision are saved with the trial.

A matching count from the terminal alone is insufficient: compare the exact bytes. See [Troubleshooting](docs/troubleshooting/README.md) when a check fails and [the verification record](docs/validation.md) for what has actually been tested.

## Updating an existing clone

Stop any old receive or display process, preserve trial data and commit or back up local configuration changes, then pull the current `main`. The receive entry now accepts only `listen`; remove old `[display]` settings and `display` fields when migrating a customized TOML. Reapply your local role/port with the helper. Keep each firmware manifest with its installed build; use the setup guide when rebuilding is required.

Open [the architecture HTML](docs/architecture/architecture.html) locally after cloning. GitHub shows HTML source; the [architecture guide](docs/architecture/README.md) explains viewing and source navigation. This repository provides the independent antenna experiment and its code documentation.
