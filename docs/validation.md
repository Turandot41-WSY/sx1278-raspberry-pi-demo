# Public demo release verification

Verified on 22 September 2026 using Python 3.12 in `sx1278-benchmark` on macOS ARM64. Public source commit `a66b0d014293c16b2dd244bbb3d062b67f2e33eb` was cloned again from GitHub into an independent directory. That fresh clone passed all 143 tests, both Nano builds, and preparation of all 2,072 frames followed by cancellation before serial access. The documentation-only follow-up records these results. Use `git rev-parse HEAD` to save the revision of your own reproduction clone.

| Check | Observed result | Scope |
|---|---|---|
| Python test suite | 143 passed | Protocol, serial transport, frame preparation, firmware staging, display HTTP integration, exact reception comparison and configuration |
| Dependency installation and `pip check` | Passed | Installed snapshot in the development environment |
| Linux ARM64 / Python 3.12 wheel resolution | 12 packages resolved | Binary package availability; no Pi installation or execution implied |
| Windows x86-64 / Python 3.12 wheel resolution | 13 packages resolved, including colorama | Binary package availability; no Windows execution implied |
| Nano A compile | Passed; flash 19,826 bytes, static RAM 1,521 bytes | Arduino CLI 1.5.1, AVR Boards 1.8.8, old Nano bootloader target |
| Nano B compile | Passed; flash 19,826 bytes, static RAM 1,521 bytes | Same toolchain; separate endpoint identity and manifest |
| Full archive preparation | 2,072 frames prepared, then cancelled before sending | Offline archive validation, frame reconstruction and Doppler planning |
| CLI help | Seven entry/action help commands passed | Imports and argument parsing |
| README | Bash syntax and local links checked | PowerShell instructions reviewed but not executed on Windows |
| Architecture HTML | 9/9 showcase checks, no errors or warnings | Deterministic artifact validation; see its delivery receipt |
| Architecture browser | Containment passed at 1440×900, 1600×1000, 1920×1080 and 2048×1320 | Automated Chrome checks; light/dark screenshots retained |
| Architecture visual review | Light 1440×900 and dark 2048×1320 screenshots inspected | Labels, routes and cards visible; one layout correction round |
| Receiver page | HTTP assets, read-only API, decoded synthetic fixture and empty state passed | Synthetic fixture explicitly labeled; no physical reception inferred |
| Receiver browser | Empty session shows zero packets and no fabricated rows | Headless browser; temporary session and processes closed |

The build tool stages production firmware under the ignored `firmware/build/` directory. Compilation did not upload firmware, open a serial port, or radiate RF. The receiver browser check used an empty local log root. Its HTTP server has been stopped.

The operator must still verify the actual Pi's USB permissions, bootloader handshake, successful flash verification, radio register readback and matching physical received bytes. Those results should be saved with the run's exact code revision, TX log, RX log and configuration snapshots. They are not claimed by this software release.

The archive is calculated orbital telemetry from public source data. Tests and archive reconstruction do not establish an on-air satellite measurement, calibrated RF power, or a packet error rate experiment.
