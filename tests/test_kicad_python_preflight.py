"""Host configuration failure happens before any IPC plugin code can recover."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import check_kicad_python as host


def installation(root, *, windowless=True):
    folder = root / 'bin'
    folder.mkdir(parents=True)
    for name in ('pcbnew.exe', 'python.exe') + (('pythonw.exe',) if windowless else ()):
        (folder / name).write_bytes(b'fixture executable, never executed')
    return folder


def config(root, value, **extra):
    path = root / host.CONFIG_NAME
    data = {'api': {'interpreter_path': value, 'enable_server': True}, **extra}
    path.write_text(json.dumps(data, indent=4) + '\n', encoding='utf-8')
    return path


@pytest.fixture
def prerequisite_probe(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'version': [3, 11, 9], 'venv': True, 'ensurepip': True,
            'executable': command[0], 'base_prefix': str(Path(command[0]).parent)}))

    monkeypatch.setattr(host.subprocess, 'run', run)
    return calls


def test_configuration_override_appends_version_and_standard_appdata(tmp_path):
    assert host.config_path(environ={'APPDATA': str(tmp_path)}) == tmp_path / 'kicad/10.0/kicad_common.json'
    assert host.config_path('11.0', environ={'KICAD_CONFIG_HOME': str(tmp_path)}) == tmp_path / '11.0/kicad_common.json'
    with pytest.raises(ValueError, match='major.minor'):
        host.config_path('../10.0', environ={'APPDATA': str(tmp_path)})
    with pytest.raises(ValueError, match='absolute'):
        host.config_path(environ={'KICAD_CONFIG_HOME': 'relative'})


def test_per_user_and_program_files_discovery_never_assumes_user_name(tmp_path):
    local = tmp_path / 'Profile With Spaces' / 'Local'
    program = tmp_path / 'Program Files'
    user_bin = installation(local / 'Programs/KiCad/10.0')
    machine_bin = installation(program / 'KiCad/10.0')
    candidates = host.discover_interpreters(environ={'LOCALAPPDATA': str(local), 'ProgramFiles': str(program),
                                                   'ProgramW6432': str(program), 'PATH': ''})
    assert candidates == [user_bin / 'pythonw.exe', machine_bin / 'pythonw.exe']


def test_missing_pythonw_uses_console_only_when_installed_host_exists(tmp_path, prerequisite_probe):
    folder = installation(tmp_path / 'Portable KiCad/10.0', windowless=False)
    missing = folder / 'pythonw.exe'
    path = config(tmp_path, str(missing))
    before = path.read_bytes()
    report, _, _ = host.diagnose(path, environ={}, kicad_root=folder.parent)
    assert report['configured_status'] == 'unavailable'
    assert report['proposed_interpreter'] == str(folder / 'python.exe')
    assert path.read_bytes() == before
    assert all(call[0][0] != str(missing) for call in prerequisite_probe)
    other = tmp_path / 'ordinary-python/bin'
    other.mkdir(parents=True)
    (other / 'python.exe').write_bytes(b'fixture')
    assert host.discover_interpreters(environ={}, kicad_root=other.parent) == []


def test_stale_other_user_path_recommends_detected_install_without_write(tmp_path, prerequisite_probe):
    program = tmp_path / 'Program Files'
    folder = installation(program / 'KiCad/10.0')
    path = config(tmp_path, str(tmp_path / 'Old User/Local/Programs/KiCad/10.0/bin/pythonw.exe'))
    before = path.read_bytes()
    report, _, _ = host.diagnose(path, environ={'ProgramFiles': str(program), 'PATH': ''})
    assert report['configured_status'] == 'unavailable'
    assert report['proposed_interpreter'] == str(folder / 'pythonw.exe')
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.wayricad-backup-*'))


def test_multiple_installations_need_explicit_selection(tmp_path, prerequisite_probe):
    local, program = tmp_path / 'Local', tmp_path / 'Program Files'
    installation(local / 'Programs/KiCad/10.0')
    intended = installation(program / 'KiCad/10.0')
    path = config(tmp_path, '')
    report, _, _ = host.diagnose(path, environ={'LOCALAPPDATA': str(local), 'ProgramFiles': str(program), 'PATH': ''})
    assert len(report['candidates']) == 2
    assert 'proposed_interpreter' not in report
    explicit, _, _ = host.diagnose(path, environ={}, kicad_root=intended.parent)
    assert explicit['proposed_interpreter'] == str(intended / 'pythonw.exe')


@pytest.mark.parametrize('value', [False, 42, None, [], {}, 'python.exe', '"C:/Program Files/Python/python.exe"',
                                  'C:/Program Files/Python/python.exe -m venv', 'C:/Missing/pythonw.exe'])
def test_malformed_and_missing_interpreters_are_never_executed(value, prerequisite_probe):
    with pytest.raises(ValueError):
        host.interpreter_path(value)
    assert prerequisite_probe == []


def test_probe_checks_windowless_and_console_without_shell_or_writes(tmp_path, prerequisite_probe):
    folder = installation(tmp_path / 'KiCad With Spaces')
    details = host.probe_interpreter(folder / 'pythonw.exe')
    assert details['venv'] and details['ensurepip']
    assert [command[0] for command, _ in prerequisite_probe] == [str(folder / 'pythonw.exe'), str(folder / 'python.exe')]
    for command, kwargs in prerequisite_probe:
        assert command[1:4] == ['-I', '-B', '-c']
        assert not kwargs.get('shell', False)
        assert kwargs['timeout'] == 15
        assert '-m' not in command
        assert '--system-site-packages' not in command


def test_probe_rejects_missing_venv_support_and_old_python(tmp_path, monkeypatch):
    folder = installation(tmp_path / 'KiCad', windowless=False)
    monkeypatch.setattr(host.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stderr='No module named venv', stdout=''))
    with pytest.raises(ValueError, match='venv/ensurepip'):
        host.probe_interpreter(folder / 'python.exe')
    monkeypatch.setattr(host.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stderr='', stdout=json.dumps({'version': [3, 9, 0], 'venv': True, 'ensurepip': True})))
    with pytest.raises(ValueError, match='3.10'):
        host.probe_interpreter(folder / 'python.exe')


def test_existing_but_broken_pythonw_is_not_certified_by_console_sibling(tmp_path, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stderr='', stdout='')

    monkeypatch.setattr(host.subprocess, 'run', run)
    with pytest.raises(ValueError, match='pythonw.exe cannot load'):
        host.probe_interpreter(folder / 'pythonw.exe')
    assert len(calls) == 1 and calls[0][0] == str(folder / 'pythonw.exe')


def test_malformed_setting_can_be_previewed_without_resetting_other_settings(tmp_path, prerequisite_probe):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, None, appearance={'scale': 2})
    before = path.read_bytes()
    report, _, _ = host.diagnose(path, environ={}, interpreter=folder / 'python.exe')
    assert report['configured_status'] == 'malformed'
    assert report['proposed_interpreter'] == str(folder / 'python.exe')
    assert path.read_bytes() == before


@pytest.mark.parametrize('contents', ['invalid JSON', '[]', '{"api":[]}', '{"api":{},"api":{}}', '{"api":{"interpreter_path":NaN}}'])
def test_invalid_json_is_preserved_and_never_replaced(tmp_path, contents):
    path = tmp_path / host.CONFIG_NAME
    path.write_text(contents, encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        host.read_config(path)
    assert path.read_bytes() == original


def test_apply_replaces_only_interpreter_and_backs_up_exact_bytes(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'Program Files/KiCad/10.0')
    path = config(tmp_path, 'C:/Missing/pythonw.exe', environment={'vars': {'CUSTOM': 'keep'}}, appearance={'scale': 2})
    original, settings = host.read_config(path)
    monkeypatch.setattr(host, 'running_kicad', lambda: [])
    backup = host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert backup.read_bytes() == original
    expected = json.loads(original)
    expected['api']['interpreter_path'] = str(folder / 'pythonw.exe')
    assert json.loads(path.read_bytes()) == expected
    assert not list(tmp_path.glob('.wayricad-kicad-*'))
    unchanged, current = host.read_config(path)
    assert host.apply_repair(path, unchanged, current, folder / 'pythonw.exe') is None
    assert len(list(tmp_path.glob('*.wayricad-backup-*'))) == 1


def test_apply_refuses_running_kicad_and_stale_settings(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original, settings = host.read_config(path)
    monkeypatch.setattr(host, 'running_kicad', lambda: ['pcbnew.exe'])
    with pytest.raises(ValueError, match='Close KiCad'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('*.wayricad-backup-*'))
    monkeypatch.setattr(host, 'running_kicad', lambda: [])
    path.write_bytes(original + b' ')
    with pytest.raises(ValueError, match='changed after inspection'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original + b' '


def test_apply_failed_atomic_replace_keeps_original_and_backup(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original, settings = host.read_config(path)
    monkeypatch.setattr(host, 'running_kicad', lambda: [])
    monkeypatch.setattr(host.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('replace denied')))
    with pytest.raises(OSError, match='replace denied'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original
    backups = list(tmp_path.glob('*.wayricad-backup-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert not list(tmp_path.glob('.wayricad-kicad-*'))


def test_apply_detects_setting_change_during_staging(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original, settings = host.read_config(path)
    monkeypatch.setattr(host, 'running_kicad', lambda: [])
    real_copystat = host.shutil.copystat

    def concurrent_change(source, target, **kwargs):
        real_copystat(source, target, **kwargs)
        path.write_bytes(original + b' ')

    monkeypatch.setattr(host.shutil, 'copystat', concurrent_change)
    with pytest.raises(ValueError, match='changed while preparing repair'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original + b' '
    assert not list(tmp_path.glob('.wayricad-kicad-*'))


def test_apply_refuses_kicad_started_during_staging(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original, settings = host.read_config(path)
    observations = iter([[], ['pcbnew.exe']])
    monkeypatch.setattr(host, 'running_kicad', lambda: next(observations))
    with pytest.raises(ValueError, match='Close KiCad'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original
    backups = list(tmp_path.glob('*.wayricad-backup-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert not list(tmp_path.glob('.wayricad-kicad-*'))


def test_apply_refuses_process_check_failure_during_staging(tmp_path, prerequisite_probe, monkeypatch):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original, settings = host.read_config(path)
    calls = []

    def process_check():
        calls.append(True)
        if len(calls) == 2:
            raise ValueError('Cannot verify KiCad is closed')
        return []

    monkeypatch.setattr(host, 'running_kicad', process_check)
    with pytest.raises(ValueError, match='Cannot verify KiCad is closed'):
        host.apply_repair(path, original, settings, folder / 'pythonw.exe')
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('.wayricad-kicad-*'))


def test_cli_is_preview_only_until_apply(tmp_path, prerequisite_probe, monkeypatch, capsys):
    folder = installation(tmp_path / 'KiCad')
    path = config(tmp_path, '')
    original = path.read_bytes()
    monkeypatch.setattr(host.sys, 'platform', 'win32')
    # This is the Windows CLI boundary, not a probe of the runner's PATH.
    # Changing sys.platform also changes shutil.which's host implementation.
    monkeypatch.setattr(host.shutil, 'which', lambda *args, **kwargs: None)
    monkeypatch.setattr(host, 'running_kicad', lambda: [])
    args = ['--config-file', str(path), '--interpreter', str(folder / 'python.exe'), '--json']
    assert host.main(args) == 1
    assert json.loads(capsys.readouterr().out)['change_required']
    assert path.read_bytes() == original
    assert host.main(args + ['--apply']) == 0
    assert json.loads(capsys.readouterr().out)['applied']


def test_process_inventory_matches_only_kicad_hosts(monkeypatch):
    monkeypatch.setattr(host.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='"pcbnew.exe","2"\n"python.exe","3"\n"KiCad.exe","4"\n', stderr=''))
    assert host.running_kicad() == ['KiCad.exe', 'pcbnew.exe']


def test_process_inventory_failure_refuses_configuration_write(monkeypatch):
    monkeypatch.setattr(host.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='access denied'))
    with pytest.raises(ValueError, match='Cannot verify KiCad is closed'):
        host.running_kicad()
