# macOS setup from zero

[Repository overview](../../../README.md) · [All setup guides](../README.md) · [Hardware](../../hardware/README.md)

Prepare a Mac as the receiver with Nano A (endpoint 1). Its sender can be Raspberry Pi 5 or Windows. Complete the hardware wiring guide before powering the radio.

## Install Git, Arduino CLI and Miniforge

In Terminal, run `git --version`. If macOS requests Command Line Tools, install them and reopen Terminal. Alternatively start that installation with `xcode-select --install`.

Install the matching Arduino CLI archive:

```bash
mkdir -p "$HOME/.local/bin"
cd "$HOME/Downloads"
case "$(uname -m)" in
  arm64) CLI_ARCH=ARM64 ;;
  x86_64) CLI_ARCH=64bit ;;
  *) echo "Unsupported Mac architecture"; exit 1 ;;
esac
curl -fL -o arduino-cli.tar.gz "https://github.com/arduino/arduino-cli/releases/download/v1.5.1/arduino-cli_1.5.1_macOS_${CLI_ARCH}.tar.gz"
tar -xzf arduino-cli.tar.gz arduino-cli
install -m 755 arduino-cli "$HOME/.local/bin/arduino-cli"
printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.zshrc"
export PATH="$HOME/.local/bin:$PATH"
arduino-cli version
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli core list
```

If Conda is already available, retain it. Otherwise install Miniforge:

```bash
cd "$HOME/Downloads"
curl -fL -o Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-$(uname -m).sh"
bash Miniforge3.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init zsh
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda --version
```

## Clone and create the Python environment

Run from your home directory. This public repository requires no GitHub login.

```bash
cd "$HOME"
git clone https://github.com/Turandot41-WSY/sx1278-raspberry-pi-demo.git
cd sx1278-raspberry-pi-demo
```

Run the following commands in the repository root:

```text
conda env create -f environment.yml
conda activate sx1278-benchmark
python -m pip install -r requirements.txt
python -m pip check
python --version
python -m pytest -q
python main_transmit.py --help
python main_receive.py --help
```

If `sx1278-benchmark` already exists, skip creation, activate it and verify Python 3.12 before installing `requirements.txt`. Reuse this single environment for the demo. `pip check` must report no broken requirements, and every test must pass. The tests use simulated UART endpoints and do not transmit.

Every later command assumes the environment is active and the terminal is in the repository root. Run `git rev-parse HEAD` on both computers to record the same source revision.

## Connect, configure and flash Nano A

Connect A by USB and inspect the actual serial port:

```bash
python -m serial.tools.list_ports -v
```

Replace the example `/dev/cu.usbserial-110` below with the reported port:

```bash
python tools/configure_antenna.py --device /dev/cu.usbserial-110 --board A --role rx --profile LoRa
python firmware/tools/board_control.py --action handshake
python firmware/tools/board_control.py --action build
python firmware/tools/board_control.py --action upload
```

The expected manifest is `firmware/build/single-endpoint/manifest.json`, with `endpoint_id: 1` and `compiled: true`. Upload must complete with flash verification.

## If the bootloader handshake fails

Check the data cable, selected port and power. Close any program owning the port. Then try:

```text
python firmware/tools/board_control.py --action handshake --baud 115200
```

The default is `arduino:avr:nano:cpu=atmega328old` (57600 upload baud). If only 115200 succeeds, change `fqbn` in the selected board TOML to `arduino:avr:nano:cpu=atmega328`, then build and upload again. The override does not save a new FQBN. Application UART remains 115200 regardless of the bootloader.

Board A uses `config/internal/transmit_endpoint.toml` and `firmware/build/single-endpoint/manifest.json`. Board B uses `config/internal/receive_endpoint.toml` and `firmware/build/receive-endpoint/manifest.json`. The filenames identify physical boards, not permanent TX/RX roles.

If tools are not found, check `arduino-cli version` and `arduino-cli core list`. Custom Arduino paths belong in `config/internal/board_control.toml`. A slow build can use `command_timeout_seconds = 300`. A changed board file, including comments, requires a new build and upload with the matching manifest. Never edit identity hashes to bypass a mismatch.

## Setup is complete when

- Git, Arduino CLI and Conda are available in the terminal.
- AVR Boards 1.8.8 and Python 3.12 are selected; all software tests pass.
- The actual `/dev/cu.*` port is selected; Nano A builds and uploads successfully.

Continue with the [antenna experiment](../../experiments/README.md). Keep the receiver running while the sender operates. The receiver prints packets and writes `events.jsonl`; all verification is performed from those logs.
