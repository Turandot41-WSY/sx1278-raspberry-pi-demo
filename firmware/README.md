# Nano endpoint firmware

Both Nano boards use `endpoint/endpoint.ino`, including the same binary serial protocol and SX1278 driver. Nano B (endpoint 2) transmits; Nano A (endpoint 1) receives in the documented experiment. These identities apply to Pi and Windows senders and Mac/Windows receivers.

Use the platform setup guide to find the USB port, select the board, check its bootloader, compile and upload:

- [Raspberry Pi 5](../docs/setup/raspberry-pi/README.md)
- [macOS](../docs/setup/macos/README.md)
- [Windows](../docs/setup/windows/README.md)

Run `python firmware/tools/board_control.py --action build` to compile the selected board and `--action upload` to upload and verify it. The tool resolves the installed Arduino CLI and AVR tools for the host platform. The build stages production source into `firmware/build/`, generates identity/configuration headers and writes a manifest. It does not modify the firmware already installed until upload is requested.

The UART application protocol is 115200 baud, 8 data bits, no parity, one stop bit. Bootloader handshake/upload baud is selected separately by the board FQBN. Keep the flashed image and its generated manifest together. Hardware wiring and power are documented in the [hardware guide](../docs/hardware/README.md).
