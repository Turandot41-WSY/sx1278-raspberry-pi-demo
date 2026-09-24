# Demo verification record

Verified on 24 September 2026 using Python 3.12 in `sx1278-benchmark` on macOS ARM64. A clean clone of source revision `e844e94468b545f8ab684abd5eea718fd1bbe529` passed the 149 tests, both endpoint builds and full archived frame preparation. Record the exact public revision of your reproduction with `git rev-parse HEAD`.

## Current scope

The public demo contains local antenna transmission, reception, input preparation, Nano firmware, log comparison and architecture documentation. The current maintained radio/data/firmware sources were compared before this update. Their common implementations remain aligned; public entry points and configuration deliberately expose only the antenna workflows.

The documented pairs are Pi 5 → Mac, Pi 5 → Windows, Windows → Mac and Windows → Windows. Role configuration tests exercise all four device/identity combinations. These tests do not constitute execution on those operating systems or physical RF validation.

## Checks performed

| Check | Observed result | Scope |
|---|---|---|
| Python suite | 149 passed | Serial protocol, independent TX/RX, data validation, firmware staging, four platform role configurations and log comparison |
| Scope regression | Passed | Receiver exposes only `listen`; browser runtime/assets and display configuration are absent |
| Python dependencies | `pip check` passed | Existing pinned dependency snapshot; no new dependencies |
| Nano A and B builds | Both passed; each uses 19,826 bytes flash and 1,521 bytes static RAM | Clean clone; Arduino CLI 1.5.1 and AVR Boards 1.8.8 |
| Full archive preparation | 2,072 frames prepared, then cancelled before UART | Frozen inputs, frame reconstruction and frequency plan |
| CLI help | Six entry/tool help commands passed | Imports and argument parsing |
| Setup/README checks | 17 Bash blocks and 115 local Markdown links passed | Bash syntax and local destinations; PowerShell was not executed on Windows |
| Architecture validation | 9/9 showcase, no errors or warnings | Deterministic HTML/specification validation |
| Architecture browser | Passed at 1440×900, 1600×1000, 1920×1080 and 2048×1320 | Automated containment and screenshot evidence |
| Architecture review | 1440 light and 2048 dark screenshots inspected | Current TX/RX diagram, no operational display component |

The endpoint firmware and board configuration bytes are unchanged from the preceding verified release. Both were compiled again from the clean revision clone during this update. The 22 September release also resolved binary Python packages for Linux ARM64 and Windows x86-64; package availability is not a hardware or OS execution result.

No serial port was opened, no Nano was uploaded, and no RF was transmitted during this update. Run the [experiment checks](experiments/README.md) on your assemblies and retain the original logs. Actual USB permissions, bootloader, supply/wiring, radio register readback and received byte matches remain physical operator checks.
