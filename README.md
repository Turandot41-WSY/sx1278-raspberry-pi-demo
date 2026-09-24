# SX1278 antenna demo: Raspberry Pi 5 to Mac or Windows

Send telemetry from a **Raspberry Pi 5** through an Arduino Nano and Ra-02/SX1278 radio. A second Nano and Ra-02 receive it on **macOS or Windows**. Each computer connects to its own Nano over USB; the two radios communicate through antennas.

This README is the complete procedure from an empty microSD card to a checked reception. Start with **3 LoRa frames**, then try 20 and the complete archived dataset. The included archive contains 2,072 frames generated from five propagated GOMX-1 passes. It is demonstration input, not a recording received from the satellite.

| Machine | Physical board | Endpoint identity | Role |
|---|---|---|---|
| Raspberry Pi 5, Raspberry Pi OS 64-bit | Nano B + Ra-02 | 2 | Transmitter |
| Mac **or** Windows PC | Nano A + Ra-02 | 1 | Receiver and local browser display |

The setup uses Python 3.12 in the `sx1278-benchmark` Conda environment, Arduino CLI 1.5.1, and Arduino AVR Boards 1.8.8. Defaults are LoRa, nominal 437.5 MHz, 2 dBm, a 1,000 ms pause after each transmission, and the archived Doppler offsets on the transmitter. Use a frequency and power authorized for your location. No LAN connection between the two computers is required for radio operation.

**Read in order:** [hardware](#1-hardware-and-wiring) → [Pi OS](#2-install-raspberry-pi-os--on-the-mac) → [network](#3-network-and-optional-bluetooth--on-the-pi) → [Pi tools](#4-install-tools--on-the-pi) → [receiver tools](#5-install-tools--on-the-receiver-computer) → [clone and environment](#6-clone-and-create-the-python-environment--both-computers) → [flash](#7-identify-configure-build-and-flash-each-board) → [receive and send](#8-first-reception-and-transmission) → [verify](#9-check-the-received-bytes) → [repeat](#10-repeat-with-20-frames-or-the-full-dataset).

The architecture diagram records the initial package; its `web/app.js` label now corresponds to `web/editor.mjs`. The [code architecture HTML](docs/architecture/architecture.html) and its [JSON source](docs/architecture/architecture.json) are included. GitHub displays HTML source; [section 13](#13-code-architecture-and-reading-order) explains how to view it locally.

## 1. Hardware and wiring

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

## 2. Install Raspberry Pi OS — on the Mac

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

## 3. Network and optional Bluetooth — on the Pi

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

## 4. Install tools — on the Pi

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

## 5. Install tools — on the receiver computer

Choose **one** receiver platform. The following sections prepare the receiver before the common clone and firmware steps.

### macOS

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

### Windows 10/11, x86-64

1. Install [Git for Windows](https://git-scm.com/download/win), allowing Git in the command line.
2. Download and run [Miniforge3 for Windows x86-64](https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe). Open **Miniforge Prompt** and run `conda init powershell`. Close it, then open a new PowerShell terminal.
3. Run `conda --version` and `git --version`. If PowerShell blocks the Conda profile, run the Python/Conda/Git steps in **Miniforge Prompt** instead; run the PowerShell download block below in PowerShell. The remaining Python commands work in either shell.

In PowerShell:

```powershell
$cliDir = Join-Path $HOME 'arduino-cli'
$cliZip = Join-Path $HOME 'Downloads/arduino-cli.zip'
Invoke-WebRequest 'https://github.com/arduino/arduino-cli/releases/download/v1.5.1/arduino-cli_1.5.1_Windows_64bit.zip' -OutFile $cliZip
Expand-Archive $cliZip -DestinationPath $cliDir -Force
$env:Path = "$cliDir;$env:Path"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $cliDir) {
    [Environment]::SetEnvironmentVariable('Path', "$cliDir;$userPath", 'User')
}
arduino-cli version
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli core list
```

Open a new terminal after modifying PATH. In Miniforge Prompt, a temporary PATH repair is `set "PATH=%USERPROFILE%\arduino-cli;%PATH%"`. The installer uses Windows x86-64; Windows ARM has not been verified for this release.

## 6. Clone and create the Python environment — both computers

Run on the Pi **and** the selected receiver computer. Choose a location with enough free space. This public clone requires no GitHub login or password.

Pi/macOS:

```bash
cd "$HOME"
git clone https://github.com/Turandot41-WSY/sx1278-raspberry-pi-demo.git
cd sx1278-raspberry-pi-demo
```

Windows PowerShell:

```powershell
Set-Location $HOME
git clone https://github.com/Turandot41-WSY/sx1278-raspberry-pi-demo.git
Set-Location sx1278-raspberry-pi-demo
```

In Miniforge Prompt, use `cd /d "%USERPROFILE%"` before cloning and `cd sx1278-raspberry-pi-demo` afterward.

All platforms, from the repository root:

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

If `sx1278-benchmark` already exists, skip `conda env create`; activate it, verify Python 3.12, and install `requirements.txt`. The requirements file is the authoritative dependency snapshot. Avoid installing into the OS Python or Conda base environment.

Proceed when `pip check` reports no broken requirements, the tests pass, and both help commands work. Tests use simulated endpoints and do not transmit. Every later command assumes this environment is active and the terminal is in this repository root. `git rev-parse HEAD` should report the same code revision on both computers.

## 7. Identify, configure, build and flash each board

Close Arduino Serial Monitor and any older send/receive processes before using a Nano. Build and upload on the computer that will own that board; its manifest is generated locally.

### Pi: Nano B, transmitter

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

### Mac: Nano A, receiver

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

### Windows: Nano A, receiver

Connect A by USB. Run:

```powershell
python -m serial.tools.list_ports -v
```

Replace `COM4` with the port actually listed:

```powershell
python tools/configure_antenna.py --device COM4 --board A --role rx --profile LoRa
python firmware/tools/board_control.py --action handshake
python firmware/tools/board_control.py --action build
python firmware/tools/board_control.py --action upload
```

If no COM port appears, check the cable and Device Manager. Install the CH340/CH341 driver from the board or chip manufacturer's official support page if Windows has not installed it.

For either receiver, the expected manifest is `firmware/build/single-endpoint/manifest.json`, with `endpoint_id: 1` and `compiled: true`.

### Bootloader troubleshooting and board identity

The supplied board files select `arduino:avr:nano:cpu=atmega328old`, whose upload baud is 57600. If handshake fails, try:

```text
python firmware/tools/board_control.py --action handshake --baud 115200
```

If only 115200 succeeds, edit `fqbn` in **that board's** TOML to `arduino:avr:nano:cpu=atmega328`, then build and upload again. A successful `--baud` override does not save a new board type. The application UART always uses 115200; bootloader baud and application baud are separate settings.

| Board | Board TOML | Build folder |
|---|---|---|
| A / endpoint 1 | `config/internal/transmit_endpoint.toml` | `firmware/build/single-endpoint` |
| B / endpoint 2 | `config/internal/receive_endpoint.toml` | `firmware/build/receive-endpoint` |

The filenames are historical board identifiers. Both use `firmware/endpoint/endpoint.ino` and can transmit or receive. **For this demo B transmits and A receives.** The role helper selects the correct manifest automatically.

Editing a board TOML, including comments, changes its identity hash. Build, upload and use the corresponding manifest together. Do not replace a manifest with one from another board or edit its hash to bypass an identity mismatch. Rebuilding alone does not change the firmware already installed on the Nano.

## 8. First reception and transmission

### Check the saved configuration

On the Pi, `config/main_transmit.toml` should contain these fields in `[antenna]`:

```toml
# Keep the existing full file; these are the fields to inspect.
data_source = "saved"
saved_dataset = "data/replay/gomx1-example/orbit"
port = "/dev/ttyUSB0"
manifest = "firmware/build/receive-endpoint/manifest.json"
start = 0
count = "3"
profile = "LoRa"
pa_dbm = 2
interval_ms = 1000
timeout_ms = 2000
```

Its top-level `action` is `"antenna"`. A nonempty `saved_dataset` rebuilds and verifies frames from the complete archived dataset and applies its frequency offsets. The `frames`, `sha256` and `orbit_dataset` fields are an alternative explicit frame-file input; leave them as supplied for the first run.

On the receiver, `config/main_receive.toml` has `action = "listen"`, the actual local `device`, A's manifest, `profile = "LoRa"`, `max_windows = 0`, and `display = true`. `[display].reference_dataset` must be `data/replay/gomx1-example/orbit` for this first run.

### Start the receiver first — Mac or Windows

```text
python main_receive.py
```

Wait for `RX_ARMED`. Empty windows print `RX_TIMEOUT` and reopen; this is normal while the sender is idle. In that computer's browser open:

**http://127.0.0.1:8878/monitor**

The page reads the current session's real packet log. It uses the same approved Lunar White dashboard as the full project: IT:U, S3 Lab and SPOK Space Lab logos with the author credit, a regional orbit map, received telemetry, and slant range and model Doppler plots. Only valid received frames add points; earlier received passes remain visible. The source and frame dialog shows frame counts, raw frame bytes and exact reference matching. RSSI/SNR values are labeled raw because the display does not convert them to calibrated measurements. The local HTTP service does not transport the radio frames between computers.

The [dashboard preview and verification record](docs/frontend/README.md) show the restored layout.

### Prepare without sending — Pi

```bash
python main_transmit.py
```

Read the data selection and frame count. At the confirmation prompt, enter **n**. Expect `CANCELLED_BEFORE_SEND`; this checks data preparation without opening the serial port. It still requires the compiled local manifest. The prepared files remain in the printed evidence directory.

### Send three frames — Pi

Keep the receiver running and execute:

```bash
python main_transmit.py
```

At the confirmation prompt, enter **y**. Expected sender progression includes:

```text
Frame 0: TX_DONE (1/3)
Frame 1: TX_DONE (2/3)
Frame 2: TX_DONE (3/3)
[Complete] 3/3 frames transmitted.
```

The receiver should report three `RX_PACKET` events with `length=64` and `phy_crc_ok=1`. The browser should show three valid frames and matching references. Stop the receiver with **Ctrl+C** after collecting the test. This also closes its browser service; the log files remain.

`TX_DONE` establishes transmitter completion. It does not establish successful reception. Complete the byte comparison below before marking the first test successful.

## 9. Check the received bytes

Each run prints its evidence directory. Retain those exact paths:

| Computer | Files |
|---|---|
| Pi | `output/antenna-doppler/<UTC>/events.jsonl`, prepared frames, frequency plan and manifests |
| Receiver | `output/receive/<UTC>/events.jsonl` and configuration snapshots |

Copy the Pi's **completed** `events.jsonl` to the receiver as `tx-events.jsonl` using a USB drive or an available file transfer method. Do not choose the earlier cancelled run. On the receiver, replace `YOUR_RX_RUN` with the directory printed by the receive process:

```text
python tools/verify_reception.py --tx tx-events.jsonl --rx output/receive/YOUR_RX_RUN/events.jsonl
```

For a successful three-frame demo, expect `requested: 3`, `tx_done: 3`, `matched: 3`, `missing: 0`, and `passed: true`. The command compares exact payload bytes and multiplicities, rejects CRC failures, checks the profile and completed transmitter counts, and exits nonzero when frames are missing. Extra or rejected packets are reported separately.

Use one fresh receive session for each verification and avoid other transmitters using the same payload. Independent reception has no shared attempt identifier with the sender; matching bytes do not distinguish an unrelated replay of the same frozen frame. These logs support this functional demonstration, not a synchronized scientific packet error rate experiment.

## 10. Repeat with 20 frames or the full dataset

Start a fresh receiver session before each send. On the Pi:

```bash
python tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --profile LoRa --count 20
python main_transmit.py
```

After confirming 20 matching receptions, select the whole archive:

```bash
python tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --profile LoRa --count all
python main_transmit.py
```

At `start = 0`, the supplied archive has 2,072 frames. The run takes more than 34 minutes with the 1,000 ms pause, because radio airtime and serial work add time. Keep both computers awake. A receiver reopening its windows can miss a frame; retain the actual match count rather than assuming every emitted frame arrived.

Changing count, saved data selection or pause does not require flashing. Changing firmware, profile tables, pins, endpoint identity or board configuration does. Selecting an already compiled modulation profile requires matching settings and restarting both hosts; use LoRa for the first demonstration. The other compiled profiles are FSK, GFSK, MSK, GMSK and OOK; this release does not claim a Pi hardware result for each.

After a reboot, activate the environment, return to the repository, verify each serial port, start the receiver, then start the sender. Successful firmware uploads persist across power cycles. Upload again when the source or board configuration changes.

## 11. Acquire a new dataset after the archived demo works

The default archive works offline and makes the first comparison reproducible. To obtain new orbit input, inspect all fields in `config/main_dataset.toml`, including satellite, ground station, lookback interval, source age limits and output directory. Then run on the Pi:

```bash
python main_dataset.py acquire
```

This downloads public orbit/Earth orientation inputs and freezes a validated dataset under `data/orbit/`. Acquisition requires internet access. A network, source age or validation failure stops the command; it does not silently substitute the bundled archive.

Copy the **entire resulting dataset directory**, including `source/`, to the receiver. A USB drive is sufficient. On the Pi set `[antenna].data_source = "saved"` and `[antenna].saved_dataset` to that directory. On the receiver set `[display].reference_dataset` to its local copy. Paths may differ across computers; the dataset bytes must agree. Restart the receiver, return the sender count to `"3"`, and repeat sections 8–9.

`data_source = "latest"` is also supported and acquires new input before each send. For a demonstration with a matching browser reference, the explicit acquire → copy → saved sequence above makes it easier to keep both machines on the same dataset. Do not update a receiver's reference while its service is running.

The sampled positions and timestamps represent the selected orbit data. Displaying them does not imply a live satellite downlink or measurements made at the current wall-clock time.

## 12. Troubleshooting

| Symptom | Action |
|---|---|
| `arduino-cli: command not found` | Extract the archive, install the executable, add its directory to PATH, reopen the terminal, then run `arduino-cli version`. On Pi/macOS try `export PATH="$HOME/.local/bin:$PATH"`. |
| Arduino index download appears idle | Check HTTPS access and the network; run `arduino-cli core update-index --verbose` to see progress. Installing the CLI and downloading its core are separate steps. |
| `conda` unavailable after installation | Open a new initialized shell or source `~/miniforge3/etc/profile.d/conda.sh` on Pi/Mac. Use Miniforge Prompt on Windows. |
| Git asks for a password | Verify the exact public URL in section 6. This repository can be cloned anonymously. A browser login does not authenticate another private repository's HTTPS clone. |
| Pi permission denied on `/dev/ttyUSB0` | Add the user to `dialout`, log out and back in, and check `id -nG`. Avoid running the project with `sudo`. |
| No serial port or no `/dev/serial/by-id` | Use `python -m serial.tools.list_ports -v`; verify a data cable, USB enumeration and the CH340 driver. `/dev/ttyUSB0` is usable even without the by-id directory. |
| Port is busy | Close old transmit, receive, Arduino monitor and other serial sessions; only one process should own each Nano. |
| Handshake fails | Try the other bootloader baud, check power/cable/port, then save the matching FQBN before build/upload. |
| Build tool missing | Confirm `arduino-cli core list` includes 1.8.8 and CLI is on PATH. If using a custom Arduino installation, set its paths in `config/internal/board_control.toml`. |
| Build exceeds the maintenance timeout | Increase `command_timeout_seconds` in `config/internal/board_control.toml`, for example to 300, then rebuild. |
| `manifest` missing or `compiled` false | Run the role helper, build and upload on that computer. Builds are generated locally and are excluded from Git. |
| HELLO identity mismatch | Check A/B selection, source version and matching local manifest. Rebuild and upload the intended board; do not edit hashes. |
| SX1278 version/register check fails | Verify regulated 3.3 V, common ground, level translation, NSS/RESET/SPI wiring and module identity. |
| TX_DONE but receiver sees only timeouts | Start RX first, check equal profiles, antennas, supply, frequency and actual A/B assemblies. Retain logs; TX completion alone does not prove reception. |
| Browser port is occupied | Stop an older display service or change `[display].port` and open that port. |
| Page says reference mismatch | Copy the exact transmit dataset to the receiver, update its reference path and restart. A decoded frame can be valid but absent from the selected reference. |
| A run stops partway | Keep its evidence. Fix the cause and start a new run; there is no automatic silent retry. |

To reopen a saved receive log without accessing hardware:

```text
python main_receive.py display --events output/receive/YOUR_RX_RUN/events.jsonl
```

Open the printed local URL and stop the service with Ctrl+C when finished.

## 13. Code architecture and reading order

Open `docs/architecture/architecture.html` directly in a browser after cloning. It is self-contained, works offline, and supports theme selection, zoom, search and relationship tracing. No Node.js installation is needed to view it. The JSON specification, validation receipt, browser containment measurements and screenshots accompany it. Its viewer includes software from Archify under the [included MIT notice](docs/architecture/ARCHIFY-LICENSE.txt).

Read the actual implementation in this order:

| Layer | Source | Responsibility |
|---|---|---|
| Operator entries | [`main_transmit.py`](main_transmit.py), [`main_receive.py`](main_receive.py), [`main_dataset.py`](main_dataset.py) | Select actions from their corresponding TOML files |
| Settings | [`config/README.md`](config/README.md), [`runtime_config.py`](host/common/runtime_config.py) | Parse English operator fields and resolve repository paths |
| Frame preparation | [`transmit_inputs.py`](host/cli/transmit_inputs.py), [`orbit_dataset.py`](host/dataset/orbit_dataset.py), [`ccsds_tm.py`](host/dataset/ccsds_tm.py) | Validate archived input and construct the 64-byte telemetry frames |
| Transmitter | [`transmit_saved.py`](host/cli/transmit_saved.py), [`single_transmit.py`](host/radio/single_transmit.py), [`antenna_doppler.py`](host/radio/antenna_doppler.py) | Confirm, configure, load each frame/frequency, start TX and record TX_DONE |
| UART | [`serial_transport.py`](host/radio/serial_transport.py), [`serial_protocol.py`](host/radio/serial_protocol.py) | COBS framing, serial CRC, identities, command/event validation and timeouts |
| Firmware | [`endpoint.ino`](firmware/endpoint/endpoint.ino), [`sx1278_driver.cpp`](firmware/endpoint/src/sx1278_driver.cpp) | Parse Nano commands and operate the radio through SPI |
| Receiver | [`receive_saved.py`](host/cli/receive_saved.py), [`single_receive.py`](host/radio/single_receive.py) | Arm independent windows and preserve actual packet bytes |
| Browser | [`receiver.py`](host/display/receiver.py), [`server.py`](host/display/server.py), [`web/editor.mjs`](web/editor.mjs) | Validate log frames, decode positions and serve local telemetry |
| Build tools | [`board_control.py`](firmware/tools/board_control.py), [`build_single_endpoint.py`](firmware/tools/build_single_endpoint.py) | Find tools, compile identity-bound firmware and upload with verification |
| Offline comparison | [`verify_reception.py`](tools/verify_reception.py) | Match completed transmit requests to CRC-valid received bytes |

The main command paths are:

```text
main_transmit → prepare_transmit_inputs → load/validate dataset → confirmation
              → open_nano_port → configure_transmitter
              → LOAD_TX → TX_READY → START_TX → TX_STARTED → TX_DONE

main_receive → configure_transmitter (shared register/identity setup)
             → ARM_RX → RX_ARMED → RX_PACKET or RX_TIMEOUT → events.jsonl
             → ReceiverStore → /api/telemetry → browser
```

The receiver reuses the setup function named `configure_transmitter`; this sets identity/profile/PA registers and does not transmit. `main_receive` does not issue `LOAD_TX` or `START_TX`.

## 14. Validation and evidence boundaries

See [the release verification record](docs/validation.md) for the actual checks performed. Software tests, AVR compilation and browser checks can run without connected hardware. They do not establish a Raspberry Pi 5 physical RF result. Complete the checks in sections 7–9 on your assemblies and preserve their logs.

The public repository includes only the independent antenna workflow, its firmware, data preparation, display and relevant tests.

The Pi stores its own transmit log; the Mac or Windows receiver stores its receive log and serves its local browser. The receiver sends no logs or radio commands back to the Pi. Optional transfer of the completed transmit log to the receiver supports the exact-byte check in section 9. MATLAB processing, statistical experiment analysis and remote control of receiver UARTs are outside this public distribution.

Generated binaries, local settings secrets and experimental output are excluded from version control. Public input attribution is retained in the [archive README](data/replay/gomx1-example/README.md) and its source manifests.
