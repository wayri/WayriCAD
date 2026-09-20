"""Deterministic, dependency-free pattern planning. All distances are millimetres.

The host geometry adapter supplies exact polygon containment and copper area.
No board mutation occurs during planning.
"""
from dataclasses import dataclass, field
import math
import random
from typing import Callable, Optional, Tuple

Point = Tuple[float, float]
Ring = Tuple[Point, ...]
SHAPES = ("Circle", "Square", "Diamond", "Hexagon", "Octagon", "Rounded square", "Organic blob", "Bar")
MODES = ("Uniform thieving", "Local density balance", "Edge band")
LATTICES = ("Square", "Hexagonal")


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    shape: str = "Circle"
    mode: str = "Uniform thieving"
    lattice: str = "Hexagonal"
    size: float = 1.0
    gap: float = 0.5
    clearance: float = 0.5
    edge_clearance: float = 1.0
    rotation: float = 0.0
    target: float = 35.0
    tile_size: float = 10.0
    band_width: float = 5.0
    seed: int = 42
    max_shapes: int = 12000
    replace: bool = True
    region: Optional[Tuple[float, float, float, float]] = None

    def validate(self):
        if self.shape not in SHAPES or self.mode not in MODES or self.lattice not in LATTICES:
            raise ValueError("Choose a supported pattern, mode, and lattice.")
        for name in ("size", "gap", "clearance", "edge_clearance", "rotation", "target", "tile_size", "band_width"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), (int,float)) or not math.isfinite(getattr(self, name)):
                raise ValueError(name.replace("_", " ").title() + " must be a finite number.")
        for name, lower, upper in (("size", .2, 20), ("gap", .1, 20), ("clearance", .1, 20),
                                   ("edge_clearance", .1, 50), ("tile_size", 2, 100), ("band_width", .2, 100), ("target", 1, 90)):
            if not lower <= getattr(self, name) <= upper:
                raise ValueError(f"{name.replace('_', ' ').title()} must be between {lower} and {upper}.")
        if type(self.seed) is not int or type(self.replace) is not bool:
            raise ValueError("Seed must be an integer and replace must be a boolean.")
        if type(self.max_shapes) is not int or not 1 <= self.max_shapes <= 50000:
            raise ValueError("Shape limit must be between 1 and 50,000.")
        if self.region is not None:
            if not isinstance(self.region, (tuple,list)) or len(self.region) != 4 or not all(type(v) in (int,float) and math.isfinite(v) for v in self.region):
                raise ValueError("Region coordinates must be finite numbers.")
            x0, y0, x1, y1 = self.region
            if x1 <= x0 or y1 <= y0:
                raise ValueError("Region width and height must be positive.")


@dataclass
class Tile:
    bounds: tuple
    board_area: float
    existing_area: float
    added_area: float = 0.0

    @property
    def density(self):
        return 100 * (self.existing_area + self.added_area) / self.board_area if self.board_area else 0


@dataclass
class Plan:
    shapes: list = field(default_factory=list)
    tiles: dict = field(default_factory=dict)
    candidates: int = 0
    rejected: int = 0
    limited: bool = False
    board_area: float = 0
    existing_area: float = 0
    rejection_reasons: dict = field(default_factory=lambda: dict(region_boundary=0, density_ceiling=0, geometry_clearance=0))

    def reject(self, reason):
        self.rejected += 1
        self.rejection_reasons[reason] += 1

    def diagnostics(self, target):
        cells = [t for t in self.tiles.values() if t.board_area > 0]
        return dict(rejections=dict(self.rejection_reasons), tiles=len(cells),
                    minimum_density=min((t.density for t in cells), default=0),
                    maximum_density=max((t.density for t in cells), default=0),
                    tiles_below_target=sum(t.density < target-1e-6 for t in cells),
                    tiles_initially_above_target=sum(100*t.existing_area/t.board_area > target+1e-6 for t in cells),
                    deficit_area_mm2=sum(max(0,t.board_area*target/100-t.existing_area-t.added_area) for t in cells))

    @property
    def added_area(self):
        return sum(area(poly) for poly in self.shapes)

    @property
    def density(self):
        return 100 * (self.existing_area + self.added_area) / self.board_area if self.board_area else 0


def area(points):
    return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def template(settings):
    """Size is outer diameter, or side length for square-derived patterns.

    Bars are size long and size/3 wide. Every template has a bounded envelope;
    the lattice uses its circumcircle to guarantee a minimum inter-shape gap.
    """
    size, shape = settings.size, settings.shape
    r = size / 2
    if shape in ("Square", "Diamond"):
        points = [(-r,-r), (r,-r), (r,r), (-r,r)]
    elif shape == "Rounded square":
        cr = size * .2
        points = []
        for cx, cy, start in ((r-cr,r-cr,0), (-r+cr,r-cr,90), (-r+cr,-r+cr,180), (r-cr,-r+cr,270)):
            for j in range(9):
                a = math.radians(start + j*90/8)
                points.append((cx + cr*math.cos(a), cy + cr*math.sin(a)))
    elif shape == "Bar":
        points = [(-r,-r/3), (r,-r/3), (r,r/3), (-r,r/3)]
    else:
        n = {"Circle":48, "Hexagon":6, "Octagon":8, "Organic blob":64}[shape]
        points = []
        for i in range(n):
            a = i*2*math.pi/n
            radius = r * (.84 + .1*math.cos(3*a) + .06*math.sin(5*a)) if shape == "Organic blob" else r
            points.append((radius*math.cos(a), radius*math.sin(a)))
    angle = math.radians(settings.rotation + (45 if shape == "Diamond" else 0))
    return tuple((x*math.cos(angle)-y*math.sin(angle), x*math.sin(angle)+y*math.cos(angle)) for x,y in points)


def clip_rect(poly, bounds):
    """Clip a simple candidate polygon to an axis-aligned density tile."""
    result = list(poly)
    for axis, bound, sign in ((0,bounds[0],1), (0,bounds[2],-1), (1,bounds[1],1), (1,bounds[3],-1)):
        output = []
        for a,b in zip(result, result[1:] + result[:1]):
            ia, ib = sign*(a[axis]-bound) >= 0, sign*(b[axis]-bound) >= 0
            if ia:
                output.append(a)
            if ia != ib:
                t = (bound-a[axis])/(b[axis]-a[axis])
                output.append((a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])))
        result = output
    return result


def generate(settings: Settings, bounds, accepts: Callable, measure: Callable, progress=None):
    """measure(rect) -> (board area, existing copper area), accepts(poly) -> bool.

    A deterministic shuffle distributes limited/targeted fill over the board.
    Density budgets account for every tile crossed by a candidate, including
    partial board-edge tiles. Candidates crossing a full tile are rejected.
    """
    settings.validate()
    plan = Plan()
    if not isinstance(bounds, (tuple,list)) or len(bounds) != 4 or not all(type(v) in (int,float) and math.isfinite(v) for v in bounds):
        raise ValueError("Board bounds must contain four finite numbers.")
    x0,y0,x1,y1 = bounds
    if settings.region:
        rx0,ry0,rx1,ry1 = settings.region
        x0,y0,x1,y1 = max(x0,rx0),max(y0,ry0),min(x1,rx1),min(y1,ry1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("The chosen region does not overlap the board.")
    tile = settings.tile_size
    nx,ny = math.ceil((x1-x0)/tile),math.ceil((y1-y0)/tile)
    if nx*ny > 10000:
        raise ValueError("Too many density tiles. Increase the tile size or use a smaller region.")
    for iy in range(ny):
        if progress and progress(0, "Measuring copper density…") is False:
            raise Cancelled()
        for ix in range(nx):
            rect = (x0+ix*tile,y0+iy*tile,min(x1,x0+(ix+1)*tile),min(y1,y0+(iy+1)*tile))
            ba,ca = measure(rect)
            rect_area = (rect[2]-rect[0])*(rect[3]-rect[1])
            tolerance = max(1e-7,rect_area*1e-7)
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (ba,ca)) or ba < -tolerance or ca < -tolerance or ca > ba+tolerance or ba > rect_area+tolerance:
                raise ValueError("Geometry adapter returned invalid board/copper areas; refill zones and inspect the outline.")
            ba,ca = max(0,min(ba,rect_area)),max(0,min(ca,ba))
            plan.tiles[ix,iy] = Tile(rect,ba,ca)
            plan.board_area += ba
            plan.existing_area += ca
    base = template(settings)
    radius = max(math.hypot(x,y) for x,y in base)
    pitch = radius*2 + settings.gap + .002  # IU rounding guard
    row_step = pitch * (math.sqrt(3)/2 if settings.lattice == "Hexagonal" else 1)
    rows,cols = math.ceil((y1-y0)/row_step),math.ceil((x1-x0)/pitch)
    if rows*cols > 500000:
        raise ValueError("More than 500,000 candidate sites. Increase size/gap or narrow the region.")
    sites = [(ix,iy) for iy in range(rows) for ix in range(cols)]
    random.Random(settings.seed).shuffle(sites)
    for index,(ix,iy) in enumerate(sites):
        if index % 100 == 0 and progress and progress(index/max(1,len(sites)), f"Checking {index:,} of {len(sites):,} sites…") is False:
            raise Cancelled()
        x = x0 + radius + ix*pitch + (pitch/2 if settings.lattice == "Hexagonal" and iy%2 else 0)
        y = y0 + radius + iy*row_step
        poly = tuple((px+x,py+y) for px,py in base)
        plan.candidates += 1
        if any(px < x0 or px > x1 or py < y0 or py > y1 for px,py in poly):
            plan.reject('region_boundary')
            continue
        covered = []
        bx0,by0 = min(p[0] for p in poly),min(p[1] for p in poly)
        bx1,by1 = max(p[0] for p in poly),max(p[1] for p in poly)
        for ty in range(max(0,int((by0-y0)//tile)), min(ny-1,int((by1-y0)//tile))+1):
            for tx in range(max(0,int((bx0-x0)//tile)), min(nx-1,int((bx1-x0)//tile))+1):
                cell = plan.tiles[tx,ty]
                contribution = area(clip_rect(poly,cell.bounds))
                if contribution > 1e-12:
                    covered.append((cell,contribution))
        if settings.mode == "Local density balance" and any(
            cell.existing_area + cell.added_area + amount > cell.board_area*settings.target/100 + 1e-9
            for cell,amount in covered
        ):
            plan.reject('density_ceiling')
            continue
        if not accepts(poly):
            plan.reject('geometry_clearance')
            continue
        plan.shapes.append(poly)
        for cell,amount in covered:
            cell.added_area += amount
        if len(plan.shapes) >= settings.max_shapes:
            plan.limited = index + 1 < len(sites)
            break
    if progress:
        progress(1, "Preview ready")
    return plan
