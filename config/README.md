# Operator configuration

The full installation and operating procedure is in the [root README](../README.md).

| Entry | Default action and section | Output |
|---|---|---|
| `main_transmit.py` | `antenna` / `[antenna]` | `output/antenna-doppler/<UTC>` |
| `main_receive.py` | `listen` / `[listen]`, optional `[display]` | `output/receive/<UTC>` |
| `main_dataset.py` | `acquire` / `[acquire]`, `[orbit_model]` | `data/orbit/` |

Terminal and debugger read the same top-level `action`. A CLI override applies to that run only. The role helper saves selected values to these TOML files and `internal/board_control.toml`. Every operator field is explained next to its value.

Board A is endpoint 1 (`internal/transmit_endpoint.toml`); board B is endpoint 2 (`internal/receive_endpoint.toml`). The historical filenames identify physical boards, independently of the current role. For this demo B sends from the Pi and A receives on Mac/Windows.

Board files, including their comments, participate in build identity. After editing them, build, upload, and use the matching manifest. A new manifest cannot describe an older installed firmware image. Generated firmware build directories are intentionally ignored by Git.
