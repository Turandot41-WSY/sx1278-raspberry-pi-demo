"""Run explicit Nano port, bootloader, build and verified-upload operations.

Call tree:
run() - read operator settings and select one operation
+-- make_plan() - resolve tools and validate board/build identity
|   +-- find_tool() - locate the configured executable or bundled tool
|   `-- validate_upload() - bind the HEX file to the selected board configuration
`-- execute_plan() - run one command and save its output and exit status

This utility does not start an RF experiment. Handshake can reset the Nano;
close receive/transmit programs before opening the same port with this tool.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ACTIONS = ("ports", "handshake", "build", "upload")


def project_path(value: str) -> Path:
    """Resolve an operator path relative to the repository root on this computer.

    Processing flow:
        Expand home directory -> resolve relative project path -> absolute path.

    Direct call tree (static source order):
        project_path
        +-- Path
        +-- Path(...).expanduser
        +-- path.is_absolute
        `-- path.resolve
    """
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def arduino_data_path(settings: dict) -> Path:
    """Select the configured Arduino data directory or its platform default.

    Processing flow:
        Explicit directory -> platform default -> tool package parent directory.

    Direct call tree (static source order):
        arduino_data_path
        +-- settings.get
        +-- project_path
        +-- os.environ.get
        +-- ValueError
        +-- Path
        `-- Path.home
    """
    configured = settings.get("arduino_data_dir", "")
    if configured:
        return project_path(configured)
    if sys.platform == "win32":
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data:
            raise ValueError("LOCALAPPDATA unavailable; set arduino_data_dir")
        return Path(local_data) / "Arduino15"
    if sys.platform == "darwin":
        return Path.home() / "Library/Arduino15"
    return Path.home() / ".arduino15"


def find_tool(settings: dict, name: str) -> str:
    """Find one tool using explicit settings, PATH or the tested Arduino package layout.

    Processing flow:
        Explicit path -> PATH for CLI -> platform package candidates
        -> existing file or actionable missing-tool error.

    Direct call tree (static source order):
        find_tool
        +-- settings.get
        +-- settings.get(...).get
        +-- project_path
        +-- path.is_file
        +-- ValueError
        +-- str
        +-- shutil.which
        +-- candidates.append
        +-- Path
        +-- os.environ.get
        `-- arduino_data_path
    """
    configured = settings.get("tools", {}).get(name, "")
    if configured:
        path = project_path(configured)
        if not path.is_file():
            raise ValueError(f"tools.{name} is not a file: {path}")
        return str(path)
    suffix = ""
    if sys.platform == "win32":
        suffix = ".exe"
    candidates = []
    if name == "arduino_cli":
        on_path = shutil.which("arduino-cli")
        if on_path:
            return on_path
        if sys.platform == "darwin":
            candidates.append(Path("/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"))
        if sys.platform == "win32":
            for variable in ("LOCALAPPDATA", "ProgramFiles"):
                base = os.environ.get(variable)
                if base:
                    base_path = Path(base)
                    if variable == "LOCALAPPDATA":
                        base_path = base_path / "Programs"
                    candidates.append(base_path / "Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe")
    else:
        packages = arduino_data_path(settings) / "packages/arduino/tools"
        # These are the installed tool versions used with Arduino AVR Boards 1.8.8
        # in this project; a different installation can supply explicit paths.
        if name == "avrdude":
            candidates.append(packages / "avrdude/8.0.0-arduino1/bin" / ("avrdude" + suffix))
        elif name == "avrdude_config":
            candidates.append(packages / "avrdude/8.0.0-arduino1/etc/avrdude.conf")
        elif name == "avr_size":
            candidates.append(packages / "avr-gcc/7.3.0-atmel3.6.1-arduino7/bin" / ("avr-size" + suffix))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise ValueError(f"Cannot find {name}; set tools.{name} in board_control.toml")


def upload_baud_for(fqbn: str) -> int:
    """Return the Nano bootloader upload rate for the selected board menu option.

    References:
        ArduinoCore-avr 1.8.8, boards.txt, nano.menu.cpu.atmega328.upload.speed
        and nano.menu.cpu.atmega328old.upload.speed; both build.mcu=atmega328p.
        https://github.com/arduino/ArduinoCore-avr/blob/1.8.8/boards.txt#L214-L242

    Processing flow:
        Nano FQBN -> selected bootloader speed -> reject unsupported target.

    Direct call tree (static source order):
        upload_baud_for
        `-- ValueError
    """
    if fqbn == "arduino:avr:nano:cpu=atmega328old":
        return 57600
    if fqbn == "arduino:avr:nano:cpu=atmega328":
        return 115200
    raise ValueError("Board fqbn must select Nano atmega328 or atmega328old")


def validate_upload(build: Path, board_path: Path, board: dict) -> dict:
    """Require a compiled local artifact that matches the current board file and HEX hash.

    Processing flow:
        Read build manifest -> compare configuration bytes and values
        -> verify HEX identity and local staged sketch -> upload inputs ready.

    Direct call tree (static source order):
        validate_upload
        +-- json.loads
        +-- <BinOp expression>.read_text
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- board_path.read_bytes
        +-- manifest.get
        +-- ValueError
        +-- hex_path.read_bytes
        +-- sketch.is_dir
        +-- Path
        +-- Path(...).resolve
        `-- sketch.resolve
    """
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    board_hash = hashlib.sha256(board_path.read_bytes()).hexdigest()
    if manifest.get("compiled") is not True:
        raise ValueError("Firmware build is incomplete; run build before upload")
    if manifest.get("board_sha256") != board_hash:
        raise ValueError("Board configuration changed; rebuild before upload")
    if manifest.get("configuration") != board:
        raise ValueError("Board configuration changed; rebuild before upload")
    hex_path = build / "artifacts/endpoint.ino.hex"
    hex_hash = hashlib.sha256(hex_path.read_bytes()).hexdigest()
    if manifest.get("hex_sha256") != hex_hash:
        raise ValueError("HEX hash differs from compiled manifest; rebuild before upload")
    sketch = build / "source/endpoint"
    if not sketch.is_dir():
        raise ValueError("Build belongs to another path/computer; rebuild locally")
    if Path(manifest.get("sketch", "")).resolve() != sketch.resolve():
        raise ValueError("Build belongs to another path/computer; rebuild locally")
    return manifest


def make_plan(settings: dict, action=None, baud_override=None) -> dict:
    """Construct one explicit command without opening a serial port or invoking tools.

    References:
        AVRDUDE 8.0 manual, section 2.1 Option Descriptions, -p/-c/-P/-b,
        -n (no memory writes), -D (no automatic erase), and -v (verbose).
        https://avrdudes.github.io/avrdude/8.0/avrdude_4.html

    Processing flow:
        Selected action -> board identity and tool paths -> validate action inputs
        -> signature check, production build or verified upload command.

    Direct call tree (static source order):
        make_plan
        +-- ValueError
        +-- dict
        +-- project_path
        +-- tomllib.loads
        +-- board_path.read_text
        +-- upload_baud_for
        +-- plan.update
        +-- str
        +-- settings[...].strip
        +-- type
        +-- find_tool
        `-- validate_upload
    """
    if action is None:
        action = settings["action"]
    if action not in ACTIONS:
        raise ValueError("Unknown board action")
    plan: dict[str, Any] = dict(action=action)
    if action == "ports":
        plan["command"] = [sys.executable, "-m", "serial.tools.list_ports", "-v"]
        return plan
    board_path = project_path(settings["board_config"])
    board = tomllib.loads(board_path.read_text(encoding="utf-8"))
    fqbn = board["fqbn"]
    upload_baud = upload_baud_for(fqbn)
    plan.update(board_config=str(board_path), fqbn=fqbn, upload_baud=upload_baud)
    build = project_path(settings["build_dir"])
    device = ""
    if action in ("handshake", "upload"):
        device = settings["device"].strip()
        if not device:
            raise ValueError("Set device to this board's COM port or /dev/cu.* path")
        plan["device"] = device
    if action == "handshake":
        baud = settings["handshake_baud"]
        if baud_override is not None:
            baud = baud_override
        if baud == 0:
            baud = upload_baud
        if type(baud) is not int:
            raise ValueError("handshake_baud must be 0, 57600 or 115200")
        if baud not in (57600, 115200):
            raise ValueError("handshake_baud must be 0, 57600 or 115200")
        plan["handshake_baud"] = baud
        plan["command"] = [find_tool(settings, "avrdude"),
                           "-C", find_tool(settings, "avrdude_config"),
                           "-p", "atmega328p", "-c", "arduino",
                           "-P", device, "-b", str(baud), "-n", "-D", "-v"]
    elif action == "build":
        plan["command"] = [sys.executable, str(ROOT / "firmware/tools/build_single_endpoint.py"),
                           "--config", str(board_path), "--build", str(build),
                           "--arduino-cli", find_tool(settings, "arduino_cli"),
                           "--avr-size", find_tool(settings, "avr_size")]
    elif action == "upload":
        manifest = validate_upload(build, board_path, board)
        plan["command"] = [find_tool(settings, "arduino_cli"), "upload",
                           "--fqbn", fqbn, "--port", device,
                           "--input-dir", str(build / "artifacts"),
                           "--verify", "--verbose", manifest["sketch"]]
        plan["hex_sha256"] = manifest["hex_sha256"]
    return plan


def execute_plan(plan: dict, settings: dict) -> int:
    """Run one planned command and save output, tool status and handshake evidence.

    Processing flow:
        Create evidence directory -> execute argument list with a bounded wait
        -> preserve stdout/stderr -> check signature for handshake -> save result.

    Direct call tree (static source order):
        execute_plan
        +-- type
        +-- ValueError
        +-- datetime.now
        +-- datetime.now(...).strftime
        +-- project_path
        +-- evidence.mkdir
        +-- dict
        +-- result.update
        +-- print
        +-- json.dumps
        +-- subprocess.run
        +-- re.search
        +-- str
        +-- isinstance
        +-- getattr
        +-- partial.decode
        +-- <BinOp expression>.write_text
        `-- result.get
    """
    timeout = settings["command_timeout_seconds"]
    if type(timeout) is not int:
        raise ValueError("command_timeout_seconds must be a positive integer")
    if timeout <= 0:
        raise ValueError("command_timeout_seconds must be a positive integer")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    evidence = project_path(settings["output"]) / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    result = dict(plan)
    result.update(signature_verified=False, flash_written=False, tool_exit_code=None)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    print(f"Evidence: {evidence}", flush=True)
    try:
        completed = subprocess.run(plan["command"], cwd=ROOT, shell=False,
                                   capture_output=True, text=True, errors="replace", timeout=timeout)
        result.update(stdout=completed.stdout, stderr=completed.stderr,
                      tool_exit_code=completed.returncode)
        exit_status = 0
        if completed.returncode != 0:
            exit_status = 1
        if plan["action"] == "handshake":
            output = completed.stdout + "\n" + completed.stderr
            signature = re.search(r"Device signature\s*=\s*(?:0x)?1e\s*95\s*0f\b", output, re.IGNORECASE)
            if completed.returncode == 0:
                result["signature_verified"] = signature is not None
            if not result["signature_verified"]:
                exit_status = 1
        elif plan["action"] == "upload":
            if exit_status == 0:
                result["flash_written"] = True
    except (OSError, subprocess.TimeoutExpired) as error:
        # A failed or interrupted upload may have written some Flash. This record
        # does not claim an intact previous image when tool completion is unknown.
        result["error"] = str(error)
        if plan["action"] == "upload":
            result["flash_written"] = None
        exit_status = 1
        if isinstance(error, subprocess.TimeoutExpired):
            for name in ("stdout", "stderr"):
                partial = getattr(error, name)
                if partial is None:
                    partial = b""
                if isinstance(partial, bytes):
                    partial = partial.decode(errors="replace")
                result[name] = partial
    if plan["action"] == "upload":
        if exit_status != 0:
            result["flash_written"] = None
    result["exit_status"] = exit_status
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for field in ("stdout", "stderr", "error"):
        if result.get(field):
            print(result[field], flush=True)
    if plan["action"] == "handshake":
        print(f"Bootloader signature verified: {result['signature_verified']}; Flash write requested: False")
    return exit_status


def run(arguments=None) -> int:
    """Load the board settings and execute or preview the selected operation.

    Processing flow:
        Parse explicit action -> read TOML -> construct validated command
        -> preview without device access or execute and save evidence.

    Direct call tree (static source order):
        run
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parser.parse_args
        +-- tomllib.loads
        +-- args.settings.read_text
        +-- ValueError
        +-- make_plan
        +-- print
        +-- json.dumps
        `-- execute_plan
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=ROOT / "firmware/config/internal/board_control.toml")
    parser.add_argument("--action", choices=ACTIONS)
    parser.add_argument("--baud", type=int, choices=(57600, 115200))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(arguments)
    try:
        settings = tomllib.loads(args.settings.read_text(encoding="utf-8"))
        selected_action = args.action
        if selected_action is None:
            selected_action = settings["action"]
        if args.baud is not None:
            if selected_action != "handshake":
                raise ValueError("--baud only applies to handshake; upload uses board fqbn")
        plan = make_plan(settings, args.action, args.baud)
        if args.dry_run:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        return execute_plan(plan, settings)
    except (OSError, ValueError, KeyError) as error:
        print(f"Board operation stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
