import json
from types import SimpleNamespace

import pytest

from wayricad_runtime import cli, verification


@pytest.mark.parametrize('accepted,code', [(True, 0), (False, 1)])
def test_verify_without_pcbnew(monkeypatch, capsys, accepted, code):
    monkeypatch.setattr(cli, 'load_api', lambda: pytest.fail('verify imported pcbnew'))
    def verify(board, output, **kwargs):
        assert (board, output) == ('board.kicad_pcb', 'drc.json')
        assert kwargs == dict(baseline='before.json', kicad_cli='native-cli', timeout=42)
        return {'accepted': accepted, 'clean': False}
    monkeypatch.setattr(verification, 'verify_board', verify)
    assert cli.main(['verify', '--board', 'board.kicad_pcb', '--output', 'drc.json',
                     '--baseline', 'before.json', '--kicad-cli', 'native-cli', '--timeout', '42']) == code
    assert json.loads(capsys.readouterr().out)['accepted'] is accepted


def test_verify_failure_is_json(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise verification.VerificationError('Engine timed out')
    monkeypatch.setattr(verification, 'verify_board', fail)
    assert cli.main(['verify', '--board', 'board.kicad_pcb', '--output', 'drc.json']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'failed' and result['accepted'] is False
    assert result['error'] == 'Engine timed out'


def test_plan_preserves_group_outcomes(tmp_path, monkeypatch):
    board = tmp_path / 'board.kicad_pcb'; board.touch()
    document = {'candidates': [1], 'rejected': ['blocked'],
                'group_summary': [{'name': 'Power', 'accepted': 1}],
                'unmatched_count': 3, 'skipped_count': 3}
    monkeypatch.setattr(cli, 'load_api', lambda: SimpleNamespace(LoadBoard=lambda _: object()))
    monkeypatch.setattr(cli, 'plan_document', lambda *args: document)
    result = cli.execute(SimpleNamespace(kind='fanout', operation='plan', board=str(board),
                         settings=None, output=str(tmp_path / 'plan.json'), svg=None))
    for key in ('group_summary', 'unmatched_count', 'skipped_count'):
        assert result[key] == document[key]


def test_group_settings_example_is_valid():
    from wayricad_runtime.fanout_groups import validate_groups
    result = cli.execute(SimpleNamespace(kind='fanout', operation='settings', board=None))
    example = result['group_rules']['example']
    validate_groups(example['groups'], example['unmatched'], result['defaults'])
