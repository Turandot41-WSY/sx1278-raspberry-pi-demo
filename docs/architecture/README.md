# Code architecture

[Repository overview](../../README.md) · [Experiment guide](../experiments/README.md)

Open [architecture.html](architecture.html) in a browser from a local clone. It is self-contained and works offline. GitHub shows its HTML source; download or clone the repository to view it. The page documents the software and hardware path, with theme selection, zoom, search and relationship tracing. It is not an operational receiver frontend.

The diagram covers Pi/Windows transmission, Nano B, the antenna link, Nano A, Mac/Windows reception and exact TX/RX log comparison. [architecture.json](architecture.json) is its editable specification. The packaged viewer retains the [Archify MIT notice](ARCHIFY-LICENSE.txt).

## Read the implementation in execution order

| Layer | Source | Input and result |
|---|---|---|
| Main entries | [`main_transmit.py`](../../main_transmit.py), [`main_receive.py`](../../main_receive.py), [`main_dataset.py`](../../main_dataset.py) | Operator action → selected production workflow |
| Operator settings | [`runtime_config.py`](../../host/common/runtime_config.py), [`config/README.md`](../../config/README.md) | TOML + CLI overrides → validated paths and options |
| Frame preparation | [`transmit_inputs.py`](../../host/cli/transmit_inputs.py), [`orbit_dataset.py`](../../host/dataset/orbit_dataset.py) | Frozen orbit files → validated frames |
| Wire payload | [`ccsds_tm.py`](../../host/dataset/ccsds_tm.py), [`orbit_record.py`](../../host/dataset/orbit_record.py) | Mission fields → binary frame of 64 bytes |
| TX frequency and loop | [`antenna_doppler.py`](../../host/radio/antenna_doppler.py), [`transmit_saved.py`](../../host/cli/transmit_saved.py) | Per-frame frequency + confirmation → recorded transmissions |
| UART commands | [`single_transmit.py`](../../host/radio/single_transmit.py), [`serial_transport.py`](../../host/radio/serial_transport.py), [`serial_protocol.py`](../../host/radio/serial_protocol.py) | Identity/profile setup, command bytes → checked Nano events |
| Nano firmware | [`endpoint.ino`](../../firmware/endpoint/endpoint.ino), [`sx1278_driver.cpp`](../../firmware/endpoint/src/sx1278_driver.cpp) | Serial commands → SPI radio operations and events |
| RX loop | [`receive_saved.py`](../../host/cli/receive_saved.py), [`single_receive.py`](../../host/radio/single_receive.py) | Armed windows → packet bytes or timeouts in JSONL |
| Comparison | [`verify_reception.py`](../../tools/verify_reception.py) | Completed TX log + RX log → matched/missing counts |
| Maintenance | [`board_control.py`](../../firmware/tools/board_control.py), [`build_single_endpoint.py`](../../firmware/tools/build_single_endpoint.py) | Board TOML + source → compiled manifest and verified upload |

## Transmission path

```text
main_transmit.main
  -> select_action: antenna
  -> transmit_antenna.run -> transmit_saved.run
  -> prepare_transmit_inputs: validate dataset, build frames and frequency plan
  -> confirm_transmission: n cancels before opening UART
  -> open_nano_port
  -> configure_transmitter: HELLO, identity, profile and PA checks
  -> transmit_frame for each selected frame:
       LOAD_TX -> TX_READY -> START_TX -> TX_STARTED -> TX_DONE
  -> summary and close
```

## Reception path

```text
main_receive.main
  -> select_action: listen
  -> receive_saved.run
  -> open_nano_port
  -> configure_transmitter: shared identity and register setup
  -> receive_window:
       ARM_RX -> RX_ARMED -> RX_PACKET or RX_TIMEOUT
  -> events.jsonl and repeat
  -> summary and close on Ctrl+C or failure
```

The receiver reuses the function named `configure_transmitter` only for identity/profile/PA register setup. That setup does not transmit. The receive loop never issues `LOAD_TX` or `START_TX`.

The current public radio/data/firmware modules were checked against the maintained source on 24 September 2026. Public entry points and configuration expose independent antenna operation. Remote coordination, experiment qualification and scientific report processing are outside this repository.

## Validation artifacts

`delivery.json` binds the HTML and specification hashes. `architecture.visual-check.json` records browser containment at four desktop dimensions; the accompanying light/dark screenshots show the checked artifact. [docs/validation.md](../validation.md) records the current software checks separately from physical RF validation.
