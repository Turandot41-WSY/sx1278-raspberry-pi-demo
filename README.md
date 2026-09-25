# SX1278 antenna transmission and reception

Send saved telemetry through two Arduino Nano and Ra-02/SX1278 assemblies, capture the received bytes, and compare the original terminal logs. Nano **B / endpoint 2** sends; Nano **A / endpoint 1** receives.

| Folder | Purpose | Start here |
|---|---|---|
| [`dataset/`](dataset/README.md) | Acquire orbit inputs and keep the bundled replay data | [Dataset and frame format](dataset/README.md) |
| [`transmit/`](transmit/README.md) | Prepare frames and transmit through the local Nano | [Trial with three frames](transmit/README.md) |
| [`receiver/`](receiver/README.md) | Capture packets and verify them against the sender log | [Receive and compare](receiver/README.md) |
| [`firmware/`](firmware/README.md) | Nano firmware, radio tables, shared UART code and build tools | [Wiring and firmware](firmware/README.md) |
| [`setup/`](setup/README.md) | Install tools and configure each computer | [Raspberry Pi 5](setup/raspberry-pi/README.md) · [macOS](setup/macos/README.md) · [Windows](setup/windows/README.md) |
| [`tests/`](tests/README.md) | Run individual checks after connecting the hardware | [Hardware checks](tests/README.md) |

## Supported computer pairs

| Transmitter with Nano B | Receiver with Nano A | Setup guides |
|---|---|---|
| Raspberry Pi 5 | Mac | [Pi](setup/raspberry-pi/README.md) + [macOS](setup/macos/README.md) |
| Raspberry Pi 5 | Windows | [Pi](setup/raspberry-pi/README.md) + [Windows](setup/windows/README.md) |
| Windows | Mac | [Windows](setup/windows/README.md) + [macOS](setup/macos/README.md) |
| Windows | Another Windows computer | [Windows](setup/windows/README.md) on both computers |

Each computer controls its own Nano through USB UART at 115200 baud. Each Nano controls its SX1278 through SPI. The two radios exchange frames through antennas; the computers need no network connection to each other during a trial with saved data. Serial port names belong to the local computer, so two Windows computers may each use `COM4`.

The first trial uses LoRa at nominal 437.5 MHz, 2 dBm and a 1,000 ms pause after each completed frame. Use frequency and power authorized for your location. These guides define the supported setup; success on a particular computer pair requires its own upload and radio logs.

## Start a trial

1. Assemble both boards using [the wiring instructions](firmware/README.md#hardware-and-wiring).
2. Follow the setup guide for each computer. Both use Python 3.12 in `sx1278-benchmark`, Arduino CLI 1.5.1 and Arduino AVR Boards 1.8.8.
3. Follow [the hardware checks](tests/README.md) in order. They cover port discovery through the first transmission and comparison.
4. For ordinary runs, start [the receiver](receiver/README.md), then follow [the transmitter guide](transmit/README.md).
5. [Compare the completed TX and RX logs](receiver/README.md#compare-the-original-logs) before increasing the count.

Run commands from the repository root with the environment active:

```text
conda activate sx1278-benchmark
```

On the receiving computer:

```text
python receiver/main.py
```

On the transmitting computer:

```text
python transmit/main.py
```

The bundled archive supports offline trials. Optional fresh acquisition uses `python dataset/main.py`; see [dataset preparation](dataset/README.md).

## Files and settings

Each module owns its `config.toml`. The top-level `action` selects the operation; explicit command-line flags apply to the current run. Paths in TOML are relative to the repository root unless absolute. Windows TOML paths use forward slashes, such as `C:/Users/me/data`.

```text
sx1278-raspberry-pi-demo/
├── README.md
├── environment.yml             Conda environment with Python 3.12
├── requirements.txt            authoritative Python dependency snapshot
├── dataset/                    main.py, config.toml, data and preparation code
├── transmit/                   main.py, config.toml and sending code
├── receiver/                   main.py, config.toml and verify.py
├── firmware/                   endpoint, config, host, conformance and tools
├── setup/                      index and three platform setup READMEs
└── tests/                      individual hardware checks and their README
```

`firmware/build/`, `dataset/data/orbit/` and `output/` are generated locally and excluded from Git. Build and upload on the computer attached to each Nano, then keep the generated manifest with that installed image. Save original trial directories and the source revision from `git rev-parse HEAD`.

When updating an existing clone, stop radio processes and preserve local settings and trial output before pulling. Operator settings now live in `dataset/config.toml`, `transmit/config.toml` and `receiver/config.toml`. Reapply the actual device and board with `firmware/tools/configure_antenna.py`, and follow the module README commands.
