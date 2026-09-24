"""Load operator settings and apply explicit command-line overrides."""

import argparse
import copy
import sys
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Each command name identifies a section in its owning main configuration.
# These names are internal lookup keys; they do not create additional TOML files.
COMMAND_SETTINGS = {
    "dataset": ("main_dataset", "acquire"),
    "transmit": ("main_transmit", "saved"),
    "receive": ("main_receive", "listen"),
}

ENTRY_TABLES = {
    "main_dataset": {"action", "acquire", "orbit_model"},
    "main_transmit": {"action", "antenna", "saved"},
    "main_receive": {"action", "listen"},
}


def settings_path(name: str) -> Path:
    """Locate the maintained TOML file for an entry, command or internal tool.

    Processing flow:
        Logical configuration name -> owning entry or support directory -> file path.

    Direct call tree (static source order):
        settings_path
        `-- name.startswith
    """
    if name in COMMAND_SETTINGS:
        entry_name, section_name = COMMAND_SETTINGS[name]
        return PROJECT_ROOT / "config" / (entry_name + ".toml")
    if name == "orbit_model":
        return PROJECT_ROOT / "config" / "main_dataset.toml"
    if name.startswith("main_"):
        return PROJECT_ROOT / "config" / (name + ".toml")
    if name == "debug":
        return PROJECT_ROOT / "tests" / "settings" / "debug.toml"
    return PROJECT_ROOT / "config" / "internal" / (name + ".toml")


def load_settings(name: str, path: str | Path | None = None) -> dict[str, Any]:
    """Read a command's parameter table or an internal settings document.

    Processing flow:
        Resolve the owning file -> read TOML -> select the requested parameter table.

    Explicit files with [arguments] remain supported for isolated tests and tools.
    A main file contains named action tables; this function returns only the table
    requested by its caller, so an unused action does not require hardware inputs.

    Direct call tree (static source order):
        load_settings
        +-- settings_path
        +-- Path
        +-- Path(...).expanduser
        +-- Path(...).expanduser(...).resolve
        +-- selected.open
        +-- tomllib.load
        +-- set
        +-- <str literal>.join
        +-- sorted
        `-- ValueError
    """
    selected = settings_path(name)
    if path is not None:
        selected = Path(path).expanduser().resolve()
    with selected.open("rb") as stream:
        document = tomllib.load(stream)
    entry_name = name
    if name in COMMAND_SETTINGS:
        entry_name, section_name = COMMAND_SETTINGS[name]
    if name == "orbit_model":
        entry_name = "main_dataset"
    if entry_name in ENTRY_TABLES and set(document) != {"arguments"}:
        allowed_tables = ENTRY_TABLES[entry_name]
        unknown_tables = set(document) - allowed_tables
        if unknown_tables:
            unknown_names = ", ".join(sorted(unknown_tables))
            raise ValueError(f"{selected}: unknown configuration table(s): {unknown_names}")
    if name == "orbit_model":
        return document["orbit_model"]
    if name in COMMAND_SETTINGS:
        entry_name, section_name = COMMAND_SETTINGS[name]
        # Standalone overrides are useful in automated tests of one command.
        if set(document) == {"arguments"}:
            return document
        if section_name not in document:
            raise ValueError(f"{selected}: missing [{section_name}] table")
        return {"arguments": document[section_name]}
    return document


def configured_path(value: str, *, timestamp: str = "") -> Path:
    """Resolve a configured path against the project root and expand its UTC token.

    Processing flow:
        Configured text -> expand UTC token and user home -> absolute project path.

    Direct call tree (static source order):
        configured_path
        +-- Path
        +-- Path(...).expanduser
        +-- value.replace
        +-- path.is_absolute
        `-- path.resolve
    """
    path = Path(value.replace("{utc}", timestamp)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def parse_configured_args(
    parser: argparse.ArgumentParser,
    arguments: Sequence[str] | None,
    name: str,
    *,
    section: str | None = None,
) -> argparse.Namespace:
    """Combine one entry's TOML settings with explicitly supplied command arguments.

    Inputs: parser defines supported parameters; name selects main_*.toml;
    section selects its action table; arguments supplies optional CLI overrides.
    Returns an argparse.Namespace, whose attributes are the effective typed values.
    Empty strings supply no default; required fields for the active action must come from TOML or command-line arguments.

    Processing flow:
        Select settings file -> validate configured argument names -> apply typed
        defaults and group precedence -> parse overrides -> validate effective choices.

    Direct call tree (static source order):
        parse_configured_args
        +-- list
        +-- argparse.ArgumentParser
        +-- selector.add_argument
        +-- settings_path
        +-- selector.parse_known_args
        +-- copy.deepcopy
        +-- active.add_argument
        +-- load_settings
        +-- active.error
        +-- set
        +-- isinstance
        +-- <str literal>.join
        +-- sorted
        +-- word.startswith
        +-- word.split
        +-- explicit_flags.add
        +-- explicit_flags.intersection
        +-- overridden_groups.add
        +-- datetime.now
        +-- datetime.now(...).strftime
        +-- values.items
        +-- configured_path
        +-- str
        +-- callable
        +-- converter
        +-- defaults.get
        +-- configured.append
        +-- len
        +-- conflicting_names.append
        +-- active.set_defaults
        +-- active.parse_args
        +-- print
        +-- actions.items
        `-- getattr
    """
    command = sys.argv[1:]
    if arguments is not None:
        command = list(arguments)
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--settings", type=Path, default=settings_path(name))
    selected, _ = selector.parse_known_args(command)
    active = copy.deepcopy(parser)
    active.add_argument("--settings", type=Path, default=selected.settings,
                        help="TOML settings file; explicit command arguments take precedence")
    try:
        document = load_settings(name, selected.settings)
    except (OSError, ValueError) as error:
        active.error(f"cannot read settings {selected.settings}: {error}")
    selected_section = "arguments"
    if section is not None and set(document) != {"arguments"}:
        selected_section = section
    if selected_section not in document:
        active.error(f"{selected.settings}: missing [{selected_section}] table")
    if section is None and set(document) != {"arguments"}:
        active.error("settings must contain exactly one [arguments] table")
    values = document[selected_section]
    if not isinstance(values, dict):
        active.error(f"[{selected_section}] must be a table")
    actions = {}
    for argument_definition in active._actions:
        if argument_definition.dest not in ("help", "settings"):
            actions[argument_definition.dest] = argument_definition
    unknown = set(values) - set(actions)
    if unknown:
        active.error("unknown configuration field(s): " + ", ".join(sorted(unknown)))

    # An explicit member selects the whole group, e.g. --offline replaces configured fetch=true.
    explicit_flags = set()
    for word in command:
        if word.startswith("-"):
            flag = word.split("=", 1)[0]
            explicit_flags.add(flag)
    overridden_groups = set()
    for group in active._mutually_exclusive_groups:
        group_has_override = False
        for argument_definition in group._group_actions:
            if explicit_flags.intersection(argument_definition.option_strings):
                group_has_override = True
        if group_has_override:
            for argument_definition in group._group_actions:
                overridden_groups.add(argument_definition.dest)

    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    defaults = {}
    for key, value in values.items():
        if value == "" or key in overridden_groups:
            continue
        action = actions[key]
        if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                               argparse.BooleanOptionalAction)):
            if not isinstance(value, bool):
                active.error(f"{key} must be true or false")
            converted = value
        elif isinstance(value, (dict, list, bool)):
            active.error(f"{key} must be a scalar argument value")
        elif action.type is Path:
            converted = configured_path(str(value), timestamp=stamp)
        elif action.type is not None:
            converter = action.type
            if not callable(converter):
                active.error(f"unsupported argument converter for {key}")
            try:
                converted = converter(str(value))
            except (ValueError, TypeError, argparse.ArgumentTypeError) as error:
                active.error(f"invalid configuration field {key}: {error}")
        else:
            converted = str(value)
        defaults[key] = converted
        action.required = False
        if not action.option_strings and action.nargs is None:
            action.nargs = "?"
    for group in active._mutually_exclusive_groups:
        configured = []
        for argument_definition in group._group_actions:
            if defaults.get(argument_definition.dest) not in (None, False):
                configured.append(argument_definition)
        if len(configured) > 1:
            conflicting_names = []
            for argument_definition in configured:
                conflicting_names.append(argument_definition.dest)
            active.error("configuration selects conflicting modes: " + ", ".join(conflicting_names))
        if configured:
            group.required = False
    active.set_defaults(**defaults)
    try:
        result = active.parse_args(command)
    except SystemExit as error:
        if error.code != 0:
            section_name = selected_section
            if name in COMMAND_SETTINGS:
                entry_name, section_name = COMMAND_SETTINGS[name]
            print(
                f"Check section [{section_name}] in {selected.settings}. "
                "Required arguments listed above must be set; an empty string means no value was provided.",
                file=sys.stderr,
            )
        raise
    for key, action in actions.items():
        value = getattr(result, key)
        if action.choices is not None and value is not None and value not in action.choices:
            active.error(f"invalid choice for {key}: {value!r}")
    return result
