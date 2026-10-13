"""Export connector escapes with scoped clearance rules to a separate review project.

The source board is never routed or given clearance overrides. Existing custom
rules keep higher priority than the generated exception. Native DRC on the
exported project remains necessary before accepting the proposed geometry.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import tempfile

from .geometry import board_fingerprint
from .routing import fanout_items


def validate_connector_clearance(board, api, clearance):
    """Return the board's clearance floor in native units; reject lower values.

    ``clearance`` is a positive native-unit distance. The saved project floor
    and the current native board floor are both retained, using the stricter
    value when the editor and saved project differ.
    """
    floor = int(board.GetDesignSettings().m_MinClearance)
    if floor < 0:
        raise ValueError('The native board clearance floor is invalid.')
    filename = board.GetFileName()
    project = Path(filename).with_suffix('.kicad_pro') if filename else None
    if project and project.exists():
        data = json.loads(project.read_text(encoding='utf-8-sig'))
        value = data.get('board', {}).get('design_settings', {}).get('rules', {}).get('min_clearance')
        if value is not None:
            value = float(value)
            if not math.isfinite(value) or value < 0:
                raise ValueError('The saved project clearance floor is invalid.')
            floor = max(floor, int(api.FromMM(value)))
    if int(clearance) <= 0 or int(clearance) < floor:
        raise ValueError('Connector clearance must be positive and at least the board minimum clearance.')
    return floor


def _expression_string(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def _rule_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def _rules(existing, generated):
    """Insert lower-priority rules before existing rules without changing them."""
    if not existing.strip():
        return '(version 1)\n\n' + generated
    if not re.search(r'^\s*\(version\s+1\s*\)', existing, re.MULTILINE):
        raise ValueError('The source custom rules need a supported (version 1) header.')
    first = re.search(r'^\s*\(rule\s', existing, re.MULTILINE)
    index = first.start() if first else len(existing)
    return existing[:index].rstrip() + '\n\n' + generated + '\n' + existing[index:]


def export_connector_review(board, api, plans, destination, name=None):
    """Write a new review directory containing a board, project and custom rules.

    ``plans`` contains the reviewed fanout candidates. Local-clearance candidates
    must carry ``connector_region`` polygon corners, ``clearance`` (native
    units), ``layer`` and their source pad. ``destination`` must not exist.
    ``name`` is an optional file basename; the source basename is used by default.
    Returns basenames and rule names, suitable for a UI completion message.
    """
    plans = list(plans)
    local = [plan for plan in plans if getattr(plan, 'local_clearance', False)]
    if not local:
        raise ValueError('No connector local-clearance candidates were supplied.')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Choose a new review directory; existing files are never overwritten.')
    if not destination.parent.is_dir():
        raise ValueError('The review directory parent must already exist.')
    filename = str(board.GetFileName())
    stem = name or ((Path(filename).stem if filename else 'board') + '-connector-review')
    if not stem or Path(stem).name != stem or stem in ('.', '..') or any(c in stem for c in '/\\:'):
        raise ValueError('Use a plain filename for the review project.')
    source = Path(filename).resolve() if filename else None
    siblings = {suffix: source.with_suffix(suffix) for suffix in ('.kicad_pro', '.kicad_dru')} if source else {}
    captured = {suffix: path.read_bytes() if path.exists() else None for suffix, path in siblings.items()}
    original = board_fingerprint(board)
    groups = {}
    for plan in local:
        validate_connector_clearance(board, api, plan.clearance)
        corners = getattr(plan, 'connector_region', [])
        if len(corners) < 3 or not plan.pad.GetNetname():
            raise ValueError('Connector candidates require an enclosed region and a named net.')
        key = (str(plan.footprint.GetReference()), int(plan.layer), int(plan.clearance),
               tuple((int(p.x), int(p.y)) for p in corners))
        groups.setdefault(key, []).append(plan)
    rule_names = []
    generated = []
    # Staging and a directory rename avoid leaving a partially written project.
    with tempfile.TemporaryDirectory(prefix='.connector-review-', dir=destination.parent) as staging:
        stage = Path(staging)
        snapshot = stage / 'snapshot.kicad_pcb'
        try:
            if api.SaveBoard(str(snapshot), board) is False:
                raise OSError('KiCad could not save the review snapshot.')
        finally:
            board.SetFileName(filename)
        clone = api.LoadBoard(str(snapshot))
        snapshot.unlink()
        if clone is None:
            raise ValueError('KiCad could not read the review snapshot.')
        existing_names = {str(zone.GetZoneName()) for zone in clone.Zones()}
        for index, (key, group) in enumerate(groups.items(), 1):
            ref, layer, clearance, corners = key
            area_name = 'WayriCAD connector ' + re.sub(r'[^A-Za-z0-9_-]', '_', ref) + ' ' + str(index)
            while area_name in existing_names:
                area_name += '_'
            existing_names.add(area_name)
            rule_names.append(area_name)
            zone = api.ZONE(clone)
            zone.SetIsRuleArea(True)
            zone.SetZoneName(area_name)
            zone.SetLayer(layer)
            for setter in ('SetDoNotAllowTracks', 'SetDoNotAllowVias', 'SetDoNotAllowPads',
                           'SetDoNotAllowFootprints', 'SetDoNotAllowZoneFills'):
                getattr(zone, setter)(False)
            polygon = zone.Outline()
            polygon.NewOutline()
            for x, y in corners:
                polygon.Append(x, y)
            # Enclosure includes copper width, not just a track's centerline.
            extent = max(max(plan.width // 2, plan.via_diameter // 2 if plan.add_via or plan.start_via else 0)
                         for plan in group) + 1
            polygon.Inflate(extent, api.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, 1)
            clone.Add(zone)
            nets = sorted({str(plan.pad.GetNetname()) for plan in group})
            selected = ' || '.join(obj + '.NetName == ' + _expression_string(net)
                                   for obj in ('A', 'B') for net in nets)
            condition = "A.enclosedByArea(" + _expression_string(area_name) + ") && B.enclosedByArea(" + _expression_string(area_name) + ") && (" + selected + ")"
            # Clearance applies only to copper pairs, leaving hole, edge and
            # mechanical constraints unchanged. Existing rules resolve later.
            generated.append('(rule ' + _rule_string(area_name) + '\n  (layer ' + _rule_string(clone.GetLayerName(layer)) + ')\n  (condition ' + _rule_string(condition) + ')\n  (constraint clearance (min ' + format(api.ToMM(clearance), '.9g') + 'mm)))\n')
        for item in fanout_items(clone, api, plans):
            clone.Add(item)
        board_name = stem + '.kicad_pcb'
        if api.SaveBoard(str(stage / board_name), clone) is False:
            raise OSError('KiCad could not save the routed review board.')
        project_bytes = captured.get('.kicad_pro')
        if project_bytes is None:
            # Standalone boards still retain the native fabrication floor.
            floor = int(board.GetDesignSettings().m_MinClearance)
            project_bytes = json.dumps({'board': {'design_settings': {'rules': {'min_clearance': api.ToMM(floor)}}}}).encode()
        else:
            # An unsaved native floor increase must not be lost when the saved
            # project accompanies the snapshot. Keep all other project fields.
            project_data = json.loads(project_bytes.decode('utf-8-sig'))
            rules = project_data.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {})
            native_floor = api.ToMM(int(board.GetDesignSettings().m_MinClearance))
            if float(rules.get('min_clearance') or 0) < native_floor:
                rules['min_clearance'] = native_floor
                project_bytes = (json.dumps(project_data, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
        (stage / (stem + '.kicad_pro')).write_bytes(project_bytes)
        rules_bytes = captured.get('.kicad_dru')
        existing = rules_bytes.decode('utf-8-sig') if rules_bytes is not None else ''
        (stage / (stem + '.kicad_dru')).write_text(_rules(existing, '\n'.join(generated)), encoding='utf-8', newline='\n')
        if board_fingerprint(board) != original:
            raise ValueError('The board changed during export; preview again.')
        for suffix, path in siblings.items():
            now = path.read_bytes() if path.exists() else None
            if now != captured[suffix]:
                raise ValueError('Project rules changed during export; preview again.')
        # rename() refuses an existing nonempty directory; check empty ones too.
        if destination.exists():
            raise ValueError('The review directory already exists.')
        stage.rename(destination)
    return {'board': board_name, 'project': stem + '.kicad_pro', 'rules': stem + '.kicad_dru',
            'rule_names': rule_names,
            'warning': 'Existing custom rules retain higher priority. Open the review project and run KiCad DRC.'}
