"""Keep the public demo limited to local radio operation and display."""

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_public_entry_points_and_host_modules_stay_within_demo_scope():
    """Reject private processing stages accidentally copied into a public release."""
    assert {path.name for path in ROOT.glob('main_*.py')} == {
        'main_dataset.py', 'main_transmit.py', 'main_receive.py',
    }
    host_modules = {
        path.name for path in (ROOT / 'host').iterdir()
        if path.is_dir() and path.name != '__pycache__'
    }
    assert host_modules == {'cli', 'common', 'dataset', 'display', 'radio'}
    for directory in ('host', 'tools', 'config', 'firmware'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or 'build' in path.parts:
                continue
            assert 'bridge' not in path.stem.lower(), path.relative_to(ROOT)
    assert not list(ROOT.glob('**/*.m')), 'MATLAB source belongs in the private repository'
    assert not list(ROOT.glob('**/*.mlx')), 'MATLAB live scripts belong in the private repository'


def test_radio_and_operator_modules_do_not_import_network_control():
    """Keep UART operation local while allowing the separate browser HTTP service."""
    prohibited = {'socket', 'socketserver', 'paramiko', 'matlab', 'scipy', 'pandas', 'matplotlib'}
    for directory in ('host/radio', 'host/cli', 'tools'):
        for path in (ROOT / directory).rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    assert module.split('.')[0] not in prohibited, (path.relative_to(ROOT), module)
            assert 'SAS2027_RECEIVER_TOKEN' not in path.read_text(encoding='utf-8'), path


def test_public_dependencies_exclude_private_analysis_and_remote_control():
    """Prevent scientific report and remote UART dependencies from entering the demo."""
    names = set()
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            names.add(re.split(r'[<>=!~;\s\[]', line.strip(), maxsplit=1)[0].lower())
    assert not names & {'matlabengine', 'matlab', 'scipy', 'pandas', 'matplotlib', 'paramiko'}
