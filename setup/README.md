# Platform setup

[Repository overview](../README.md) · [Hardware and wiring](../firmware/README.md#hardware-and-wiring)

Follow the guide for each computer. Each guide covers tool installation, clone, Python environment, serial port selection, bootloader handshake, build and upload.

| Computer | Role in the demo | Setup guide |
|---|---|---|
| Raspberry Pi 5 with Raspberry Pi OS 64-bit | Send through Nano B, endpoint 2 | [Raspberry Pi 5](raspberry-pi/README.md) |
| macOS on Apple Silicon or Intel | Receive through Nano A, endpoint 1 | [macOS](macos/README.md) |
| Windows 10/11 x86-64 | Send through B or receive through A | [Windows](windows/README.md) |

Supported pairs are Pi → Mac, Pi → Windows, Windows → Mac, and Windows → another Windows computer. For two Windows computers, select each computer's actual COM port independently.

All hosts use the same source revision, Python 3.12 in `sx1278-benchmark`, [Arduino CLI 1.5.1](https://github.com/arduino/arduino-cli/releases/tag/v1.5.1), and [Arduino AVR Boards 1.8.8](https://github.com/arduino/ArduinoCore-avr/releases/tag/1.8.8). `environment.yml` creates the Conda environment; `requirements.txt` is the authoritative Python dependency snapshot. Install it after activating the environment.

The guides use [Miniforge](https://github.com/conda-forge/miniforge) to provide Conda. Its base Python version is separate from the demo's Python 3.12 environment. An existing working Conda installation can create the same environment.

For a first trial, the [hardware checks](../tests/README.md) expose each step separately. For ordinary operation, start [reception](../receiver/README.md) before [transmission](../transmit/README.md), then compare the original logs. Keep actual logs for each computer pair and radio profile you test.
