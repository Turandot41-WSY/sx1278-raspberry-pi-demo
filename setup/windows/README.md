# Windows setup from zero

[Repository overview](../../README.md) · [All setup guides](../README.md) · [Hardware](../../firmware/README.md#hardware-and-wiring)

Prepare a Windows 10/11 x86-64 computer as either a transmitter (Nano B, endpoint 2) or a receiver (Nano A, endpoint 1). For Windows → Windows, follow this guide separately on both computers, selecting one role on each.

## Install Git, Miniforge and Arduino CLI

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

Open a new terminal after modifying PATH. In Miniforge Prompt, a temporary PATH repair is `set "PATH=%USERPROFILE%\arduino-cli;%PATH%"`. This guide targets Windows 10/11 on x86-64.

## Clone and create the Python environment

Run from your home directory. This public repository requires no GitHub login.

```powershell
Set-Location $HOME
git clone https://github.com/Turandot41-WSY/sx1278-raspberry-pi-demo.git
Set-Location sx1278-raspberry-pi-demo
```

In Miniforge Prompt, use `cd /d "%USERPROFILE%"` before cloning and `cd sx1278-raspberry-pi-demo` afterward.

Run the following commands in the repository root:

```text
conda env create -f environment.yml
conda activate sx1278-benchmark
python -m pip install -r requirements.txt
python -m pip check
python --version
python transmit/main.py --help
python receiver/main.py --help
python dataset/main.py --help
```

If `sx1278-benchmark` already exists, skip creation, activate it and verify Python 3.12 before installing `requirements.txt`. Reuse this single environment for the demo. `pip check` should report no broken requirements. The three help commands should display usage and return successfully. The [hardware checks](../../tests/README.md) are separate commands to run after connecting and configuring the boards.

Every later command assumes the environment is active and the terminal is in the repository root. Run `git rev-parse HEAD` on both computers to record the same source revision.

## Identify the local serial port

Connect one Nano through a USB data cable. Close Arduino Serial Monitor and old radio processes. Run:

```powershell
python -m serial.tools.list_ports -v
```

Use the actual COM number below. If no COM port appears, check Device Manager, the cable and USB enumeration. Install the CH340/CH341 driver from the board or chip manufacturer's official support page if Windows has not installed it.

## Select one role on this computer

### Windows transmitter: Nano B

Replace `COM6` with the port connected to Nano B:

```powershell
python firmware/tools/configure_antenna.py --device COM6 --board B --role tx --profile LoRa --count 3
```

This selects `firmware/config/internal/receive_endpoint.toml` and B's `firmware/build/receive-endpoint/manifest.json`.

### Windows receiver: Nano A

Replace `COM4` with the port connected to Nano A:

```powershell
python firmware/tools/configure_antenna.py --device COM4 --board A --role rx --profile LoRa
```

This selects `firmware/config/internal/transmit_endpoint.toml` and A's `firmware/build/single-endpoint/manifest.json`.

Run only the role block for this computer. The helper saves the selected device and board into the maintenance and operator TOML files; it does not flash or start radio operation.

## Check communication, build and upload

After selecting the role:

```powershell
python firmware/tools/board_control.py --action ports
python firmware/tools/board_control.py --action handshake
python firmware/tools/board_control.py --action build
python firmware/tools/board_control.py --action upload
```

Proceed when compilation succeeds, the manifest contains `compiled: true` with the selected endpoint ID, and upload finishes with flash verification.

## If the bootloader handshake fails

Check the data cable, selected port and power. Close any program owning the port. Then try:

```text
python firmware/tools/board_control.py --action handshake --baud 115200
```

The default is `arduino:avr:nano:cpu=atmega328old` (57600 upload baud). If only 115200 succeeds, change `fqbn` in the selected board TOML to `arduino:avr:nano:cpu=atmega328`, then build and upload again. The override does not save a new FQBN. Application UART remains 115200 regardless of the bootloader.

Board A uses `firmware/config/internal/transmit_endpoint.toml` and `firmware/build/single-endpoint/manifest.json`. Board B uses `firmware/config/internal/receive_endpoint.toml` and `firmware/build/receive-endpoint/manifest.json`. The filenames identify physical boards independently of their current transmit or receive roles.

If tools are not found, check `arduino-cli version` and `arduino-cli core list`. Custom Arduino paths belong in `firmware/config/internal/board_control.toml`. A slow build can use `command_timeout_seconds = 300`. A changed board file, including comments, requires a new build and upload with the matching manifest. Never edit identity hashes to bypass a mismatch.

## Setup is complete when

- `git --version`, `conda --version` and `arduino-cli version` work in the current terminal.
- Python 3.12 and AVR Boards 1.8.8 are selected; the help commands run.
- The intended COM port and A/B board are configured; build and upload succeed.

Continue with the [transmitter](../../transmit/README.md), [receiver](../../receiver/README.md), or [hardware checks](../../tests/README.md) for the selected role. A Windows sender runs `python transmit/main.py`; a Windows receiver runs `python receiver/main.py`. In Windows → Windows, these commands run on different computers with separate local serial ports.
