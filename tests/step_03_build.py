"""Compile the production firmware for the board selected in the maintenance settings."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Run the production firmware build with the configured board and output path.

    Processing flow:
        Read board settings -> select the build action -> preview or compile firmware.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path,
                        default=ROOT / "firmware/config/internal/board_control.toml",
                        help="Board maintenance TOML file containing board_config and build_dir")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the build command before compiling firmware")
    options = parser.parse_args(arguments)

    from firmware.tools.board_control import run

    command = ["--settings", str(options.settings), "--action", "build"]
    if options.dry_run:
        command.append("--dry-run")
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
