import json
from pathlib import Path
import sys
import zipfile

import pytest

from tools import check_kicad_python as host
from tools import install_suite


def config_with_path(tmp_path, interpreter):
    config = tmp_path / 'kicad_common.json'
    config.write_text(json.dumps({'api': {'interpreter_path': str(interpreter), 'enable_server': True}, 'other': {'keep': 7}}), encoding='utf-8')
    return config


def test_invalid_kicad_interpreter_is_reported_before_plugin_runs(tmp_path):
    broken = tmp_path / 'KiCad' / '10.0' / 'bin' / 'pythonw' / '.exe'
    config = config_with_path(tmp_path, broken)
    okay, message = host.check(config)
    assert not okay and 'does not exist' in message


def test_existing_python_with_venv_passes(tmp_path):
    okay, message = host.check(config_with_path(tmp_path, sys.executable))
    assert okay, message


def test_exact_typo_is_repaired_with_backup_and_other_settings_preserved(tmp_path):
    bin_dir = tmp_path / 'KiCad' / '10.0' / 'bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'python.exe').write_bytes(b'fixture')
    broken = bin_dir / 'pythonw' / '.exe'
    config = config_with_path(tmp_path, broken)
    original = config.read_bytes()
    report = host.repair_malformed(config, probe=lambda path: (True, 'ok'), running=lambda: False)
    data = json.loads(config.read_text(encoding='utf-8'))
    assert data['api']['interpreter_path'] == str(bin_dir / 'python.exe')
    assert data['api']['enable_server'] is True and data['other']['keep'] == 7
    backups = list(tmp_path.glob('kicad_common.json.wayricad-backup-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert str(bin_dir / 'python.exe') in report


def test_repair_refuses_other_paths_and_running_kicad(tmp_path):
    other = config_with_path(tmp_path, tmp_path / 'missing.exe')
    with pytest.raises(RuntimeError, match='not the known'):
        host.repair_malformed(other, probe=lambda path: (True, 'ok'), running=lambda: False)
    bin_dir = tmp_path / 'KiCad' / '10.0' / 'bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'python.exe').write_bytes(b'fixture')
    config = config_with_path(tmp_path, bin_dir / 'pythonw' / '.exe')
    with pytest.raises(RuntimeError, match='Close KiCad'):
        host.repair_malformed(config, probe=lambda path: (True, 'ok'), running=lambda: True)
    assert not list(tmp_path.glob('kicad_common.json.wayricad-backup-*'))


def test_source_installer_repairs_before_copy(tmp_path, monkeypatch):
    identifier = 'com.github.wayri.wayricad.sample'
    source = tmp_path / 'source'
    plugin = source / 'sample_plugin'
    plugin.mkdir(parents=True)
    (plugin / 'metadata.json').write_text(json.dumps({'versions': [{'version': '3.4.0'}]}), encoding='utf-8')
    archives = tmp_path / 'archives'
    archives.mkdir()
    with zipfile.ZipFile(archives / 'WayriCAD-sample-3.4.0-PCM.zip', 'w') as archive:
        archive.writestr('plugins/plugin.json', json.dumps({'identifier': identifier, 'name': 'Sample'}))
        archive.writestr('plugins/entrypoint.py', 'pass')
    roaming = tmp_path / 'roaming'
    config = roaming / 'kicad' / '10.0' / 'kicad_common.json'
    config.parent.mkdir(parents=True)
    bin_dir = tmp_path / 'KiCad' / '10.0' / 'bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'python.exe').write_bytes(b'fixture')
    config.write_text(json.dumps({'api': {'interpreter_path': str(bin_dir / 'pythonw' / '.exe')}}), encoding='utf-8')
    real_repair = host.repair_malformed
    monkeypatch.setattr(host, 'repair_malformed', lambda path: real_repair(path, probe=lambda candidate: (True, 'ok'), running=lambda: False))
    monkeypatch.setitem(sys.modules, 'check_kicad_python', host)
    monkeypatch.setenv('APPDATA', str(roaming))
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(install_suite, 'ROOT', source)
    destination = tmp_path / 'installed' / 'plugins'
    monkeypatch.setattr(sys, 'argv', ['install_suite.py', '--destination', str(destination), '--archive-dir', str(archives), '--apply'])
    install_suite.main()
    assert json.loads(config.read_text(encoding='utf-8'))['api']['interpreter_path'] == str(bin_dir / 'python.exe')
    assert (destination / identifier / 'entrypoint.py').is_file()
