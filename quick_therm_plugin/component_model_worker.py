"""Standalone workers; run prepare with KiCad Python, mesh with FreeCAD Python."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from collections import Counter


def model_variables(project):
    variables = dict(os.environ)
    roots = [Path('/usr'), Path('/usr/local')]
    config = Path.home()/'.config/kicad'
    if os.name == 'nt':
        roots = list(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'), 'KiCad').glob('*'))
        roots += list(Path(os.environ.get('LOCALAPPDATA', ''), 'Programs/KiCad').glob('*'))
        config = Path(os.environ.get('APPDATA', ''), 'kicad')
    for root in roots:
        library = root/'share/kicad/3dmodels'
        if library.is_dir():
            for version in range(6, 12):
                variables.setdefault('KICAD%d_3DMODEL_DIR'%version, str(library))
            variables.setdefault('KISYS3DMOD', str(library))
    for common in sorted(config.glob('*/kicad_common.json')):
        try:
            for key, value in (json.loads(common.read_text())['environment']['vars'] or {}).items():
                if key not in os.environ:
                    variables[key] = value
        except (OSError, ValueError, KeyError):
            continue
    variables['KIPRJMOD'] = str(project)
    return variables


def resolve_model(filename, variables, project):
    text = str(filename)
    for _ in range(8):
        expanded = re.sub(r'\$\{([^}]+)\}|\$\(([^)]+)\)',
                          lambda m:str(variables.get(m[1] or m[2],m[0])), text)
        if text == expanded:
            break
        text = expanded
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        path = Path(project)/path
    if path.suffix.lower() == '.wrl':
        for suffix in ('.step','.stp','.STEP','.STP'):
            if path.with_suffix(suffix).is_file():
                return path.with_suffix(suffix)
    return path if path.suffix.lower() in ('.step','.stp') and path.is_file() else None


def prepare(job):
    import pcbnew as p
    path, root = Path(job['board_path']), Path(job['root'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != job['source_sha256']:
        raise ValueError('Saved board changed before geometry snapshot.')
    board = p.LoadBoard(str(path))
    variables = model_variables(path.parent)
    counts = Counter(fp.GetReference() for fp in board.GetFootprints())
    data = {'model_map':{}, 'model_files':[], 'missing':[],
            'thickness_mm':p.ToMM(board.GetDesignSettings().GetBoardThickness())}
    (root/'models').mkdir()
    for index, fp in enumerate(board.GetFootprints()):
        ref = str(fp.GetReference())
        if not ref or '*' in ref or counts[ref] != 1 or fp.IsDNP():
            data['missing'].append({'reference':ref or '(blank)',
                                    'reason':'DNP or ambiguous reference; no traceable component model'})
            fp.Models().clear()
            continue
        loaded = 0
        for model_index, model in enumerate(fp.Models()):
            if hasattr(model, 'm_Show') and not model.m_Show:
                continue
            source = resolve_model(model.m_Filename, variables, path.parent)
            if source is None:
                data['missing'].append({'reference':ref, 'reason':'Enabled model has no resolved STEP/STP solid'})
                # Avoid accidental library substitutions outside reviewed resolution.
                model.m_Show = False
                fp.Models()[model_index] = model
                continue
            raw = source.read_bytes()
            if len(raw) > 100*1024*1024:
                raise ValueError(ref+': STEP model exceeds 100 MiB.')
            token = 'QTM%06dM%03d'%(index, model_index)
            literal = rb"'(?:[^']|'')*'"
            tagged, count = re.subn(rb'\bPRODUCT\s*\(\s*'+literal+rb'\s*,\s*'+literal,
                                    lambda m:b"PRODUCT('"+token.encode()+b"','"+token.encode()+b"'", raw)
            if not count:
                data['missing'].append({'reference':ref,'reason':'STEP has no PRODUCT identity for traceable import'})
                model.m_Show = False
                fp.Models()[model_index] = model
                continue
            dest = root/'models'/(token+'.step')
            dest.write_bytes(tagged)
            model.m_Filename = str(dest)
            fp.Models()[model_index] = model
            data['model_map'][token] = {'reference':ref,'sha256':hashlib.sha256(raw).hexdigest()}
            data['model_files'].append({'path':str(source),'sha256':hashlib.sha256(raw).hexdigest()})
            loaded += 1
        if not loaded and not any(row['reference']==ref for row in data['missing']):
            data['missing'].append({'reference':ref,'reason':'No enabled STEP model'})
    if not p.SaveBoard(str(root/'snapshot.kicad_pcb'),board):
        raise RuntimeError('KiCad could not create the private model snapshot.')
    (root/'prepared.json').write_text(json.dumps(data),encoding='utf-8')


def native_vertex(point, thickness):
    """KiCad STEP reverses Y; preserve its Z and model surface offsets."""
    return [float(point.x), -float(point.y), float(point.z)]


def mesh(job):
    import FreeCAD as App
    import Import
    import Part
    root = Path(job['root'])
    prepared = json.loads((root/'prepared.json').read_text(encoding='utf-8'))
    doc = App.newDocument('QuickThermModels')
    output = {'components':{},'missing':[]}
    try:
        Import.insert(str(root/'board.step'),doc.Name)
        groups, imported = {}, set()
        for obj in doc.Objects:
            if obj.TypeId not in ('PartDesign::Feature','Part::Feature') or not hasattr(obj,'Shape') or obj.Shape.isNull():
                continue
            match = re.search(r'QTM\d{6}M\d{3}', obj.Label)
            if not match or match[0] not in prepared['model_map']:
                continue
            shape = obj.Shape.copy()
            shape.Placement = obj.getGlobalPlacement()
            info = prepared['model_map'][match[0]]
            groups.setdefault(info['reference'],[]).append((shape,info['sha256']))
            imported.add(match[0])
        total = 0
        for ref, items in groups.items():
            shape = Part.makeCompound([item[0] for item in items])
            if not shape.isValid() or not shape.Solids:
                output['missing'].append({'reference':ref,'reason':'STEP import is invalid or has no solids'})
                continue
            # Coarsen only the display mesh; keep the exact STEP placement.
            for deflection in (.15,.3,.6,1.2):
                vertices, triangles = shape.tessellate(deflection)
                if len(triangles) <= 5000:
                    break
            if len(triangles)>5000 or total+len(triangles)>150000:
                output['missing'].append({'reference':ref,'reason':'STEP display triangle budget exceeded'})
                continue
            points = [native_vertex(point,prepared['thickness_mm']) for point in vertices]
            if not points or any(not math.isfinite(v) for point in points for v in point):
                output['missing'].append({'reference':ref,'reason':'STEP mesh is empty or nonfinite'})
                continue
            low = [min(p[i] for p in points) for i in range(3)]
            high = [max(p[i] for p in points) for i in range(3)]
            output['components'][ref] = {'vertices_mm':points,'triangles':[list(t) for t in triangles],
                                         'bounds_mm':low+high,'model_sha256':sorted(set(item[1] for item in items))}
            total += len(triangles)
        for token,info in prepared['model_map'].items():
            if token not in imported:
                output['missing'].append({'reference':info['reference'], 'reason':'KiCad/FreeCAD omitted an enabled STEP solid'})
    finally:
        App.closeDocument(doc.Name)
    (root/'meshes.json').write_text(json.dumps(output,allow_nan=False),encoding='utf-8')


if __name__ == '__main__':
    job = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    {'prepare':prepare,'mesh':mesh}[sys.argv[1]](job)
