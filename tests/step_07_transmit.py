"""Send an explicit finite number of saved frames through the production transmitter."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None) -> int:
    """Call the production transmitter with a finite frame count and saved input.

    Processing flow:
        Read the antenna settings and frame count -> require saved frames at fixed frequency
        -> prepare saved frames -> use the production confirmation and transmission flow.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=ROOT / "transmit/config.toml",
                        help="Transmitter TOML file; [antenna] supplies the port, manifest and saved data")
    parser.add_argument("--count", type=int, required=True,
                        help="Positive number of saved frames to send; example: 3")
    options = parser.parse_args(arguments)
    if options.count <= 0:
        parser.error("count must be a positive integer")

    from firmware.host.runtime_config import load_settings

    try:
        document = load_settings("main_transmit", options.settings)
        antenna = document["antenna"]
        fixed_saved_input = (
            antenna.get("data_source") == "saved"
            and antenna.get("saved_dataset", "") == ""
            and antenna.get("orbit_dataset", "") == ""
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(f"cannot read [antenna] settings: {error}")
    if not fixed_saved_input:
        parser.error(
            "step 07 requires saved frames at fixed frequency; run "
            "firmware/tools/configure_antenna.py with --role tx --doppler off, "
            "or set [antenna] data_source='saved', saved_dataset='' and orbit_dataset=''"
        )

    from transmit.send import run

    command = ["--settings", str(options.settings),
               "--data-source", "saved", "--count", str(options.count)]
    return run(command, section="antenna")


if __name__ == "__main__":
    raise SystemExit(main())
