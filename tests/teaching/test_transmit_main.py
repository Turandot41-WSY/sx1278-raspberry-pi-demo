"""Exercise the exact main used by the debugger through the serial boundary."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import main_transmit

from host.radio import serial_protocol as p
from host.common.runtime_config import load_settings
from tests.teaching.debug_transmit_main import prepare_session


def session_for(tmp_path: Path, profile: str, *, fault=None):
    """Provide two explicit synthetic frames while keeping real radio settings.

    Direct call tree (static source order):
        session_for
        +-- source.write_bytes
        +-- bytes
        +-- range
        +-- reversed
        +-- load_settings
        +-- values.update
        +-- str
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- source.read_bytes
        +-- values.items
        +-- setting_lines.append
        +-- json.dumps
        +-- settings.write_text
        +-- <str literal>.join
        `-- prepare_session
    """
    source = tmp_path / "frames.bin"
    source.write_bytes(bytes(range(64)) + bytes(reversed(range(64))))
    values = load_settings("transmit")["arguments"]
    values.update(frames=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  profile=profile, count="all", start=0, timeout_ms=10, interval_ms=0)
    settings = tmp_path / "operator.toml"
    setting_lines = []
    for key, value in values.items():
        setting_lines.append(f"{key} = {json.dumps(value)}")
    settings.write_text("[arguments]\n" + "\n".join(setting_lines))
    return source, prepare_session(tmp_path / "session", settings, fault=fault)


@pytest.mark.parametrize("profile", ["LoRa", "FSK", "GFSK", "MSK", "GMSK", "OOK"])
def test_main_reads_config_and_sends_exact_frames(tmp_path, profile):
    """Require two real host transactions and synthetic-labelled evidence per profile.

    Direct call tree (static source order):
        test_main_reads_config_and_sends_exact_frames
        +-- session_for
        +-- patch
        +-- AssertionError
        +-- patch.object
        +-- session.run
        +-- entry.assert_called_once_with
        +-- str
        +-- loaded_frames.append
        +-- <bytes literal>.join
        +-- source.read_bytes
        +-- next
        +-- session.output.rglob
        +-- events_path.read_text
        +-- events_path.read_text(...).splitlines
        +-- events.append
        +-- json.loads
        `-- <BinOp expression>.read_bytes
    """
    source, session = session_for(tmp_path, profile)
    with (
        patch("serial.Serial", side_effect=AssertionError("physical port opened")),
        patch.object(main_transmit, "main", wraps=main_transmit.main) as entry,
    ):
        assert session.run() == 0
    entry.assert_called_once_with(["saved", "--settings", str(session.settings)])
    assert session.port.closed
    assert session.port.reset_count == 1
    assert session.responder.types == [p.MessageType.HELLO, p.MessageType.RESET_TO_STANDBY,
        p.MessageType.APPLY_PROFILE, p.MessageType.SET_PA,
        p.MessageType.LOAD_TX, p.MessageType.START_TX,
        p.MessageType.LOAD_TX, p.MessageType.START_TX]
    loaded_frames = []
    for item in session.responder.loaded:
        loaded_frames.append(item.frame)
    assert b"".join(loaded_frames) == source.read_bytes()
    events_path = next(session.output.rglob("events.jsonl"))
    events = []
    for line in events_path.read_text().splitlines():
        events.append(json.loads(line))
    for event in events:
        assert event["data_origin"] == "simulated_serial"
    assert events[0]["profile"] == profile
    assert events[-1]["status"] == "COMPLETED"
    assert events[-1]["tx_done"] == 2
    assert (events_path.parent / "input_frames.bin").read_bytes() == source.read_bytes()


def test_main_cli_override_reaches_profile_and_pa_commands(tmp_path):
    """Verify explicit settings reach actual protocol payloads, not only argparse.

    Direct call tree (static source order):
        test_main_cli_override_reaches_profile_and_pa_commands
        +-- session_for
        +-- session.run
        +-- commands.append
        +-- p.decode_wire
        +-- p.unpack_apply_profile
        `-- p.unpack_set_pa
    """
    _, session = session_for(tmp_path, "GFSK")
    assert session.run(["--profile", "OOK", "--pa-dbm", "17"]) == 0
    commands = []
    for wire in session.port.writes:
        commands.append(p.decode_wire(wire))
    for command in commands:
        if command.message_type == p.MessageType.APPLY_PROFILE:
            apply = command
            break
    else:
        raise StopIteration
    for command in commands:
        if command.message_type == p.MessageType.SET_PA:
            pa = command
            break
    else:
        raise StopIteration
    assert p.unpack_apply_profile(apply.payload).profile_code == p.ProfileCode.OOK
    assert p.unpack_set_pa(pa.payload).pa_command_dbm == 17


@pytest.mark.parametrize("fault,starts", [("identity", 0), ("readback", 0), ("frf", 0),
                                         ("start_timeout", 1), ("done_timeout", 1), ("wrong_done", 1)])
def test_main_stops_without_retry_and_closes_port(tmp_path, fault, starts):
    """Keep uncertain completion as incomplete and never transmit the next frame.

    Direct call tree (static source order):
        test_main_stops_without_retry_and_closes_port
        +-- session_for
        +-- session.run
        +-- session.responder.types.count
        +-- next
        +-- session.output.rglob
        +-- events_path.read_text
        +-- events_path.read_text(...).splitlines
        +-- events.append
        `-- json.loads
    """
    _, session = session_for(tmp_path, "GFSK", fault=fault)
    assert session.run() == 1
    assert session.port.closed
    assert session.responder.types.count(p.MessageType.START_TX) == starts
    events_path = next(session.output.rglob("events.jsonl"))
    events = []
    for line in events_path.read_text().splitlines():
        events.append(json.loads(line))
    assert events[-1]["status"] == "INCOMPLETE"
    assert events[-1]["tx_done"] == 0
    assert events[-1]["retry_performed"] is False
