"""Acquire and freeze orbit data for independent antenna transmission."""

from host.cli.dispatch import select_action
from host.cli import acquire


def main(arguments=None) -> int:
    """Run the dataset acquisition action selected in the operator configuration."""
    action, remaining = select_action(arguments, "main_dataset", ("acquire",))
    return acquire.run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
