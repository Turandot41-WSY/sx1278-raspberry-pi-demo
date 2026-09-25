# Hardware checks

Run these scripts individually after connecting the hardware. Each script calls
the production implementation. Imports and `--help` do not open a serial port.
The scripts use `step_*.py` names and are not collected by
pytest.

Use the `sx1278-benchmark` Conda environment and run commands from the repository
root. Install the dependencies and Arduino tools described in
[setup](../setup/README.md), then check the wiring in
[firmware](../firmware/README.md). Close any process using the selected serial
port before opening it with another step.

```sh
conda activate sx1278-benchmark
python tests/step_01_ports.py
```

Choose the reported port for each computer. The board identity A or B is separate
from its current transmit or receive role. This example assigns board B to the
transmitter and board A to the receiver; run each command on its own computer and
replace the port with the value reported there.

```sh
# Transmitter computer
python firmware/tools/configure_antenna.py --device /dev/ttyUSB0 --board B --role tx --doppler off --count 3 --profile LoRa

# Receiver computer
python firmware/tools/configure_antenna.py --device COM4 --board A --role rx --profile LoRa
```

Review `firmware/config/internal/board_control.toml`, `transmit/config.toml` and
`receiver/config.toml` before running the selected step. The board maintenance
file specifies the local device, board configuration, build directory and tool
paths. Step 07 uses the `[antenna]` settings selected by the role configuration
command. Use the same profile on both computers. Keep the `[antenna]` frame file and SHA256
together when changing its input data.

| Step | Command | Evidence to check |
| --- | --- | --- |
| 01 | `python tests/step_01_ports.py` | The expected local USB serial port appears. |
| 02 | `python tests/step_02_handshake.py` | `Bootloader signature verified: True`; command evidence records the signature. |
| 03 | `python tests/step_03_build.py` | The production build completes and saves its manifest and compiled HEX. |
| 04 | `python tests/step_04_upload.py` | The build validation and Arduino upload with verification both complete. |
| 05 | `python tests/step_05_configure.py --device PORT --manifest BUILD/manifest.json` | HELLO identity, profile readback and PA readback pass. |
| 06 | `python tests/step_06_receive.py --max-windows 6` | The receiver saves exactly six completed windows as packets or timeouts. |
| 07 | `python tests/step_07_transmit.py --count 3` | After terminal confirmation, three frames receive matching `TX_DONE` events. |
| 08 | `python tests/step_08_verify_logs.py --tx TX/events.jsonl --rx RX/events.jsonl` | The verifier reports `passed: true` and `missing: 0` for the selected logs. |

Replace uppercase placeholders with actual paths or ports. Board A normally uses
`firmware/build/single-endpoint/manifest.json`; board B normally uses
`firmware/build/receive-endpoint/manifest.json`. Check the actual build selection
in the maintenance settings. Repeat steps 02–05 on both boards when first setting
up the pair. Step 03 can compile before a board is connected.

Steps 02, 03 and 04 support `--dry-run` to validate their inputs and show the
command. Step 02 can reset the Nano and checks its bootloader without requesting
a Flash write. Step 04 writes the compiled firmware to Flash. Step 05 opens the
production serial protocol and applies the selected profile and PA registers;
it leaves the radio in standby after successful configuration.

Start step 06 on the receiver before step 07 on the transmitter. With six windows
of 5000 ms, the receiver has at most 30 seconds of radio window time; packets end
windows early and serial setup adds time. Increase the finite window count when
more time is needed to start the transmitter. A receive timeout confirms an
empty completed window, and does not establish a successful radio link. Step 07
uses `[antenna]` in `transmit/config.toml` and the production terminal confirmation.
It requires `data_source = "saved"`, `saved_dataset = ""` and `orbit_dataset = ""`,
as selected by `--doppler off`, to check saved frames at fixed frequency.
Its explicit `--count` overrides the configured count. Step 06 similarly
overrides `max_windows`, so neither check selects an unlimited run.

The production commands print their evidence directory under `output/`. Step 05
uses `output/hardware-configure/`; board actions use the maintenance file's
`output` setting. Keep each original run directory. After the receiver finishes,
copy the two selected logs to one computer and run step 08. The comparison checks
the recorded physical sessions and counts exact payload matches with valid PHY
CRC and length. It does not authenticate which radio emitted matching bytes or
distinguish a replay of identical saved frames.

Each step returns zero on its documented completion and a nonzero status on
failure. The transmitter also returns zero when its confirmation is declined;
its evidence then records `CANCELLED_BEFORE_SEND`, which is not a completed
transmission. A completed receiver run can contain only timeouts. Use step 08 to
check actual payload reception. `--help` explains each script's arguments:

```sh
python tests/step_05_configure.py --help
python tests/step_06_receive.py --help
python tests/step_07_transmit.py --help
```
