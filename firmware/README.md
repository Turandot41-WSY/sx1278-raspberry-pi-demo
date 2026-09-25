# Nano firmware and hardware setup

[Repository overview](../README.md) · [Pi setup](../setup/raspberry-pi/README.md) · [macOS setup](../setup/macos/README.md) · [Windows setup](../setup/windows/README.md)

Both Nano boards run [`endpoint/endpoint.ino`](endpoint/endpoint.ino), the production endpoint with the binary UART protocol and SX1278 driver. The documented trial uses **B / endpoint 2** to send and **A / endpoint 1** to receive. Each computer connects to its Nano through USB.

## Hardware and wiring

Prepare two classic Nano boards with ATmega328P, two Ra-02/SX1278 modules, antennas for the operating band, two USB data cables, and a regulated 3.3 V radio supply for each assembly. Use suitable level translation between the Nano's 5 V outputs and the radio's 3.3 V inputs. The firmware targets the classic Nano; Nano Every and Nano 33 use different hardware.

For a Pi sender, also prepare a Raspberry Pi 5, suitable power supply and cooling, a microSD card of at least 32 GB, card reader, monitor with micro-HDMI cable, and keyboard. The Pi controls its Nano through USB.

Connect each Nano/radio assembly identically:

| Nano / supply | Ra-02 signal | Purpose |
|---|---|---|
| D10 through level translation | NSS | SPI chip select |
| D11 / MOSI through level translation | MOSI | Nano sends register and packet bytes |
| D12 / MISO with a compatible return logic level | MISO | Radio returns register and packet bytes |
| D13 / SCK through level translation | SCK | SPI clock |
| D9 through level translation | RESET | Radio reset |
| D2 with a compatible return logic level | DIO0 | Packet completion interrupt |
| Regulated 3.3 V | VCC | Radio supply |
| Common ground | GND | Shared electrical reference |
| Antenna connector | Antenna | RF connection |

Power off before changing wiring. Do not connect Ra-02 VCC or its inputs directly to 5 V. Size the external radio supply for transmission current, share ground with the Nano, and fit both antennas before transmission. Ai-Thinker lists 3.3 V operation and a maximum operating current of 105 mA in [Ra-02 Technical Highlights](https://docs.ai-thinker.com/en/Ra-02/index.html). The classic Nano's 3.3 V pin is limited to 50 mA, so this setup uses an external regulated radio supply. That limit and the power/SPI pin assignments appear on pages 1–2 of the [Arduino Nano pinout](https://docs.arduino.cc/resources/pinouts/A000005-full-pinout.pdf).

D10, D9 and D2, together with a 100 kHz SPI clock, are project selections recorded in the board TOML files. Label the assembled boards A and B before connecting USB.

## Board configuration and build outputs

| Board and trial role | Board configuration | Generated manifest |
|---|---|---|
| B / endpoint 2 / TX | `firmware/config/internal/receive_endpoint.toml` | `firmware/build/receive-endpoint/manifest.json` |
| A / endpoint 1 / RX | `firmware/config/internal/transmit_endpoint.toml` | `firmware/build/single-endpoint/manifest.json` |

The board filenames retain their original identity mapping. Both boards support transmit and receive commands. The platform setup guide selects the appropriate board, actual serial port and runtime role through `firmware/tools/configure_antenna.py`.

The firmware folder owns these resources:

| Path | Responsibility |
|---|---|
| [`endpoint/`](endpoint/) | Nano endpoint, UART protocol implementation and radio driver |
| [`config/profiles.csv`](config/profiles.csv) | Compiled modulation profiles |
| [`config/pa_settings.csv`](config/pa_settings.csv) | Available transmit power settings |
| [`config/profile_registers.csv`](config/profile_registers.csv) | Register values for each profile |
| [`config/internal/`](config/internal/) | Board pins, build identity, runtime protocol settings and build tools' configuration |
| [`host/`](host/) | Shared Python UART, configuration and radio support |
| [`conformance/`](conformance/) | Shared protocol resources |
| [`tools/`](tools/) | Role configuration, firmware generation, build, size and upload tools |

`config/internal/board_control.toml` selects the device, board configuration, build directory and optional tool paths. Operator settings for acquisition, transmit and receive belong to their respective module's `config.toml`. Both radios need compatible compiled tables and the same selected profile.

## Build and upload the selected board

Close transmit, receive and serial monitor processes before maintenance. Run from the repository root in `sx1278-benchmark`, after completing the platform setup and selecting the local role:

```text
python firmware/tools/board_control.py --action ports
python firmware/tools/board_control.py --action handshake
python firmware/tools/board_control.py --action build
python firmware/tools/board_control.py --action upload
```

The build tool stages source under `firmware/build/`, generates configuration and identity headers, compiles with Arduino CLI and writes the manifest. Check `compiled: true` and the intended `endpoint_id`. Upload changes the attached Nano and should finish with flash verification.

The application UART uses 115200 baud, 8 data bits, no parity and one stop bit. Bootloader handshake and upload baud are selected separately by the board FQBN. Generated files are excluded from Git, so each host builds locally. Keep the uploaded image and its generated manifest together.

Changing firmware source, a board file, or compiled tables requires a new build and upload. Board file comments also affect the identity hash. A newly generated manifest cannot describe an older installed image. Runtime HELLO checks reject mismatched identities.

## Troubleshooting

| Symptom | Action |
|---|---|
| `arduino-cli` missing | Extract the official archive and verify the executable. On Windows, follow [manual tool discovery and TOML configuration](../setup/windows/README.md#find-tools-and-set-their-paths-manually) |
| AVR build tools missing | Check that `core list` includes `arduino:avr` 1.8.8; the [Windows guide](../setup/windows/README.md#find-tools-and-set-their-paths-manually) shows how to locate `avrdude.exe`, `avrdude.conf` and `avr-size.exe` and save their paths |
| Index download stalls | Check HTTPS access; run `arduino-cli core update-index --verbose` to inspect progress |
| Build timeout | Set `command_timeout_seconds = 300` in `firmware/config/internal/board_control.toml`, then rebuild |
| Serial port missing | Check USB enumeration and a data cable; enumerate with `python -m serial.tools.list_ports -v` |
| Port busy | Close other serial sessions before retrying |
| Missing manifest or `compiled: false` | Select the correct board, build and upload on the attached computer |
| HELLO identity mismatch | Verify A/B selection and source revision; rebuild and upload with the matching manifest |
| Radio version/register failure | Check the regulated 3.3 V supply, shared ground, level translation, and SPI/RESET/NSS wiring |

For a bootloader handshake failure, check power, cable and port, then try:

```text
python firmware/tools/board_control.py --action handshake --baud 115200
```

The default FQBN is `arduino:avr:nano:cpu=atmega328old`, which uses 57600 upload baud. If only 115200 succeeds, change `fqbn` in the selected board TOML to `arduino:avr:nano:cpu=atmega328`, then rebuild and upload. The command-line baud override does not save that FQBN. The application UART remains 115200.

After uploading, use the [hardware checks](../tests/README.md) for a trial in separate steps, or start [reception](../receiver/README.md) before [transmission](../transmit/README.md).
