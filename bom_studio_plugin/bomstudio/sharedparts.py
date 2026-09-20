"""Cross-project parts workflow. Native registration is separately reviewed.

The catalogue remains authoritative; generated native libraries are immutable
snapshots. Alternates belong to workspace metadata, never schematic fields.
"""
from copy import deepcopy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid
import io
import zipfile

from . import partsdb, engineering, catalog, assetbundle
from .native import BASE
from .sexpr import parse, quote, apply_edits


def validate_alternates(records):
    if not isinstance(records, dict) or len(records) > 100000:
        raise ValueError('Invalid plugin-only alternate records.')
    for key, r in records.items():
        if not isinstance(r, dict) or set(r) != {'component','variant','library_id','part_id','revision','fields','note','status'}:
            raise ValueError('Invalid alternate record.')
        for name in ('component','variant','library_id','part_id','note','status'):
            partsdb.text(r[name], name, 2000)
        partsdb.number(r['revision'], 'revision', 1)
        if key != partsdb.digest([r['variant'], r['component']]):
            raise ValueError('Alternate record identity mismatch.')
        if not isinstance(r['fields'], dict) or len(r['fields']) > 500:
            raise ValueError('Invalid alternate fields.')
        for k,v in r['fields'].items():
            partsdb.text(k, 'field', 256); partsdb.text(v, 'value')


def config_directory():
    if os.environ.get('KICAD_CONFIG_HOME'):
        return Path(os.environ['KICAD_CONFIG_HOME']).expanduser()
    if os.name == 'nt':
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'kicad'
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Preferences/kicad'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'kicad'
    return base / '10.0'


def bounded_regex(pattern):
    """Small predictable regex subset: no groups/backreferences/repeated repeats."""
    partsdb.text(pattern, 'regex', 128)
    if not pattern or any(c in pattern for c in '(){}\\'):
        raise ValueError('Regex supports literals, ., anchors, character classes and |; no groups, braces or backslashes.')
    if len(pattern.split('|')) > 8:
        raise ValueError('Use at most eight regex alternatives.')
    for branch in pattern.split('|'):
        if not branch or sum(branch.count(c) for c in '*+?') > 1:
            raise ValueError('Use at most one quantifier (* + ?) per regex alternative.')
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise ValueError('Invalid regex: ' + str(exc)) from None


def suggestions(lib, fields, query='', regex=False, limit=30):
    partsdb.text(query, 'search', 256)
    partsdb.number(limit, 'limit', 1, 100)
    if type(regex) is not bool or not isinstance(fields, dict):
        raise ValueError('Invalid suggestion request.')
    rx = bounded_regex(query) if regex else None
    terms = query.casefold().split()
    critical = ('Value', 'Footprint', 'Voltage', 'Power', 'Tolerance', 'Dielectric')
    results = []
    # Bounded scan is explicit. Ranking never hides a broader compatibility claim.
    rows = lib.db.execute('SELECT payload FROM parts ORDER BY id LIMIT 5001').fetchall()
    from .classification import classify
    for row in rows[:5000]:
        p = json.loads(row[0]); f = p['fields']
        if p.get('status') == 'blocked':
            continue
        category = classify(p)['category']
        hint = 'IC' if p.get('reference_hint', '').startswith('U') or 'integrated' in category.casefold() else ''
        hay = ' '.join([category, hint, *f.values(), *p.get('tags', [])])[:16384]
        if rx:
            if not rx.search(hay): continue
        elif terms and not all(t in hay.casefold() for t in terms):
            continue
        score = 0; matches = []; differences = []; unknown = []
        for key in critical:
            a, b = str(fields.get(key, '')).strip(), str(f.get(key, '')).strip()
            if not a or not b: unknown.append(key)
            elif a.casefold() == b.casefold():
                matches.append(key); score += 12 if key in ('Value', 'Footprint') else 4
            else: differences.append({'field': key, 'project': a, 'candidate': b})
        if fields.get('MPN') and fields['MPN'] == f.get('MPN'):
            score += 20
        if not query and not matches and score == 0: continue
        results.append({'id': p['id'], 'revision': p['revision'], 'fields': f,
                        'score': score, 'matches': matches, 'differences': differences,
                        'unknown': unknown, 'category': category, 'status': p.get('status'),
                        'qualification': 'Not established: verify ratings, pinout and function.'})
    results.sort(key=lambda p: (-p['score'], p['fields'].get('MPN', ''), p['id']))
    return {'items': results[:limit], 'matches': len(results), 'scan_limited': len(rows) > 5000,
            'notice': 'Text/specification suggestions only. No automatic replacement or pin compatibility claim.'}


@contextmanager
def exclusive(folder):
    lock = folder / '.wayricad-shared-library.lock'
    try: fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('Another library operation is active. If it crashed, inspect and remove the stale .wayricad-shared-library.lock.') from None
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally: lock.unlink()


def _read(path):
    if path.is_symlink(): raise ValueError('Refusing a symbolic-link library/table file.')
    if not path.exists(): return None
    if path.stat().st_size > 32 * 1024 * 1024: raise ValueError('Library table exceeds size limit.')
    return path.read_bytes()


def _atomic(path, raw):
    fd, tmp = tempfile.mkstemp(prefix='.wayricad-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if Path(tmp).exists(): Path(tmp).unlink()


def _table_bytes(raw, tag, name, uri, owned_root):
    text = raw.decode('utf-8-sig') if raw is not None else '(' + tag + '\n  (version 7)\n)\n'
    root = parse(text)
    if root.tag != tag: raise ValueError('Unexpected KiCad library-table format.')
    entries = [n for n in root.nodes('lib') if n.get('name') == name]
    if len(entries) > 1: raise ValueError('Duplicate existing library nickname: ' + name)
    entry = '(lib (name ' + quote(name) + ') (type "KiCad") (uri ' + quote(uri) + ') (options "") (descr "WayriCAD shared parts"))'
    if entries:
        old = Path(entries[0].get('uri')).resolve()
        if owned_root.resolve() not in old.parents:
            raise ValueError('Nickname belongs to another library: ' + name + '. Choose another nickname.')
        return apply_edits(text, [(entries[0].start, entries[0].end, entry)]).encode('utf-8')
    return apply_edits(text, [(root.end - 1, root.end - 1, '  ' + entry + '\n')]).encode('utf-8')


def native_preview(lib, config, name='WayriCADParts', choices=None):
    with lib.transaction():
        return _native_preview(lib, config, name, choices)


def _native_preview(lib, config, name, choices):
    config = Path(config).expanduser()
    if not config.is_absolute() or not config.is_dir() or config.is_symlink():
        raise ValueError('Choose the existing KiCad version configuration directory (for example kicad/10.0).')
    ids = [r[0] for r in lib.db.execute('SELECT id FROM parts ORDER BY id LIMIT 10001')]
    if not ids: raise ValueError('Save project parts to the catalogue first.')
    observations = []
    for pid in ids:
        conflicts = lib.get(pid).get('conflicts', [])
        if any(c.get('field') in partsdb.CRITICAL for c in conflicts):
            raise ValueError('Resolve conflicting observations in Library & control before publishing: ' + pid)
        if conflicts: observations.append({'part': pid, 'retained_metadata_conflicts': conflicts})
    revision = partsdb.digest([lib.meta('id'), lib.meta('epoch'), name, choices or {}])[:24]
    destination = lib.root / 'native' / revision
    if (lib.root / 'native').is_symlink() or destination.is_symlink():
        raise ValueError('Native snapshot folder must not be a symbolic link.')
    raw, _, _ = assetbundle.export_library(lib, ids, choices, require_complete=True,
        model_prefix=(destination / (name + '.3dshapes')).as_posix(), library_name=name, readable_names=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        payload_hash = partsdb.digest({n: partsdb.sha(z.read(n)) for n in sorted(z.namelist())})
    snapshots = {}; tables = {}
    for file, tag, suffix in [('sym-lib-table', 'sym_lib_table', '.kicad_sym'), ('fp-lib-table', 'fp_lib_table', '.pretty')]:
        before = _read(config / file)
        snapshots[file] = None if before is None else partsdb.sha(before)
        tables[file] = _table_bytes(before, tag, name, (destination / (name + suffix)).as_posix(), lib.root / 'native').decode('utf-8')
    return {'schema': 'wayricad-shared-native-1', 'library': str(lib.root), 'epoch': lib.meta('epoch'),
            'library_id': lib.meta('id'), 'destination': str(destination), 'config': str(config), 'name': name,
            'choices': choices or {}, 'parts': len(ids), 'payload_hash': payload_hash, 'before': snapshots,
            'tables': tables, 'observations': observations,
            'notice': 'Adds/updates only this nickname; backups preserve both existing global tables. Close KiCad library managers before applying.'}


def native_apply(lib, plan):
    from .librarymaker import _unpack
    config = Path(plan['config'])
    with exclusive(lib.root), exclusive(config):
        fresh = native_preview(lib, config, plan['name'], plan['choices'])
        if fresh != plan: raise ValueError('Library or global tables changed; preview again.')
        with lib.transaction():
            raw = assetbundle.export_library(lib, [r[0] for r in lib.db.execute('SELECT id FROM parts ORDER BY id')],
                plan['choices'], True, (Path(plan['destination']) / (plan['name'] + '.3dshapes')).as_posix(), plan['name'], True)[0]
        # Catalogue edits do not use the publication lock. Validate the exact
        # immutable bytes that will be unpacked, not only the earlier DB view.
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            payload_hash = partsdb.digest({n: partsdb.sha(archive.read(n)) for n in sorted(archive.namelist())})
        if payload_hash != plan['payload_hash']:
            raise ValueError('Library changed during publication; preview again.')
        dest = Path(plan['destination']); dest.parent.mkdir(exist_ok=True)
        # ZIP metadata timestamps are irrelevant; published payload hashes are checked.
        if dest.exists():
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if any(not (dest / n).is_file() or (dest / n).read_bytes() != z.read(n) for n in z.namelist()):
                    raise ValueError('Existing native snapshot differs; it was not overwritten.')
        else:
            with tempfile.TemporaryDirectory(dir=dest.parent, prefix='.stage-') as t:
                stage = Path(t) / 'payload'; stage.mkdir(); _unpack(raw, stage)
                stage.rename(dest)
        backups = {}; written = []
        try:
            for name, text in plan['tables'].items():
                path = config / name; before = _read(path)
                if (None if before is None else partsdb.sha(before)) != plan['before'][name]:
                    raise ValueError('Global table changed during publication; preview again.')
                backups[name] = before
                if before is not None:
                    backup = config / (name + '.wayricad-' + uuid.uuid4().hex + '.bak')
                    with backup.open('xb') as f: f.write(before)
                _atomic(path, text.encode('utf-8')); written.append(name)
        except BaseException:
            for name in reversed(written):
                # Do not overwrite a concurrent external change during rollback.
                path = config / name
                if _read(path) == plan['tables'][name].encode('utf-8'):
                    if backups[name] is None: path.unlink()
                    else: _atomic(path, backups[name])
            raise
    return {'registered': True, 'destination': str(dest), 'parts': plan['parts'], 'restart': 'Reopen KiCad editors to reload global library tables.'}


def dispatch(app, op, body):
    ws = app.workspace
    if op == 'context':
        try: path = engineering.library_path(ws, app=app)
        except ValueError: path = None
        return {'library': str(path) if path else '', 'config': str(config_directory()),
                'default_destination': str(Path.home() / 'Documents' / 'WayriCADParts'),
                'alternates': ws.state.get('engineering', {}).get('shared_alternates', {}) if ws else {}}
    if op == 'open':
        return engineering.dispatch(app, 'create' if body.get('create') is True else 'attach',
            {'path': body['path'], 'remember': True, 'confirmation': 'CREATE' if body.get('confirmation') == 'CREATE' else ''})
    path = engineering.library_path(ws, body.get('library', ''), app)
    if op == 'harvest-start':
        if ws is None: raise ValueError('Open the originating project first.')
        if ws.dirty: raise ValueError('Save the workspace first so harvested parts include your edits.')
        return engineering.dispatch(app, 'harvest-start', {'paths': [str(ws.project.root)], 'include_variants': True, 'capture_assets': True})
    with partsdb.Library(path) as lib:
        if op == 'suggest':
            if ws is None: raise ValueError('Open a project first.')
            rows = ws.rows(body.get('variant', BASE))
            row = next((r for r in rows if r['id'] == body['component']), None)
            if row is None: raise ValueError('Component is no longer in this project.')
            return suggestions(lib, row['fields'], body.get('query', ''), body.get('regex', False))
        if op == 'choose':
            if ws is None: raise ValueError('Open a project first.')
            variant = body.get('variant', BASE)
            component = engineering.resolve_id(ws, variant, body['component'])
            p = lib.get(body['id'])
            if p['revision'] != body['revision']: raise ValueError('Candidate changed; search again.')
            if p.get('status') == 'blocked': raise ValueError('Candidate is blocked in the library.')
            note = partsdb.text(body.get('note', ''), 'alternate note', 2000)
            key = partsdb.digest([variant, component])
            record = {'component': component, 'variant': variant, 'library_id': lib.meta('id'),
                      'part_id': p['id'], 'revision': p['revision'], 'fields': deepcopy(p['fields']),
                      'note': note, 'status': 'candidate; engineering review required'}
            ws.commit('Record plugin-only alternate', lambda: ws.state.setdefault('engineering', {}).setdefault('shared_alternates', {}).__setitem__(key, record))
            return record
        if op == 'clear':
            if ws is None: raise ValueError('Open a project first.')
            variant = body.get('variant', BASE)
            component = engineering.resolve_id(ws, variant, body['component'])
            key = partsdb.digest([variant, component])
            ws.commit('Clear plugin-only alternate', lambda: ws.state.setdefault('engineering', {}).setdefault('shared_alternates', {}).pop(key, None))
            return {'cleared': True}
        if op == 'templates-save':
            if ws is None: raise ValueError('Open a project first.')
            payload = catalog.bundle(ws); catalog.parse_bundle(json.dumps(payload))
            raw = partsdb.encoded(payload); key = 'shared_templates_' + partsdb.digest(payload)
            with lib.transaction():
                lib.db.execute('INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)', (key, raw))
                lib.audit('shared-template-bundle', {'key': key, 'project': str(ws.project.root)})
            return {'key': key, 'saved': True}
        if op == 'templates-list':
            return {'items': [{'key': r[0], 'templates': [t['name'] for t in json.loads(r[1]).get('templates', [])]} for r in lib.db.execute("SELECT key,value FROM meta WHERE key LIKE 'shared_templates_%' ORDER BY key")]}
        if op == 'templates-load':
            if ws is None: raise ValueError('Open a project first.')
            row = lib.db.execute("SELECT value FROM meta WHERE key=? AND key LIKE 'shared_templates_%'", (body['key'],)).fetchone()
            if not row: raise ValueError('Template bundle no longer exists.')
            return catalog.import_apply(ws, row[0], 'keep_both')
        if op == 'native-preview':
            plan = native_preview(lib, body['config'], body.get('name', 'WayriCADParts'), body.get('choices'))
            app.shared_native_plan = plan
            return plan
        if op == 'native-apply':
            if body.get('confirmation') != 'REGISTER': raise ValueError('Review the tables and type REGISTER.')
            plan = getattr(app, 'shared_native_plan', None)
            if not plan or plan['library'] != str(lib.root): raise ValueError('Preview this library first.')
            result = native_apply(lib, plan); app.shared_native_plan = None
            return result
    raise ValueError('Unknown shared-library operation.')
