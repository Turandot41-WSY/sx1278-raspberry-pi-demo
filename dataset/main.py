"""Acquire and freeze orbit data for independent antenna transmission."""

import sys
from pathlib import Path

# Direct execution must find sibling packages independently of the working directory.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firmware.host.dispatch import select_action
from dataset import acquire


def main(arguments=None) -> int:
    """Run the dataset acquisition action selected in the operator configuration."""
    action, remaining = select_action(arguments, "main_dataset", ("acquire",))
    return acquire.run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
