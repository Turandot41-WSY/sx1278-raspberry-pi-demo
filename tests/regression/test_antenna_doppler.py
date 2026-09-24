"""Verify diagnostic orbit binding and real host commands with simulated UART."""
from types import SimpleNamespace
from unittest.mock import patch, Mock
import json
import hashlib
from host.dataset.ccsds_tm import build_tm_frame
import pytest
from host.cli import transmit_saved
from host.radio import antenna_doppler
from tests.teaching.test_transmit_main import session_for


def test_plan_rejects_mismatched_orbit_before_serial(tmp_path):
    """Reject a mission record mismatch before opening the sender port.

    Direct call tree (static source order):
        test_plan_rejects_mismatched_orbit_before_serial
        +-- session_for
        +-- SimpleNamespace
        +-- bytes
        +-- patch.object
        +-- pytest.raises
        +-- transmit_saved.run
        +-- str
        `-- opened.assert_not_called
    """
    source, session = session_for(tmp_path, 'LoRa')
    sample = SimpleNamespace(mission_record=bytes(50), reg_frf_word=7168032,
                             requested_cfo_hz=1953.125, programmed_cfo_hz=1953.125)
    dataset = SimpleNamespace(passes=[SimpleNamespace(schedule=SimpleNamespace(samples=[sample, sample]))])
    with patch.object(antenna_doppler, 'load_frozen_orbit_dataset', return_value=dataset):
        with patch.object(transmit_saved, 'open_nano_port') as opened:
            with pytest.raises(ValueError, match='orbit'):
                transmit_saved.run(['--settings', str(session.settings), '--orbit-dataset', str(tmp_path)])
            opened.assert_not_called()


def test_signed_orbit_values_reach_load_tx_and_logs(tmp_path):
    """Preserve frame bytes while sending positive and negative programmed offsets.

    Direct call tree (static source order):
        test_signed_orbit_values_reach_load_tx_and_logs
        +-- session_for
        +-- build_tm_frame
        +-- bytes
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- source.read_bytes
        +-- source.write_bytes
        +-- session.settings.write_text
        +-- session.settings.read_text
        +-- session.settings.read_text(...).replace
        +-- enumerate
        +-- samples.append
        +-- SimpleNamespace
        +-- patch.object
        +-- session.run
        +-- str
        +-- words.append
        +-- next
        +-- session.output.rglob
        +-- events_path.read_text
        +-- events_path.read_text(...).splitlines
        +-- events.append
        `-- json.loads
    """
    source, session = session_for(tmp_path, 'LoRa')
    data = build_tm_frame(bytes(50), 0, 0, 0) + build_tm_frame(bytes([1])*50, 1, 1, 1)
    previous = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_bytes(data)
    session.settings.write_text(session.settings.read_text().replace(previous, hashlib.sha256(data).hexdigest()))
    samples = []
    for index, word in enumerate([7168032, 7167968]):
        samples.append(SimpleNamespace(mission_record=data[index*64+12:index*64+62],
            reg_frf_word=word, requested_cfo_hz=(word-7168000)*61.03515625,
            programmed_cfo_hz=(word-7168000)*61.03515625))
    dataset = SimpleNamespace(passes=[SimpleNamespace(schedule=SimpleNamespace(samples=samples))])
    with patch.object(antenna_doppler, 'load_frozen_orbit_dataset', return_value=dataset):
        assert session.run(['--orbit-dataset', str(tmp_path)]) == 0
    words = []
    for item in session.responder.loaded:
        words.append(item.reg_frf_word)
    assert words == [7168032,7167968]
    assert session.responder.loaded[0].frame == data[:64]
    events_path = next(session.output.rglob('events.jsonl'))
    events = []
    for line in events_path.read_text().splitlines():
        events.append(json.loads(line))
    assert events[0]['experiment_kind'] == 'antenna_doppler_diagnostic'
    words = []
    for event in events:
        if event['event'] == 'frame_requested':
            words.append(event['reg_frf_word'])
    assert words == [7168032,7167968]


@pytest.mark.parametrize("fault", [None, "rx_frf"])
def test_receive_callback_runs_only_after_valid_armed(fault):
    """Run the sending callback only after validating the receiver register reply.

    Direct call tree (static source order):
        test_receive_callback_runs_only_after_valid_armed
        +-- ReceiverReplies
        +-- load_profile_truth
        +-- EndpointTransport
        +-- TeachingBytePort
        +-- EvidenceSpy
        +-- FakeClock
        +-- pytest.raises
        +-- receive_window
        `-- Mock
    """
    from host.radio.single_receive import receive_window
    from host.radio.serial_transport import EndpointTransport
    from host.radio.profile_truth import load_profile_truth
    from host.common.runtime_config import PROJECT_ROOT
    from tests.teaching.test_receive_main import ReceiverReplies
    from tests.fakes.transmit_endpoint import TeachingBytePort
    from tests.fakes.fake_clock import FakeClock
    from tests.fakes.fake_endpoints import EvidenceSpy
    responder = ReceiverReplies(load_profile_truth(PROJECT_ROOT / 'config'), fault)
    transport = EndpointTransport(TeachingBytePort(responder), 1, EvidenceSpy(), FakeClock())
    sent = []

    def record_send():
        """Record the callback after a validated receiver acknowledgement.

        Direct call tree (static source order):
            record_send
            `-- sent.append
        """
        sent.append(True)

    if fault:
        with pytest.raises(ValueError, match='frequency'):
            receive_window(transport, 1, 0, 10, 10, Mock(), on_armed=record_send)
        assert sent == []
    else:
        result = receive_window(transport, 1, 0, 10, 10, Mock(), on_armed=record_send)
        assert sent == [True]
        assert result['event'] == 'rx_timeout'




@pytest.mark.parametrize('device', ['COM4', '/dev/cu.usbserial-110', '/dev/ttyUSB0'])
def test_antenna_main_uses_local_uart_on_each_platform(tmp_path, monkeypatch, device):
    """Send exact saved frames through one local UART on all operator platforms.

    Direct call tree (static source order):
        test_antenna_main_uses_local_uart_on_each_platform
        +-- session_for
        +-- monkeypatch.setattr
        +-- Mock
        +-- patch.object
        +-- main_transmit.main
        +-- str
        +-- opened.assert_called_once_with
        +-- bytearray
        +-- data.extend
        +-- bytes
        `-- source.read_bytes
    """
    import main_transmit
    from tests.fakes.fake_clock import FakeClock
    from tests.fakes.transmit_endpoint import SimulatedTransmitEvidence

    source, session = session_for(tmp_path, 'LoRa')
    monkeypatch.setattr('builtins.input', Mock(return_value='yes'))
    opened = Mock(return_value=session.port)
    with patch.object(transmit_saved, 'open_nano_port', opened), \
         patch.object(transmit_saved, 'SystemClock', FakeClock), \
         patch.object(transmit_saved, 'TransmitEvidence', SimulatedTransmitEvidence):
        result = main_transmit.main(['antenna', '--settings', str(session.settings), '--port', device])
    assert result == 0
    opened.assert_called_once_with(device)
    data = bytearray()
    for item in session.responder.loaded:
        data.extend(item.frame)
        assert item.reg_frf_word == 7168000
    assert bytes(data) == source.read_bytes()


def test_antenna_rejects_tcp_sender_before_opening_hardware(tmp_path):
    """Keep the independent antenna action local even if a stale TCP URL is supplied.

    Direct call tree (static source order):
        test_antenna_rejects_tcp_sender_before_opening_hardware
        +-- session_for
        +-- patch.object
        +-- pytest.raises
        +-- main_transmit.main
        +-- str
        `-- opened.assert_not_called
    """
    import main_transmit
    _, session = session_for(tmp_path, 'LoRa')
    with patch.object(transmit_saved, 'open_nano_port') as opened:
        with pytest.raises(SystemExit):
            main_transmit.main(['antenna', '--settings', str(session.settings),
                                '--port', 'tcp://127.0.0.1:8765'])
        opened.assert_not_called()


def test_published_replay_input_validates_without_generation():
    """Validate every archived demonstration frame and frequency before publication.

    Direct call tree (static source order):
        test_published_replay_input_validates_without_generation
        +-- Path
        +-- Path(...).resolve
        +-- load_saved_frames
        +-- antenna_doppler.load_antenna_plan
        `-- len
    """
    from pathlib import Path
    from host.radio.single_transmit import load_saved_frames
    root = Path(__file__).resolve().parents[2] / 'data/replay/gomx1-example'
    frames = load_saved_frames(root / 'frames.bin',
        '5a9c5b296490e989e4f8b29221ecd9c640cec7fd059452394cca22a78e636e63', 0, 'all')
    plan = antenna_doppler.load_antenna_plan(root / 'orbit', frames)
    assert len(plan) == frames.count == 2072
    assert plan[0].reg_frf_word == 7168032
