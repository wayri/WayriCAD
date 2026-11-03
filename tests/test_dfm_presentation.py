"""DFM visual evidence must retain literal labels, limits and source identity."""
from copy import deepcopy
import base64
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from manufacturing_readiness_plugin import checklists
from manufacturing_readiness_plugin.common_checklist import COMMON_CHECKS, with_common_checks
from manufacturing_readiness_plugin.dfm_checks import source_inputs
from manufacturing_readiness_plugin.dfm_dimensions import track_width_dimensions
from manufacturing_readiness_plugin.dfm_present import describe, displayed_status, evidence_entries, family
from manufacturing_readiness_plugin.dfm_report import export_report


ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    board = tmp_path / 'Example.kicad_pcb'; board.write_text('(saved board)')
    board.with_suffix('.kicad_pro').write_text('{}')
    board.with_suffix('.kicad_dru').write_text('(version 1)')
    catalog = json.loads((ROOT / 'manufacturing_readiness_plugin/vendor_catalog.json').read_text(encoding='utf-8'))
    profile = with_common_checks(next(row for row in catalog['profiles'] if row['id'] == 'lion-mii-1oz'))
    profile['name'] = 'Literal & <strong>Fab</strong>'
    context = {'board_type': 'rigid', 'copper_oz': 1, 'layers': 2,
               'copper_basis': 'vendor_order_option'}
    source_sha = source_inputs(board, context)[1]
    document = checklists.new_checklist(profile); document['selected_context'] = deepcopy(context)
    results = [dict(rule_id=rule['id'], status='UNKNOWN', message='Not geometrically checked') for rule in profile['rules']]
    document = checklists.record_run(document, source_sha, results)
    entries = [dict(result, rule=profile['rules'][i]) for i, result in enumerate(checklists.checklist_state(document, source_sha)['results'])]
    finding = {'type': 'silk_overlap', 'severity': 'warning',
               'description': 'Literal <script>alert("x")</script>', 'items': []}
    bundle = dict(source_sha256=source_sha, board_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
                  notice='Unknown & unsupported remain unknown', results=results,
                  findings=[finding], rule_preview=checklists.compile_native_rules(profile, context))
    entries = evidence_entries(document, source_sha, bundle)[2]
    return board, context, bundle, document, entries


def test_all_catalog_profiles_get_23_unsourced_manual_engineering_tasks():
    catalog = json.loads((ROOT / 'manufacturing_readiness_plugin/vendor_catalog.json').read_text(encoding='utf-8'))
    assert len(catalog['profiles']) >= 21
    assert len(COMMON_CHECKS) == 23
    for original in catalog['profiles']:
        before = deepcopy(original)
        profile = with_common_checks(original)
        assert original == before
        generic = [rule for rule in profile['rules'] if rule['id'].startswith('engineering-')]
        assert len(generic) == 23
        assert all(rule['backend'] == 'manual' and rule['minimum'] is None and rule['maximum'] is None
                   and rule['source_ids'] == [] for rule in generic)
        assert all('not a published vendor limit' in rule['notes'] for rule in generic)
        assert checklists.checklist_state(checklists.new_checklist(profile), 'a'*64)['passed'] is False


def test_severity_changes_display_not_recorded_failure():
    warning = dict(status='FAIL', finding={'severity': 'warning', 'type': 'silk_overlap'})
    failure = dict(status='FAIL', rule={'severity': 'error', 'title': 'Copper clearance'})
    unknown = dict(status='UNKNOWN', rule={'severity': 'warning', 'title': 'Assembly access'})
    entries = [warning, failure, unknown]
    assert [displayed_status(row) for row in entries] == ['WARN', 'FAIL', 'UNKNOWN']
    assert sum(displayed_status(row) == 'FAIL' for row in entries) == 1
    assert warning['status'] == 'FAIL'
    assert family(warning) == 'Silkscreen'
    assert family(failure) == 'Routing and copper'
    assert family(unknown) == 'Assembly and placement'


def test_dimension_is_exact_track_width_not_marker_separation():
    def track(uid, kind='PCB_TRACK', start=(0, 0), end=(4e6, 3e6), width=200000):
        return SimpleNamespace(m_Uuid=SimpleNamespace(AsString=lambda: uid), GetClass=lambda: kind,
            GetStart=lambda: SimpleNamespace(x=start[0], y=start[1]),
            GetEnd=lambda: SimpleNamespace(x=end[0], y=end[1]), GetWidth=lambda: width)
    report = track_width_dimensions([track('a'), track('arc', 'PCB_ARC'), track('zero', end=(0, 0)),
                                    track('excluded')], ['a', 'arc', 'zero'], lambda value: value/1e6)
    assert len(report['items']) == 1
    dimension = report['items'][0]
    assert dimension['kind'] == 'track_width' and dimension['actual_mm'] == .2
    assert math.dist(dimension['start_mm'], dimension['end_mm']) == pytest.approx(.2)
    vector = [b-a for a, b in zip(dimension['start_mm'], dimension['end_mm'])]
    assert 4*vector[0]+3*vector[1] == pytest.approx(0)
    assert 'not copper clearances' in report['notice']
    limited = track_width_dimensions([track('a'), track('b')], ['a', 'b'], lambda value: value/1e6, limit=1)
    assert len(limited['items']) == 1 and limited['omitted'] == 1


def test_report_escapes_labels_and_preserves_unknown_manual_status(tmp_path):
    board, context, bundle, document, entries = fixture(tmp_path)
    bundle['snapshot_overrides'] = dict(provider_severities={
        'track_width': dict(original='ignore', applied='error')}, excluded_findings_removed=2)
    output = tmp_path / 'review.html'
    export_report(output, board, context, bundle, document, entries)
    html = output.read_text(encoding='utf-8')
    assert escape(document['profile']['name']) in html
    assert '<strong>Fab</strong>' not in html
    assert '<script>alert("x")</script>' not in html
    assert escape('Literal <script>alert("x")</script>') in html
    assert '<p>WARN</p>' in html
    assert 'WayriCAD engineering checklist item, not a published vendor limit.' in html
    assert 'Unknown and waived items are not verified passing checks.' in html
    assert '<td>track_width</td><td>ignore</td><td>error</td>' in html
    assert 'private copy: 2.' in html
    data = json.loads((tmp_path / 'review.json').read_text())
    assert data['board_sha256'] == hashlib.sha256(board.read_bytes()).hexdigest()
    assert data['source_sha256'] != data['board_sha256']
    assert data['snapshot_overrides'] == bundle['snapshot_overrides']
    assert sum(row['status'] == 'UNKNOWN' for row in data['checklist']['run']['results']) == len(document['profile']['rules'])


@pytest.mark.parametrize('changed', ['board', 'project', 'rules', 'context'])
def test_stale_source_or_context_preserves_existing_outputs(tmp_path, changed):
    board, context, bundle, document, entries = fixture(tmp_path)
    output = tmp_path / 'review.html'; output.write_text('previous HTML')
    evidence = tmp_path / 'review.json'; evidence.write_text('previous evidence')
    original_board = board.read_bytes()
    if changed == 'context': context['copper_oz'] = 2
    else:
        path = board if changed == 'board' else board.with_suffix('.kicad_pro' if changed == 'project' else '.kicad_dru')
        path.write_bytes(path.read_bytes()+b' changed')
    with pytest.raises(ValueError): export_report(output, board, context, bundle, document, entries)
    assert output.read_text() == 'previous HTML' and evidence.read_text() == 'previous evidence'
    if changed != 'board': assert board.read_bytes() == original_board


def test_mid_pdf_generation_source_change_does_not_publish_partial_set(tmp_path):
    pytest.importorskip('reportlab')
    board, context, bundle, document, entries = fixture(tmp_path)
    for extension in ('html', 'json', 'pdf'): (tmp_path / ('review.'+extension)).write_text('previous '+extension)
    original = board.read_bytes()
    def render(_html, **kwargs):
        board.with_suffix('.kicad_dru').write_text('changed during rendering')
        return b'%PDF-test'
    with patch('wayricad_runtime.pdf_report.pdf_bytes', side_effect=render):
        with pytest.raises(ValueError, match='changed'): export_report(tmp_path / 'review.pdf', board, context, bundle, document, entries)
    assert all((tmp_path / ('review.'+extension)).read_text() == 'previous '+extension for extension in ('html', 'json', 'pdf'))
    assert board.read_bytes() == original


def test_report_cannot_overwrite_source_through_hardlink(tmp_path):
    board, context, bundle, document, entries = fixture(tmp_path)
    output = tmp_path / 'alias.html'
    try: os.link(board, output)
    except OSError as exc: pytest.skip('Hardlink unavailable: '+str(exc))
    original = board.read_bytes()
    with pytest.raises(ValueError, match='overwrite'): export_report(output, board, context, bundle, document, entries)
    assert board.read_bytes() == original and output.read_bytes() == original


def test_mismatched_profile_or_context_packet_is_rejected(tmp_path):
    board, context, bundle, document, entries = fixture(tmp_path)
    changed = deepcopy(document); changed['profile']['name'] += ' changed'
    with pytest.raises(ValueError, match='profile'): export_report(tmp_path/'profile.html', board, context, bundle, changed, entries)
    changed = deepcopy(document); changed['selected_context']['layers'] = 4
    with pytest.raises(ValueError, match='Checklist evidence'): export_report(tmp_path/'context.html', board, context, bundle, changed, entries)


def test_injected_entries_cannot_replace_current_evidence(tmp_path):
    board, context, bundle, document, entries = fixture(tmp_path)
    export_report(tmp_path/'review.html', board, context, bundle, document,
                  [dict(status='PASS', message='FORGED RESULT', rule={'title': 'FORGED RESULT'})])
    html = (tmp_path/'review.html').read_text(encoding='utf-8')
    assert 'FORGED RESULT' not in html
    assert 'WayriCAD engineering checklist item, not a published vendor limit.' in html
    assert '<p>UNKNOWN</p>' in html


@pytest.mark.parametrize('payload', ['AA==" onerror="alert(1)', base64.b64encode(b'not a PNG').decode('ascii'),
    base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\0'*8+(100000).to_bytes(4,'big')+(100000).to_bytes(4,'big')).decode('ascii')])
def test_bad_or_oversized_board_image_cannot_publish(tmp_path, payload):
    board, context, bundle, document, entries = fixture(tmp_path)
    with pytest.raises(ValueError):
        export_report(tmp_path/'image.html', board, context, bundle, document, entries, board_png=payload)
    assert not (tmp_path/'image.html').exists() and not (tmp_path/'image.json').exists()


def test_report_cannot_replace_loaded_checklist_input(tmp_path):
    board, context, bundle, document, entries = fixture(tmp_path)
    checklist_input = tmp_path/'review.json'; checklist_input.write_text('saved checklist input')
    with pytest.raises(ValueError, match='overwrite'):
        export_report(tmp_path/'review.html', board, context, bundle, document, entries,
                      protected_sources=[checklist_input])
    assert checklist_input.read_text() == 'saved checklist input'
    assert not (tmp_path/'review.html').exists()
