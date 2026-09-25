"""Run a finite number of production receive windows on the connected receiver."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Call the production receiver with an explicit finite window count.

    Processing flow:
        Read the receiver settings path and window limit -> reject an unbounded run
        -> capture packets and timeouts through the production receiver.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=ROOT / "receiver/config.toml",
                        help="Receiver TOML file; [listen] supplies the device, manifest and timing")
    parser.add_argument("--max-windows", type=int, required=True,
                        help="Completed receive windows, from 1 through 4294967296; example: 6")
    options = parser.parse_args(arguments)
    if not 1 <= options.max_windows <= 0x100000000:
        parser.error("max-windows must be from 1 through 4294967296")

    from receiver.listen import run

    command = ["--settings", str(options.settings),
               "--max-windows", str(options.max_windows)]
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
