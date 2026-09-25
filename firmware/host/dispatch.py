"""Read an entry's selected action before main calls the corresponding command."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from firmware.host.runtime_config import load_settings, settings_path


def select_action(
    arguments: Sequence[str] | None,
    entry_name: str,
    available_actions: tuple[str, ...],
) -> tuple[str, list[str]]:
    """Select a configured action and return the remaining command arguments.

    Processing flow:
        Read startup arguments -> choose the entry TOML -> select its action or
        explicit command override -> return action and command parameters to main.

    Inputs are optional CLI words, the main filename without .py and its allowed
    action names. The return value contains no hardware objects. Reading this
    selection does not start an experiment; main makes the next function call.

    Direct call tree (static source order):
        select_action
        +-- list
        +-- first_word.startswith
        +-- command_arguments.pop
        +-- argparse.ArgumentParser
        +-- settings_path
        +-- selector.add_argument
        +-- selector.parse_known_args
        +-- load_settings
        +-- selector.error
        +-- configuration.get
        +-- <str literal>.join
        `-- print
    """
    if arguments is None:
        command_arguments = list(sys.argv[1:])
    else:
        command_arguments = list(arguments)

    explicit_action = None
    if command_arguments:
        first_word = command_arguments[0]
        if not first_word.startswith("-"):
            explicit_action = command_arguments.pop(0)

    selector = argparse.ArgumentParser(add_help=False)
    default_settings = settings_path(entry_name)
    selector.add_argument("--settings", type=Path, default=default_settings)
    selected, remaining_arguments = selector.parse_known_args(command_arguments)

    try:
        configuration = load_settings(entry_name, selected.settings)
    except (OSError, ValueError) as error:
        selector.error(f"cannot read settings {selected.settings}: {error}")

    if explicit_action is not None:
        action = explicit_action
    else:
        action = configuration.get("action")
    if action not in available_actions:
        choices = ", ".join(available_actions)
        selector.error(f"{selected.settings}: action must be one of {choices}; got {action!r}")

    if "--help" in command_arguments or "-h" in command_arguments:
        print(f"Configuration file: {selected.settings}")
        print(f"Selected action: {action}; available actions: {', '.join(available_actions)}")
        print("Set action at the top of the configuration file and restart. An explicit ACTION argument overrides it for this run.")
    return action, command_arguments
