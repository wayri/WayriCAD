"""RLC CLI error/status and report safety contracts without a native runtime."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from trace_impedance_plugin import cli


@pytest.mark.parametrize('status,expected', [('ok', 0), ('partial', 3), ('disconnected', 2)])
def test_status_preserved_in_json(tmp_path, status, expected):
    source = tmp_path / 'board.kicad_pcb'
    source.write_text('original copper', encoding='utf-8')
    output = tmp_path / 'result.json'
    document = {'result': {'status': status, 'capacitance_pf': None}}
    with patch.object(cli, 'analyze', return_value=document):
        assert cli.main(['path', str(source), '--net', 'GND', '--start', 'U1.1',
                         '--end', 'J1.1', '--output', str(output)]) == expected
    assert json.loads(output.read_text()) == document
    assert source.read_text() == 'original copper'


def test_report_rejects_design_and_nonfinite_values(tmp_path):
    source = tmp_path / 'board.kicad_pcb'
    source.write_text('original copper')
    with pytest.raises(ValueError):
        cli.write_report(source, {'result': {}}, source)
    output = tmp_path / 'result.json'
    output.write_text('previous report')
    with pytest.raises(ValueError):
        cli.write_report(output, {'result': {'r': float('nan')}}, source)
    assert output.read_text() == 'previous report'
    assert source.read_text() == 'original copper'


def test_missing_board_returns_actionable_error(tmp_path, capsys):
    assert cli.main(['inspect', str(tmp_path / 'missing.kicad_pcb')]) == 1
    assert 'existing .kicad_pcb' in capsys.readouterr().err


def test_independent_si_bundle_uses_current_engine():
    root = Path(__file__).resolve().parents[1]
    for name in ('measurement.py', 'rlc_model.py', 'copper_path.py'):
        assert (root / 'trace_impedance_plugin' / name).read_bytes() == (
            root / 'signal_integrity_advisor_plugin' / name).read_bytes(), (
                'Run tools/prepare_suite.py to synchronize the independent SI bundle')
