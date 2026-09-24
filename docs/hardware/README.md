# Hardware and wiring

[Repository overview](../../README.md) · [Setup guides](../setup/README.md)


Prepare:

- Raspberry Pi 5, suitable power supply, cooling, microSD card of at least 32 GB, card reader, monitor with micro-HDMI cable, and keyboard. A mouse is optional during setup.
- One Mac or Windows computer.
- Two classic Nano boards using ATmega328P, often with CH340 USB serial converters. This firmware does not target Nano Every or Nano 33.
- Two Ra-02 modules using SX1278, two antennas for the operating band, and two USB **data** cables.
- A stable regulated **3.3 V** radio supply for each assembly, common ground, and suitable logic level translation between the 5 V Nano outputs and the 3.3 V radio inputs.

Connect each assembly identically. The Pi does not connect directly to radio GPIO.

| Nano / supply | Ra-02 signal | Meaning |
|---|---|---|
| D10, through appropriate level translation | NSS | SPI chip select |
| D11 / MOSI, through level translation | MOSI | Nano sends register and packet bytes |
| D12 / MISO, with a compatible return logic level | MISO | Radio returns register and packet bytes |
| D13 / SCK, through level translation | SCK | SPI clock |
| D9, through level translation | RESET | Radio reset |
| D2, with a compatible return logic level | DIO0 | Packet completion interrupt |
| Regulated 3.3 V | VCC | Radio supply |
| Common ground | GND | Shared electrical reference |
| Antenna connector | Antenna | RF connection |

Power off before changing wiring. Do not connect Ra-02 VCC or its inputs directly to 5 V. Provide sufficient current for radio transmission; the classic Nano's 3.3 V pin is specified for only 50 mA and is unsuitable as the assumed radio supply. The radio supply and Nano must share ground. Fit both antennas before transmitting and start with some physical separation between assemblies.

Source: [Arduino Nano pinout, page 1, power and SPI pins](https://docs.arduino.cc/resources/pinouts/A000005-full-pinout.pdf); [Ai-Thinker Ra-02 product documentation, electrical parameters](https://docs.ai-thinker.com/en/Ra-02/index.html). The D10/D9/D2 assignment and 100 kHz SPI clock are project selections recorded in the board TOML files.


## Board identity and role

Attach a label to each assembly: **B / endpoint 2 / transmitter** and **A / endpoint 1 / receiver**. Both boards use the same production firmware, which supports both directions. This labeling makes the commands consistent across operating systems.

| Board | Board TOML | Local build output |
|---|---|---|
| B, endpoint 2 | `config/internal/receive_endpoint.toml` | `firmware/build/receive-endpoint/` |
| A, endpoint 1 | `config/internal/transmit_endpoint.toml` | `firmware/build/single-endpoint/` |

The sending computer can be a Pi 5 or Windows PC. The receiving computer can be a Mac or another Windows PC. Two Windows computers can both enumerate their own board as COM4; those names belong to separate computers and do not conflict.

Close send/receive and serial monitor processes before maintenance. Build and upload on the computer owning the attached board. Generated manifests and binaries stay under ignored `firmware/build/`; a clone does not restore them.
