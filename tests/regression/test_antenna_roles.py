"""Verify platform role setup without opening a serial port."""
from pathlib import Path
import tomllib
import pytest
from tools.configure_antenna import configure

ROOT = Path(__file__).resolve().parents[2]


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



@pytest.mark.parametrize('tx_device,rx_device', [
    ('/dev/ttyUSB0', '/dev/cu.usbserial-A'),
    ('/dev/ttyUSB0', 'COM4'),
    ('COM6', '/dev/cu.usbserial-A'),
    ('COM6', 'COM4'),
])
def test_platform_pairs_keep_independent_ports_and_board_identities(tmp_path, tx_device, rx_device):
    """Configure each computer independently while retaining B TX and A RX identity."""
    for role, device, board in [('tx', tx_device, 'B'), ('rx', rx_device, 'A')]:
        computer = tmp_path / role
        for relative in ('config/internal/board_control.toml', 'config/main_transmit.toml', 'config/main_receive.toml'):
            destination = computer / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        configure(computer, device=device, board=board, role=role, profile='LoRa')
        maintenance = tomllib.loads((computer/'config/internal/board_control.toml').read_text())
        assert maintenance['device'] == device
        main_name = 'main_transmit' if role == 'tx' else 'main_receive'
        main = tomllib.loads((computer/'config'/f'{main_name}.toml').read_text())
        selected = main[main['action']]
        assert selected['port' if role == 'tx' else 'device'] == device
        expected_build = 'receive-endpoint' if role == 'tx' else 'single-endpoint'
        assert selected['manifest'] == f'firmware/build/{expected_build}/manifest.json'
        board_config = tomllib.loads((ROOT/maintenance['board_config']).read_text())
        assert board_config['endpoint_id'] == (2 if role == 'tx' else 1)
