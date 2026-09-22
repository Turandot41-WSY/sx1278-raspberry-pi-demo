"""Send saved or freshly acquired orbit frames from the Raspberry Pi 5."""

from host.cli.dispatch import select_action
from host.cli import transmit_antenna, transmit_saved


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
