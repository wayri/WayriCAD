"""Bulk worker lifecycle, source guards and complete per-net report evidence."""
import json
import threading

import pytest

from trace_impedance_plugin.bulk_ui import BulkController, export_report, report_html, source_fingerprints, verify_sources


def document(tmp_path):
    source = tmp_path / 'Example.kicad_pcb'; source.write_text('saved board')
    fingerprints = source_fingerprints(source)
    section = dict(section_id='uuid:0', item_uuid='uuid', layer='F.Cu', kind='track', status='partial',
                   length_mm=10., start_mm=[0., 0.], end_mm=[10., 0.], width_mm=.2,
                   resistance_ohm=.1, resistance_ac_ohm=.2, inductance_nh=None, capacitance_pf=None,
                   impedance_ohm=None, reference_candidates=[dict(net='RETURN', layer='B.Cu', island_id='plane:2:0')],
                   blockers=[dict(code='UNKNOWN_REFERENCE', message='Return continuity unverified')])
    return dict(board_path=str(source), source_sha256=fingerprints[str(source)], source_files=fingerprints,
                result=dict(status='partial', frequency_mhz=100., limitations=['No coupled field solve'],
                    bundles=[dict(name='Bus', nets=['/Hierarchy/D0'], notice='Independent sections only')],
                    nets=[dict(net='/Hierarchy/D0', display_name='/Hierarchy/D0', status='partial',
                               sections=[section], pads=['J1.1', 'U1.2'], zones=[])],
                    coverage=dict(extracted_sections=1, complete=True)))


def test_project_and_rule_creation_invalidate_result(tmp_path):
    source = tmp_path / 'Example.kicad_pcb'; source.write_text('board')
    before = source_fingerprints(source)
    source.with_suffix('.kicad_dru').write_text('(version 1)')
    with pytest.raises(ValueError, match='rules changed'): verify_sources(before)
    current = source_fingerprints(source)
    source.with_suffix('.kicad_pro').write_text('{}')
    with pytest.raises(ValueError, match='rules changed'): verify_sources(current)


def test_controller_delivers_error_and_rejects_duplicate_work():
    controller = BulkController(); queued = []; finished = []
    dispatch = lambda callback, *args: queued.append((callback, args))
    def fail(cancelled, progress): raise ValueError('unsupported geometry')
    controller.start(fail, lambda value, error: finished.append((value, error)), dispatch)
    controller.thread.join(2)
    with pytest.raises(ValueError): controller.start(fail, lambda *args: None, dispatch)
    for callback, args in queued: callback(*args)
    assert finished == [(None, 'unsupported geometry')]
    assert not controller.busy


def test_cancel_and_close_suppress_late_callbacks():
    controller = BulkController(); queued = []; finished = []; started = threading.Event(); release = threading.Event()
    def operation(cancelled, progress):
        started.set(); release.wait(2); progress(1, 2); return cancelled()
    controller.start(operation, lambda *args: finished.append(args), lambda callback, *args: queued.append((callback, args)), progress=lambda *args: finished.append(args))
    assert started.wait(2)
    controller.cancel(); release.set(); controller.thread.join(2); controller.close()
    for callback, args in queued: callback(*args)
    assert not finished


def test_html_preserves_full_net_pins_reference_and_unknown_units(tmp_path):
    html = report_html(document(tmp_path))
    assert 'Net: /Hierarchy/D0' in html
    assert 'J1.1, U1.2' in html
    assert 'Unknown nH' in html and 'Unknown pF' in html and 'Unknown ohm' in html
    assert 'RETURN / B.Cu / plane:2:0' in html
    assert '<svg ' in html


def test_paired_html_json_export_rejects_stale_source(tmp_path):
    data = document(tmp_path); output = tmp_path / 'study.html'
    paths = export_report(output, data)
    assert output.is_file() and json.loads((tmp_path / 'study.json').read_text()) == data
    before = output.read_bytes()
    (tmp_path / 'Example.kicad_pro').write_text('{}')
    with pytest.raises(ValueError): export_report(output, data)
    assert output.read_bytes() == before


def test_pdf_preserves_geometry_as_lossless_png(tmp_path):
    pytest.importorskip('reportlab')
    pytest.importorskip('PIL')
    paths = export_report(tmp_path / 'study.pdf', document(tmp_path), pdf=True)
    assert (tmp_path / 'study.pdf').read_bytes().startswith(b'%PDF-')
    assert 'data:image/png;base64,' in (tmp_path / 'study.html').read_text()
    assert paths['pdf'].endswith('study.pdf')
