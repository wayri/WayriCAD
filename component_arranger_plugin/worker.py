"""Owned native child for independent saved-candidate DRC; never editor globals."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from collections import Counter


def main():
    result = Path(sys.argv[2])
    try:
        import pcbnew as api
        root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location('arranger_worker', root / '__init__.py', submodule_search_locations=[str(root)])
        package = importlib.util.module_from_spec(spec); sys.modules[spec.name] = package; spec.loader.exec_module(package)
        from arranger_worker.native import materialize, uid, rule_state, model, courtyard
        request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        source = Path(request['board'])
        cli = Path(sys.executable).with_name('kicad-cli.exe' if sys.platform == 'win32' else 'kicad-cli')
        if not cli.is_file():
            found = shutil.which('kicad-cli')
            if not found:
                raise ValueError('Matching KiCad CLI required for validation.')
            cli = Path(found)
        board = api.LoadBoard(str(source))
        manager = api.SETTINGS_MANAGER()
        manager.LoadProject(str(source.with_suffix('.kicad_pro')), False)
        board.SetProject(manager.GetProject(str(source.with_suffix('.kicad_pro'))))
        if json.loads(json.dumps(rule_state(board))) != request['rules']:
            raise ValueError('Live Board Setup differs from saved project. Save Board Setup and preview again.')
        before_pads = sorted((uid(fp), uid(p), p.GetNumber(), p.GetNetname()) for fp in board.GetFootprints() for p in fp.Pads())
        before_tracks = sorted((uid(t), str(t.GetStart()), str(t.GetEnd()), t.GetLayer(), t.GetWidth()) for t in board.GetTracks())
        reports = {}
        partitions = {}
        def connectivity():
            board.BuildConnectivity()
            terminals = [p for fp in board.GetFootprints() for p in fp.Pads()]
            terminals += [t for t in board.GetTracks() if isinstance(t, api.PCB_VIA)]
            terminals += list(board.Zones())
            ids = {uid(t) for t in terminals}; visited = set(); groups = []
            for terminal in terminals:
                if uid(terminal) in visited: continue
                connected = {uid(item) for item in board.GetConnectivity().GetConnectedItems(terminal)} | {uid(terminal)}
                visited.update(connected)
                groups.append(tuple(sorted(connected & ids)))
            return tuple(sorted(groups))
        for name in ('baseline', 'candidate'):
            folder = source.parent / name; folder.mkdir()
            staged = folder / source.name
            for ext in ('.kicad_pro', '.kicad_dru'):
                context = source.with_suffix(ext)
                if context.is_file():
                    shutil.copy2(context, staged.with_suffix(ext))
            settings = json.loads(staged.with_suffix('.kicad_pro').read_text(encoding='utf-8'))
            severity = settings.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rule_severities', {})
            for key in ('clearance', 'shorting_items', 'copper_edge_clearance', 'hole_clearance',
                        'hole_to_hole', 'courtyards_overlap', 'missing_courtyard', 'malformed_courtyard',
                        'silk_over_copper', 'solder_mask_bridge', 'disallowed_items', 'physical_clearance'):
                severity[key] = 'error'
            staged.with_suffix('.kicad_pro').write_text(json.dumps(settings), encoding='utf-8')
            if name == 'candidate':
                materialize(board, api, request['placements'])
                l,t,r,b = request['area']
                for fp in board.GetFootprints():
                    if uid(fp) not in request['placements']: continue
                    margin = model(fp, api).routing_margin
                    if any(x-margin < l-1e-8 or x+margin > r+1e-8 or y-margin < t-1e-8 or y+margin > b+1e-8
                           for poly in courtyard(fp, api) for x,y in poly):
                        raise ValueError('Rounded native placement leaves the permitted area or routing reservation.')
            if list(board.Zones()): api.ZONE_FILLER(board).Fill(board.Zones())
            partitions[name] = connectivity()
            if name == 'candidate' and partitions['candidate'] != partitions['baseline']:
                raise ValueError('Native pad/via/zone connectivity changed; rearrange only unrouted parts without copper contacts.')
            api.SaveBoard(str(staged), board, True)
            output = folder / 'drc.json'
            process = subprocess.run([str(cli), 'pcb', 'drc', '--format', 'json', '--severity-all',
                       '--all-track-errors', '--refill-zones', '-o', str(output), str(staged)],
                       capture_output=True, text=True, timeout=170,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if process.returncode or not output.is_file():
                raise ValueError('Native DRC failed: ' + (process.stderr or process.stdout)[-400:])
            reports[name] = json.loads(output.read_text(encoding='utf-8'))
            if name == 'baseline':
                counts = Counter(f.get('type') for f in reports[name].get('violations', []))
                if any(n >= 199 for n in counts.values()):
                    raise ValueError('Excessive baseline DRC findings prevent reliable comparison; resolve them first.')
        def signature(finding):
            return finding.get('type'), finding.get('severity'), tuple(sorted(i.get('uuid', '') for i in finding.get('items', [])))
        baseline = {signature(v) for v in reports['baseline'].get('violations', [])}
        candidate = reports['candidate'].get('violations', [])
        new = {signature(v) for v in candidate} - baseline
        moved = set(request['placements'])
        moved_pads = {uid(p) for fp in board.GetFootprints() if uid(fp) in moved for p in fp.Pads()}
        affected = [v for v in candidate if any(i.get('uuid') in moved | moved_pads for i in v.get('items', []))]
        if new or affected:
            raise ValueError(f'Candidate has {len(new)} new findings or {len(affected)} findings involving the group. Inspect placement/footprint geometry.')
        if before_pads != sorted((uid(fp), uid(p), p.GetNumber(), p.GetNetname()) for fp in board.GetFootprints() for p in fp.Pads()):
            raise ValueError('Pad identity or net assignment changed.')
        if before_tracks != sorted((uid(t), str(t.GetStart()), str(t.GetEnd()), t.GetLayer(), t.GetWidth()) for t in board.GetTracks()):
            raise ValueError('Existing routing changed.')
        result.write_text(json.dumps(dict(validated=True, baseline=len(baseline), candidate=len(candidate),
                          new_findings=0, pad_net_identity='unchanged', connectivity='unchanged', routing='unchanged')), encoding='utf-8')
        return 0
    except Exception as error:
        result.write_text(json.dumps(dict(validated=False, error=str(error))), encoding='utf-8')
        return 1


if __name__ == '__main__':
    # KiCad project globals belong to this disposable child. The response file
    # is closed before bypassing unsafe SWIG global-finalizer ordering.
    os._exit(main())
