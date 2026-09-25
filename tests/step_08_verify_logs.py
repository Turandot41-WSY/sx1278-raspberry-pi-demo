"""Compare the saved transmitter and receiver logs from one hardware check."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Compare physical acquisition logs using the production reception verifier.

    Processing flow:
        Select the two saved event logs -> call the production verifier
        -> print the payload comparison and return its status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tx", type=Path, required=True,
                        help="Transmitter events.jsonl from the selected completed hardware run")
    parser.add_argument("--rx", type=Path, required=True,
                        help="Receiver events.jsonl captured during that hardware run")
    options = parser.parse_args(arguments)

    from receiver.verify import main as verify_logs

    command = ["--tx", str(options.tx), "--rx", str(options.rx)]
    return verify_logs(command)


if __name__ == "__main__":
    raise SystemExit(main())
