"""Reviewed repairs on new source copies; never mutate the input project.

Repairs compile the selected assembly into Default. Originals and other variants
remain in the source archive. Ambiguous copper blocks repair; it is never deleted.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import copy
import hashlib
import json
import shutil
import tempfile
import os
import subprocess
import sys
import zipfile

from . import sexpr as sx
from .model import MergeError, SourceSpec,validate_source_aliases
from .schematic import discover, new_uuid
from .board import fp_reference, net_name, net_table, prepare_board
from .netlist import KiCadCLI
from .variants import effective_board_flags, set_field
from .copper_preservation import copper_geometry, require_preservable_copper, remap_preserved_copper

SKIP = {'.git', '.svn', '__pycache__', 'node_modules', '.venv', 'venv'}


def pad_geometry_signature(footprint):
    """Compare local pad geometry, normalizing rotation and 0.1 micrometre rounding."""
    position = sx.child(footprint, 'at', ['at', '0', '0'])
    rotation = float(position[3]) if len(position) > 3 else 0.0
    pads = []
    for original in sx.children(footprint, 'pad'):
        pad = copy.deepcopy(original)
        for node in sx.walk(pad):
            sx.remove(node, 'uuid'); sx.remove(node, 'tstamp'); sx.remove(node, 'net')
            if sx.tag(node) in {'at','size','drill','offset','xy'}:
                for index in range(1, len(node)):
                    if isinstance(node[index], list): continue
                    try: node[index] = format(round(float(node[index]), 4), '.4f')
                    except (ValueError, TypeError): pass
        at = sx.child(pad, 'at')
        if at is not None:
            angle = (float(at[3]) if len(at)>3 else 0.0) - rotation
            if len(at) < 4: at.append('0')
            at[3] = format(angle % 360.0, '.6f')
        pads.append(sx.dumps(pad))
    return tuple(pads)


def project_files(directory):
    directory = Path(directory).resolve()
    files = []
    total_bytes=0
    visited=set()
    def visit(folder):
        nonlocal total_bytes
        resolved=folder.resolve()
        if resolved in visited:raise MergeError('Source directory link/cycle is not supported: '+str(folder))
        visited.add(resolved)
        for p in sorted(folder.iterdir()):
            if p.name in SKIP:continue
            junction=getattr(p,'is_junction',lambda:False)() or getattr(p.lstat(),'st_reparse_tag',0)==0xA0000003
            if p.is_symlink() or junction or directory not in p.resolve().parents:
                raise MergeError('Source-copy repair does not follow symlinks: ' + str(p))
            if p.is_dir():
                if p.name not in SKIP and not p.name.endswith('-backups'):
                    visit(p)
            elif p.is_file() and not p.name.endswith(('.lck', '.kicad_prl')):
                files.append(p)
                total_bytes+=p.stat().st_size
                if total_bytes>12*1024**3:raise MergeError('Source copy exceeds 12 GiB.')
                if len(files) > 60000:
                    raise MergeError('Source copy exceeds 60,000 files.')
    visit(directory)
    return files


def fingerprint(directory):
    root = Path(directory).resolve()
    def digest(path):
        value=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
        return value.hexdigest()
    return {str(p.relative_to(root)): digest(p)
            for p in project_files(root)}


def copy_project(directory, destination):
    root = Path(directory).resolve()
    destination = Path(destination)
    destination.mkdir()
    for p in project_files(root):
        out = destination / p.relative_to(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)


def normalize_root_paths(tree, project_name):
    """Repair only a unique stale root-only owning-project path, never guess sheets."""
    root = sx.value(tree, 'uuid')
    paths = []
    for symbol in sx.children(tree, 'symbol'):
        for project in sx.children(sx.child(symbol, 'instances', ['instances']), 'project'):
            if str(project[1]) == project_name:
                paths.extend(sx.children(project, 'path'))
    roots = {str(p[1]).strip('/') for p in paths}
    if not paths or roots == {root}:
        return []
    if len(roots) != 1 or any('/' in r for r in roots) or not sx.UUID_RE.fullmatch(next(iter(roots))):
        raise MergeError('Ambiguous owning-project hierarchy. Save/annotate it in KiCad before repair.')
    old = next(iter(roots))
    for p in paths:
        p[1] = sx.q('/' + root)
    return [{'kind': 'root_path', 'before': '/' + old, 'after': '/' + root, 'instances': len(paths)}]


def net_partition_map(board, schematic):
    """Compare numbered-pad partitions; added components do not erase good routing."""
    old = defaultdict(set)
    keys = set()
    table = net_table(board)
    for fp in sx.children(board, 'footprint'):
        ref = fp_reference(fp)
        for pad in sx.children(fp, 'pad'):
            if str(pad[1]):
                key = (ref, str(pad[1]))
                keys.add(key)
                name = net_name(pad, table)
                if name:
                    old[name].add(key)
    restricted = {name: pins & keys for name, pins in schematic.nets.items()}
    mapping, changed = {}, []
    for name, pins in old.items():
        matches = [new for new, endpoints in restricted.items() if endpoints == pins]
        if len(matches) == 1:
            mapping[name] = matches[0]
        else:
            changed.append(name)
    return mapping, sorted(changed)


def _save_local_footprint(footprint, library, io, lib_id=None):
    """Freeze local geometry without moving or relinking the placed footprint.

    Native FootprintSave does not normalize footprint-owned zone vertices when
    given a positioned board footprint. Normalize a detached native copy so
    pads, graphics and rule areas all use the same library coordinate frame.
    """
    import pcbnew
    local = pcbnew.FOOTPRINT(footprint)
    if lib_id is not None:
        local.SetFPID(lib_id)
    if local.GetLayer() == pcbnew.B_Cu:
        local.Flip(local.GetPosition(), False)
    local.SetPosition(pcbnew.VECTOR2I(0, 0))
    local.SetOrientationDegrees(0)
    io.FootprintSave(str(library), local)


def _compile_copy(spec, cli, retain_blank=False):
    """Mutates only a disposable staged source directory supplied by caller."""
    project = Path(spec.project).with_suffix('.kicad_pro').resolve()
    tree = sx.load(project.with_suffix('.kicad_sch'))
    actions = normalize_root_paths(tree, project.stem)
    sx.save(project.with_suffix('.kicad_sch'), tree)
    source = discover(spec, new_uuid())
    if len({s.source_path for s in source.sheets}) != len(source.sheets):
        raise MergeError('Repair of reused sheet occurrences requires separate source copies; use the merge engine after synchronization.')
    if any(project.parent not in s.source_path.parents for s in source.sheets):
        raise MergeError('Repair cannot write external child sheets. Bring them into a candidate project first.')
    board = sx.load(source.pcb_file)
    original_copper_geometry = copper_geometry(board)
    ids = sx.declared_uuids(board)
    if len(ids) != len(set(ids)):
        raise MergeError('Repair does not guess genuinely duplicated PCB object UUIDs.')
    records = defaultdict(list)
    for record in source.symbols:
        records[record.old_ref].append(record)
    placed = {}
    used_refs = set(records)
    for fp in sx.children(board, 'footprint'):
        ref = fp_reference(fp)
        attr = sx.child(fp, 'attr', [])
        board_only = 'board_only' in attr
        if board_only:
            from .merge_issues import PLACEHOLDER
            if not ref or ref in used_refs or PLACEHOLDER.fullmatch(ref):
                raise MergeError(f'{ref!r}: review the Board Only reference issue and repair a detached source copy first.')
            used_refs.add(ref)
            continue
        if not ref or ref in placed or ref not in records:
            raise MergeError('Cannot safely match PCB component ' + repr(ref) + ' to a unique schematic reference.')
        rr = records[ref]
        desired = {sx.propval(r.node, 'Footprint') for r in rr}
        if len(desired) != 1:
            raise MergeError(ref + ': multi-unit footprint assignments disagree.')
        expected = desired.pop()
        if not expected:
            if not retain_blank:
                raise MergeError(ref + ': blank schematic footprint; explicitly select Retain placed blank assignments to repair it.')
            for r in rr:
                set_field(r.node, 'Footprint', str(fp[1]))
            expected = str(fp[1])
            actions.append({'kind': 'retain_blank_footprint', 'reference': ref, 'footprint': expected})
        if expected.split(':')[-1] != str(fp[1]).split(':')[-1]:
            raise MergeError(ref + ': incompatible footprint change. Repair will not resize/replace routed footprints.')
        if any(effective_board_flags(r)['on_board'] != 'yes' for r in rr):
            raise MergeError(ref + ': selected variant excludes a placed PCB part. Remove it in a reviewed native source copy first.')
        placed[ref] = fp

    # Compile effective fields/flags to a standalone Default source. Native export
    # is authoritative, including versions which ignore footprint field overrides.
    for sheet in source.sheets:
        sx.save(sheet.source_path, sheet.tree)
    project_data = source.project
    schematic = project_data.setdefault('schematic', {})
    schematic['variants'] = []
    for key in ('variant', 'current_variant'):
        schematic.pop(key, None)
    project.write_text(json.dumps(project_data, indent=2) + '\n', encoding='utf-8')
    native = cli.export_netlist(project.with_suffix('.kicad_sch'), project.parent / 'repair-netlist.xml')
    physical = {ref: rr for ref, rr in records.items()
                if not ref.startswith('#') and sx.propval(rr[0].node, 'Footprint')
                and effective_board_flags(rr[0])['on_board'] == 'yes'}
    unknown = set(placed) - set(native.components)
    if unknown:
        raise MergeError('Placed parts missing from native export: ' + ', '.join(sorted(unknown)))
    mapping, changed = net_partition_map(board, native)
    # Preflight before creating templates or writing PCB changes. A changed pad
    # does not justify deleting every plane/via/track on its former net.
    require_preservable_copper(board, native, mapping)
    for ref, fp in placed.items():
        padnums = {str(p[1]) for p in sx.children(fp, 'pad') if str(p[1])}
        pins = {pin for rr, pin in native.pins if rr == ref}
        if not pins.issubset(padnums):
            raise MergeError(ref + ': schematic pins are absent from the placed footprint: ' + ', '.join(sorted(pins-padnums)))

    import pcbnew
    # Preserve existing per-reference physical geometry, avoiding ambiguous missing
    # custom library nicknames and differing footprint revisions under one name.
    native_board = pcbnew.LoadBoard(str(source.pcb_file))
    templates = {}
    library = project.parent / 'FusionRepair.pretty'
    library.mkdir(exist_ok=True)
    io = pcbnew.PCB_IO_KICAD_SEXPR()
    for native_fp in native_board.GetFootprints():
        ref = native_fp.GetReference()
        if ref not in placed:
            continue
        item = str(native_fp.GetFPID().GetLibItemName())
        templates.setdefault(item, []).append(ref)
        _save_local_footprint(native_fp, library, io, pcbnew.LIB_ID('FusionRepair', ref))
    bounds = native_board.GetBoardEdgesBoundingBox()
    right,bottom = bounds.GetRight(),bounds.GetBottom()
    new_board = pcbnew.BOARD()
    for index, ref in enumerate(sorted(set(physical) - set(placed))):
        desired = sx.propval(physical[ref][0].node, 'Footprint').split(':')[-1]
        choices = templates.get(desired, [])
        if not choices:
            raise MergeError(ref + ': no placed geometry template for missing footprint ' + desired + '. Place it with KiCad first.')
        # A library ID alone is insufficient: templates must have equal pad geometry.
        signatures = set()
        for choice in choices:
            f = placed[choice]
            signatures.add(pad_geometry_signature(f))
        if len(signatures) != 1:
            raise MergeError(ref + ': placed templates disagree on pad geometry; choose a library revision in KiCad.')
        fp = io.FootprintLoad(str(library), choices[0])
        fp.SetReference(ref)
        fp.SetFPID(pcbnew.LIB_ID('FusionRepair', ref))
        # Place beside the saved footprint envelope, not inside existing routing.
        fp.SetPosition(pcbnew.VECTOR2I(right + pcbnew.FromMM(10 + index*4), bottom + pcbnew.FromMM(5)))
        fp.SetOrientationDegrees(0)
        _save_local_footprint(fp, library, io)
        # Use native temporary serialization to retain exact footprint semantics.
        new_board.Add(fp)
        actions.append({'kind': 'added_unplaced', 'reference': ref, 'footprint': desired})
    if list(new_board.GetFootprints()):
        temp = project.parent / ('.repair-new-' + new_uuid() + '.kicad_pcb')
        pcbnew.SaveBoard(str(temp), new_board)
        for node in sx.children(sx.load(temp), 'footprint'):
            board.append(node); placed[fp_reference(node)] = node
        for suffix in ('.kicad_pcb','.kicad_pro','.kicad_prl'):
            temp.with_suffix(suffix).unlink(missing_ok=True)
    table = net_table(board)
    pad_connectivity_changed = any(
        native.pins.get((ref, str(pad[1])), '') != mapping.get(net_name(pad, table), net_name(pad, table))
        for ref, fp in placed.items() for pad in sx.children(fp, 'pad') if str(pad[1]))
    copper_report = remap_preserved_copper(
        board, native, mapping,
        invalidate_fill=bool(pad_connectivity_changed or changed
                             or any(a['kind'] == 'added_unplaced' for a in actions)))
    actions.extend({'kind': 'invalidated_zone_fill_cache', 'uuid': item_id}
                   for item_id in copper_report['invalidated_zone_fill_uuids'])
    for ref, fp in placed.items():
        rr = records[ref]
        # Prefer a still-valid UUID association, then the reviewed unique unit 1.
        linked = source.link_map.get(sx.value(fp, 'path'))
        record = linked if linked in rr else next((r for r in rr if r.unit == 1), rr[0])
        from .schematic import pcb_association_path
        expected = pcb_association_path(record.old_path, source.old_root_uuid)
        if sx.value(fp, 'path') != expected:
            actions.append({'kind': 'relinked', 'reference': ref, 'before': sx.value(fp, 'path'), 'after': expected})
        sx.put(fp, 'path', sx.q(expected))
        fp[1] = sx.q('FusionRepair:' + ref)
        for r in rr:
            set_field(r.node, 'Footprint', 'FusionRepair:' + ref)
        for pad in sx.children(fp, 'pad'):
            old = net_name(pad, table)
            if str(pad[1]):
                desired = native.pins.get((ref, str(pad[1])), '')
            else:
                # Unnumbered exposed copper may intentionally be tied to drain/GND.
                # Preserve its assignment only when the numbered-pad partition agrees.
                if old and old not in mapping:
                    raise MergeError(ref + ': unnumbered copper pad belongs to a changed net; review it in KiCad.')
                desired = mapping.get(old, '')
            if old != desired:
                actions.append({'kind': 'pad_net', 'reference': ref, 'pad': str(pad[1]), 'before': old, 'after': desired})
            sx.remove(pad, 'net')
            if desired: pad.append(['net', sx.q(desired)])
        for n in sx.walk(fp):
            sx.remove(n, 'variant'); sx.remove(n, 'variants')
    sx.remove(board, 'net')
    sx.remove(board, 'variant'); sx.remove(board, 'variants')
    for sheet in source.sheets:
        sx.save(sheet.source_path, sheet.tree)
    sx.save(source.pcb_file, board)
    fp_table = sx.load(project.parent/'fp-lib-table') if (project.parent/'fp-lib-table').is_file() else ['fp_lib_table', ['version', '7']]
    for entry in list(sx.children(fp_table, 'lib')):
        if sx.value(entry, 'name') == 'FusionRepair': fp_table.remove(entry)
    fp_table.append(['lib', ['name', sx.q('FusionRepair')], ['type', sx.q('KiCad')],
                     ['uri', sx.q('${KIPRJMOD}/FusionRepair.pretty')], ['options', sx.q('')], ['descr', sx.q('Retained placed geometry for source repair')]])
    sx.save(project.parent/'fp-lib-table', fp_table)
    compiled = SourceSpec(str(project), spec.alias, spec.x_mm, spec.y_mm, '<Default>',
                          spec.path_variables.copy(), spec.path_remaps.copy(), spec.extra_asset_paths.copy(),
                          copy.deepcopy(spec.section_origin))
    checked = discover(compiled, new_uuid())
    prepare_board(checked)
    sx.save(checked.pcb_file, checked.board)
    pcbnew.LoadBoard(str(checked.pcb_file))
    final = cli.export_netlist(checked.schematic_file, project.parent/'repair-netlist.xml')
    saved = sx.load(checked.pcb_file)
    for fp in sx.children(saved, 'footprint'):
        ref = fp_reference(fp)
        if ref not in placed: continue
        if final.components[ref]['footprint'] != str(fp[1]):
            raise MergeError('Native footprint parity failed for ' + ref)
        if sx.value(fp, 'path') not in final.components[ref]['paths']:
            raise MergeError('Native UUID association failed for ' + ref)
        for pad in sx.children(fp, 'pad'):
            if str(pad[1]) and net_name(pad, net_table(saved)) != final.pins.get((ref, str(pad[1])), ''):
                raise MergeError('Native pad/net parity failed for ' + ref + '.' + str(pad[1]))
    if copper_geometry(saved) != original_copper_geometry:
        raise MergeError('Source repair changed existing copper identity or geometry; no output published.')
    report = {'selected_variant': spec.variant, 'compiled_variant': '<Default>', 'actions': actions,
              'copper_preservation': copper_report,
              'changed_old_nets': changed, 'board_preflight': 'passed', 'native_pad_net_parity': 'passed',
              'native_uuid_associations': 'passed', 'copper_identity_and_geometry': 'preserved',
              'manufacturing_ready': False, 'template_geometry_rounding_mm': 0.0001,
              'routing_review_required': bool(pad_connectivity_changed or changed
                                               or any(a['kind']=='added_unplaced' for a in actions))}
    (project.parent/'source-repair-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return compiled, report


@dataclass
class RepairPlan:
    spec: SourceSpec
    hashes: dict
    retain_blank: bool
    report: dict
    resolutions: dict | None = None


def _native_compile(spec,cli_path,retain_blank):
    """Keep SWIG board I/O out of the editor and wx worker process."""
    from .netlist import find_cli
    cli=Path(find_cli(cli_path))
    candidates=[cli.parent/('python.exe' if os.name=='nt' else 'python3'),Path(sys.executable)]
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):env.pop(key,None)
    errors=[]
    for python in dict.fromkeys(candidates):
        if not python.is_file() or not python.name.casefold().startswith('python'):continue
        probe=subprocess.run([str(python),'-I','-c','import pcbnew'],env=env,capture_output=True,text=True,
                             timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if probe.returncode:errors.append(probe.stderr[-1000:]);continue
        request={'spec':asdict(spec),'cli_path':str(cli),'retain_blank':retain_blank}
        proc=subprocess.run([str(python),'-I','-X','faulthandler',str(Path(__file__).with_name('repair_runner.py'))],
                            input=json.dumps(request),env=env,capture_output=True,text=True,encoding='utf-8',
                            timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode:
            raise MergeError('Native repair worker failed; originals are unchanged.\n'+proc.stderr[-5000:])
        try:data=json.loads(proc.stdout)
        except ValueError as exc:raise MergeError('Native repair worker returned an invalid result.') from exc
        return SourceSpec(**data['spec']),data['report']
    raise MergeError('Source repair needs KiCad Python with pcbnew.\n'+'\n'.join(errors))


def preview_repair(spec, cli_path='', retain_blank=False, resolutions=None):
    validate_source_aliases([spec])
    directory = Path(spec.project).with_suffix('.kicad_pro').resolve().parent
    before = fingerprint(directory)
    issue_report = None
    if resolutions is not None:
        from .merge_issues import scan_source, validate_resolutions
        issue_report = scan_source(spec)
        if issue_report['original_source_hashes'] != before:
            raise MergeError('Source changed during issue scan; preview again.')
        validate_resolutions(issue_report, resolutions)
        retain_blank = any(issue['action'] == 'retain_placed_footprint'
                           for issue in issue_report['issues'])
    with tempfile.TemporaryDirectory(prefix='fusion-repair-preview-') as folder:
        candidate = Path(folder)/directory.name
        copy_project(directory, candidate)
        if fingerprint(candidate)!=before:raise MergeError('Copied source differs from the repair preview snapshot.')
        reviewed_actions = []
        if issue_report is not None:
            from .merge_issues import apply_to_detached_board
            reviewed_actions = apply_to_detached_board(
                candidate / Path(spec.project).with_suffix('.kicad_pcb').name,
                issue_report, resolutions)
        copied = SourceSpec(**{**asdict(spec), 'project': str(candidate/Path(spec.project).with_suffix('.kicad_pro').name)})
        _, report = _native_compile(copied, cli_path, retain_blank)
        report['actions'] = reviewed_actions + report.get('actions', [])
    if before != fingerprint(directory):
        raise MergeError('Source changed during repair preview. Save and preview again.')
    return RepairPlan(spec, before, retain_blank, report, resolutions)


def apply_repair(plan, destination, cli_path=''):
    validate_source_aliases([plan.spec])
    from .engine import publish
    directory = Path(plan.spec.project).with_suffix('.kicad_pro').resolve().parent
    destination = Path(destination).resolve()
    if destination == directory or directory in destination.parents or destination.exists():
        raise MergeError('Choose a new repair-copy folder outside the source project.')
    if plan.hashes != fingerprint(directory):
        raise MergeError('Source changed after preview; preview again before creating a repair copy.')
    if not destination.parent.is_dir():
        raise MergeError('Repair output parent folder does not exist.')
    stage = Path(tempfile.mkdtemp(prefix='.fusion-repair-', dir=destination.parent))
    try:
        candidate = stage/'project'
        copy_project(directory, candidate)
        if fingerprint(candidate)!=plan.hashes:raise MergeError('Copied source differs from the reviewed repair snapshot.')
        reviewed_actions = []
        if plan.resolutions is not None:
            from .merge_issues import scan_source, apply_to_detached_board
            issue_report = scan_source(plan.spec)
            if issue_report['original_source_hashes'] != plan.hashes:
                raise MergeError('Original source changed after issue review; scan again.')
            reviewed_actions = apply_to_detached_board(
                candidate / Path(plan.spec.project).with_suffix('.kicad_pcb').name,
                issue_report, plan.resolutions)
        copied = SourceSpec(**{**asdict(plan.spec), 'project': str(candidate/Path(plan.spec.project).with_suffix('.kicad_pro').name)})
        compiled, report = _native_compile(copied, cli_path, plan.retain_blank)
        report['actions'] = reviewed_actions + report.get('actions', [])
        with zipfile.ZipFile(candidate/'original-source.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            for original in project_files(directory):archive.write(original,original.relative_to(directory).as_posix())
        (candidate/'original-source-hashes.json').write_text(json.dumps(plan.hashes,indent=2)+'\n',encoding='utf-8')
        if plan.hashes != fingerprint(directory):
            raise MergeError('Source changed during repair. Output was not published.')
        publish(candidate, destination)
        compiled.project = str(destination/Path(compiled.project).name)
        return compiled, report
    finally:
        shutil.rmtree(stage, ignore_errors=True)
