# Local receiver display

[Receiver guide](../README.md#browser-demonstration)

`receiver/main.py` starts this service by default. It serves the approved English
page from `web/`, reads the current receiver's `events.jsonl`, and validates and
decodes packets using `dataset/`. The page shows only received valid frames.

| File | Responsibility |
|---|---|
| `receiver.py` | Read complete JSONL records, validate frames, derive geographic positions and associate exact bytes with reference passes |
| `server.py` | Serve local assets and telemetry on `127.0.0.1`; close the HTTP worker when reception ends |
| `web/approved-scene.json` | Approved layout, labels, logos and plot positions |
| `web/editor.mjs` | Render the approved page and poll local telemetry |
| `web/presentation.mjs` | Start an empty presentation on each page load without changing capture logs |
| `web/assets/` | Local logos, Natural Earth map and display artwork |

The web requests use Python's standard library. The existing environment already
includes Astropy for ECEF conversion. No additional environment or frontend build
is required. Radio commands remain in `receiver/listen.py` and `receiver/radio.py`;
the display reads logs and never owns the serial port.

Refresh before the next transmission and wait for **Ready for new transmission**.
Only packets after the page's first successful snapshot appear. Counters and
tracks are scoped to the current page; the original log retains all batches.
See the receiver guide for port, reference dataset and terminal-only options.

The basemap uses [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/)
public domain country boundaries. IT:U and SPOK identity links are available in the
page source; the supplied laboratory artwork is preserved in the approved layout.
