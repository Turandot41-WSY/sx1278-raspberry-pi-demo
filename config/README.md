# Operator configuration

[Repository overview](../README.md) · [Experiment guide](../docs/experiments/README.md)

Each real entry owns one TOML file. The top-level `action` selects its section; explicit command-line flags override only the current run. Save edits, stop the previous process and restart it.

| Entry | Configuration | Action and section | Output |
|---|---|---|---|
| `main_transmit.py` | `main_transmit.toml` | `antenna` / `[antenna]`; explicit file alternative `saved` / `[saved]` | `output/antenna-doppler/<UTC>` or `output/transmit/<UTC>` |
| `main_receive.py` | `main_receive.toml` | `listen` / `[listen]` | `output/receive/<UTC>` |
| `main_dataset.py` | `main_dataset.toml` | `acquire` / `[acquire]` and `[orbit_model]` | `data/orbit/` |

Every field has an English explanation next to its value. Paths are relative to the repository root unless absolute. Use forward slashes in Windows TOML paths, for example `C:/Users/me/data/orbit`.

The role helper writes the selected host device and manifest into the appropriate operator file and `internal/board_control.toml`. Use B TX/A RX on every supported platform pair. The actual device is `/dev/ttyUSB0` or similar on Pi, `/dev/cu.*` on Mac, and `COMn` on Windows.

| Identity | Board TOML | Build output |
|---|---|---|
| A / endpoint 1 | `internal/transmit_endpoint.toml` | `firmware/build/single-endpoint` |
| B / endpoint 2 | `internal/receive_endpoint.toml` | `firmware/build/receive-endpoint` |

These historical filenames identify physical boards independently of their runtime roles. Both compile `firmware/endpoint/endpoint.ino`. Editing a board file, including comments, changes its identity hash; rebuild and upload, then retain the matching manifest. A new manifest cannot describe an old installed image.

In `[antenna]`, a nonempty `saved_dataset` takes precedence over the explicit `frames`/`sha256`/`orbit_dataset` input. `data_source = "latest"` acquires before preparing frames. Start with the bundled saved dataset and three LoRa frames. See [Dataset preparation](../docs/datasets/README.md).

`profiles.csv`, `pa_settings.csv` and `profile_registers.csv` define compiled radio settings. Firmware tools generate the tables and build identity from them. Profile selection at runtime requires the same compiled tables at both ends.
