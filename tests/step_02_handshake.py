"""Check the configured Nano bootloader and save its reported device signature."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Run the production bootloader handshake for the configured local board.

    Processing flow:
        Read board settings -> apply an optional diagnostic baud override
        -> preview the command or check the bootloader signature.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path,
                        default=ROOT / "firmware/config/internal/board_control.toml",
                        help="Board maintenance TOML file containing device and board_config")
    parser.add_argument("--baud", type=int, choices=(57600, 115200),
                        help="Optional bootloader handshake rate in baud; upload settings stay in the board file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the validated command before opening the port")
    options = parser.parse_args(arguments)

    from firmware.tools.board_control import run

    command = ["--settings", str(options.settings), "--action", "handshake"]
    if options.baud is not None:
        command.extend(["--baud", str(options.baud)])
    if options.dry_run:
        command.append("--dry-run")
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
