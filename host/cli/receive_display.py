"""Run the approved receiver page against local acquisition logs."""

import argparse
from pathlib import Path

from host.common.runtime_config import PROJECT_ROOT, load_settings, parse_configured_args
from host.display.server import DisplayService, create_server


def display_options(arguments=None):
    """Read the display section owned by main_receive and validate paths.

    Processing flow:
        Parse display options -> inherit configured receive directory when blank
        -> validate port and selected log -> return resolved inputs.

    Direct call tree (static source order):
        display_options
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- parser.error
        +-- load_settings
        +-- document.get
        +-- document.get(...).get
        `-- options.events.is_file
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--receive-root', type=Path)
    parser.add_argument('--events', type=Path)
    parser.add_argument('--reference-dataset', type=Path,
                        default=PROJECT_ROOT / 'data/replay/gomx1-example/orbit')
    options = parse_configured_args(parser, arguments, 'main_receive', section='display')
    if not 1 <= options.port <= 65535:
        parser.error('port must be between 1 and 65535')
    if options.receive_root is None:
        document = load_settings('main_receive', options.settings)
        options.receive_root = PROJECT_ROOT / document.get('listen', {}).get('output', 'output/receive')
    if options.events is not None and not options.events.is_file():
        parser.error('events must identify an existing receiver events.jsonl file')
    return options


def start_for_capture(settings, directory):
    """Start a display bound to the exact session owned by the receiver.

    Processing flow:
        Read the same entry configuration -> bind the current log and reference
        -> start the HTTP worker -> return its cleanup owner.

    Direct call tree (static source order):
        start_for_capture
        +-- display_options
        +-- str
        +-- create_server
        +-- DisplayService
        `-- service.start
    """
    options = display_options(['--settings', str(settings), '--events',
                               str(directory / 'events.jsonl')])
    server = create_server(options.port, directory.parent, options.reference_dataset,
                           directory / 'events.jsonl')
    service = DisplayService(server)
    service.start()
    return service


def run(arguments=None):
    """Show receiver logs until interrupted without opening a serial port.

    Processing flow:
        Resolve display configuration -> validate reference and start service
        -> wait for HTTP requests -> release socket on interrupt.

    Direct call tree (static source order):
        run
        +-- display_options
        +-- create_server
        +-- print
        +-- server.serve_forever
        `-- server.server_close
    """
    options = display_options(arguments)
    server = create_server(options.port, options.receive_root, options.reference_dataset,
                           options.events)
    print(f'Receiver display: http://127.0.0.1:{server.server_port}/monitor', flush=True)
    print(f'Local reference: {options.reference_dataset}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
