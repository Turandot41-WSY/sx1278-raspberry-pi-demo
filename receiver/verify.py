"""Compare one completed transmit log with one stopped receiver log."""

import argparse
from collections import Counter
import json
from pathlib import Path


def compare_logs(tx_events, rx_events):
    """Count exact received payload matches for a completed transmission.

    Processing flow:
        Validate session identity and completion -> select confirmed transmit bytes
        -> count CRC-valid receive bytes -> compare payload multiplicities.
    This is an offline demo check. Logs do not authenticate radio provenance or
    distinguish a replay of the same frozen payload from its original emission.
    """
    tx_start = [e for e in tx_events if e.get('event') == 'run_start']
    rx_start = [e for e in rx_events if e.get('event') == 'run_start']
    if len(tx_start) != 1 or len(rx_start) != 1:
        raise ValueError('Select exactly one transmitter session and one receiver session')
    if tx_start[0].get('data_origin') != 'physical_serial' or rx_start[0].get('data_origin') != 'physical_serial':
        raise ValueError('Both logs must identify physical_serial acquisition')
    if tx_start[0].get('profile') != rx_start[0].get('profile'):
        raise ValueError('Transmitter and receiver profiles differ')
    summaries = [e for e in tx_events if e.get('event') == 'summary']
    if len(summaries) != 1 or summaries[0].get('status') != 'COMPLETED':
        raise ValueError('The transmitter did not complete this session')
    frames = {}
    completed = []
    for event in tx_events:
        if event.get('event') == 'frame_requested':
            index = event['frame_index']
            if index in frames:
                raise ValueError('Duplicate requested frame index')
            payload = bytes.fromhex(event['frame_hex'])
            if len(payload) != 64:
                raise ValueError('Requested frame must contain 64 bytes')
            frames[index] = payload
        elif event.get('event') == 'tx_done':
            completed.append(event['frame_index'])
    requested = tx_start[0]['count']
    if not isinstance(requested, int) or requested <= 0:
        raise ValueError('Transmit count must be positive')
    if len(frames) != requested or len(completed) != requested or set(completed) != set(frames):
        raise ValueError('Frame requests and TX_DONE events disagree')
    summary = summaries[0]
    if summary.get('tx_done') != requested or summary.get('requested') != requested:
        raise ValueError('Transmit summary counts disagree')
    expected = Counter(frames.values())
    received = Counter()
    rejected = 0
    for event in rx_events:
        if event.get('event') != 'rx_packet':
            continue
        try:
            payload = bytes.fromhex(event['packet_hex'])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if event.get('phy_crc_ok') != 1 or event.get('received_length') != 64 or len(payload) != 64:
            rejected += 1
            continue
        received[payload] += 1
    matched = sum((expected & received).values())
    return {'requested':requested, 'tx_done':len(completed), 'matched':matched,
            'missing':requested-matched, 'extra_packets':sum((received-expected).values()),
            'rejected_packets':rejected, 'passed':matched == requested}


def main(arguments=None):
    """Print an exact payload comparison and return failure when frames are missing.

    Processing flow:
        Read selected JSONL logs -> compare sessions -> print result and exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tx', type=Path, required=True)
    parser.add_argument('--rx', type=Path, required=True)
    options = parser.parse_args(arguments)
    try:
        tx = [json.loads(line) for line in options.tx.read_text().splitlines() if line.strip()]
        rx = [json.loads(line) for line in options.rx.read_text().splitlines() if line.strip()]
        result = compare_logs(tx, rx)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Cannot compare logs: {error}\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
