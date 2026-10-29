"""Complete Quick SI numerical saves with explicit saved/live source custody."""
from __future__ import annotations

import copy
from pathlib import Path


UNITS = {'length_mm': 'mm', 'impedance_ohm': 'ohm', 'screening_z0_ohm': 'ohm',
         'time_ns': 'ns', 'voltage_v': 'V', 'time_ui': 'UI', 'traces_v': 'V'}


def report_document(report, *, study=False):
    if study:
        from .report_plots import study_html
        return study_html(report)
    from .quick_si import html_report
    return html_report(report)


def write_results(path, report, *, board_path=None, fingerprints=None, saved=False,
                  study=False, pocket_kivi=True):
    """Save full HTML/JSON and a portable copy only for verified saved-board results."""
    from wayricad_runtime.report_ui import publish_report
    from wayricad_runtime.pocket_report import evidence_context, producer_version
    from .service import source_fingerprints, bind_saved_result

    bundle = copy.deepcopy(report)
    version = producer_version(module_file=__file__, package=__package__)
    bundle['producer'] = {'tool': 'quick-si', 'version': version}
    evidence = None
    if saved:
        if board_path is None or not fingerprints:
            raise ValueError('Save results with the original Quick SI saved-board fingerprints.')
        if source_fingerprints(board_path) != fingerprints:
            raise ValueError('Saved PCB or rules changed. Reopen Quick SI and rerun before saving results.')
        bundle = bind_saved_result(bundle, board_path, fingerprints)
        if pocket_kivi:
            evidence = evidence_context(bundle, tool='quick-si', module_file=__file__,
                                        package=__package__, board_path=board_path, units=UNITS)
    else:
        if any(bundle.get(key) for key in ('source_sha256', 'source_path', 'source_fingerprints')):
            raise ValueError('Live Quick SI results carry saved-source metadata; do not certify an unsaved result.')
        bundle['export_source_state'] = 'live-unverified'
        bundle['export_notes'] = ['Complete numerical samples are retained, but live editor state is not bound to a saved PCB.']
    document = report_document(bundle, study=study)
    return publish_report(path, document, bundle, pocket_kivi=evidence)
