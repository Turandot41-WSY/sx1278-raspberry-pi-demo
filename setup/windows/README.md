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

If PowerShell reports that `arduino-cli` is not recognized, use [Find tools and set their paths manually](#find-tools-and-set-their-paths-manually). Locate and verify the CLI before continuing with the AVR installation commands.

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

## Find tools and set their paths manually

Use this section for `Cannot find arduino_cli`, `Cannot find avrdude`, `Cannot find avrdude_config`, or `Cannot find avr_size`. Run the search commands in **PowerShell**, including when the Python environment is managed through Miniforge Prompt.

The command `arduino-cli` searches PATH. `.\arduino-cli.exe` looks only in the current directory; the repository does not contain that executable. A quoted executable path needs PowerShell's `&` call operator, as shown below. See Microsoft's [command precedence](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_command_precedence?view=powershell-7.5) and [call operator](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_operators?view=powershell-7.5#call-operator-) documentation.

### 1. Find arduino-cli.exe

First check whether PowerShell can already locate it:

```powershell
Get-Command arduino-cli.exe -All -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Source
```

If there is no result, search the download folder and common installation locations:

```powershell
$demoSearchRoots = @(
    (Join-Path $HOME 'arduino-cli')
    (Join-Path $HOME 'Downloads')
    (Join-Path $env:LOCALAPPDATA 'Programs/Arduino IDE')
    (Join-Path $env:ProgramFiles 'Arduino IDE')
)
$demoSearchRoots |
    Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
    ForEach-Object {
        Get-ChildItem -LiteralPath $_ -Filter arduino-cli.exe -File -Recurse -ErrorAction SilentlyContinue
    } |
    Select-Object -ExpandProperty FullName
```

If you installed Arduino in another folder, add that folder to `$demoSearchRoots` and repeat the search. You can also search for `arduino-cli.exe` in that folder with File Explorer and use **Copy as path**. If no executable is found, extract the official ZIP using the [installation block above](#install-git-miniforge-and-arduino-cli). Installing Arduino CLI is documented in the [Arduino installation guide](https://docs.arduino.cc/arduino-cli/installation/).

Paste the complete blocks. If PowerShell remains at a `>>` prompt after a paste, press **Ctrl+C**, then paste the complete block again.

### 2. Verify the selected CLI and install AVR Boards

Replace the example path with one of the actual results. This guide uses Arduino CLI **1.5.1**; check the version if you found a CLI bundled with Arduino IDE.

```powershell
$demoCli = 'C:/Users/YOUR_NAME/arduino-cli/arduino-cli.exe'
Test-Path -LiteralPath $demoCli -PathType Leaf
& $demoCli version
& $demoCli config dump --verbose
& $demoCli core list
```

`Test-Path` must return `True`, and the version command must succeed. In the configuration output, check `directories.data`: this is the package installation directory. The Windows default is `%LOCALAPPDATA%/Arduino15`. Use the configured location if it differs; the sketchbook directory `Documents/Arduino` has a different purpose. See [Arduino CLI configuration](https://docs.arduino.cc/arduino-cli/configuration).

If `core list` does not show `arduino:avr` **1.8.8**, run:

```powershell
& $demoCli core update-index
& $demoCli core install arduino:avr@1.8.8
& $demoCli core list
```

The AVR Boards installation supplies AVRDUDE and AVR GCC, including `avr-size.exe`. Extracting the CLI ZIP alone does not install them. Keep using `& $demoCli ...` while PATH is unresolved. After opening another PowerShell terminal, assign `$demoCli` again before using it.

### 3. Find the AVR executables and configuration file

For the default data directory, run:

```powershell
$demoArduinoData = Join-Path $env:LOCALAPPDATA 'Arduino15'
$demoToolRoot = Join-Path $demoArduinoData 'packages/arduino/tools'
Get-ChildItem -LiteralPath $demoToolRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('avrdude.exe', 'avrdude.conf', 'avr-size.exe') } |
    Select-Object -ExpandProperty FullName
```

For a custom `directories.data`, replace the first line with `$demoArduinoData = 'D:/Your/Actual/ArduinoData'`, using the location from step 2. If the search returns nothing, check that the AVR installation succeeded using the same `$demoCli` and data directory.

Copy all three paths. `avrdude.exe` and `avrdude.conf` must come from the **same AVRDUDE version folder**, usually its `bin` and `etc` subfolders. `avr-size.exe` is inside an `avr-gcc` version folder. The example below uses the tool versions expected by this repository's automatic discovery; copy your actual paths instead of assuming those folders exist.

### 4. Save the paths in board_control.toml

Open [`firmware/config/internal/board_control.toml`](../../firmware/config/internal/board_control.toml) in VS Code. Replace its existing values using this mapping:

| Found item | Field to edit | What the field controls |
|---|---|---|
| Arduino package data directory | Top-level `arduino_data_dir`, above `[tools]` | Where the Python maintenance tool searches for installed AVR tools |
| `arduino-cli.exe` | `[tools]` → `arduino_cli` | CLI used for compilation and upload |
| `avrdude.exe` | `[tools]` → `avrdude` | Executable used for the bootloader handshake |
| Matching `avrdude.conf` | `[tools]` → `avrdude_config` | AVRDUDE's chip and programmer definitions for the handshake |
| `avr-size.exe` | `[tools]` → `avr_size` | Reports compiled firmware memory usage |

Example, with paths to replace:

```toml
# Keep this existing top-level field ABOVE [tools].
arduino_data_dir = "C:/Users/YOUR_NAME/AppData/Local/Arduino15"

[tools]
arduino_cli = "C:/Users/YOUR_NAME/arduino-cli/arduino-cli.exe"
avrdude = "C:/Users/YOUR_NAME/AppData/Local/Arduino15/packages/arduino/tools/avrdude/8.0.0-arduino1/bin/avrdude.exe"
avrdude_config = "C:/Users/YOUR_NAME/AppData/Local/Arduino15/packages/arduino/tools/avrdude/8.0.0-arduino1/etc/avrdude.conf"
avr_size = "C:/Users/YOUR_NAME/AppData/Local/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin/avr-size.exe"
```

Use full paths with **forward slashes** and your actual username and version folders. The four `[tools]` values must include the filename. Do not put `%LOCALAPPDATA%`, `$env:LOCALAPPDATA`, or `$demoCli` into TOML: the Python loader does not expand those variables. Replace the existing fields; do not append a second `[tools]` table. Keep the device, board and build settings selected earlier, then save with **Ctrl+S**.

These values configure the Python maintenance tool. They do not add the CLI to PowerShell's PATH. `arduino_data_dir` must match the CLI's package location; setting this field does not change the CLI's own `directories.data` setting. A nonempty tool path must point to an existing file, or the maintenance tool stops with `tools.<name> is not a file`.

### 5. Check the saved paths before using the board

From the repository root, with `sx1278-benchmark` active and the local role and COM port selected, run:

```powershell
python firmware/tools/board_control.py --action handshake --dry-run
python firmware/tools/board_control.py --action build --dry-run
```

Both commands should print their plans with the selected tool paths and no `Cannot find` or `is not a file` error. These checks validate the paths and construct commands; they do not communicate with the board or compile firmware. Continue with the actual handshake, build and upload below.

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

For missing tools, follow [Find tools and set their paths manually](#find-tools-and-set-their-paths-manually). A slow build can use `command_timeout_seconds = 300`. A changed board file, including comments, requires a new build and upload with the matching manifest. Never edit identity hashes to bypass a mismatch.

## Setup is complete when

- `git --version` and `conda --version` work; Arduino CLI runs through `arduino-cli version` or `& $demoCli version` with its verified full path.
- Python 3.12 and AVR Boards 1.8.8 are selected; the help commands run.
- The intended COM port and A/B board are configured; build and upload succeed.

Continue with the [transmitter](../../transmit/README.md), [receiver](../../receiver/README.md), or [hardware checks](../../tests/README.md) for the selected role. A Windows sender runs `python transmit/main.py`; a Windows receiver runs `python receiver/main.py`. In Windows → Windows, these commands run on different computers with separate local serial ports.
