# Frozen orbit replay input

This archive provides 2,072 frames across five propagated GOMX-1 passes. It is an offline replay of calculated orbit telemetry, not a recording received from the satellite and not a measurement from the radio demo.

`orbit/source/` retains CelesTrak OMM and IERS Earth orientation inputs. `provenance.json` records retrieval, model and hashes; `orbit_manifest.json` binds all derived files. The sender validates the archive and rebuilds the 64-byte frames. `frames.bin` retains the corresponding reference bytes.

Sources: [CelesTrak GP data](https://celestrak.org/NORAD/documentation/gp-data-formats.php) and [IERS Earth orientation data](https://datacenter.iers.org/data/9/finals2000A.all). Source data remain attributed to their providers. The README documents optional fresh acquisition separately from this frozen replay.
