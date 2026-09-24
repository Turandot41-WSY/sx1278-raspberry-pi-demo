# Troubleshooting

[Repository overview](../../README.md) · [Experiment guide](../experiments/README.md)


| Symptom | Action |
|---|---|
| `arduino-cli: command not found` | Extract the archive, install the executable, add its directory to PATH, reopen the terminal, then run `arduino-cli version`. On Pi/macOS try `export PATH="$HOME/.local/bin:$PATH"`. |
| Arduino index download appears idle | Check HTTPS access and the network; run `arduino-cli core update-index --verbose` to see progress. Installing the CLI and downloading its core are separate steps. |
| `conda` unavailable after installation | Open a new initialized shell or source `~/miniforge3/etc/profile.d/conda.sh` on Pi/Mac. Use Miniforge Prompt on Windows. |
| Git asks for a password | Verify the exact public URL in the platform setup guide. This repository can be cloned anonymously. A browser login does not authenticate another private repository's HTTPS clone. |
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
| A run stops partway | Keep its evidence. Fix the cause and start a new run; there is no automatic silent retry. |
