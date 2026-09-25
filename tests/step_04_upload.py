"""Upload the validated local firmware build and request Flash verification."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Run the production upload after its board, manifest and HEX checks pass.

    Processing flow:
        Read board settings -> validate the local build identity
        -> preview or upload firmware with verification enabled.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path,
                        default=ROOT / "firmware/config/internal/board_control.toml",
                        help="Board maintenance TOML file containing device, board_config and build_dir")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate upload inputs and print the command before writing Flash")
    options = parser.parse_args(arguments)

    from firmware.tools.board_control import run

    command = ["--settings", str(options.settings), "--action", "upload"]
    if options.dry_run:
        command.append("--dry-run")
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
