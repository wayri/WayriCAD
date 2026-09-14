"""KiCad 10 geometry and board edits; only KiCad's bundled libraries are used."""
from dataclasses import dataclass, replace
import re
import uuid
import pcbnew as pcb
from .engine import Cancelled, generate

PREFIX = "WayriCADCopper::v1::"
LEGACY_PREFIX = "CopperBalancer::v1::"
NET_PATTERN = re.compile(r"^(?:WayriCADCopper|CopperBalancer)/L(?P<layer>\d+)_[^/]+/[0-9a-f]{32}/\d{6}$")
ERROR_MM = .005


def polygon(points):
    result = pcb.SHAPE_POLY_SET()
    result.NewOutline()
    for x,y in points:
        result.Append(pcb.FromMM(x),pcb.FromMM(y))
    return result


def rectangle(bounds):
    x0,y0,x1,y1 = bounds
    return polygon(((x0,y0),(x1,y0),(x1,y1),(x0,y1)))


def copy(poly):
    return pcb.SHAPE_POLY_SET(poly)


def mm_area(poly):
    return abs(poly.Area()) / pcb.FromMM(1)**2


def rings(poly):
    result = []
    for i in range(poly.OutlineCount()):
        chains = [poly.COutline(i)] + [poly.CHole(i,j) for j in range(poly.HoleCount(i))]
        result.append([[(pcb.ToMM(c.CPoint(k).x),pcb.ToMM(c.CPoint(k).y)) for k in range(c.PointCount())] for c in chains])
    return result


def bounds_of(poly):
    points = [p for outer in rings(poly) for ring in outer for p in ring]
    if not points:
        raise ValueError("No usable board outline. Add a closed outline on Edge.Cuts first.")
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))


def inflate(poly, distance):
    if distance:
        poly.Inflate(pcb.FromMM(distance),pcb.CORNER_STRATEGY_ROUND_ALL_CORNERS,pcb.FromMM(ERROR_MM))
    return poly


def copper_layers(board):
    return [(int(layer),board.GetLayerName(layer)) for layer in board.GetEnabledLayers().CuStack()]


def managed_groups(board, layers):
    names = {prefix + str(layer) for prefix in (PREFIX, LEGACY_PREFIX) for layer in layers}
    groups = [g for g in board.Groups() if g.GetName() in names]
    for group in groups:
        for item in group.GetItems():
            if not isinstance(item,pcb.PCB_SHAPE) or item.GetShape() != pcb.SHAPE_T_POLY:
                raise ValueError("A WayriCAD copper group was edited to contain other items. Ungroup or rename it before replacing it.")
    return groups


def is_generated_net(name):
    return NET_PATTERN.fullmatch(name) is not None


def managed_items(board,layers):
    """Net identity survives ungrouping; legacy groups remain manageable.

    Select the object's current layer, so objects moved in KiCad can still be
    edited/removed by layer even though their net records the creation layer.
    """
    selected = set(layers)
    found = {item_id(item):item for item in board.GetDrawings()
             if isinstance(item,pcb.PCB_SHAPE) and item.GetLayer() in selected
             and is_generated_net(item.GetNetname())}
    for group in board.Groups():
        if not any(re.fullmatch(re.escape(prefix)+r"\d+",group.GetName()) for prefix in (PREFIX, LEGACY_PREFIX)):
            continue
        for item in group.GetItems():
            if item.GetLayer() not in selected:
                continue
            if not isinstance(item,pcb.PCB_SHAPE) or item.GetShape() != pcb.SHAPE_T_POLY:
                raise ValueError("A WayriCAD copper group contains unrelated items. Ungroup or rename it before replacing it.")
            found[item_id(item)] = item
    return list(found.values())


def allocate_net_names(board,layer,count,reserved):
    """Never attach generated copper to any existing net, including same-prefix nets."""
    layer_label = re.sub(r"[^A-Za-z0-9_.+-]","_",board.GetLayerName(layer)) or "Copper"
    for _ in range(100):
        batch = uuid.uuid4().hex
        names = [f"WayriCADCopper/L{layer}_{layer_label}/{batch}/{i:06d}" for i in range(1,count+1)]
        if not any(name in reserved for name in names):
            reserved.update(names)
            return names
    raise RuntimeError("Could not allocate unique copper net names. No board changes were made.")


def used_net_names(board):
    items = list(board.GetDrawings())+list(board.GetTracks())+list(board.Zones())
    for fp in board.GetFootprints():
        items.extend(fp.Pads())
        items.extend(fp.GraphicalItems())
        items.extend(fp.Zones())
        items.extend(fp.GetFields())
    return {item.GetNetname() for item in items if hasattr(item,"GetNetname")}


def item_id(item):
    return item.m_Uuid.AsString()


def selected_bounds(board):
    selected = [item for item in list(board.GetDrawings()) + list(board.GetTracks()) + list(board.GetFootprints()) if item.IsSelected()]
    selected += [z for z in board.Zones() if z.IsSelected()]
    if not selected:
        raise ValueError("Select board items before opening WayriCAD Copper Balancer, or use a manual rectangle.")
    boxes = [item.GetBoundingBox() for item in selected]
    return (min(pcb.ToMM(b.GetX()) for b in boxes),min(pcb.ToMM(b.GetY()) for b in boxes),
            max(pcb.ToMM(b.GetRight()) for b in boxes),max(pcb.ToMM(b.GetBottom()) for b in boxes))


@dataclass
class LayerPreview:
    layer: int
    name: str
    outline: list
    copper: list
    allowed: list
    plan: object
    clearance: float
    edge_clearance: float


class Geometry:
    def __init__(self, board, layer, settings, progress=None):
        self.board, self.layer, self.settings = board,layer,settings
        self.outline = pcb.SHAPE_POLY_SET()
        # Do not let KiCad silently infer a rectangular outline from board items.
        if not board.GetBoardPolygonOutlines(self.outline, False):
            raise ValueError("Edge.Cuts is not a valid closed outline. Repair gaps or intersections before generating copper.")
        self.bounds = bounds_of(self.outline)
        rules = board.GetDesignSettings()
        netclasses = board.GetAllNetClasses()
        default_nc = netclasses.get("Default")
        default_clearance = pcb.ToMM(default_nc.GetClearance()) if default_nc else 0
        maximum_net_clearance = max([0]+[pcb.ToMM(c.GetClearance()) for c in netclasses.values()])
        self.clearance = max(settings.clearance,pcb.ToMM(rules.m_MinClearance),default_clearance)
        self.settings = replace(settings,gap=max(settings.gap,pcb.ToMM(rules.m_MinClearance),default_clearance))
        self.edge_clearance = max(settings.edge_clearance,pcb.ToMM(rules.m_CopperEdgeClearance))
        self.allowed = inflate(copy(self.outline),-self.edge_clearance-ERROR_MM*2)
        if settings.mode == "Edge band":
            interior = inflate(copy(self.outline),-self.edge_clearance-settings.band_width)
            self.allowed.BooleanSubtract(interior)
        if settings.region:
            self.allowed.BooleanIntersection(rectangle(settings.region))
        # A local preview must not union the entire PCB. Bounding boxes provide
        # only a broad phase: every retained object still uses native polygon
        # geometry, and its own clearance expands the search region first.
        scope = settings.region
        if scope and (scope[2] <= self.bounds[0] or scope[0] >= self.bounds[2]
                      or scope[3] <= self.bounds[1] or scope[1] >= self.bounds[3]):
            raise ValueError("The chosen region does not overlap the board.")

        def relevant(box, margin):
            if scope is None:
                return True
            x0,y0,x1,y1 = [pcb.FromMM(v) for v in scope]
            gap = pcb.FromMM(margin)
            return not (box.GetRight()+gap < x0 or box.GetLeft()-gap > x1
                        or box.GetBottom()+gap < y0 or box.GetTop()-gap > y1)

        def clip_to_scope(poly, margin=0):
            if scope is not None:
                x0,y0,x1,y1 = scope
                poly.BooleanIntersection(rectangle((x0-margin,y0-margin,x1+margin,y1+margin)))
            return poly

        def add_obstacle(poly, clearance):
            # Keep a clearance-wide halo before inflation so shapes crossing
            # the region boundary retain exactly the same collision envelope.
            guard = clearance+ERROR_MM*2
            clip_to_scope(poly, guard)
            inflate(poly,guard)
            self.obstacles.BooleanAdd(clip_to_scope(poly))
        self.copper = pcb.SHAPE_POLY_SET()
        self.warnings = []
        self.ignored = set()
        if settings.replace:
            self.ignored = {item_id(item) for item in managed_items(board,[layer])}
        self.obstacles = pcb.SHAPE_POLY_SET()
        holes = pcb.SHAPE_POLY_SET()
        items = list(board.GetTracks()) + list(board.GetDrawings())
        zones = list(board.Zones())
        for fp in board.GetFootprints():
            items.extend(fp.Pads())
            items.extend(fp.GraphicalItems())
            items.extend(fp.GetFields())
            zones.extend(fp.Zones())
        for index,item in enumerate(items):
            if index % 100 == 0 and progress and progress(0,"Reading board geometry…") is False:
                raise Cancelled()
            if item_id(item) in self.ignored:
                continue
            # Holes are excluded on every copper layer, including NPTH and slots.
            if isinstance(item,(pcb.PAD,pcb.PCB_VIA)):
                hole = item.GetEffectiveHoleShape()
                hole_clearance = max(self.clearance,pcb.ToMM(rules.m_HoleClearance))
                if hole and hole.GetWidth() > 0 and relevant(hole.BBox(),hole_clearance+ERROR_MM*2):
                    hp = pcb.SHAPE_POLY_SET()
                    hole.TransformToPolygon(hp,pcb.FromMM(ERROR_MM),pcb.ERROR_OUTSIDE)
                    clip_to_scope(hp,hole_clearance+ERROR_MM*2)
                    holes.BooleanAdd(hp)
                    add_obstacle(hp,hole_clearance)
            if not item.IsOnLayer(layer):
                continue
            clearance = self.clearance
            if hasattr(item,"GetOwnClearance"):
                clearance = max(clearance,pcb.ToMM(item.GetOwnClearance(layer)))
            if hasattr(item,"GetLocalClearance"):
                local = item.GetLocalClearance()
                if local is not None:
                    clearance = max(clearance,pcb.ToMM(local))
            if hasattr(item,"GetNetClassName"):
                nc = netclasses.get(item.GetNetClassName())
                if nc:
                    clearance = max(clearance,pcb.ToMM(nc.GetClearance()))
                else:
                    # Composite netclasses are not exposed as NETCLASS proxies
                    # in KiCad 10 SWIG. A conservative fallback is intentional.
                    clearance = max(clearance,maximum_net_clearance)
            if not relevant(item.GetBoundingBox(),clearance+ERROR_MM*2):
                continue
            if not hasattr(item,"TransformShapeToPolygon"):
                raise ValueError(f"Cannot safely read a copper object ({type(item).__name__}). Generation stopped.")
            raw = pcb.SHAPE_POLY_SET()
            item.TransformShapeToPolygon(raw,layer,0,pcb.FromMM(ERROR_MM),pcb.ERROR_OUTSIDE)
            clip_to_scope(raw,clearance+ERROR_MM*2)
            self.copper.BooleanAdd(raw)
            add_obstacle(raw,clearance)
        for index,zone in enumerate(zones):
            if index % 10 == 0 and progress and progress(0,"Reading copper zones…") is False:
                raise Cancelled()
            if not zone.IsOnLayer(layer):
                continue
            # Reserve the entire zone, even if currently unfilled. Later refills
            # cannot merge the thieves with a net or reclaim their clearance.
            clearance = self.clearance
            if not zone.GetIsRuleArea():
                clearance = max(clearance,pcb.ToMM(zone.GetLocalClearance() or 0),pcb.ToMM(zone.GetOwnClearance(layer)))
            if not relevant(zone.GetBoundingBox(),clearance+ERROR_MM*2):
                continue
            boundary = copy(zone.Outline())
            if not zone.GetIsRuleArea():
                if zone.IsFilled() and zone.HasFilledPolysForLayer(layer):
                    self.copper.BooleanAdd(clip_to_scope(copy(zone.GetFilledPolysList(layer))))
                else:
                    self.warnings.append("An unfilled zone was reserved; fill zones in KiCad for accurate density measurements.")
            add_obstacle(boundary,clearance)
        self.allowed.BooleanSubtract(self.obstacles)
        self.outline.BooleanSubtract(holes)
        clip_to_scope(self.outline)
        self.copper.BooleanIntersection(self.outline)

    def accepts(self, points):
        candidate = polygon(points)
        candidate.BooleanSubtract(self.allowed)
        return candidate.OutlineCount() == 0

    def measure(self, bounds):
        region = rectangle(bounds)
        board_part = copy(self.outline)
        board_part.BooleanIntersection(region)
        copper_part = copy(self.copper)
        copper_part.BooleanIntersection(region)
        return mm_area(board_part),mm_area(copper_part)

    def preview(self, progress=None):
        plan = generate(self.settings,self.bounds,self.accepts,self.measure,progress)
        return LayerPreview(self.layer,self.board.GetLayerName(self.layer),rings(self.outline),rings(self.copper),
                            rings(self.allowed),plan,self.clearance,self.edge_clearance)


def build_preview(board, layers, settings, progress=None):
    settings.validate()
    previews,warnings = [],[]
    for i,layer in enumerate(layers):
        def update(fraction,message):
            return progress((i+fraction)/len(layers),f"{board.GetLayerName(layer)} · {message}") if progress else True
        geo = Geometry(board,layer,settings,update)
        previews.append(geo.preview(update))
        warnings.extend(geo.warnings)
    return previews,sorted(set(warnings))


def apply_preview(board, previews, settings):
    """Pre-create objects, then mutate with rollback. The action plugin owns undo.

    Returning from the modal action lets KiCad capture its before/after state.
    Each polygon gets a distinct, layer-labelled net. Existing nets are never
    reused. No saves, zone fills or mask openings are performed here.
    """
    layers = [preview.layer for preview in previews]
    old_items = managed_items(board,layers) if settings.replace else []
    old_ids = {item_id(item) for item in old_items}
    old_memberships = []
    for group in board.Groups():
        members = list(group.GetItems())
        if any(item_id(item) in old_ids for item in members):
            old_memberships.append((group,members))
    old_net_names = {item.GetNetname() for item in old_items if is_generated_net(item.GetNetname())}
    # KiCad 10 exposes map keys as wxString proxies. Their hashes are not
    # compatible with Python str; normalize before checking name collisions.
    reserved = {str(name) for name in board.GetNetsByName().keys()}
    prepared = []
    for preview in previews:
        if not preview.plan.shapes:
            continue
        group = pcb.PCB_GROUP(board)
        group.SetName(PREFIX+str(preview.layer))
        shapes = []
        names = allocate_net_names(board,preview.layer,len(preview.plan.shapes),reserved)
        for points,name in zip(preview.plan.shapes,names):
            shape = pcb.PCB_SHAPE(board)
            shape.SetShape(pcb.SHAPE_T_POLY)
            shape.SetPolyShape(polygon(points))
            shape.SetFilled(True)
            shape.SetWidth(0)
            shape.SetLayer(preview.layer)
            shapes.append((shape,pcb.NETINFO_ITEM(board,name)))
        prepared.append((group,shapes))
    removed,added,removed_nets = [],[],[]
    try:
        # Keep Python references to everything until the operation completes.
        for item in old_items:
            board.Remove(item)
            removed.append(item)
        for group,_ in old_memberships:
            if group.GetName().startswith((PREFIX, LEGACY_PREFIX)) and not group.GetItems():
                board.Remove(group)
                removed.append(group)
        for group,shapes in prepared:
            board.Add(group)
            added.append(group)
            for shape,net in shapes:
                board.Add(net)
                added.append(net)
                shape.SetNetCode(net.GetNetCode())
                if shape.GetNetname() != net.GetNetname():
                    raise RuntimeError("KiCad did not assign the generated net to a copper object.")
                board.Add(shape)
                added.append(shape)
                group.AddItem(shape)
        # Remove only the retired generated nets, and only when nothing else
        # anywhere on the board still uses them. Never sweep unrelated nets.
        still_used = used_net_names(board)
        for name in sorted(old_net_names-still_used):
            net = board.FindNet(name)
            if net:
                board.Remove(net)
                removed_nets.append(net)
    except Exception:
        for item in reversed(added):
            board.Remove(item)
        for net in removed_nets:
            board.Add(net)
        for item in removed:
            board.Add(item)
        # BOARD.Remove detaches members from their group. Restoring objects alone
        # is not enough to restore ownership after a failed replacement.
        for group,members in old_memberships:
            for item in members:
                group.AddItem(item)
        raise
    return sum(len(shapes) for _,shapes in prepared)


def remove_generated(board,layers):
    # Reuse transactional replacement with empty per-layer plans.
    from .engine import Plan,Settings
    previews = [LayerPreview(l,"",[],[],[],Plan(),0,0) for l in layers]
    count = len(managed_items(board,layers))
    apply_preview(board,previews,Settings(replace=True))
    return count


def review_stamp(board):
    """Include actual geometry so direct edits cannot bypass a timestamp check."""
    from pathlib import Path
    import sys
    root = Path(__file__).resolve().parents[1]
    if not (root / "wayricad_runtime").is_dir():
        sys.path.insert(0, str(root.parent))
    from wayricad_runtime.geometry import board_fingerprint
    return (board.GetTimeStamp(), board_fingerprint(board))
