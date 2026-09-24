"""Receive antenna packets on macOS or Windows and preserve the local log."""

from host.cli.dispatch import select_action
from host.cli import receive_saved


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
