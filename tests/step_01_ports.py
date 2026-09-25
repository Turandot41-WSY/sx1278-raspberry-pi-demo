"""List the USB serial ports available on this computer."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Run the production port listing and save its command evidence.

    Processing flow:
        Read optional settings path -> select the ports action -> list local ports.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path,
                        default=ROOT / "firmware/config/internal/board_control.toml",
                        help="Board maintenance TOML file; paths inside it use the project root")
    options = parser.parse_args(arguments)

    from firmware.tools.board_control import run

    command = ["--settings", str(options.settings), "--action", "ports"]
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
