"""Launch the real main_transmit.main with an explicitly simulated serial port.

The default inputs and radio selection come from config/main_transmit.toml. The
launcher creates a separate teaching settings file, synthetic build identity,
and evidence directory; it never opens a physical serial device. All production
configuration, frame loading, wire encoding, response checks, and logs still run.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import main_transmit
from host.cli import transmit_saved
from host.radio.profile_truth import load_profile_truth
from host.common.runtime_config import PROJECT_ROOT, load_settings
from tests.fakes.fake_clock import FakeClock
from tests.fakes.transmit_endpoint import (
    SimulatedTransmitEvidence,
    TeachingBytePort,
    TransmitterReplies,
)


@dataclass
class TeachingSession:
    """Hold fixture settings and the observable serial boundary for one main run."""

    settings: Path
    output: Path
    responder: TransmitterReplies
    port: TeachingBytePort

    def run(self, arguments=None, *, debug=False) -> int:
        """Call the real main once with only hardware, time, and provenance adapted.

        Processing flow:
            Teaching settings -> bind in-memory serial and clock -> optional stop
            -> real main entry -> restore original production dependencies.

        Direct call tree (static source order):
            run
            +-- str
            +-- args.extend
            +-- print
            +-- patch
            +-- patch.object
            +-- breakpoint
            `-- main_transmit.main
        """
        args = ["saved", "--settings", str(self.settings)]
        if arguments is not None:
            args.extend(arguments)
        print("SIMULATED SERIAL: real Python main; no Nano firmware or RF execution.")
        print(f"Teaching settings: {self.settings}")
        with (
            patch("builtins.input", return_value="yes"),
            patch.object(transmit_saved, "open_nano_port", return_value=self.port),
            patch.object(transmit_saved, "SystemClock", FakeClock),
            patch.object(transmit_saved, "TransmitEvidence", SimulatedTransmitEvidence),
        ):
            if debug:
                # This stop stays in tests. One Step Into on the following call
                # enters main; production files contain no teaching breakpoints.
                breakpoint()
            result = main_transmit.main(args)
        return result


def prepare_session(directory: Path, settings_path: Path | None = None,
                    *, fault: str | None = None) -> TeachingSession:
    """Preserve chosen input settings and create a labelled synthetic endpoint.

            Processing flow:
                Read real operator settings -> create isolated teaching identity/output
                -> bind real profile tables to scripted replies -> return main launcher.

    Direct call tree (static source order):
        prepare_session
        +-- directory.resolve
        +-- directory.mkdir
        +-- load_settings
        +-- <BinOp expression>.write_bytes
        +-- selected.read_bytes
        +-- dict
        +-- load_profile_truth
        +-- TransmitterReplies
        +-- manifest.write_text
        +-- json.dumps
        +-- str
        +-- values.items
        +-- lines.append
        +-- settings.write_text
        +-- <str literal>.join
        +-- TeachingSession
        `-- TeachingBytePort
    """
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    selected = PROJECT_ROOT / "config/main_transmit.toml"
    if settings_path is not None:
        selected = settings_path
    document = load_settings("transmit", selected)
    (directory / "operator-settings.toml").write_bytes(selected.read_bytes())
    values = dict(document["arguments"])
    truth = load_profile_truth(PROJECT_ROOT / "config")
    responder = TransmitterReplies(truth, fault)
    manifest = directory / "synthetic-manifest.json"
    manifest.write_text(json.dumps({
        **responder.manifest,
        "compiled": True,  # Synthetic success fixture for main's build-record check.
        "data_origin": "simulated_serial",
        "note": "Synthetic identity; not a compiled or flashed hardware artifact.",
    }, indent=2) + "\n")
    values["port"] = "SIMULATED"
    values["manifest"] = str(manifest)
    output = directory / "runs"
    values["output"] = str(output)
    settings = directory / "transmit.toml"
    # These settings contain only the scalar argument types accepted by main.
    lines = ["# Teaching settings: simulated serial, not physical evidence.", "[arguments]"]
    for key, value in values.items():
        lines.append(f"{key} = {json.dumps(value)}")
    settings.write_text("\n".join(lines) + "\n")
    return TeachingSession(settings, output, responder, TeachingBytePort(responder))


if __name__ == "__main__":
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    session = prepare_session(PROJECT_ROOT / "tests/teaching/output" / stamp)
    raise SystemExit(session.run(sys.argv[1:], debug=os.environ.get("SAS2027_TEACHING_DEBUG") == "1"))
