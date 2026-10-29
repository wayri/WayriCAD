"""Full numerical SI saves, exact PCB custody and portable viewer bindings."""
import copy
import hashlib
import json
from unittest.mock import patch

import pytest

from signal_integrity_advisor_plugin.saved_results import write_results
from signal_integrity_advisor_plugin.service import bind_saved_result, source_fingerprints


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'controller.kicad_pcb'
    path.write_bytes(b'(kicad_pcb (version 20240108))\n')
    return path


@pytest.fixture
def report():
    # Custody/serialization fixture, not a solver-accuracy claim.
    return {'schema': 'wayricad.quick-si/v1', 'status': 'APPROXIMATE',
            'path': {'net_name': '/Front outputs/SLOT1', 'start_pad': 'J2.1', 'end_pad': 'U1.7',
                     'segments': [{'length_mm': 12.5, 'impedance_ohm': 49.2},
                                  {'length_mm': 0.4, 'impedance_ohm': None}]},
            'eye': {'time_ui': [0., 0.5, 1.], 'traces_v': [[0., None, 1.2]]},
            'notes': ['Via reflection remains unknown.'], 'blockers': [{'code': 'VIA_UNMODELED'}]}


def test_saved_export_retains_samples_bindings_and_input_bytes(source, report, tmp_path):
    fingerprints = source_fingerprints(source)
    original = copy.deepcopy(report)
    before = source.read_bytes()
    with patch('signal_integrity_advisor_plugin.saved_results.report_document', return_value='<h1>Quick SI</h1>'):
        result = write_results(tmp_path / 'si.html', report, board_path=source,
                               fingerprints=fingerprints, saved=True)
    complete = json.loads((tmp_path / 'si.json').read_text())
    portable = json.loads((tmp_path / 'si.pocket-kivi.json').read_text())
    assert result['pocket_kivi_json'].endswith('si.pocket-kivi.json')
    assert complete['path'] == portable['path'] == original['path']
    assert complete['eye'] == portable['eye'] == original['eye']
    assert portable['source_path'] == source.name
    assert portable['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert portable['pocket_kivi_export']['tool'] == 'quick-si'
    assert portable['pocket_kivi_export']['units']['time_ui'] == 'UI'
    assert source.read_bytes() == before and report == original
    assert 'Download' in (tmp_path / 'si.html').read_text()


def test_saved_export_rejects_rules_or_board_change(source, report, tmp_path):
    fingerprints = source_fingerprints(source)
    source.with_suffix('.kicad_dru').write_text('(version 1)')
    with pytest.raises(ValueError, match='rules changed'):
        write_results(tmp_path / 'si.html', report, board_path=source, fingerprints=fingerprints, saved=True)
    assert not (tmp_path / 'si.html').exists()


def test_saved_export_never_rebinds_foreign_report(source, report, tmp_path):
    report['source_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='different saved PCB'):
        write_results(tmp_path / 'si.html', report, board_path=source,
                      fingerprints=source_fingerprints(source), saved=True)


def test_live_export_keeps_full_json_but_does_not_invent_pcb_hash(report, tmp_path):
    with patch('signal_integrity_advisor_plugin.saved_results.report_document', return_value='<h1>Quick SI</h1>'):
        result = write_results(tmp_path / 'live.html', report, saved=False)
    value = json.loads((tmp_path / 'live.json').read_text())
    assert value['eye'] == report['eye'] and value['path'] == report['path']
    assert 'source_sha256' not in value and 'pocket_kivi_json' not in result
    assert value['export_source_state'] == 'live-unverified'


def test_live_export_cannot_misrepresent_saved_evidence(report, tmp_path):
    report['source_sha256'] = 'a' * 64
    with pytest.raises(ValueError, match='Live Quick SI'):
        write_results(tmp_path / 'live.html', report, saved=False)


def test_study_export_preserves_all_cases_and_failed_entries(source, tmp_path):
    value = {'schema': 'wayricad.quick-si-study/v1', 'status': 'REVIEW', 'cases': [
        {'id': 'positive', 'net': '/USB/D+', 'status': 'SCREENED', 'report': {'delay_ns': 1.23}},
        {'id': 'negative', 'net': '/USB/D-', 'status': 'FAILED', 'error': 'Route unavailable'}]}
    with patch('signal_integrity_advisor_plugin.saved_results.report_document', return_value='<h1>SI study</h1>') as render:
        write_results(tmp_path / 'study.html', value, board_path=source,
                      fingerprints=source_fingerprints(source), saved=True, study=True)
    assert render.call_args.kwargs['study'] is True
    portable = json.loads((tmp_path / 'study.pocket-kivi.json').read_text())
    assert portable['cases'] == value['cases']


def test_binding_uses_given_solve_fingerprint_not_a_fresh_hash(source, report):
    fingerprints = source_fingerprints(source)
    value = bind_saved_result(report, source, fingerprints)
    assert value['source_sha256'] == fingerprints[str(source.resolve())]
    assert value['source_path'] == str(source.resolve())
    assert 'source_sha256' not in report
    with pytest.raises(ValueError):
        bind_saved_result(report, source, {'study_sha256': fingerprints[str(source.resolve())]})
