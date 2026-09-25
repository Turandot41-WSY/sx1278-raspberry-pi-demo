"""Send saved or freshly acquired orbit frames from Raspberry Pi 5 or Windows."""

import sys
from pathlib import Path

# Direct execution must find sibling packages independently of the working directory.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firmware.host.dispatch import select_action
from transmit import antenna as transmit_antenna, send as transmit_saved


def main(arguments=None) -> int:
    """Run independent antenna transmission with explicit operator confirmation.

    Processing flow:
        Select antenna settings -> prepare frames -> confirm sending
        -> verify local Nano -> transmit and record completion.
    """
    action, remaining = select_action(arguments, "main_transmit", ("antenna", "saved"))
    if action == "saved":
        return transmit_saved.run(remaining)
    return transmit_antenna.run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
