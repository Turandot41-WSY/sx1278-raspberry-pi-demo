# Nano endpoint firmware

Build and upload locally using the commands in the [root README](../README.md). Board B (ID 2) is the Pi transmitter; board A (ID 1) is the Mac/Windows receiver. Both use `endpoint/endpoint.ino` and the same UART protocol and SX1278 driver. The host selects TX or RX after verifying the uploaded manifest.

Generated headers, profile tables and protocol checks remain part of the build. The `firmware/build/` directory is local and excluded from Git. A successful compilation does not establish upload or radio success.
