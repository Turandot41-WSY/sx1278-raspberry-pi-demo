"""Check saved and freshly acquired orbit preparation before any UART use."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from host.common.runtime_config import PROJECT_ROOT
from host.cli import acquire, transmit_saved
from tests.teaching.test_transmit_main import session_for


ARCHIVE = PROJECT_ROOT / 'data/replay/gomx1-example/orbit'
REFERENCE_FRAMES = ARCHIVE.parent / 'frames.bin'


def preparation_module():
    """Require the production source resolver introduced by this feature.

    Direct call tree (static source order):
        preparation_module
        +-- importlib.util.find_spec
        `-- importlib.import_module
    """
    specification = importlib.util.find_spec('host.cli.transmit_inputs')
    assert specification is not None, 'Transmission has no latest/saved dataset preparation yet'
    return importlib.import_module('host.cli.transmit_inputs')


def options_for(source='saved', dataset: Path | None = ARCHIVE):
    """Provide operator inputs with deliberately stale legacy file settings.

    Direct call tree (static source order):
        options_for
        +-- SimpleNamespace
        `-- Path
    """
    return SimpleNamespace(data_source=source, saved_dataset=dataset,
                           frames=Path('obsolete.bin'), sha256='obsolete',
                           orbit_dataset=None, start=0, count='all')


def test_saved_dataset_builds_exact_frames_without_fetch(tmp_path):
    """Rebuild every published frame from a saved orbit without changing its files.

    Direct call tree (static source order):
        test_saved_dataset_builds_exact_frames_without_fetch
        +-- preparation_module
        +-- ARCHIVE.rglob
        +-- path.is_file
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- path.read_bytes
        +-- patch.object
        +-- module.prepare_transmit_inputs
        +-- options_for
        +-- fetch.assert_not_called
        +-- REFERENCE_FRAMES.read_bytes
        +-- len
        +-- ARCHIVE.resolve
        +-- prepared.frames.source.read_bytes
        `-- before.items
    """
    module = preparation_module()
    before = {}
    for path in ARCHIVE.rglob('*'):
        if path.is_file():
            before[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    with patch.object(module.acquire, 'fetch_latest_dataset') as fetch:
        prepared = module.prepare_transmit_inputs(options_for(), tmp_path / 'input_frames.bin')
    fetch.assert_not_called()
    assert prepared.frames.data == REFERENCE_FRAMES.read_bytes()
    assert prepared.frames.count == 2072
    assert len(prepared.plan) == 2072
    assert prepared.orbit_directory == ARCHIVE.resolve()
    assert prepared.dataset_id
    assert prepared.frames.source.read_bytes() == REFERENCE_FRAMES.read_bytes()
    for path, digest in before.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_latest_uses_acquired_directory_and_ignores_stale_paths(tmp_path, capsys):
    """Use the returned new directory even when all saved input settings are stale.

    Direct call tree (static source order):
        test_latest_uses_acquired_directory_and_ignores_stale_paths
        +-- preparation_module
        +-- options_for
        +-- Path
        +-- patch.object
        +-- module.prepare_transmit_inputs
        +-- fetch.assert_called_once_with
        +-- prepared.frames.frame
        +-- REFERENCE_FRAMES.read_bytes
        `-- capsys.readouterr
    """
    module = preparation_module()
    options = options_for('latest', Path('also-obsolete'))
    options.start = 105
    options.count = '2'
    with patch.object(module.acquire, 'fetch_latest_dataset', return_value=ARCHIVE) as fetch:
        prepared = module.prepare_transmit_inputs(options, tmp_path / 'input_frames.bin')
    fetch.assert_called_once_with()
    assert prepared.frames.start == 105
    assert prepared.frames.count == 2
    assert prepared.frames.frame(105) == REFERENCE_FRAMES.read_bytes()[105*64:106*64]
    assert prepared.data_source == 'latest'
    output = capsys.readouterr().out
    assert 'Acquiring' in output
    assert 'Validating' in output
    assert '2072' in output


def test_latest_download_failure_never_opens_uart(tmp_path, capsys):
    """Stop a failed acquisition without using the old frames or connecting a board.

    Direct call tree (static source order):
        test_latest_download_failure_never_opens_uart
        +-- preparation_module
        +-- session_for
        +-- patch.object
        +-- OSError
        +-- transmit_saved.run
        +-- str
        +-- opened.assert_not_called
        +-- capsys.readouterr
        +-- list
        `-- session.output.rglob
    """
    module = preparation_module()
    _, session = session_for(tmp_path, 'LoRa')
    with patch.object(module.acquire, 'fetch_latest_dataset', side_effect=OSError('download unavailable')):
        with patch.object(transmit_saved, 'open_nano_port') as opened:
            result = transmit_saved.run(['--settings', str(session.settings), '--data-source', 'latest'], section='antenna')
    assert result == 1
    opened.assert_not_called()
    assert 'download unavailable' in capsys.readouterr().out
    assert not list(session.output.rglob('input_frames.bin'))


def test_main_sends_newly_prepared_frames_and_records_identity(tmp_path):
    """Send real prepared bytes through the simulated Nano and retain source identity.

    Direct call tree (static source order):
        test_main_sends_newly_prepared_frames_and_records_identity
        +-- preparation_module
        +-- session_for
        +-- patch.object
        +-- session.run
        +-- REFERENCE_FRAMES.read_bytes
        +-- next
        +-- session.output.rglob
        +-- events_path.read_text
        +-- events_path.read_text(...).splitlines
        +-- events.append
        +-- json.loads
        +-- str
        +-- ARCHIVE.resolve
        `-- <BinOp expression>.read_bytes
    """
    module = preparation_module()
    _, session = session_for(tmp_path, 'LoRa')
    with patch.object(module.acquire, 'fetch_latest_dataset', return_value=ARCHIVE):
        assert session.run(['--data-source', 'latest', '--count', '2']) == 0
    frames = REFERENCE_FRAMES.read_bytes()
    assert session.responder.loaded[0].frame == frames[:64]
    assert session.responder.loaded[1].frame == frames[64:128]
    assert session.responder.loaded[0].reg_frf_word == 7168032
    events = []
    events_path = next(session.output.rglob('events.jsonl'))
    for line in events_path.read_text().splitlines():
        events.append(json.loads(line))
    assert events[0]['data_source'] == 'latest'
    assert events[0]['orbit_dataset'] == str(ARCHIVE.resolve())
    assert events[0]['dataset_id']
    assert events[-1]['tx_done'] == 2
    assert (events_path.parent / 'input_frames.bin').read_bytes() == frames


def test_legacy_saved_frames_still_require_matching_hash(tmp_path):
    """Preserve the existing saved-file hash boundary without triggering acquisition.

    Direct call tree (static source order):
        test_legacy_saved_frames_still_require_matching_hash
        +-- preparation_module
        +-- options_for
        +-- patch.object
        +-- pytest.raises
        +-- module.prepare_transmit_inputs
        `-- fetch.assert_not_called
    """
    module = preparation_module()
    options = options_for(dataset=None)
    options.frames = REFERENCE_FRAMES
    with patch.object(module.acquire, 'fetch_latest_dataset') as fetch:
        with pytest.raises(ValueError, match='SHA-256'):
            module.prepare_transmit_inputs(options, tmp_path / 'input_frames.bin')
    fetch.assert_not_called()


def test_latest_acquisition_reuses_main_dataset_online_path(tmp_path, capsys):
    """Force online acquisition and preserve the existing generator configuration.

    Direct call tree (static source order):
        test_latest_acquisition_reuses_main_dataset_online_path
        +-- hasattr
        +-- SimpleNamespace
        +-- Path
        +-- patch.object
        +-- acquire.fetch_latest_dataset
        +-- parsed.assert_called_once_with
        +-- expected.resolve
        `-- capsys.readouterr
    """
    assert hasattr(acquire, 'fetch_latest_dataset'), 'Acquisition does not return its new dataset directory'
    expected = tmp_path / 'newly-published'
    settings = SimpleNamespace(fetch=False, offline=Path('old'), output_root=tmp_path,
                               search_start_utc=None, search_end_utc=None,
                               chunk_days=2, maximum_lookback_days=7,
                               generator_git_commit='recorded-commit')
    with patch.object(acquire, '_parse_args', return_value=settings) as parsed:
        with patch.object(acquire, 'fetch_source', return_value=SimpleNamespace(content=b'x', url='source', retrieved_at_utc=None, headers={})):
            with patch.object(acquire, '_report_fetched_source'):
                with patch.object(acquire, '_freeze_fetched_dataset', return_value=expected) as freeze:
                    result = acquire.fetch_latest_dataset()
    parsed.assert_called_once_with(['--fetch'])
    assert result == expected.resolve()
    assert freeze.call_args.kwargs['dataset_root'] == tmp_path
    assert freeze.call_args.kwargs['chunk_days'] == 2
    assert freeze.call_args.kwargs['maximum_lookback_days'] == 7
    assert freeze.call_args.kwargs['generator_git_commit'] == 'recorded-commit'
    assert 'Downloading' in capsys.readouterr().out


@pytest.mark.parametrize('answer', ['n', '', 'invalid', EOFError(), KeyboardInterrupt()])
def test_confirmation_decline_keeps_prepared_data_without_opening_uart(tmp_path, answer):
    """Retain prepared inputs and cancel cleanly unless the operator explicitly agrees.

    Direct call tree (static source order):
        test_confirmation_decline_keeps_prepared_data_without_opening_uart
        +-- session_for
        +-- Mock
        +-- isinstance
        +-- patch
        +-- patch.object
        +-- transmit_saved.run
        +-- str
        +-- asked.assert_called_once
        +-- opened.assert_not_called
        +-- next
        +-- session.output.rglob
        +-- event_path.read_text
        +-- event_path.read_text(...).splitlines
        +-- events.append
        +-- json.loads
        `-- <BinOp expression>.is_file
    """
    from tests.fakes.fake_clock import FakeClock
    _, session = session_for(tmp_path, 'LoRa')
    simulated_answer = Mock(return_value=answer)
    if isinstance(answer, BaseException):
        simulated_answer.side_effect = answer
    with patch('builtins.input', new=simulated_answer) as asked:
        with patch.object(transmit_saved, 'open_nano_port', return_value=session.port) as opened:
            with patch.object(transmit_saved, 'SystemClock', FakeClock):
                result = transmit_saved.run(['--settings', str(session.settings)], section='antenna')
    assert result == 0
    asked.assert_called_once()
    opened.assert_not_called()
    event_path = next(session.output.rglob('events.jsonl'))
    events = []
    for line in event_path.read_text().splitlines():
        events.append(json.loads(line))
    assert events[-1]['status'] == 'CANCELLED_BEFORE_SEND'
    assert events[-1]['tx_done'] == 0
    assert (event_path.parent / 'input_frames.bin').is_file()


def test_confirmation_happens_after_preparation_and_before_uart(tmp_path):
    """Show the actual selected input before an affirmative answer opens the port.

    Direct call tree (static source order):
        test_confirmation_happens_after_preparation_and_before_uart
        +-- preparation_module
        +-- session_for
        +-- patch.object
        +-- patch
        +-- transmit_saved.run
        +-- str
        +-- asked.assert_called_once
        +-- opened.assert_called_once
        `-- len
    """
    from tests.fakes.fake_clock import FakeClock
    module = preparation_module()
    _, session = session_for(tmp_path, 'LoRa')
    with patch.object(module.acquire, 'fetch_latest_dataset', return_value=ARCHIVE):
        with patch.object(transmit_saved, 'open_nano_port', return_value=session.port) as opened:
            def answer_when_ready(prompt):
                """Check the preparation boundary while providing the simulated consent.

                Direct call tree (static source order):
                    answer_when_ready
                    +-- opened.assert_not_called
                    +-- next
                    +-- next(...).read_bytes
                    +-- session.output.rglob
                    `-- REFERENCE_FRAMES.read_bytes
                """
                assert prompt == 'Data is ready. Start transmission? [y/N] '
                opened.assert_not_called()
                assert next(session.output.rglob('input_frames.bin')).read_bytes() == REFERENCE_FRAMES.read_bytes()
                return ' YES '
            with patch('builtins.input', side_effect=answer_when_ready) as asked:
                with patch.object(transmit_saved, 'SystemClock', FakeClock):
                    assert transmit_saved.run(['--settings', str(session.settings), '--data-source', 'latest', '--count', '2'], section='antenna') == 0
    asked.assert_called_once()
    opened.assert_called_once()
    assert len(session.responder.loaded) == 2
