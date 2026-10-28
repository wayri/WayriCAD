"""Export bounded, data-only simulation scenes for optional Blender viewing.

The source analysis and PCB are read-only. Blender is not a solver dependency;
normalization and bundle export do not import bpy or launch an application.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

SCHEMA = 'wayricad.blender-scene/v1'
MAX_BYTES = 128 * 1024 * 1024
MAX_FACES = 200_000
MAX_VERTICES = 400_000
MAX_VALUES = 5_000_000
MAX_FRAMES = 1000


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be finite.')
    return value


def _label(value, label):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(label + ' must be a nonempty string of at most 256 characters.')


def validate_scene(scene):
    """Check topology, scalar support and resource budgets before writing files."""
    if not isinstance(scene, dict) or scene.get('schema') != SCHEMA:
        raise ValueError('Unsupported Blender scene schema.')
    objects = scene.get('objects', [])
    traces = scene.get('traces', [])
    if not isinstance(objects, list) or not isinstance(traces, list) or len(objects) > 10_000 or len(traces) > 1000:
        raise ValueError('Scene object or trace budget exceeded.')
    if not objects and not traces:
        raise ValueError('No supported geometry or temporal results are available.')
    faces_total = vertices_total = values_total = 0
    times = set()
    for obj in objects:
        if not isinstance(obj, dict):raise ValueError('Scene objects must be mappings.')
        _label(obj.get('name'), 'Object name')
        points, faces = obj.get('vertices_mm'), obj.get('faces')
        if not isinstance(points, list) or not isinstance(faces, list) or not points or not faces:
            raise ValueError('Each mesh needs vertices_mm and faces.')
        faces_total += len(faces);vertices_total += len(points)
        if faces_total > MAX_FACES or vertices_total > MAX_VERTICES:
            raise ValueError('Blender geometry budget exceeded; select a smaller study.')
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 3:
                raise ValueError('Mesh vertices require three millimetre coordinates.')
            for value in point:_number(value, 'Vertex coordinate')
        for face in faces:
            if not isinstance(face, (list, tuple)) or not 3 <= len(face) <= 64 or len(set(face)) != len(face):
                raise ValueError('Mesh faces need 3–64 distinct vertex indices.')
            if any(type(index) is not int or not 0 <= index < len(points) for index in face):
                raise ValueError('Mesh face references an invalid vertex.')
        color = obj.get('color', [.25, .45, .5, 1.])
        if not isinstance(color, (list, tuple)) or len(color) != 4:
            raise ValueError('Object color requires RGBA.')
        for value in color:
            if not 0 <= _number(value, 'Color channel') <= 1:raise ValueError('Color channels must be in [0, 1].')
        properties = obj.get('properties', {})
        if not isinstance(properties, dict) or len(properties) > 64:
            raise ValueError('Object properties must be a bounded mapping.')
        for key, value in properties.items():
            _label(key, 'Property name')
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError('Object properties must be scalar data.')
            if isinstance(value, str) and len(value) > 4096:raise ValueError('Object property is too long.')
            if isinstance(value, (int, float)) and not isinstance(value, bool):_number(value, 'Property')
        field = obj.get('field')
        if field is None:continue
        if not isinstance(field, dict):raise ValueError('Scalar field must be a mapping.')
        _label(field.get('name'), 'Field name');_label(field.get('unit'), 'Field unit')
        frames = field.get('frames', [])
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
            raise ValueError('Stored-frame budget exceeded.')
        samples = [field.get('values')]
        last = -math.inf
        for frame in frames:
            if not isinstance(frame, dict):raise ValueError('Frames must be mappings.')
            time = _number(frame.get('time_s'), 'Frame time')
            if time < 0 or time <= last:raise ValueError('Frame times must increase and be nonnegative.')
            times.add(time);last = time;samples.append(frame.get('values'))
        for values in samples:
            if not isinstance(values, list) or len(values) != len(faces):
                raise ValueError('Scalar values must match mesh face count exactly.')
            values_total += len(values)
            if values_total > MAX_VALUES:raise ValueError('Scalar-value budget exceeded.')
            for value in values:
                if value is not None:_number(value, 'Scalar value')
    for trace in traces:
        if not isinstance(trace, dict):raise ValueError('Traces must be mappings.')
        _label(trace.get('name'), 'Trace name');_label(trace.get('unit'), 'Trace unit')
        x, y = trace.get('time_s'), trace.get('values')
        if not isinstance(x, list) or not isinstance(y, list) or not x or len(x) != len(y):
            raise ValueError('Trace times and values must have equal nonzero lengths.')
        values_total += len(y)
        if values_total > MAX_VALUES:raise ValueError('Scalar-value budget exceeded.')
        last = -math.inf
        for time, value in zip(x, y):
            time = _number(time, 'Trace time')
            if time < 0 or time < last:raise ValueError('Trace times must be nondecreasing and nonnegative.')
            if value is not None:_number(value, 'Trace value')
            last = time
    if len(times) > MAX_FRAMES:raise ValueError('Combined stored-frame budget exceeded.')
    return {'objects': len(objects), 'faces': faces_total, 'vertices': vertices_total,
            'scalar_values': values_total, 'stored_times': len(times), 'traces': len(traces)}


def load_result(source):
    """Read bounded JSON, rejecting duplicate keys and nonfinite numbers."""
    source = Path(source)
    if source.stat().st_size > MAX_BYTES:raise ValueError('Saved result exceeds 128 MiB.')
    raw = source.read_bytes()
    if len(raw) > MAX_BYTES:raise ValueError('Saved result exceeds 128 MiB.')
    def mapping(items):
        result = {}
        for key, value in items:
            if key in result:raise ValueError('Duplicate result key: ' + key)
            result[key] = value
        return result
    def reject(value):raise ValueError('Nonfinite JSON number: ' + value)
    try:
        bundle = json.loads(raw, object_pairs_hook=mapping, parse_constant=reject)
    except RecursionError as exc:raise ValueError('Saved result is nested too deeply.') from exc
    if not isinstance(bundle, dict):raise ValueError('Saved result must be a JSON object.')
    return bundle, hashlib.sha256(raw).hexdigest()


def _checked_sources(bundle):
    """Check direct, study and embedded case custody without walking field arrays."""
    from .report_ui import checked_sources
    sources = []
    pending = [bundle]
    seen = set()
    while pending:
        scope = pending.pop()
        if not isinstance(scope, dict) or id(scope) in seen:continue
        seen.add(id(scope))
        if len(seen) > 2048:raise ValueError('Too many nested study cases.')
        sources.extend(checked_sources(scope))
        fingerprints = scope.get('source_fingerprints') or {}
        if not isinstance(fingerprints, dict) or len(fingerprints) > 1024:
            raise ValueError('Invalid source fingerprint mapping.')
        for path, digest in fingerprints.items():
            source = Path(path);sources.append(source)
            if digest is None:
                if source.exists():raise ValueError('Previously absent source file appeared; rerun before exporting.')
            elif not isinstance(digest, str) or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError('Source or input study changed; rerun before exporting.')
        for key in ('batch', 'electrical', 'bundle', 'geometry'):
            if isinstance(scope.get(key), dict):pending.append(scope[key])
        cases = scope.get('cases', [])
        if isinstance(cases, list):pending.extend(case for case in cases if isinstance(case, dict))
    return sources


def export_bundle(bundle, destination, *, tool='auto', metric=None, _source_guard=None):
    """Create a new self-contained visualization bundle; never overwrite a path."""
    from .blender_adapters import normalize
    from .blender_board import with_board_context
    sources = _checked_sources(bundle)
    contextual, warning = with_board_context(bundle)
    scene = normalize(contextual, tool=tool, metric=metric)
    if warning:scene.setdefault('notes', []).append(warning)
    counts = validate_scene(scene)
    from .blender_import import validate_scene as validate_import
    validate_import(scene)
    payload = (json.dumps(scene, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
    if len(payload) > MAX_BYTES:raise ValueError('Normalized scene exceeds 128 MiB.')
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():raise ValueError('Choose a new Blender output directory.')
    if not target.parent.is_dir():raise ValueError('Blender output parent directory must exist.')
    for path in sources:
        if Path(path).resolve() == target.resolve():raise ValueError('Output aliases a protected input.')
    script = Path(__file__).with_name('blender_import.py').read_bytes()
    readme = ('# WayriCAD Blender visualization\n\n'
        'This is a visualization of saved simulation data, not a new simulation.\n'
        'Input coordinates are PCB millimetres; the importer converts to Blender metres and reflects Y.\n'
        'Unknown scalar samples remain gray. Component envelopes, when present, are not STEP solids.\n'
        'Animation uses computed stored states; timeline markers identify physical time.\n'
        'A static DC result has no invented transient animation.\n\n'
        'Create the scene:\n\n'
        '    blender --background --python blender_import.py -- --scene scene.json --output visualization.blend\n\n'
        'Open visualization.blend in Blender, use Material Preview to inspect field colors, and press Space to play stored frames.\n'
        'Select objects to inspect field names, units, scope and source information in custom properties.\n'
        'Keep the generated textures directory beside the blend file for animated fields.\n\n'
        'Scene notes:\n' + ''.join('- ' + str(note) + '\n' for note in scene.get('notes', []))).encode('utf-8')
    files = {'scene.json': payload, 'blender_import.py': script, 'README.md': readme}
    manifest = {'schema': 'wayricad.blender-bundle/v1', 'scene_schema': SCHEMA,
                'counts': counts, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    _checked_sources(bundle)
    if _source_guard:_source_guard()
    written = []
    target.mkdir()
    try:
        for name, data in files.items():
            path = target / name
            with path.open('xb') as handle:
                written.append(path)
                handle.write(data)
        _checked_sources(bundle)
        if _source_guard:_source_guard()
    except BaseException:
        for path in reversed(written):path.unlink(missing_ok=True)
        try:target.rmdir()
        except OSError:pass
        raise
    return {'directory': str(target), 'scene': str(target / 'scene.json'),
            'manifest': str(target / 'manifest.json'), 'counts': counts, 'tool': scene.get('tool')}


def export_result(source, destination, *, tool='auto', metric=None):
    """Export a saved result with an additional unchanged-input custody check."""
    bundle, digest = load_result(source)
    def guard():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != digest:
            raise ValueError('Saved result changed during export; export the completed result again.')
    return export_bundle(bundle, destination, tool=tool, metric=metric, _source_guard=guard)


def find_blender(executable=None):
    """Locate an optional installed Blender without installing or importing it."""
    if executable:
        path = Path(executable)
        if not path.is_file():raise ValueError('Blender executable was not found.')
        return str(path.absolute())
    found = shutil.which('blender')
    if found:return found
    if os.name == 'nt':
        base = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Blender Foundation'
        candidates = sorted(base.glob('Blender */blender.exe'), reverse=True)
        if candidates:return str(candidates[0])
    raise ValueError('Install Blender separately or supply its executable path.')


def run_blender(directory, executable=None, *, background=False, render=None):
    """Launch the bundled importer without a shell; background runs are bounded."""
    directory = Path(directory).absolute()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'wayricad.blender-bundle/v1':raise ValueError('Invalid Blender bundle manifest.')
    for name in ('scene.json', 'blender_import.py'):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest.get('files', {}).get(name):
            raise ValueError('Blender bundle changed since export: ' + name)
    command = [find_blender(executable)]
    if background:command.append('--background')
    command += ['--python-exit-code', '2', '--python', str(directory / 'blender_import.py'), '--', '--scene', str(directory / 'scene.json'),
                '--output', str(directory / 'visualization.blend')]
    if render:
        render = Path(render).absolute()
        if render.exists() or render.is_symlink():raise ValueError('Render output already exists.')
        command += ['--render', str(render)]
    if (directory / 'visualization.blend').exists():raise ValueError('Blender visualization already exists; choose a new bundle.')
    if background:
        log = directory / 'blender.log'
        with log.open('x', encoding='utf-8') as handle:
            done = subprocess.run(command, cwd=directory, stdout=handle, stderr=subprocess.STDOUT, timeout=600)
        if done.returncode:raise RuntimeError('Blender import failed; inspect ' + str(log))
        if not (directory / 'visualization.blend').is_file():raise RuntimeError('Blender did not create the visualization.')
        return {'blend': str(directory / 'visualization.blend'), 'log': str(log)}
    options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if os.name == 'nt' else {}
    process = subprocess.Popen(command, cwd=directory, **options)
    return {'pid': process.pid, 'directory': str(directory)}
