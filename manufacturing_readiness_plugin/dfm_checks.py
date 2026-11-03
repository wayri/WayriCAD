"""Saved-snapshot vendor DRC, with item identities and conservative coverage."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .checklists import canonical_context, compile_native_rules, validate_profile
from .verification import drc_evidence, find_cli


_NATIVE_PROVIDERS = {
    'track_width': ('track_width',),
    'clearance': ('clearance', 'shorting_items', 'tracks_crossing'),
    'hole_size': ('drill_out_of_range', 'microvia_drill_out_of_range'),
    'annular_width': ('annular_width',),
    'edge_clearance': ('copper_edge_clearance',),
}


def _vendor_project(data, profile, preview):
    """Enable vendor checks only in the private project, without exclusions.

    KiCad's provider severity can suppress even an explicit custom-rule error.
    Original project severities and exclusion hashes are not vendor evidence.
    """
    try:
        project = json.loads(data) if data is not None else {}
        if not isinstance(project, dict):
            raise ValueError('Project must be an object.')
        board = project.setdefault('board', {})
        settings = board.setdefault('design_settings', {})
        severities = settings.setdefault('rule_severities', {})
        if not all(isinstance(value, dict) for value in (board, settings, severities)):
            raise ValueError('Project DRC settings must be objects.')
        compiled = set(preview['compiled_rule_ids'])
        providers = sorted({provider for rule in profile['rules'] if rule['id'] in compiled
                            for provider in _NATIVE_PROVIDERS[rule['constraint']]})
        previous = {name: severities.get(name) for name in providers}
        for name in providers:
            severities[name] = 'error'
        exclusions = settings.get('drc_exclusions', [])
        if not isinstance(exclusions, list):
            raise ValueError('Project DRC exclusions must be a list.')
        settings['drc_exclusions'] = []
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise ValueError('Cannot prepare private vendor DRC project settings: ' + str(exc)) from exc
    return (json.dumps(project, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8'),
            dict(provider_severities={name: dict(original=previous[name], applied='error') for name in providers},
                 excluded_findings_removed=len(exclusions)))


@contextmanager
def _snapshot_directory():
    owner = tempfile.TemporaryDirectory(prefix='wayricad-vendor-drc-')
    try:
        yield owner.name
    finally:
        # Windows can briefly retain inherited CLI handles after termination,
        # especially when cancellation lands during wx startup. Retry only
        # this owned directory; persistent cleanup failures remain errors.
        for attempt in range(4):
            try:
                owner.cleanup()
                break
            except (PermissionError, NotADirectoryError) as exc:
                if attempt == 3:
                    raise OSError('Could not remove the generated DRC workspace: ' + owner.name) from exc
                time.sleep(.1 * (attempt + 1))


def source_inputs(board_path, context=None):
    """Hash PCB, project and custom rules together; never certify live edits."""
    board_path = Path(board_path).resolve()
    if board_path.suffix.lower() != '.kicad_pcb' or not board_path.is_file():
        raise ValueError('Choose an existing saved PCB.')
    files = {board_path.name: board_path.read_bytes()}
    for suffix in ('.kicad_pro', '.kicad_dru'):
        path = board_path.with_suffix(suffix)
        if path.is_file():
            files[path.name] = path.read_bytes()
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode('utf-8') + b'\0')
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    if context is not None:
        digest.update(json.dumps(canonical_context(context), sort_keys=True, allow_nan=False).encode('utf-8'))
    return files, digest.hexdigest()


def classify_native_results(profile, preview, report, returncode):
    """Retain native findings; unrelated or unattributable failures stay unknown."""
    validate_profile(profile)
    if not isinstance(report, dict):
        raise ValueError('Native DRC report must be an object.')
    findings = []
    for group in ('violations', 'unconnected_items', 'schematic_parity'):
        rows = report.get(group, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Malformed native DRC findings.')
        for row in rows:
            if not isinstance(row.get('items', []), list) or any(not isinstance(item, dict) for item in row.get('items', [])):
                raise ValueError('Malformed native DRC item identities.')
        findings.extend(dict(row, group=group) for row in rows)
    valid = (returncode == 0 or returncode == 5 and bool(findings)) and isinstance(report.get('violations'), list) and isinstance(report.get('unconnected_items'), list)
    compiled = set(preview['compiled_rule_ids'])
    omitted = {row['rule_id']: row['reason'] for row in preview['omitted']}
    results = []
    for rule in profile['rules']:
        marker = profile['id'] + ':' + rule['id']
        pattern = r'(?<![\w.-])' + re.escape(marker) + r'(?![\w.-])'
        matched = [row for row in findings if re.search(pattern, str(row.get('description', '')))]
        status, message = 'UNKNOWN', omitted.get(rule['id'], 'Check requires its separate measurement backend.')
        if rule['id'] in compiled:
            if not valid:
                message = 'Native DRC did not complete successfully.'
            elif matched:
                status, message = 'FAIL', 'Native DRC reported a violation of this vendor rule.'
            elif findings:
                message = 'Native findings exist without this rule identity; inspect them before accepting coverage.'
            else:
                status, message = 'PASS', 'Native DRC completed with no findings for the selected process.'
        items = [item for row in matched for item in row.get('items', []) if isinstance(item, dict)]
        result = dict(rule_id=rule['id'], status=status, message=message,
                      object_ids=sorted({str(item['uuid']) for item in items if item.get('uuid')}),
                      positions_mm=[[item['pos']['x'], item['pos']['y']] for item in items
                                    if isinstance(item.get('pos'), dict) and 'x' in item['pos'] and 'y' in item['pos']])
        results.append(result)
    return results, findings


def audit_snapshot(board_path, profile, context, *, cli=None, cancelled=None, process_hook=None, timeout_s=300, project_drc=False):
    """Run native DRC on a private PCB/project copy with previewed vendor rules.

    Original custom rules are preserved in the source hash but are replaced in
    this vendor-only screening copy. Run ordinary project DRC separately. No
    Relevant providers are enabled and exclusions cleared only in that copy.
    No zone filling, board saving, routing or editor modification occurs here.
    """
    if cancelled and cancelled():
        raise InterruptedError('Vendor DRC cancelled.')
    profile = validate_profile(profile)
    preview = compile_native_rules(profile, context)
    if not preview['compiled_rule_ids'] and not project_drc:
        raise ValueError('This profile has no verified native rules for the selected process.')
    if project_drc and preview['compiled_rule_ids']:
        raise ValueError('This profile has native vendor rules; use vendor DRC for this run.')
    board_path = Path(board_path).resolve()
    files, source_sha = source_inputs(board_path, context)
    cli = Path(cli) if cli else find_cli()
    if cli is None:
        raise ValueError('KiCad CLI is unavailable. Configure the matching KiCad installation.')
    overrides = None
    if not project_drc:
        project_name = board_path.with_suffix('.kicad_pro').name
        project_bytes, overrides = _vendor_project(files.get(project_name), profile, preview)
    with _snapshot_directory() as directory:
        root = Path(directory)
        for name, data in files.items():
            (root / name).write_bytes(data)
        if not project_drc:
            (root / project_name).write_bytes(project_bytes)
            (root / board_path.with_suffix('.kicad_dru').name).write_text(preview['text'], encoding='utf-8')
        output = root / 'vendor-drc.json'
        command = [str(cli), 'pcb', 'drc', '--format', 'json', '--units', 'mm',
                   '--severity-all', '--all-track-errors', '--exit-code-violations',
                   '--output', str(output), str(root / board_path.name)]
        diagnostics = root / 'native-diagnostics.txt'
        error_stream = diagnostics.open('wb')
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=error_stream,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except BaseException:
            error_stream.close()
            raise
        started = time.monotonic()
        try:
            if process_hook:
                process_hook(process)
            if cancelled and cancelled():
                raise InterruptedError('Vendor DRC cancelled.')
            while process.poll() is None:
                if cancelled and cancelled():
                    raise InterruptedError('Vendor DRC cancelled.')
                if time.monotonic() - started > timeout_s:
                    raise TimeoutError('Native DRC exceeded the time budget.')
                if diagnostics.stat().st_size > 1024 * 1024:
                    raise ValueError('Native DRC diagnostics exceeded the size budget.')
                time.sleep(.05)
            if cancelled and cancelled():
                raise InterruptedError('Vendor DRC cancelled.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            try:
                if process_hook:
                    process_hook(None)
            finally:
                error_stream.close()
        native_diagnostics = diagnostics.read_text(encoding='utf-8', errors='replace').strip()
        if native_diagnostics:
            raise ValueError('Native DRC returned diagnostics; rules cannot be accepted: ' + native_diagnostics[:2000])
        if not output.is_file() or output.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Native DRC did not produce a bounded JSON report. Check CLI permissions and rule syntax.')
        evidence = drc_evidence(output, process.returncode)
        report = json.loads(output.read_text(encoding='utf-8'))
        results, findings = classify_native_results(profile, preview, report, process.returncode)
    if source_inputs(board_path, context)[1] != source_sha:
        raise ValueError('PCB, project or custom rules changed during checking. Run again.')
    return dict(schema='wayricad.dfm-run/v1', source_sha256=source_sha,
                board_sha256=hashlib.sha256(files[board_path.name]).hexdigest(),
                input_sha256={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                created_at=datetime.now(timezone.utc).isoformat(), results=results, findings=findings,
                kicad_version=report.get('kicad_version', 'Unknown'),
                units=dict(positions='mm', track_width='mm'),
                rule_mode='project' if project_drc else 'vendor',
                snapshot_overrides=overrides,
                native=evidence, rule_preview=preview,
                notice=('Project DRC only: this profile has no verified native vendor rules. Saved project custom rules are supplied to the private copy; vendor-specific requirements remain manual or unknown. '
                        if project_drc else 'Vendor-only screening of saved PCB/project bytes. Relevant check providers were enabled and DRC exclusions cleared in the private copy. Existing project custom rules were not applied; run project DRC too. ')
                       +
                       'Manual and unsupported DFM/DFA requirements remain unknown. Saved copper fill is used unchanged.')
