"""Native plots and paired offline evidence for coupled studies."""
from __future__ import annotations

import base64
import hashlib
from html import escape
import io
import json
import os
from pathlib import Path
import shutil
import tempfile


def valid_operating_point(bundle):
    result = bundle['electrothermal']
    if bundle['mode'] == 'steady':
        return result.get('limits', {}).get('operating_point_valid') is True
    return result.get('status') == 'completed' and result.get('feasibility', {}).get('feasible') is True


def summary(bundle):
    result = bundle['electrothermal']
    keys = ('status', 'diagnostic', 'notice', 'limits', 'feasibility', 'checks',
            'convergence', 'transfer_balance', 'bindings', 'solver_versions', 'assumptions', 'issues')
    return json.dumps({key: result[key] for key in keys if key in result}, indent=2, allow_nan=False)


def draw(figure, bundle):
    figure.clear()
    result = bundle['electrothermal']
    if bundle['mode'] == 'steady':
        voltage = figure.add_subplot(121)
        cold, hot = result['cold'], result.get('hot')
        rows = cold['sinks'][:12]
        positions = list(range(len(rows)))
        voltage.plot(positions, [r['voltage_V'] for r in rows], 'o-', label='Cold')
        if hot:
            voltage.plot(positions, [r['voltage_V'] for r in hot['sinks'][:12]], 'o-', label='Coupled hot')
        voltage.set_xticks(positions, [r['label'] for r in rows], rotation=35, ha='right')
        voltage.set_ylabel('Sink voltage (V)'); voltage.legend(); voltage.grid(alpha=.2)
        voltage.ticklabel_format(axis='y', style='plain', useOffset=False)
        temperature = figure.add_subplot(122)
        field = result.get('thermal')
        if field:
            layer = field['layers'][0]
            from wayricad_runtime.thermal_field import draw_field
            from matplotlib.colors import Normalize
            # The existing renderer masks unsupported cells and clips holes.
            low, high = layer['sampled_min_c'], layer['sampled_max_c']
            # A nearly uniform physical field can differ by solver roundoff.
            # Do not expand that noise into a full hot/cold color gradient.
            uniform = high-low < max(1e-6, max(abs(low), abs(high))*1e-10)
            if uniform:
                middle = (low+high)/2
                low, high = middle-.5, middle+.5
            artist = draw_field(temperature, layer, bundle.get('thermal_outline', []),
                                Normalize(low, high if high > low else low+1.))
            if artist is not None: figure.colorbar(artist, ax=temperature, label='°C')
            temperature.set_title(str(layer.get('name', layer.get('id'))) + ' conductor °C' +
                                  (' · uniform' if uniform else ''))
            temperature.set_aspect('equal'); temperature.set_xlabel('Source x (mm)')
        else:
            temperature.text(.5, .5, result.get('diagnostic', 'No accepted hot result'),
                             ha='center', va='center', wrap=True, transform=temperature.transAxes)
            temperature.set_axis_off()
    else:
        electrical = figure.add_subplot(211)
        thermal = figure.add_subplot(212, sharex=electrical)
        coupled = result.get('coupled')
        if not coupled:
            electrical.text(.5, .5, result.get('notice', 'Coupled study did not complete'),
                            ha='center', va='center', wrap=True, transform=electrical.transAxes)
        else:
            times = coupled['times_s']
            for row in coupled['loads'][:12]:
                electrical.plot(times, row['voltage_V'], label=row.get('label', row['id']))
            for row in coupled['thermal_nodes'][:12]:
                thermal.plot(times, row['temperature_c'], label=row.get('label', row['id']))
            if electrical.lines: electrical.legend(fontsize=8)
            if thermal.lines: thermal.legend(fontsize=8)
        electrical.set_ylabel('Load voltage (V)'); thermal.set_ylabel('Thermal-node temperature (°C)')
        thermal.set_xlabel('Time (s)'); electrical.grid(alpha=.2); thermal.grid(alpha=.2)
    figure.suptitle('Quick PI · Electrothermal ' + bundle['mode'] + ' · ' + str(result.get('status')))
    figure.tight_layout()


def write_report(path, bundle):
    path = Path(path).resolve().with_suffix('.html')
    json_path = path.with_suffix('.json')
    protected = [Path(bundle[k]).resolve() for k in ('board_path', 'study_input_path') if bundle.get(k)]
    for target in (path, json_path):
        for source in protected:
            if target == source or (target.exists() and source.exists() and os.path.samefile(target, source)):
                raise ValueError('Reports must not overwrite the saved PCB or input study.')
    for key, digest in (('board_path', 'source_sha256'), ('study_input_path', 'study_file_sha256')):
        if bundle.get(key) and bundle.get(digest):
            if hashlib.sha256(Path(bundle[key]).read_bytes()).hexdigest() != bundle[digest]:
                raise ValueError('Source or study changed. Rerun before exporting electrothermal results.')
    expected = hashlib.sha256(json.dumps(bundle['study'], sort_keys=True, separators=(',', ':'),
                                        allow_nan=False).encode('utf-8')).hexdigest()
    if expected != bundle.get('study_sha256'):
        raise ValueError('Study settings changed. Rerun before exporting electrothermal results.')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = Figure(figsize=(11, 7), dpi=130); FigureCanvasAgg(figure)
    draw(figure, bundle); stream = io.BytesIO(); figure.savefig(stream, format='png', facecolor='white')
    result = bundle['electrothermal']
    note = result.get('notice') or '; '.join(result.get('assumptions', []))
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Electrothermal study</title><style>body{font:15px system-ui;max-width:1100px;margin:30px auto;padding:0 20px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    html += '<h1>Quick PI · Electrothermal ' + escape(bundle['mode']) + '</h1><p>' + escape(note) + '</p>'
    html += '<p>Operating-point checks: ' + ('accepted' if valid_operating_point(bundle) else 'failed or violated') + '.</p>'
    if bundle.get('board_binding') == 'provenance_only':
        html += '<p>The saved PCB supplies provenance only. Geometry and physical parameters are an explicit supplied model.</p>'
    html += '<p><a href="' + escape(json_path.name) + '">Raw results, model inputs and provenance (JSON)</a></p>'
    html += '<img alt="Cold/hot electrical and thermal results" src="data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii') + '">'
    html += '<h2>Checks and assumptions</h2><pre>' + escape(summary(bundle)) + '</pre><h2>Explicit inputs</h2><pre>' + escape(json.dumps(bundle['study'], indent=2, allow_nan=False)) + '</pre></html>'
    payload = json.dumps(bundle, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = []; backups = {}; published = []; retained = set()
    try:
        for target, text in ((json_path, payload), (path, html)):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as handle:
                handle.write(text); staged.append((Path(handle.name), target))
        for _, target in staged:
            backup = None
            if target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                    backup = Path(handle.name)
                    backups[target] = backup
                    with target.open('rb') as original: shutil.copyfileobj(original, handle)
            backups[target] = backup
        try:
            for temporary, target in staged:
                os.replace(temporary, target); published.append(target)
        except BaseException as failure:
            errors = []
            for target in reversed(published):
                try:
                    if backups[target] is None: target.unlink(missing_ok=True)
                    else: os.replace(backups[target], target)
                except OSError as rollback:
                    if backups[target] is not None: retained.add(backups[target])
                    errors.append(str(target) + ': ' + str(rollback))
            if errors:
                raise OSError('Report publication and rollback failed. Preserved recovery files: ' +
                              ', '.join(str(p) for p in retained) + '. ' + '; '.join(errors)) from failure
            raise
    finally:
        for temporary, _ in staged: temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None and backup not in retained: backup.unlink(missing_ok=True)
    return {'html': str(path), 'json': str(json_path)}
