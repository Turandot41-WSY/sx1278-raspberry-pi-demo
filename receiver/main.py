"""Receive antenna packets on macOS or Windows and preserve the local log."""

import sys
from pathlib import Path

# Direct execution must find sibling packages independently of the working directory.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firmware.host.dispatch import select_action
from receiver import listen as receive_saved


def main(arguments=None) -> int:
    """Run independent radio reception using the local Nano.

    Processing flow:
        Read listen settings -> verify and configure the Nano
        -> capture packet bytes -> close UART and preserve evidence.
    """
    action, remaining = select_action(arguments, "main_receive", ("listen",))
    return receive_saved.run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
