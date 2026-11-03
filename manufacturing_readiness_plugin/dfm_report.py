"""Compact manufacturing reports with complete evidence and atomic freshness checks."""
from __future__ import annotations
from html import escape
import base64
import json
from pathlib import Path

from .dfm_checks import source_inputs
from .dfm_present import BASIS_LABELS, FAMILIES, describe, displayed_status, evidence_entries, family


def export_report(path, board_path, context, bundle, checklist, entries=None, *, board_png=None, protected_sources=()):
    from wayricad_runtime.report_ui import enhance_report, publish_documents, report_paths
    board_path = Path(board_path).resolve()
    from .checklists import compile_native_rules, profile_digest
    preview = compile_native_rules(checklist['profile'], context)
    recorded = bundle.get('rule_preview', {})
    if (recorded.get('profile_sha256') != profile_digest(checklist['profile'])
            or recorded.get('context') != context
            or recorded.get('text') != preview['text']):
        raise ValueError('The checklist profile or process does not match the native run. Rerun before exporting.')
    def guard():
        if source_inputs(board_path, context)[1] != bundle['source_sha256']:
            raise ValueError('PCB, project, custom rules or selected process changed; rerun before exporting.')
    guard()
    state, _requirements, entries = evidence_entries(checklist, bundle['source_sha256'], bundle)
    if state['stale']:
        raise ValueError('Checklist evidence does not match the current source, profile and process.')
    if board_png is not None:
        if not isinstance(board_png, str) or len(board_png) > 8 * 1024 * 1024:
            raise ValueError('Board image exceeds the report size budget.')
        try: image = base64.b64decode(board_png, validate=True)
        except (ValueError, TypeError) as exc: raise ValueError('Board image must be a PNG.') from exc
        if len(image) < 24 or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Board image must be a PNG.')
        width, height = int.from_bytes(image[16:20], 'big'), int.from_bytes(image[20:24], 'big')
        if not width or not height or width * height > 16_000_000:
            raise ValueError('Board image dimensions exceed the report budget.')
    title = 'DFM / DFA · ' + board_path.stem
    html = '<!doctype html><html><head><meta charset="utf-8"><title>'+escape(title)+'</title></head><body><h1>'+escape(title)+'</h1>'
    html += '<p>'+escape(str(board_path))+'</p><p>'+escape(checklist['profile']['name'])+'</p><p>'+escape(bundle['notice'])+'</p>'
    html += '<h2>Source revision</h2><table><tr><th>Evidence</th><th>Value</th></tr>'
    revision_rows = [('KiCad version', bundle.get('kicad_version', 'Unknown')),
                     ('PCB SHA-256', bundle['board_sha256']),
                     ('Saved inputs and process SHA-256', bundle['source_sha256']),
                     ('Profile SHA-256', preview['profile_sha256'])]
    revision_rows += [(str(board_path.parent/name), digest) for name, digest in bundle.get('input_sha256', {}).items()]
    html += ''.join('<tr><td>'+escape(label)+'</td><td>'+escape(str(value))+'</td></tr>' for label, value in revision_rows)+'</table>'
    overrides = bundle.get('snapshot_overrides')
    if overrides:
        html += '<h2>Private DRC snapshot settings</h2><p>Source project settings were preserved. The following settings apply only to the vendor screening copy.</p><table><tr><th>Check provider</th><th>Source severity</th><th>Snapshot severity</th></tr>'
        html += ''.join('<tr><td>'+escape(name)+'</td><td>'+escape(str(values.get('original') or 'KiCad default'))+'</td><td>'+escape(str(values['applied']))+'</td></tr>'
                        for name, values in overrides['provider_severities'].items())+'</table>'
        html += '<p>Saved DRC exclusions removed from the private copy: '+str(int(overrides['excluded_findings_removed']))+'.</p>'
    if board_png:
        html += '<figure><img alt="Saved board with all linked native finding objects highlighted" src="data:image/png;base64,'+board_png+'"><figcaption>Saved geometry; highlighted objects have linked findings. Consult individual checks for the actual measured dimensions.</figcaption></figure>'
    for group in FAMILIES[1:]:
        rows = [entry for entry in entries if family(entry) == group]
        if not rows: continue
        html += '<h2>'+escape(group)+'</h2>'
        for entry in rows:
            rule = entry.get('rule', {})
            html += '<h3>'+escape(rule.get('title', entry.get('message', 'Native finding')))+'</h3><p>'+escape(displayed_status(entry))+'</p><pre>'+escape(describe(entry, checklist['profile']))+'</pre>'
    html += '<h2>Process scope</h2><table><tr><th>Parameter</th><th>Selection</th></tr>'
    html += ''.join('<tr><td>'+escape(key.replace('_', ' '))+'</td><td>'+escape(str(BASIS_LABELS.get(value, value) if key == 'copper_basis' else value))+'</td></tr>' for key, value in context.items())+'</table></body></html>'
    status = 'PASS' if state['passed'] else 'FAIL' if any(displayed_status(row) == 'FAIL' for row in entries) else 'UNKNOWN'
    html = enhance_report(html, status=status, notice='Unknown and waived items are not verified passing checks.')
    output, evidence = report_paths(path)
    data = dict(bundle, board=str(board_path), checklist=checklist, selected_context=context)
    documents = {output: html, evidence: json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n'}
    if Path(path).suffix.lower() == '.pdf':
        from wayricad_runtime.pdf_report import pdf_bytes
        documents[output.with_suffix('.pdf')] = pdf_bytes(html, title=title)
    protected = [board_path.with_suffix(suffix) for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru')]
    protected.extend(protected_sources)
    publish_documents(documents, sources=protected, source_guard=guard)
    return list(documents)
