"""Run independent antenna transmission from saved or newly acquired data."""

from host.cli import transmit_saved


def run(arguments=None):
    """Select the antenna settings and reuse validated serial transmission.

    Direct call tree (static source order):
        run
        `-- transmit_saved.run
    """
    return transmit_saved.run(arguments, section="antenna")
