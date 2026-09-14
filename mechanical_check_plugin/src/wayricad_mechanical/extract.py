"""KiCad-owned geometry extraction; only imported in KiCad's Python runtime."""
import json
import os
import re
import shutil
import hashlib
import math
from collections import Counter
from pathlib import Path


def is_mounting(fp, configured=()):
    name = (str(fp.GetFPID()) + ' ' + fp.GetValue()).lower()
    return fp.GetReference() in configured or any(word in name for word in ('mounting', 'mount_hole', 'mtg', 'plated_hole', 'npth_hole'))


def model_variables(project_dir, extra=None):
    variables = dict(os.environ)
    roots = []
    if os.name == 'nt':
        roots = list(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'), 'KiCad').glob('*'))
        config_root = Path(os.environ.get('APPDATA', ''), 'kicad')
    else:
        config_root = Path.home() / '.config/kicad'
        roots = [Path('/usr'), Path('/usr/local')]
    for root in roots:
        library = root / 'share/kicad/3dmodels'
        if library.is_dir():
            for version in range(6, 12):
                variables.setdefault('KICAD%d_3DMODEL_DIR' % version, str(library))
            variables.setdefault('KISYS3DMOD', str(library))
    for common in sorted(config_root.glob('*/kicad_common.json')):
        try:
            variables.update(json.loads(common.read_text())['environment']['vars'] or {})
        except (OSError, ValueError, KeyError):
            continue
    variables.update(extra or {})
    variables['KIPRJMOD'] = str(project_dir)
    return variables


def resolve_model(filename, variables, project_dir):
    text = filename
    for _ in range(8):
        expanded = re.sub(r'\$\{([^}]+)\}|\$\(([^)]+)\)', lambda m: variables.get(m[1] or m[2], m[0]), text)
        if expanded == text:
            break
        text = expanded
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        path = Path(project_dir) / path
    if path.suffix.lower() == '.wrl':
        for suffix in ('.step', '.stp', '.STEP', '.STP'):
            if path.with_suffix(suffix).is_file():
                return path.with_suffix(suffix)
        return None
    return path if path.is_file() and path.suffix.lower() in ('.step', '.stp') else None


def prepare(board, workdir, project_dir, config):
    import pcbnew as p
    mm = p.ToMM
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    models_dir = workdir / 'models'
    models_dir.mkdir(exist_ok=True)
    variables = model_variables(project_dir, config['model_variables'])
    data = dict(name=Path(board.GetFileName()).name, thickness=mm(board.GetDesignSettings().GetBoardThickness()),
                components=[], pads=[], mounts=[], gaps=[], model_map={})
    seen = set()
    ref_counts = Counter(fp.GetReference() for fp in board.GetFootprints())
    for index, fp in enumerate(board.GetFootprints()):
        source_ref = fp.GetReference()
        ref = source_ref
        physical = bool(list(fp.Pads()) or list(fp.Models()))
        if not ref or ref_counts[ref] > 1:
            ref = (ref or 'Unreferenced') + '@' + fp.m_Uuid.AsString()[:8]
            if physical:
                data['gaps'].append(ref + ': ambiguous reference; assign a unique reference for traceable review')
        seen.add(ref)
        side = 'bottom' if fp.IsFlipped() else 'top'
        pos = fp.GetPosition()
        footprint = str(fp.GetFPID().GetLibItemName())
        mounting = is_mounting(fp, config['mounts'])
        dnp = bool(fp.IsDNP())
        bounds = fp.GetBoundingBox(False, False)
        component = dict(ref=ref, source_ref=source_ref, uuid=fp.m_Uuid.AsString(), value=fp.GetValue(), footprint=footprint, x=mm(pos.x), y=mm(pos.y),
                         side=side, dnp=dnp, mounting=mounting, smd=bool(fp.GetAttributes() & p.FP_SMD),
                         bounds_2d=[mm(bounds.GetLeft()), mm(bounds.GetTop()), mm(bounds.GetRight()), mm(bounds.GetBottom())],
                         models=[])
        data['components'].append(component)
        for pad in fp.Pads():
            point, size, drill = pad.GetPosition(), pad.GetSize(), pad.GetDrillSize()
            pad_box=pad.GetBoundingBox()
            radius=math.hypot(mm(max(abs(pad_box.GetLeft()-point.x),abs(pad_box.GetRight()-point.x))),
                              mm(max(abs(pad_box.GetTop()-point.y),abs(pad_box.GetBottom()-point.y))))
            hole = dict(ref=ref, number=pad.GetNumber(), x=mm(point.x), y=mm(point.y),
                        size=[mm(size.x), mm(size.y)], drill=[mm(drill.x), mm(drill.y)],
                        clearance_radius_mm=radius,
                        plating='NPTH' if pad.GetAttribute() == p.PAD_ATTRIB_NPTH else 'PTH' if max(drill.x, drill.y) else 'SMD',
                        copper=bool(pad.IsOnLayer(p.F_Cu) or pad.IsOnLayer(p.B_Cu)) and pad.GetAttribute() != p.PAD_ATTRIB_NPTH,
                        top=pad.IsOnLayer(p.F_Cu), bottom=pad.IsOnLayer(p.B_Cu), net=pad.GetNetname())
            data['pads'].append(hole)
            if mounting and max(drill.x, drill.y):
                data['mounts'].append(hole)
        if dnp and not config['include_dnp']:
            fp.Models().clear()
            continue
        for model_index, model in enumerate(fp.Models()):
            if hasattr(model, 'm_Show') and not model.m_Show:
                continue
            source = resolve_model(model.m_Filename, variables, project_dir)
            if source is None:
                data['gaps'].append(ref + ': unresolved STEP model ' + model.m_Filename)
                component['models'].append(dict(path=model.m_Filename, resolved=False))
                continue
            token = 'TDV%06dM%03d' % (index, model_index)
            dest = models_dir / (token + '.step')
            # KiCad preserves STEP PRODUCT names, not filenames. Give each model
            # a private identity without changing geometric entities or the source.
            raw = source.read_bytes()
            literal = rb"'(?:[^']|'')*'"
            pattern = rb'\bPRODUCT\s*\(\s*' + literal + rb'\s*,\s*' + literal
            renamed, count = re.subn(pattern, lambda m: b"PRODUCT('" + token.encode() + b"','" + token.encode() + b"'", raw)
            if not count:
                data['gaps'].append(ref + ': STEP PRODUCT identity could not be tagged')
            staging = dest.with_suffix('.tmp')
            staging.write_bytes(renamed)
            staging.replace(dest)
            model.m_Filename = str(dest.resolve())
            fp.Models()[model_index] = model
            data['model_map'][token] = ref
            component['models'].append(dict(path=str(source), resolved=True, token=token, sha256=hashlib.sha256(raw).hexdigest()))
        if not component['models'] and not mounting and physical:
            data['gaps'].append(ref + ': no enabled STEP model')
    snapshot = workdir / 'snapshot.kicad_pcb'
    original = board.GetFileName()
    try:
        if not p.SaveBoard(str(snapshot), board):
            raise RuntimeError('KiCad could not write the analysis snapshot')
    finally:
        board.SetFileName(original)
    data['snapshot'] = str(snapshot)
    return data


def prepare_file(board_path, workdir, config, project_dir=None):
    import pcbnew as p
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError('KiCad could not load board')
    return prepare(board, workdir, project_dir or Path(board_path).resolve().parent, config)
