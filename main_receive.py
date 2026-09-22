"""Receive antenna packets on Mac or Windows and display the local log."""

from host.cli.dispatch import select_action
from host.cli import receive_saved, receive_display


def main(arguments=None) -> int:
    """Select independent radio reception or display of an existing local log.

    Processing flow:
        Read action -> capture from local Nano or read existing logs
        -> preserve received bytes -> release resources on exit.
    """
    action, remaining = select_action(arguments, "main_receive", ("listen", "display"))
    if action == "display":
        return receive_display.run(remaining)
    return receive_saved.run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
