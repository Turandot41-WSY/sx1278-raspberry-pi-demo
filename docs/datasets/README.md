# Dataset preparation

[Repository overview](../../README.md) · [Experiment guide](../experiments/README.md)

## Use the bundled archive first

`data/replay/gomx1-example/` contains 2,072 frames generated from five propagated GOMX-1 passes, with the frozen public orbit and Earth orientation inputs needed to validate them. These are calculated telemetry values, not data received directly from the satellite.

The default sender settings select `data_source = "saved"` and `saved_dataset = "data/replay/gomx1-example/orbit"`. The host verifies the archive, rebuilds frames of 64 bytes and calculates each programmed frequency offset. Preparation runs before the transmission confirmation prompt.

## Acquire a fresh dataset on Pi or Windows

After the archived experiment works, inspect `config/main_dataset.toml`: source URLs and age limits, ground station, search interval and output directory. Keep the established model unless you intentionally regenerate its inputs.

```text
python main_dataset.py acquire
```

This requires internet access. A source age, download or validation failure stops acquisition rather than silently substituting the bundled archive. Successful acquisition writes a complete timestamped dataset under `data/orbit/` and prints its path.

Set `[antenna].data_source = "saved"` and `[antenna].saved_dataset` in `config/main_transmit.toml` to that complete directory. Start with three frames and repeat the [experiment](../experiments/README.md). The receiver does not need a matching dataset to capture raw frames. For verification, transfer the completed sender log to the receiver as described in the experiment guide.

Alternatively, `data_source = "latest"` acquires fresh input before each send. Use explicit acquisition followed by `saved` when repeated trials should use identical input. Keep the complete dataset and its source files with the trial evidence.

The optional `main_transmit.py saved` action reads the explicit frame file under `[saved]` and uses its fixed frequency setting. The recommended `antenna` action accepts the complete orbit dataset and applies its frequency plan. See [operator configuration](../../config/README.md).

Public data attribution and immutable hashes are in the [archive documentation](../../data/replay/gomx1-example/README.md), `orbit_manifest.json` and `provenance.json`.
