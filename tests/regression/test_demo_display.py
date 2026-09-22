"""Check that the public display serves real log data without simulated packets."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen, Request
import pytest
from host.display.server import create_server, DisplayService
from tools.configure_antenna import configure

ROOT = Path(__file__).resolve().parents[2]


def test_display_decodes_selected_log_and_rejects_writes(tmp_path):
    events = tmp_path / 'events.jsonl'
    frame = (ROOT / 'data/replay/gomx1-example/frames.bin').read_bytes()[:64]
    records = [{'event':'run_start','data_origin':'synthetic'},
               {'event':'rx_packet','packet_hex':frame.hex(),'received_length':64,'phy_crc_ok':1}]
    events.write_text('\n'.join(json.dumps(record) for record in records)+'\n')
    server = create_server(0, tmp_path, ROOT / 'data/replay/gomx1-example/orbit', events)
    service = DisplayService(server)
    service.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/api/telemetry') as response:
            snapshot = json.load(response)
        assert snapshot['valid'] == 1
        assert snapshot['dataOrigin'] == 'synthetic'
        assert snapshot['activeLatest']['frameHex'] == frame.hex()
        assert snapshot['activeLatest']['sourceMatched'] is True
        for asset in ('/monitor','/app.js','/style.css'):
            with urlopen(base+asset) as response:
                assert response.status == 200
                assert response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base+'/api/scene', data=b'{}', method='POST'))
        assert error.value.code == 405
    finally:
        service.close()


def test_empty_display_contains_no_generated_observations(tmp_path):
    server = create_server(0, tmp_path, ROOT / 'data/replay/gomx1-example/orbit')
    try:
        snapshot = server.receiver.snapshot()
        assert snapshot['received'] == 0
        assert snapshot['samples'] == []
        assert snapshot['activeLatest'] is None
    finally:
        server.server_close()


def test_doppler_off_disables_dataset_override(tmp_path):
    for relative in ('config/main_transmit.toml','config/internal/board_control.toml'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT/relative).read_bytes())
    configure(tmp_path, device='/dev/ttyUSB0', board='B', role='tx', doppler='off')
    import tomllib
    values = tomllib.loads((tmp_path/'config/main_transmit.toml').read_text())['antenna']
    assert values['saved_dataset'] == ''
    assert values['orbit_dataset'] == ''
    assert values['data_source'] == 'saved'
