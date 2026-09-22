"""Select one independent radio role while preserving board identity and other settings."""

import argparse
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def replace_fields(text, section, values):
    """Replace existing TOML scalars in one section without rewriting other settings.

    Processing flow:
        Existing lines -> locate the selected section -> replace named fields
        -> reject missing fields -> parse the complete result before returning.

    Direct call tree (static source order):
        replace_fields
        +-- set
        +-- text.splitlines
        +-- re.match
        +-- heading.group
        +-- field.group
        +-- re.search
        +-- comment.group
        +-- json.dumps
        +-- replaced.add
        +-- lines.append
        +-- ValueError
        +-- <str literal>.join
        `-- tomllib.loads
    """
    current = ''
    replaced = set()
    lines = []
    for line in text.splitlines():
        heading = re.match(r'^\s*\[([^]]+)\]\s*$', line)
        if heading:
            current = heading.group(1)
        field = re.match(r'^(\s*)([A-Za-z0-9_]+)\s*=.*$', line)
        if current == section and field and field.group(2) in values:
            key = field.group(2)
            comment = re.search(r'\s+#.*$', line)
            suffix = ''
            if comment:
                suffix = comment.group(0)
            line = field.group(1) + key + ' = ' + json.dumps(values[key], ensure_ascii=False) + suffix
            replaced.add(key)
        lines.append(line)
    if replaced != set(values):
        raise ValueError('configuration is missing expected fields in [' + section + ']')
    result = '\n'.join(lines) + '\n'
    tomllib.loads(result)
    return result


def configure(root, *, device, board, role, doppler=None, count=None, profile=None):
    """Configure a local antenna role without compiling, flashing or opening the board.

    Processing flow:
        Validate explicit board/role -> prepare maintenance and main settings
        -> validate all edits -> save configuration -> report the next command.
    Board A/B identifies the flashed endpoint, independently of its TX/RX role.
    Existing power, timing and data settings are preserved unless selected.

    Direct call tree (static source order):
        configure
        +-- device.startswith
        +-- ValueError
        +-- replace_fields
        +-- maintenance.read_text
        +-- count.isdigit
        +-- int
        +-- main.read_text
        +-- maintenance.write_text
        +-- main.write_text
        +-- print
        `-- role.upper
    """
    if not device or device.startswith('tcp://'):
        raise ValueError('antenna setup requires a local UART device')
    if board not in ('A', 'B') or role not in ('tx', 'rx'):
        raise ValueError('board must be A/B and role must be tx/rx')
    board_file = 'config/internal/transmit_endpoint.toml'
    build = 'firmware/build/single-endpoint'
    if board == 'B':
        board_file = 'config/internal/receive_endpoint.toml'
        build = 'firmware/build/receive-endpoint'
    maintenance = root / 'config/internal/board_control.toml'
    maintenance_text = replace_fields(maintenance.read_text(encoding='utf-8'), '', {
        'device': device, 'board_config': board_file, 'build_dir': build})
    main = root / 'config/main_receive.toml'
    action = 'listen'
    section = 'listen'
    values = {'device': device, 'manifest': build + '/manifest.json', 'max_windows': 0}
    if role == 'tx':
        main = root / 'config/main_transmit.toml'
        action = 'antenna'
        section = 'antenna'
        values = {'port': device, 'manifest': build + '/manifest.json'}
        if doppler == 'off':
            values['data_source'] = 'saved'
            values['saved_dataset'] = ''
            values['orbit_dataset'] = ''
            values['reg_frf_word'] = 7168000
        elif doppler == 'orbit':
            values['orbit_dataset'] = 'data/replay/gomx1-example/orbit'
        elif doppler is not None:
            raise ValueError('doppler must be orbit/off')
        if count is not None:
            if count != 'all' and (not count.isdigit() or int(count) <= 0):
                raise ValueError('count must be all or a positive integer')
            values['count'] = count
    if profile is not None:
        if profile not in ('LoRa', 'FSK', 'GFSK', 'MSK', 'GMSK', 'OOK'):
            raise ValueError('profile must match the radio profile table')
        values['profile'] = profile
    updated = replace_fields(main.read_text(encoding='utf-8'), '', {'action': action})
    updated = replace_fields(updated, section, values)
    maintenance.write_text(maintenance_text, encoding='utf-8')
    main.write_text(updated, encoding='utf-8')
    print(f'Board {board}, {role.upper()}, {device}; manifest={build}/manifest.json')
    print(f'Configuration saved. After verifying the flashed build: python {main.stem}.py')


def main():
    """Read explicit antenna setup choices and update the existing operator files.

    Processing flow:
        Parse role and board -> validate optional overrides -> write operator settings.

    Direct call tree (static source order):
        main
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parser.parse_args
        `-- configure
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--board', choices=('A', 'B'), required=True)
    parser.add_argument('--role', choices=('tx', 'rx'), required=True)
    parser.add_argument('--doppler', choices=('orbit', 'off'))
    parser.add_argument('--count')
    parser.add_argument('--profile', choices=('LoRa', 'FSK', 'GFSK', 'MSK', 'GMSK', 'OOK'))
    options = parser.parse_args()
    configure(ROOT, device=options.device, board=options.board, role=options.role,
              doppler=options.doppler, count=options.count, profile=options.profile)


if __name__ == '__main__':
    main()
