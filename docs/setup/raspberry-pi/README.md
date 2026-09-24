# Raspberry Pi 5 setup from zero

[Repository overview](../../../README.md) · [All setup guides](../README.md) · [Hardware](../../hardware/README.md)

Prepare a Raspberry Pi 5 as the transmitter with Nano B (endpoint 2). Complete the hardware wiring guide before powering the radio. A separate Mac or Windows computer receives through Nano A.

## Install the operating system using the Mac


1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Insert the microSD card. Identify the correct card by its capacity and name; writing erases its existing contents.
3. Select **Raspberry Pi 5** and **Raspberry Pi OS (64-bit)** with desktop. This procedure targets Debian 13 / Trixie. If you have already downloaded the image, choose **Use custom** and select its `.img.xz` file.
4. Select the microSD card as storage. Set a hostname, such as `radio-pi`, your time zone and keyboard layout, and a username and password you can retrieve later.
5. Configure ordinary Wi-Fi if available. For eduroam, use the institution installer after booting, as described below. Enable SSH only if you intend to use it.
6. Write and verify the card. Eject it safely. Insert it into the Pi while power is disconnected, attach monitor and keyboard, and power on.
7. Complete the desktop prompts and open a terminal with **Ctrl + Alt + T**.

Official procedure: [Raspberry Pi getting started, Install an OS onto boot media](https://www.raspberrypi.com/documentation/computers/getting-started.html).

Run on the Pi:

```bash
uname -m
cat /etc/os-release
```

Proceed when the architecture is `aarch64` and the desktop works. The Pi login password is separate from GitHub and eduroam credentials.

## Connect the Pi to the network


Use Ethernet, a home Wi-Fi network, or a phone hotspot for initial downloads. Select ordinary Wi-Fi through the desktop network menu.

### eduroam

Open [eduroam CAT](https://cat.eduroam.org/), select the institution that issued your account, and download its **Linux** installer. If necessary, download it on the Mac and transfer it with a USB drive. For a Python installer, run the following using the actual downloaded filename:

```bash
python3 "$HOME/Downloads/eduroam-linux-YOUR-INSTITUTION.py"
```

Follow the institution prompts as your normal user, using its required account format. Retain the supplied certificate and server validation settings. Select eduroam from the network menu after installation. Institution instructions take precedence for installer dependencies. [Official CAT explanation](https://eduroam.org/configuration-assistant-tool-cat/).

Check the active connection and internet access:

```bash
nmcli -t -f NAME,TYPE connection show --active
hostname -I
```

Open GitHub in the browser. Once `curl` is installed, also run:

```bash
curl -I --max-time 20 https://github.com
```

Proceed when the connection is active and HTTPS works. The radio demo can run offline after its tools and data are installed.

### Bluetooth mouse with only a keyboard

Pi 5 supports Bluetooth. Put the mouse into pairing mode, then run:

```bash
sudo systemctl start bluetooth
sudo rfkill unblock bluetooth
bluetoothctl
```

Enter each line at the Bluetooth prompt:

```text
power on
agent on
default-agent
scan on
```

When you see your mouse address, stop the scrolling with `scan off`. Replace the address below with the mouse's address:

```text
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
quit
```

If it disappeared from view, `devices` lists discovered devices. Answer pairing prompts as required. Many terminals toggle full screen with F11 or Fn+F11. [BlueZ command reference](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html).

## Install Arduino CLI and Miniforge


Run shell blocks one at a time, in order. Stop when a command reports an error.

```bash
sudo apt update
sudo apt install -y git curl ca-certificates usbutils
mkdir -p "$HOME/.local/bin"
cd "$HOME/Downloads"
curl -fL -o arduino-cli.tar.gz https://github.com/arduino/arduino-cli/releases/download/v1.5.1/arduino-cli_1.5.1_Linux_ARM64.tar.gz
tar -xzf arduino-cli.tar.gz arduino-cli
install -m 755 arduino-cli "$HOME/.local/bin/arduino-cli"
printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"
arduino-cli version
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli core list
```

The `.tar.gz` is an archive; downloading it alone does not install the command. If it is already downloaded, extract that filename and continue at `install`. Expect Arduino AVR Boards 1.8.8 in `core list`. The archive and checksums are on the [official Arduino CLI 1.5.1 release](https://github.com/arduino/arduino-cli/releases/tag/v1.5.1).

Install Miniforge for Linux ARM64:

```bash
cd "$HOME/Downloads"
curl -fL -o Miniforge3-Linux-aarch64.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh
bash Miniforge3-Linux-aarch64.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda --version
```

If Miniforge is already installed there, skip its installer and run the last two commands. Do not install over an existing directory. Miniforge supplies Conda and uses conda-forge by default; its Linux `aarch64` installer supports the Pi's 64-bit architecture. An existing working Conda installation can also create this environment. [Official Miniforge installers](https://github.com/conda-forge/miniforge).

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

## Connect, configure and flash Nano B

Connect B by USB. Inspect the USB device and serial port:

```bash
lsusb
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
python -m serial.tools.list_ports -v
sudo usermod -aG dialout "$USER"
```

After adding the group, **log out of the Pi desktop and log back in**, reopen Terminal, return to the repository and activate the environment. `id -nG` must include `dialout`. A CH340 board normally appears as `/dev/ttyUSB0`; `/dev/serial/by-id` can be absent. Use the port actually listed.

```bash
conda activate sx1278-benchmark
cd "$HOME/sx1278-raspberry-pi-demo"
id -nG
python tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --profile LoRa --count 3
python firmware/tools/board_control.py --action ports
python firmware/tools/board_control.py --action handshake
python firmware/tools/board_control.py --action build
python firmware/tools/board_control.py --action upload
```

The helper writes B's configuration into `config/internal/board_control.toml` and the transmitter settings into `config/main_transmit.toml`. The expected build output is `firmware/build/receive-endpoint/manifest.json`, with `endpoint_id: 2` and `compiled: true`. Upload must finish successfully with flash verification.

## If the bootloader handshake fails

Check the data cable, selected port and power. Close any program owning the port. Then try:

```text
python firmware/tools/board_control.py --action handshake --baud 115200
```

The default is `arduino:avr:nano:cpu=atmega328old` (57600 upload baud). If only 115200 succeeds, change `fqbn` in the selected board TOML to `arduino:avr:nano:cpu=atmega328`, then build and upload again. The override does not save a new FQBN. Application UART remains 115200 regardless of the bootloader.

Board A uses `config/internal/transmit_endpoint.toml` and `firmware/build/single-endpoint/manifest.json`. Board B uses `config/internal/receive_endpoint.toml` and `firmware/build/receive-endpoint/manifest.json`. The filenames identify physical boards, not permanent TX/RX roles.

If tools are not found, check `arduino-cli version` and `arduino-cli core list`. Custom Arduino paths belong in `config/internal/board_control.toml`. A slow build can use `command_timeout_seconds = 300`. A changed board file, including comments, requires a new build and upload with the matching manifest. Never edit identity hashes to bypass a mismatch.

## Setup is complete when

- `uname -m` reports `aarch64`; network access works for installation.
- Arduino AVR Boards 1.8.8 is installed; Python 3.12 and all software tests work.
- The actual USB port is identified and `id -nG` contains `dialout` after logging in again.
- Build succeeds and upload verifies the flash. B's manifest has `endpoint_id: 2` and `compiled: true`.

Continue with the [three-frame antenna experiment](../../experiments/README.md). Start the receiver before confirming transmission on the Pi. After reboot, activate the environment and return to the repository; repeat setup only for changed software or hardware.
