# Dataset preparation

[Repository overview](../README.md) · [Transmit](../transmit/README.md)

`dataset/main.py` acquires and saves orbit data. Its settings live in [`config.toml`](config.toml); radio transmission uses [the transmit module](../transmit/README.md).

## Use the bundled archive first

[`data/replay/gomx1-example/`](data/replay/gomx1-example/) contains 2,072 frames generated from five propagated GOMX-1 passes, together with the frozen orbit and Earth orientation inputs. The values are calculated telemetry. The [archive attribution](data/replay/gomx1-example/README.md), `orbit_manifest.json` and `provenance.json` identify the public sources, model and hashes.

The default transmitter selects `data_source = "saved"` and `saved_dataset = "dataset/data/replay/gomx1-example/orbit"`. It validates this directory, rebuilds the frames of 64 bytes and calculates the programmed frequency offsets before asking for confirmation. This trial needs no new acquisition.

## Acquire fresh inputs

Activate `sx1278-benchmark` and run from the repository root. Review `dataset/config.toml` before acquisition:

| Section | Responsibility |
|---|---|
| Top-level `action` | Selects `acquire` |
| `[acquire]` | Online or offline input, UTC search interval, output root and generator revision |
| `[orbit_model.sources]` | CelesTrak OMM and IERS URLs, maximum accepted OMM age |
| `[orbit_model.download]` | Download attempts, timeout in seconds and public client identifier |
| `[orbit_model.station]` | Station latitude/longitude in degrees, height in metres and elevation mask in degrees |
| `[orbit_model.radio]` | Nominal carrier frequency in Hz used by the orbit model |

Every field has an English explanation next to its value. The default model uses GOMX-1 and the project station near Linz. The 244 m station height is a DEM proxy. Changing the model requires regenerating the dataset; saved provenance is checked against the selected model.

For online acquisition, keep `fetch = true` and `offline = ""` in `[acquire]`:

```text
python dataset/main.py
```

`python -m dataset.main` and `python dataset/main.py acquire` select the same entry. Online acquisition needs internet access. Download, source age or validation failures stop the operation. Successful acquisition prints a timestamped directory under `dataset/data/orbit/gomx1_39430/`.

To process frozen source inputs, set `fetch = false` and `offline` to their complete dataset directory. Select exactly one mode. Set both `search_start_utc` and `search_end_utc`, or leave both empty to use the configured search strategy.

To transmit the result, set `[antenna].data_source = "saved"` and `[antenna].saved_dataset` in `transmit/config.toml` to the printed directory. Start with three frames. The receiver captures raw frames independently and needs the completed sender log for comparison.

Setting the transmitter's `data_source = "latest"` runs acquisition before each trial using this module's configuration. Acquire once and reuse `saved` when trials need identical inputs. Keep the complete dataset and its source files with the trial evidence.

## Frame format

The RF payload is a binary frame of 64 bytes. Its layout is implemented in [`ccsds_tm.py`](ccsds_tm.py) and [`orbit_record.py`](orbit_record.py). Multi-byte integers use big-endian order. Receive logs store those bytes as hexadecimal text.

| Frame byte offset | Length | Content |
|---|---|---|
| 0–5 | 6 bytes | TM primary header and frame counters |
| 6–11 | 6 bytes | Space Packet primary header and packet sequence count |
| 12–61 | 50 bytes | Project mission record |
| 62–63 | 2 bytes | Frame Error Control Field (FECF) |

Offsets below are relative to the mission record:

| Offset | Field | Type | Meaning |
|---|---|---|---|
| 0 | `trace_time_ms` | uint32 | Milliseconds from the first sample of the selected pass |
| 4, 8, 12 | `position_x_m`, `position_y_m`, `position_z_m` | 3 × int32 | Terrestrial position components in metres |
| 16, 20, 24 | `velocity_x_mmps`, `velocity_y_mmps`, `velocity_z_mmps` | 3 × int32 | Terrestrial velocity components in millimetres per second |
| 28 | `slant_range_m` | uint32 | Satellite-to-station slant range in metres |
| 32 | `range_rate_mmps` | int32 | Range rate in millimetres per second |
| 36 | `doppler_millihz` | int32 | Model Doppler in millihertz |
| 40 | `mission_state` | uint8 | Project state value; the generator sets 0 |
| 41 | `workload` | uint8 | Project workload value; the generator sets 0 |
| 42 | `trace_sample_id` | uint16 | Sample identifier within the dataset |
| 44–49 | Diagnostic pattern | 6 bytes | Sample ID, its XOR with `0xA5A5`, and its byte-swapped value |
