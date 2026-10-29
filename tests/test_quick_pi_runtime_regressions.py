"""PI GUI dependency and solve-time producer custody regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quick_pi_plugin import service
from quick_pi_plugin.console import _rl
from quick_pi_plugin.series_editor import rl_model, selected_component_references
from wayricad_runtime import bootstrap, context, runtime_setup
from wayricad_runtime.pocket_report import evidence_context, producer_version
from wayricad_runtime.project_results import load_result
from wayricad_runtime.project_results_ui import save_project_simulation


@pytest.mark.parametrize('connected', [False, True])
def test_saved_board_gui_provisions_ipc_only_with_originating_editor(monkeypatch, connected):
    monkeypatch.delenv('KICAD_API_SOCKET', raising=False)
    monkeypatch.delenv('KICAD_API_TOKEN', raising=False)
    if connected:
        monkeypatch.setenv('KICAD_API_SOCKET', 'ipc://originating-editor')
        monkeypatch.setenv('KICAD_API_TOKEN', 'test-origin-token')
    with patch.object(runtime_setup, 'ensure_runtime', return_value=Path('fake-python')) as ensure, \
         patch.object(bootstrap.subprocess, 'call', return_value=0):
        bootstrap.relaunch(Path('plugin'), 'desktop_entrypoint.py', profile='quick-pi-board')
    assert ('kipy' in ensure.call_args.args[0]) is connected
    assert ('kipy' in runtime_setup.REQUIREMENTS_QUICK_PI)


def test_missing_editor_context_reports_origin_error_before_optional_sdk(monkeypatch):
    monkeypatch.delenv('KICAD_API_SOCKET', raising=False)
    monkeypatch.delenv('KICAD_API_TOKEN', raising=False)
    monkeypatch.setitem(sys.modules, 'kipy', None)
    with pytest.raises(RuntimeError, match='No originating KiCad connection'):
        context.connect()


def test_series_component_selection_uses_exact_origin_and_rejects_changed_board(tmp_path, monkeypatch):
    board = tmp_path/'example.kicad_pcb';board.touch()
    footprint = SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value='L1')))
    client = SimpleNamespace(get_board=lambda: SimpleNamespace(get_selection=lambda: [footprint]))
    monkeypatch.setattr(context, 'connect', lambda: client)
    monkeypatch.setattr(context, 'saved_board', lambda caller: board.resolve())
    assert selected_component_references(board) == ['L1']
    monkeypatch.setattr(context, 'saved_board', lambda caller: board.with_name('other.kicad_pcb'))
    with pytest.raises(ValueError, match='changed boards'):
        selected_component_references(board)


def test_source_and_flat_pcm_versions_are_static_without_running_initializer(tmp_path):
    plugin = tmp_path/'plugins';plugin.mkdir()
    (plugin/'__init__.py').write_text("__version__ = '6.7.8'\nraise RuntimeError('must not execute')\n")
    assert producer_version(module_file=plugin/'ui.py') == '6.7.8'
    (plugin/'__init__.py').write_text("__version__ = compute_version()\n")
    assert producer_version(module_file=plugin/'ui.py') is None
    (tmp_path/'metadata.json').write_text(json.dumps({'versions': [{'version': '7.8.9'}]}))
    assert producer_version(module_file=plugin/'ui.py') == '7.8.9'


def test_execute_records_actual_version_before_analysis_and_preserves_unknown(monkeypatch):
    observed = []
    def calculate(request, **kwargs):
        observed.append(request)
        monkeypatch.setattr(service, '__package__', 'unavailable_package')
        return {'result': {'potential_V': [1., None]}}
    with patch('wayricad_runtime.pocket_report.producer_version', return_value='4.5.6') as version, \
         patch.object(service, '_execute', side_effect=calculate):
        result = service.execute({'action': 'solve'})
    assert result['producer_version'] == '4.5.6'
    assert observed == [{'action': 'solve'}]
    version.assert_called_once()
    with patch('wayricad_runtime.pocket_report.producer_version', return_value=None), \
         patch.object(service, '_execute', return_value={'result': {}}):
        assert service.execute({})['producer_version'] is None


def bound(tmp_path, version='4.5.6'):
    board = tmp_path/'example.kicad_pcb';board.write_bytes(b'saved fixture')
    return board, {'request': {'board_path': str(board)},
                   'source_sha256': hashlib.sha256(board.read_bytes()).hexdigest(),
                   'producer_version': version, 'result': {'potential_V': [1., None, 0.]}}


def test_result_version_survives_installed_package_update_and_rejects_relabeling(tmp_path):
    board, bundle = bound(tmp_path)
    with patch('wayricad_runtime.pocket_report.producer_version', return_value='99.0'):
        assert evidence_context(bundle, tool='Quick PI', module_file='ui.py')['version'] == '4.5.6'
    with pytest.raises(ValueError, match='conflicts with the original result'):
        evidence_context(bundle, tool='Quick PI', version='99.0')
    bundle['producer_version'] = None
    with pytest.raises(ValueError, match='version is unavailable'):
        evidence_context(bundle, tool='Quick PI', package=SimpleNamespace(__version__='99.0'))


def test_archive_retains_unknown_version_without_granting_portable_certificate(tmp_path):
    board, bundle = bound(tmp_path, None);before = deepcopy(bundle)
    receipt = save_project_simulation(tmp_path, 'quick-pi', bundle, board_path=board)
    saved = load_result(tmp_path, receipt['path'], plugin='quick-pi')
    expected = deepcopy(before);expected['request']['board_path'] = board.name
    assert saved['bundle'] == expected
    assert saved['receipt']['producer_version'] is None
    assert saved['receipt']['source_state'] == 'unverified'
    assert 'version is unavailable' in receipt['portable_export_unavailable']
    assert bundle == before


def test_archive_certifies_valid_result_and_retains_stale_result_only_as_unverified(tmp_path):
    board, bundle = bound(tmp_path)
    receipt = save_project_simulation(tmp_path, 'quick-pi', bundle, board_path=board)
    assert receipt['source_state'] == 'current'
    assert load_result(tmp_path, receipt['path'])['receipt']['producer_version'] == '4.5.6'
    board.write_bytes(b'changed board')
    stale = save_project_simulation(tmp_path, 'quick-pi', bundle, board_path=board)
    assert stale['source_state'] == 'unverified'
    assert stale['portable_export_unavailable']
    expected = deepcopy(bundle);expected['request']['board_path'] = board.name
    assert load_result(tmp_path, stale['path'])['bundle'] == expected


def test_unbound_study_archive_retains_values_and_never_invents_source(tmp_path):
    board, bundle = bound(tmp_path)
    bundle.pop('source_sha256');bundle['source_state'] = 'unbound'
    receipt = save_project_simulation(tmp_path, 'quick-pi', bundle, board_path=board)
    assert receipt['source_state'] == 'unverified'
    expected = deepcopy(bundle);expected['request']['board_path'] = board.name
    assert load_result(tmp_path, receipt['path'])['bundle'] == expected


@pytest.mark.parametrize('resistance,inductance', [('1m','1p'), ('1m+1p',''), ('','1p'), ('1mH',''), ('1m','1mH+1pH')])
def test_series_fields_reject_ambiguous_or_wrong_units(resistance, inductance):
    with pytest.raises(ValueError, match='one quantity per field.*explicit H unit'):
        rl_model(resistance, inductance)


def test_series_fields_preserve_explicit_quantities_and_scientific_notation():
    assert _rl(rl_model('1mΩ','1pH')) == {'resistance_ohm': .001, 'inductance_h': 1e-12}
    assert _rl(rl_model('', '1e+1nH'))['inductance_h'] == 1e-8
    assert _rl(rl_model('5m', ''))['resistance_ohm'] == .005
    with pytest.raises(ValueError, match='positive'):
        rl_model('0Ω', '0H')


@pytest.fixture
def multipad_inventory():
    return {'nets': ['VIN', 'MID', 'GATE'], 'terminals': [
        {'id': 'source', 'label': 'J1.1', 'net': 'VIN'},
        {'id': 'entry', 'label': 'Q1.1', 'net': 'VIN', 'footprint_uuid': 'q1'},
        {'id': 'exit', 'label': 'Q1.2', 'net': 'MID', 'footprint_uuid': 'q1'},
        {'id': 'gate', 'label': 'Q1.3', 'net': 'GATE', 'footprint_uuid': 'q1'},
        {'id': 'same', 'label': 'Q1.4', 'net': 'VIN', 'footprint_uuid': 'q1'},
        {'id': 'sink', 'label': 'U1.1', 'net': 'MID'}]}


def test_explicit_multipad_path_uses_only_reviewed_pair_and_supports_saved_path(multipad_inventory):
    from quick_pi_plugin.series_editor import build_command, reviewed_pair, SeriesPathDialog
    from quick_pi_plugin.console import parse_command
    inventory = multipad_inventory
    reference, entry, exit_pad = reviewed_pair(inventory, 'VIN', 'entry', 'exit')
    stages = [{'reference': reference, 'from_pad': entry['id'], 'to_pad': exit_pad['id'], 'model': '10mΩ'}]
    command = build_command('J1.1', 'U1.1', json.loads(json.dumps(stages)))
    request = parse_command(command, inventory)
    assert request['series'] == [{'id': 'Q1', 'from_pad': 'entry', 'to_pad': 'exit',
                                 'resistance_ohm': .01, 'inductance_h': 0.}]
    assert 'gate' not in command and 'same' not in command
    controller = object.__new__(SeriesPathDialog)
    controller.inventory = inventory;controller.branches = stages
    controller._chosen = lambda control: 'J1.1';controller.source = object()
    assert controller._cursor_net() == 'MID'
    assert controller._parallel_candidates(0) == []


@pytest.mark.parametrize('entry,exit_pad,pattern', [
    ('entry','same','distinct current terminals'),
    ('entry','sink','same component'),
    ('exit','entry','distinct current terminals'),
    ('missing','exit','unambiguous saved pad')])
def test_explicit_pair_rejects_disconnected_ambiguous_or_wrong_component(multipad_inventory, entry, exit_pad, pattern):
    from quick_pi_plugin.series_editor import reviewed_pair
    with pytest.raises(ValueError, match=pattern):
        reviewed_pair(multipad_inventory, 'VIN', entry, exit_pad)
