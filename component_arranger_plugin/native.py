"""KiCad 10 placement adapter. All planner distances are millimetres."""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from . import engine


def uid(item):
    return item.m_Uuid.AsString()


def identity(item):
    for _ in range(8):
        try:
            return int(item)
        except (ValueError, TypeError):
            item = getattr(item, 'this', None)
    raise ValueError('Cannot identify the originating board.')


def serialize(board, api):
    formatter = api.STRING_FORMATTER()
    api.PCB_IO_KICAD_SEXPR().FormatBoardToFormatter(formatter, board)
    return formatter.GetString()


def context(board):
    path = Path(board.GetFileName())
    return {str(path.with_suffix(ext)): hashlib.sha256(path.with_suffix(ext).read_bytes()).hexdigest()
            if path.with_suffix(ext).is_file() else None for ext in ('.kicad_pro', '.kicad_dru')}


def fingerprint(board, api):
    selected = sorted(uid(fp) for fp in board.GetFootprints() if fp.IsSelected())
    source = Path(board.GetFileName())
    saved = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    return hashlib.sha256((serialize(board, api) + json.dumps([context(board), saved, selected, rule_state(board)], sort_keys=True)).encode()).hexdigest()


def rule_state(board):
    """Relevant live dimensional settings must match the saved validation context."""
    settings = board.GetDesignSettings()
    scalars = {name: getattr(settings, name) for name in ('m_MinClearance', 'm_TrackMinWidth',
               'm_CopperEdgeClearance', 'm_HoleClearance', 'm_HoleToHoleMin') if hasattr(settings, name)}
    classes = {}
    for name in sorted({pad.GetNetname() for fp in board.GetFootprints() for pad in fp.Pads()}):
        nc = settings.m_NetSettings.GetEffectiveNetClass(name)
        classes[name] = (nc.GetClearance(), nc.GetTrackWidth(), nc.GetViaDiameter(), nc.GetViaDrill())
    return dict(scalars=scalars, classes=classes)


def pose(fp, api):
    p = fp.GetPosition()
    bottom = fp.IsFlipped()
    return (api.ToMM(p.x), api.ToMM(p.y),
            ((180 if bottom else 0) - fp.GetOrientationDegrees()) % 360,
            'bottom' if bottom else 'top')


def set_pose(fp, value, api):
    x, y, angle, side = value
    if fp.IsFlipped() != (side == 'bottom'):
        fp.Flip(fp.GetPosition(), api.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees((180 if side == 'bottom' else 0) - angle)
    fp.SetPosition(api.VECTOR2I(api.FromMM(x), api.FromMM(y)))


def polygons(poly, api):
    return tuple(tuple((api.ToMM(poly.COutline(j).CPoint(i).x),
                        api.ToMM(poly.COutline(j).CPoint(i).y))
                       for i in range(poly.COutline(j).PointCount()))
                 for j in range(poly.OutlineCount()))


def courtyard(fp, api):
    fp.BuildCourtyardCaches()
    layers = (api.F_CrtYd, api.B_CrtYd) if fp.HasThroughHolePads() else ((api.B_CrtYd,) if fp.IsFlipped() else (api.F_CrtYd,))
    return tuple(poly for layer in layers for poly in polygons(fp.GetCourtyard(layer), api))


def model(fp, api, *, locked=False):
    """Measure local coordinates through a neutral native clone, never an AABB rotation."""
    original = pose(fp, api)
    clone = api.Cast_to_FOOTPRINT(fp.Duplicate(False))
    set_pose(clone, (0, 0, 0, 'top'), api)
    outlines = courtyard(clone, api)
    if not outlines:
        raise ValueError(f'{fp.GetReference()}: valid closed courtyard required; repair the footprint first.')
    fields = {field.GetName(): field.GetText() for field in fp.GetFields()}
    fields['Value'] = fp.GetValue()
    fields['Footprint'] = str(fp.GetFPID().GetLibItemName())
    pads = tuple(engine.Pad(p.GetNumber(), p.GetNetname(), api.ToMM(p.GetPosition().x),
                            api.ToMM(p.GetPosition().y)) for p in clone.Pads())
    margin = 0.0
    rules = fp.GetBoard().GetDesignSettings()
    for pad in fp.Pads():
        nc = rules.m_NetSettings.GetEffectiveNetClass(pad.GetNetname())
        margin = max(margin, api.ToMM(max(nc.GetClearance(), rules.m_MinClearance))
                              + api.ToMM(max(nc.GetTrackWidth(), rules.m_TrackMinWidth)))
    return engine.Footprint(uid(fp), fp.GetReference(), *original, courtyards=outlines,
                            pads=pads, fields=fields, locked=locked or fp.IsLocked(),
                            through_hole=fp.HasThroughHolePads(), routing_margin=margin)


def infer_anchor(footprints):
    """Prefer a connected high-pin-count IC; stable reference breaks equal scores."""
    if not footprints:
        raise ValueError('Choose at least two footprints.')
    return min(footprints, key=lambda f: (-sum(bool(p.net) for p in f.pads),
                                         not f.reference.upper().startswith('U'), f.reference)).key


def _box_polygon(box, api):
    a, b = box.GetOrigin(), box.GetEnd()
    l, t, r, b = api.ToMM(a.x), api.ToMM(a.y), api.ToMM(b.x), api.ToMM(b.y)
    return ((l, t), (r, t), (r, b), (l, b))


@dataclass
class Preview:
    source: str
    board_id: int
    options: dict
    before: dict
    result: object
    validated_digest: str = ''
    evidence: dict = None
    external_pads: tuple = ()


def digest(plan):
    return hashlib.sha256(json.dumps(dict(options=plan.options, before=plan.before,
            placements=[(f.key, f.x, f.y, f.angle, f.side) for f in plan.result.footprints]),
            sort_keys=True, allow_nan=False).encode()).hexdigest()


def propose(board, api, references, solve=None, **options):
    """Plan unrouted placement only; never detach a footprint from existing copper."""
    source = fingerprint(board, api)
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    if len(by_ref) != len(list(board.GetFootprints())):
        raise ValueError('Duplicate footprint references must be resolved first.')
    if len(set(references)) < 2 or set(references) - by_ref.keys():
        raise ValueError('Choose at least two existing footprints.')
    selected = [by_ref[r] for r in sorted(set(references))]
    board.BuildConnectivity()
    models, fixed = [], []
    for fp in selected:
        connected = any(any(not isinstance(item, api.PAD) or item.GetParent() != fp
                            for item in board.GetConnectivity().GetConnectedItems(pad)) for pad in fp.Pads())
        models.append(model(fp, api, locked=connected))
        if connected:
            fixed.append(fp.GetReference())
    anchor = options.get('anchor') or infer_anchor(models)
    if anchor in by_ref:
        anchor = uid(by_ref[anchor])
    allowed = {f.key for f in models}
    if anchor not in allowed:
        raise ValueError('Anchor must belong to the chosen group.')
    external = []
    nets = {p.net for f in models for p in f.pads if p.net}
    for fp in board.GetFootprints():
        if fp.GetReference() not in references:
            external.extend(engine.Pad(p.GetNumber(), p.GetNetname(), api.ToMM(p.GetPosition().x), api.ToMM(p.GetPosition().y))
                            for p in fp.Pads() if p.GetNetname() in nets)
    settings = engine.Settings(anchor=anchor, external_pads=tuple(external),
                    **{k: v for k, v in options.items() if k != 'anchor'})
    obstacles = []
    for fp in board.GetFootprints():
        if fp.GetReference() in references:
            continue
        outlines = courtyard(fp, api) or (_box_polygon(fp.GetBoundingBox(False, False), api),)
        sides = ('top', 'bottom') if fp.HasThroughHolePads() else (('bottom',) if fp.IsFlipped() else ('top',))
        obstacles.extend(engine.Obstacle(poly, sides) for poly in outlines)
    for zone in board.Zones():
        if zone.GetIsRuleArea() and zone.GetDoNotAllowFootprints():
            sides = tuple(s for s, layer in [('top', api.F_Cu), ('bottom', api.B_Cu)] if zone.IsOnLayer(layer))
            obstacles.extend(engine.Obstacle(poly, sides) for poly in polygons(zone.Outline(), api))
    outline = api.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outline, False):
        raise ValueError('A valid closed Edge.Cuts outline is required.')
    if outline.OutlineCount() != 1:
        raise ValueError('Multiple separate board outlines are not supported; choose a single-board project.')
    outer = polygons(outline, api)[0]
    holes = tuple(tuple((api.ToMM(outline.CHole(0, h).CPoint(i).x), api.ToMM(outline.CHole(0, h).CPoint(i).y))
                        for i in range(outline.CHole(0, h).PointCount())) for h in range(outline.HoleCount(0)))
    result = (solve or engine.arrange)(models, settings, obstacles=obstacles, board_outline=outer, board_holes=holes)
    if fingerprint(board, api) != source:
        raise ValueError('Board changed during planning; preview again.')
    result = replace(result, warnings=result.warnings + tuple('Existing routed/contacted footprint held fixed: ' + r for r in fixed))
    return Preview(source, identity(board), dict(options, anchor=anchor),
                   {uid(fp): pose(fp, api) for fp in selected}, result, external_pads=tuple(external))


def materialize(board, api, placements):
    by_id = {uid(fp): fp for fp in board.GetFootprints()}
    for key, value in placements.items():
        set_pose(by_id[key], value, api)
    board.BuildConnectivity()


def placements(plan):
    return {f.key: (f.x, f.y, f.angle, f.side) for f in plan.result.footprints}


def check(board, api, plan):
    if identity(board) != plan.board_id or fingerprint(board, api) != plan.source:
        raise ValueError('Board, selection or saved rules changed. Preview again.')


def validate(board, api, plan, progress=None):
    """Validate a serialized live snapshot in a disposable process with saved rules."""
    plan.validated_digest = ''
    plan.evidence = None
    check(board, api, plan)
    if not plan.result.complete:
        raise ValueError('No complete legal placement was found. Enlarge the area or reduce density.')
    source = Path(board.GetFileName())
    if not source.is_file() or not source.with_suffix('.kicad_pro').is_file():
        raise ValueError('Save the board and matching project before validation.')
    requested = digest(plan)
    with tempfile.TemporaryDirectory(prefix='wayricad-arrange-') as raw:
        folder = Path(raw)
        staged = folder / source.name
        staged.write_text(serialize(board, api), encoding='utf-8')
        for path, value in context(board).items():
            if value is not None:
                shutil.copy2(path, folder / Path(path).name)
        request, response = folder / 'request.json', folder / 'response.json'
        request.write_text(json.dumps(dict(board=str(staged), placements=placements(plan), rules=rule_state(board), area=plan.options['area'])), encoding='utf-8')
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('worker.py')), str(request), str(response)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 360
        try:
            while True:
                if time.monotonic() > deadline or (progress and progress() is False):
                    raise ValueError('Validation cancelled or timed out; source unchanged.')
                try:
                    stdout, stderr = process.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            process.kill(); process.communicate(); raise
        if not response.is_file():
            raise ValueError('Native validator did not complete: ' + stderr[-300:])
        answer = json.loads(response.read_text(encoding='utf-8'))
        if process.returncode or not answer.get('validated'):
            raise ValueError(answer.get('error', 'Native validation failed.'))
    check(board, api, plan)
    if digest(plan) != requested:
        raise ValueError('Proposal changed during validation; preview again.')
    plan.evidence = answer
    plan.validated_digest = requested


class Transaction:
    """In-window placement history with durable pre-apply board backup."""
    def __init__(self, board, api, plan):
        check(board, api, plan)
        if not plan.validated_digest or plan.validated_digest != digest(plan):
            raise ValueError('Validate the exact proposal before applying.')
        self.board, self.api, self.plan = board, api, plan
        self.expected, self.applied = plan.source, False
        self.original_images = self.capture()
        self.applied_images = None
        source = Path(board.GetFileName())
        self.backup = source.with_name(source.stem + '.arranger-backup-' + str(time.time_ns()) + '.kicad_pcb')
        with self.backup.open('x', encoding='utf-8') as stream:
            stream.write(serialize(board, api))

    def capture(self):
        """Keep full native children, not an inverse sequence of rounded transforms."""
        return {uid(fp): (self.api.FOOTPRINT(fp), fp.GetParentGroup(),
                {field.GetName(): self.api.KIID(uid(field)) for field in fp.GetFields()})
                for fp in self.board.GetFootprints() if uid(fp) in self.plan.before}

    def restore(self, images):
        by_id = {uid(fp): fp for fp in self.board.GetFootprints()}
        for key, (image, group, fields) in images.items():
            fp = by_id[key]
            fp.CopyFrom(image)
            fp.SetParentGroup(group)
            # KiCad CopyFrom recreates mandatory field UUIDs. Restore their
            # original identities after copying the full footprint children.
            for field in fp.GetFields():
                field.SetUuid(fields[field.GetName()])
        self.board.BuildConnectivity()

    def exchange(self, forward):
        if fingerprint(self.board, self.api) != self.expected or digest(self.plan) != self.plan.validated_digest:
            raise ValueError('Board or proposal changed; operation blocked.')
        if self.applied == forward:
            raise ValueError('Operation already performed.')
        old = self.original_images if forward else self.applied_images
        try:
            if forward:
                materialize(self.board, self.api, placements(self.plan))
            else:
                self.restore(self.original_images)
            self.board.SetModified()
            current = fingerprint(self.board, self.api)
            if not forward and current != self.plan.source:
                raise RuntimeError('Original footprint restoration differs; operation blocked.')
            if forward:
                self.applied_images = self.capture()
        except BaseException as error:
            try:
                self.restore(old)
                if fingerprint(self.board, self.api) != self.expected:
                    raise RuntimeError('Restored serialization differs.')
            except BaseException as recovery:
                raise RuntimeError('Recovery needs inspection; use the saved backup. ' + str(recovery)) from error
            raise
        self.expected, self.applied = current, forward
        return self
