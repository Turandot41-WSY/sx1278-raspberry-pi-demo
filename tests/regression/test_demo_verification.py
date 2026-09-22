"""Exercise missing, repeated and invalid packets in the offline demo check."""
from copy import deepcopy
import pytest
from tools.verify_reception import compare_logs


def sessions():
    payload = bytes(range(64)).hex()
    start = {'event':'run_start','data_origin':'physical_serial','profile':'LoRa'}
    tx = [dict(start, count=2),
          {'event':'frame_requested','frame_index':0,'frame_hex':payload},
          {'event':'tx_done','frame_index':0},
          {'event':'frame_requested','frame_index':1,'frame_hex':payload},
          {'event':'tx_done','frame_index':1},
          {'event':'summary','status':'COMPLETED','tx_done':2,'requested':2}]
    packet = {'event':'rx_packet','packet_hex':payload,'received_length':64,'phy_crc_ok':1}
    return tx, [start, packet, deepcopy(packet)]


def test_repeated_payloads_require_matching_multiplicity():
    tx, rx = sessions()
    assert compare_logs(tx, rx)['passed']
    assert compare_logs(tx, rx[:-1])['missing'] == 1


def test_crc_failed_and_truncated_packets_do_not_count():
    tx, rx = sessions()
    rx[1]['phy_crc_ok'] = 0
    rx[2]['packet_hex'] = '00'
    result = compare_logs(tx, rx)
    assert result['matched'] == 0
    assert result['rejected_packets'] == 2


@pytest.mark.parametrize('change', ['incomplete','profile','origin','duplicate_done'])
def test_inconsistent_sessions_are_rejected(change):
    tx, rx = sessions()
    if change == 'incomplete': tx[-1]['status'] = 'INCOMPLETE'
    if change == 'profile': rx[0] = dict(rx[0], profile='FSK')
    if change == 'origin': rx[0] = dict(rx[0], data_origin='synthetic')
    if change == 'duplicate_done': tx[4]['frame_index'] = 0
    with pytest.raises(ValueError): compare_logs(tx, rx)
