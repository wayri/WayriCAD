"""Behavioral checks for read-only analysis of newer saved boards."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from wayricad_runtime import pocket_kivi_export, project_results, saved_board


def pcb(version):
    return f'(kicad_pcb (version {version}) (generator "test"))\n'.encode()


class Board:
    def SetFileName(self, name):
        self.filename = name


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_board.tempfile, 'tempdir', str(tmp_path))
    source = tmp_path / 'design.kicad_pcb'
    source.write_bytes(pcb(20261031))
    source.with_suffix('.kicad_pro').write_text('{"text_variables": {"TITLE": "project"}}')
    source.with_suffix('.kicad_dru').write_text('rules')
    converter = tmp_path / 'kicad-cli'
    converter.write_bytes(b'converter')
    monkeypatch.setenv(saved_board.CLI_ENV, str(converter))
    monkeypatch.delenv('KICAD_CLI', raising=False)
    monkeypatch.delenv(saved_board.HOST_ENV, raising=False)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == '--version':
            return SimpleNamespace(returncode=0, stdout='11.0.0\n', stderr='')
        output = Path(command[command.index('--output') + 1])
        output.write_bytes(pcb(20260206))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(saved_board.subprocess, 'run', run)
    return SimpleNamespace(source=source, converter=converter, calls=calls, run=run)


def native(loader):
    return SimpleNamespace(LoadBoard=loader)


def test_direct_proxy_does_not_invent_a_conversion_lease():
    board=Mock()
    saved_board.assert_current(board)
    assert saved_board.provenance(board) is None


def test_native_board_loads_directly_without_converter(setup, monkeypatch):
    setup.source.write_bytes(pcb(20260206))
    monkeypatch.delenv(saved_board.CLI_ENV)
    result = Board()
    paths = []
    assert saved_board.load_board(setup.source, pcbnew=native(lambda p: paths.append(p) or result)) is result
    assert paths == [str(setup.source.resolve())]
    assert not setup.calls
    assert saved_board.provenance(result) is None


def test_conversion_preserves_origin_and_snapshot_lifetime(setup):
    original = setup.source.read_bytes()
    loaded = []

    def load(path):
        loaded.append(Path(path))
        assert Path(path).read_bytes() == pcb(20260206)
        assert json.loads(Path(path).with_suffix('.kicad_pro').read_text())['text_variables']['TITLE'] == 'project'
        assert Path(path).with_suffix('.kicad_dru').read_text() == 'rules'
        return Board()

    board = saved_board.load_board(setup.source, pcbnew=native(load))
    assert board.filename == str(setup.source.resolve())
    assert setup.source.read_bytes() == original
    assert loaded[0].is_file()
    assert loaded[0] != setup.source
    record = saved_board.provenance(board)
    assert record['source_path'] == str(setup.source.resolve())
    assert record['source_sha256'] == hashlib.sha256(original).hexdigest()
    assert record['source_format'] == 20261031
    assert record['analysis_format'] == 20260206
    assert record['converter_path'] == str(setup.converter.resolve())
    assert record['converter_version'] == '11.0.0'
    assert record['target'] == '10.0'
    record['source_fingerprints'].clear()
    assert saved_board.provenance(board)['source_fingerprints']
    command = setup.calls[1]
    assert command[1:5] == ['pcb', 'downgrade', '--target', '10.0']
    assert not any('force' in arg.lower() or 'drop' in arg.lower() for arg in command)
    saved_board.assert_current(board)
    board._wayricad_saved_board.temporary.cleanup()
    assert not loaded[0].exists()


def test_missing_converter_fails_with_actionable_diagnostic(setup, monkeypatch):
    monkeypatch.delenv(saved_board.CLI_ENV)
    with pytest.raises(ValueError, match='KICAD_CLI'):
        saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    monkeypatch.setenv(saved_board.CLI_ENV, str(setup.source.parent / 'missing'))
    with pytest.raises(ValueError, match='does not exist'):
        saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))


@pytest.mark.parametrize('version,host', [('10.0.0', None), ('11.0.0', '11.1.0'), ('unknown', None)])
def test_wrong_converter_version_is_rejected(setup, monkeypatch, version, host):
    if host:
        monkeypatch.setenv(saved_board.HOST_ENV, host)
    monkeypatch.setattr(saved_board.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=version, stderr=''))
    with pytest.raises(ValueError, match='CLI'):
        saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))


@pytest.mark.parametrize('failure', ['nonzero', 'missing', 'newer', 'invalid', 'native'])
def test_conversion_failures_refuse_board_and_cleanup(setup, monkeypatch, failure):
    output_paths = []

    def run(command, **kwargs):
        if command[-1] == '--version':
            return SimpleNamespace(returncode=0, stdout='11.0.0', stderr='')
        output = Path(command[command.index('--output') + 1])
        output_paths.append(output)
        if failure == 'nonzero':
            return SimpleNamespace(returncode=1, stdout='', stderr='lossy conversion refused')
        if failure != 'missing':
            output.write_bytes(pcb(20261031) if failure == 'newer' else
                               b'not a board' if failure == 'invalid' else pcb(20260206))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(saved_board.subprocess, 'run', run)
    with pytest.raises(ValueError):
        saved_board.load_board(setup.source, pcbnew=native(lambda _: None))
    assert output_paths and not output_paths[0].parent.parent.exists()
    assert setup.source.read_bytes() == pcb(20261031)


@pytest.mark.parametrize('suffix', ['.kicad_pcb', '.kicad_pro', '.kicad_dru'])
def test_changed_inputs_are_rejected(setup, suffix):
    board = saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    setup.source.with_suffix(suffix).write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        saved_board.assert_current(board)


def test_converter_change_invalidates_cache_and_live_snapshot(setup):
    key = saved_board.cache_identity(setup.source)
    board = saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    setup.converter.write_bytes(b'updated converter')
    assert saved_board.cache_identity(setup.source) != key
    with pytest.raises(ValueError, match='changed'):
        saved_board.assert_current(board)


@pytest.mark.parametrize('expression', ['${DRILL_SITES}', '@{1mils}'])
def test_project_expression_cannot_bypass_the_initial_cli_loss_gate(setup, expression):
    setup.source.with_suffix('.kicad_pro').write_text(json.dumps({'text_variables': {'ALIAS': expression}}))
    with pytest.raises(ValueError, match='text-variable expressions'):
        saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    assert not setup.calls


@pytest.mark.parametrize('suffix', ['.kicad_pro', '.kicad_dru'])
def test_converted_provenance_stays_portable_and_checks_saved_sources(setup, suffix):
    board = saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    provenance = saved_board.provenance(board)
    digest = provenance['source_sha256']
    bundle = {'request': {'board_path': str(setup.source)}, 'source_sha256': digest,
              'saved_board_provenance': provenance, 'result': {'potential_V': [3.3]}}
    evidence = dict(board_path=setup.source, source_sha256=digest, tool='Quick PI',
                    version='1.2.3', source_state='saved')
    payload = json.loads(pocket_kivi_export.portable_json(bundle, **evidence))
    fingerprints = payload['saved_board_provenance']['source_fingerprints']
    assert set(fingerprints) == {'design.kicad_pcb', 'design.kicad_pro', 'design.kicad_dru'}
    assert all(not Path(key).is_absolute() for key in fingerprints)

    receipt = project_results.save_result(setup.source.parent, 'pi', bundle, pocket_kivi=evidence)
    saved = json.loads(Path(receipt['path']).read_bytes())
    assert set(saved['saved_board_provenance']['source_fingerprints']) == set(fingerprints)
    assert project_results.load_result(setup.source.parent, receipt['path'])['receipt']['source_state'] == 'current'

    original = setup.source.read_bytes()
    setup.source.with_suffix(suffix).write_bytes(b'changed project input')
    assert setup.source.read_bytes() == original
    with pytest.raises(ValueError, match='changed'):
        pocket_kivi_export.portable_json(bundle, **evidence)
    loaded = project_results.load_result(setup.source.parent, receipt['path'])
    assert loaded['receipt']['source_state'] == 'stale'
    assert not loaded['receipt']['can_restore']
    assert any(suffix in issue for issue in loaded['receipt']['source_issues'])


def test_origin_environment_binds_matching_editor_and_clears_stale(setup):
    class Client:
        def __init__(self, major, minor):
            self.version = SimpleNamespace(major=major, minor=minor, patch=0)

        def get_version(self):
            return self.version

        def get_kicad_binary_path(self, name):
            assert name == 'kicad-cli'
            return str(setup.converter)

    env = {saved_board.CLI_ENV: 'stale', saved_board.HOST_ENV: 'stale',
           'KICAD_CLI': 'unrelated converter', 'OTHER': 'kept'}
    bound = saved_board.origin_environment(Client(11, 0), env)
    assert bound == {saved_board.CLI_ENV: str(setup.converter.resolve()),
                     saved_board.HOST_ENV: '11.0.0', 'OTHER': 'kept'}
    assert saved_board.origin_environment(Client(10, 0), env) == {'OTHER': 'kept'}
    assert env[saved_board.CLI_ENV] == 'stale'


def test_explicit_standalone_cli_fallback_remains_available(setup, monkeypatch):
    monkeypatch.delenv(saved_board.CLI_ENV)
    monkeypatch.setenv('KICAD_CLI', str(setup.converter))
    board = saved_board.load_board(setup.source, pcbnew=native(lambda _: Board()))
    assert saved_board.provenance(board)['converter_path'] == str(setup.converter.resolve())


def test_origin_environment_missing_cli_is_actionable(setup):
    client = SimpleNamespace(get_version=lambda: SimpleNamespace(major=11, minor=0, patch=0),
                             get_kicad_binary_path=lambda _: str(setup.source.parent / 'missing'))
    with pytest.raises(ValueError, match='originating KiCad editor.*analysis CLI'):
        saved_board.origin_environment(client, {})
