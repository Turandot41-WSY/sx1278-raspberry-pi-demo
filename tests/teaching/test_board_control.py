"""Verify board command plans without opening a physical port or flashing a Nano."""

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest


def board_settings(tmp_path, fqbn="atmega328old") -> dict[str, Any]:
    """Create explicit synthetic tool paths and one operator board configuration.

    Direct call tree (static source order):
        board_settings
        +-- board.write_text
        +-- tool.write_text
        +-- dict
        `-- str
    """
    board = tmp_path / "board.toml"
    board.write_text('fqbn = "arduino:avr:nano:cpu=' + fqbn + '"\n', encoding="utf-8")
    tool = tmp_path / "tool with spaces"
    tool.write_text("synthetic executable placeholder", encoding="utf-8")
    return dict(action="handshake", device="COM3", board_config=str(board),
                build_dir=str(tmp_path / "build"), output=str(tmp_path / "logs"),
                handshake_baud=0, command_timeout_seconds=120,
                arduino_data_dir="", tools=dict(arduino_cli=str(tool), avrdude=str(tool),
                avrdude_config=str(tool), avr_size=str(tool)))


@pytest.mark.parametrize("fqbn,baud", [("atmega328old", "57600"), ("atmega328", "115200")])
def test_handshake_matches_board_and_never_writes_flash(tmp_path, fqbn, baud):
    """Build a signature-check command with the selected bootloader rate and no writes.

    Direct call tree (static source order):
        test_handshake_matches_board_and_never_writes_flash
        +-- board_settings
        +-- make_plan
        +-- command.index
        `-- int
    """
    from firmware.tools.board_control import make_plan
    settings = board_settings(tmp_path, fqbn)
    plan = make_plan(settings)
    command = plan["command"]
    assert command[command.index("-b") + 1] == baud
    assert command[command.index("-P") + 1] == "COM3"
    assert "-n" in command and "-D" in command and "-v" in command
    assert "-U" not in command and "-e" not in command and "-F" not in command
    assert plan["upload_baud"] == int(baud)


def test_diagnostic_baud_override_does_not_modify_board(tmp_path):
    """Try another handshake speed while preserving the operator's build file bytes.

    Direct call tree (static source order):
        test_diagnostic_baud_override_does_not_modify_board
        +-- board_settings
        +-- Path
        +-- board.read_bytes
        `-- make_plan
    """
    from firmware.tools.board_control import make_plan
    settings = board_settings(tmp_path)
    board = Path(settings["board_config"])
    before = board.read_bytes()
    plan = make_plan(settings, baud_override=115200)
    assert plan["handshake_baud"] == 115200
    assert board.read_bytes() == before


@pytest.mark.parametrize("bad_field,bad_value", [("device", ""), ("handshake_baud", 9600)])
def test_handshake_rejects_missing_port_or_wrong_speed(tmp_path, bad_field, bad_value):
    """Reject invalid settings before any subprocess can open a physical device.

    Direct call tree (static source order):
        test_handshake_rejects_missing_port_or_wrong_speed
        +-- board_settings
        +-- pytest.raises
        `-- make_plan
    """
    from firmware.tools.board_control import make_plan
    settings = board_settings(tmp_path)
    settings[bad_field] = bad_value
    with pytest.raises(ValueError):
        make_plan(settings)


def test_upload_requires_current_verified_artifact(tmp_path):
    """Reject stale build configuration and changed HEX bytes before an upload.

    Direct call tree (static source order):
        test_upload_requires_current_verified_artifact
        +-- board_settings
        +-- Path
        +-- artifacts.mkdir
        +-- sketch.mkdir
        +-- hex_path.write_bytes
        +-- dict
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- board.read_bytes
        +-- hex_path.read_bytes
        +-- str
        +-- sketch.resolve
        +-- <BinOp expression>.write_text
        +-- json.dumps
        +-- make_plan
        +-- pytest.raises
        `-- board.write_bytes
    """
    from firmware.tools.board_control import make_plan
    settings = board_settings(tmp_path)
    build = Path(settings["build_dir"])
    artifacts = build / "artifacts"
    artifacts.mkdir(parents=True)
    sketch = build / "source" / "endpoint"
    sketch.mkdir(parents=True)
    hex_path = artifacts / "endpoint.ino.hex"
    hex_path.write_bytes(b"synthetic HEX bytes")
    board = Path(settings["board_config"])
    manifest = dict(compiled=True, board_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
                    hex_sha256=hashlib.sha256(hex_path.read_bytes()).hexdigest(),
                    configuration=dict(fqbn="arduino:avr:nano:cpu=atmega328old"),
                    sketch=str(sketch.resolve()))
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    plan = make_plan(settings, action="upload")
    assert "--verify" in plan["command"]
    assert "upload" in plan["command"]
    hex_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="HEX"):
        make_plan(settings, action="upload")
    hex_path.write_bytes(b"synthetic HEX bytes")
    board.write_bytes(board.read_bytes() + b"# changed comment\n")
    with pytest.raises(ValueError, match="configuration"):
        make_plan(settings, action="upload")


def test_execute_records_signature_and_uses_argv(tmp_path, monkeypatch):
    """Capture verified handshake output with shell-free arguments and exact evidence.

    Direct call tree (static source order):
        test_execute_records_signature_and_uses_argv
        +-- board_settings
        +-- board_control.make_plan
        +-- monkeypatch.setattr
        +-- board_control.execute_plan
        +-- calls[...][...].get
        +-- next
        +-- Path
        +-- Path(...).rglob
        +-- json.loads
        `-- evidence_path.read_text
    """
    from firmware.tools import board_control
    settings = board_settings(tmp_path)
    plan = board_control.make_plan(settings)
    calls = []

    def command_result(argv, **kwargs):
        """Return a labelled synthetic signature result without running a tool.

        Direct call tree (static source order):
            command_result
            +-- calls.append
            `-- subprocess.CompletedProcess
        """
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "Device signature = 1E 95 0F\n")

    monkeypatch.setattr(board_control.subprocess, "run", command_result)
    assert board_control.execute_plan(plan, settings) == 0
    assert calls[0][0] == plan["command"]
    assert calls[0][1].get("shell", False) is False
    evidence_path = next(Path(settings["output"]).rglob("result.json"))
    result = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert result["signature_verified"] is True
    assert result["flash_written"] is False


def test_zero_exit_without_signature_is_not_handshake_success(tmp_path, monkeypatch):
    """Reject a tool result that contains no verified signature despite zero exit status.

    Direct call tree (static source order):
        test_zero_exit_without_signature_is_not_handshake_success
        +-- board_settings
        +-- board_control.make_plan
        +-- monkeypatch.setattr
        `-- board_control.execute_plan
    """
    from firmware.tools import board_control
    settings = board_settings(tmp_path)
    plan = board_control.make_plan(settings)

    def no_signature(argv, **kwargs):
        """Return synthetic empty success output for the missing-evidence test.

        Direct call tree (static source order):
            no_signature
            `-- subprocess.CompletedProcess
        """
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(board_control.subprocess, "run", no_signature)
    assert board_control.execute_plan(plan, settings) == 1


def test_windows_tool_discovery_uses_local_app_data(tmp_path, monkeypatch):
    """Locate Windows executable suffixes and Arduino package paths without hardware.

    Direct call tree (static source order):
        test_windows_tool_discovery_uses_local_app_data
        +-- monkeypatch.setattr
        +-- monkeypatch.setenv
        +-- str
        +-- avrdude.parent.mkdir
        +-- avrdude.write_text
        `-- board_control.find_tool
    """
    from firmware.tools import board_control
    monkeypatch.setattr(board_control.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    avrdude = tmp_path / "Arduino15/packages/arduino/tools/avrdude/8.0.0-arduino1/bin/avrdude.exe"
    avrdude.parent.mkdir(parents=True)
    avrdude.write_text("synthetic", encoding="utf-8")
    assert board_control.find_tool({}, "avrdude") == str(avrdude)


def test_preview_never_invokes_subprocess(tmp_path, monkeypatch):
    """Preview a configured action without running even the port-listing subprocess.

    Direct call tree (static source order):
        test_preview_never_invokes_subprocess
        +-- settings_path.write_text
        +-- monkeypatch.setattr
        +-- board_control.run
        `-- str
    """
    from firmware.tools import board_control
    settings_path = tmp_path / "preview.toml"
    settings_path.write_text('action="ports"\n', encoding="utf-8")

    def unexpected_command(*args, **kwargs):
        """Reject every external invocation in the preview-only test.

        Direct call tree (static source order):
            unexpected_command
            `-- AssertionError
        """
        raise AssertionError("dry-run invoked a subprocess")

    monkeypatch.setattr(board_control.subprocess, "run", unexpected_command)
    assert board_control.run(["--settings", str(settings_path), "--dry-run"]) == 0


def test_upload_timeout_keeps_partial_output_and_unknown_flash_state(tmp_path, monkeypatch):
    """Preserve interrupted tool output without claiming that Flash stayed unchanged.

    Direct call tree (static source order):
        test_upload_timeout_keeps_partial_output_and_unknown_flash_state
        +-- board_settings
        +-- dict
        +-- monkeypatch.setattr
        +-- board_control.execute_plan
        +-- next
        +-- Path
        +-- Path(...).rglob
        +-- json.loads
        `-- evidence_path.read_text
    """
    from firmware.tools import board_control
    settings = board_settings(tmp_path)
    plan = dict(action="upload", command=["synthetic-upload"])

    def timed_out(argv, **kwargs):
        """Return a synthetic timeout after a possible partial Flash write.

        Direct call tree (static source order):
            timed_out
            `-- subprocess.TimeoutExpired
        """
        raise subprocess.TimeoutExpired(argv, 120, output=b"Writing", stderr=b"partial")

    monkeypatch.setattr(board_control.subprocess, "run", timed_out)
    assert board_control.execute_plan(plan, settings) == 1
    evidence_path = next(Path(settings["output"]).rglob("result.json"))
    result = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert result["flash_written"] is None
    assert result["stdout"] == "Writing"
    assert result["stderr"] == "partial"


def test_build_reuses_production_builder_and_configured_paths(tmp_path):
    """Delegate compilation to the existing production builder using explicit arguments.

    Direct call tree (static source order):
        test_build_reuses_production_builder_and_configured_paths
        +-- board_settings
        +-- make_plan
        +-- Path
        `-- command.index
    """
    from firmware.tools.board_control import make_plan
    settings = board_settings(tmp_path)
    plan = make_plan(settings, action="build")
    command = plan["command"]
    assert Path(command[1]).name == "build_single_endpoint.py"
    assert command[command.index("--config") + 1] == settings["board_config"]
    assert command[command.index("--arduino-cli") + 1] == settings["tools"]["arduino_cli"]
