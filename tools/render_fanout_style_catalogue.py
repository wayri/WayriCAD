"""Render README construction diagrams using native fanout geometry.

Run from the repository root with KiCad's Python and matplotlib installed.
These synthetic templates illustrate path construction, not DRC acceptance.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import pcbnew as api

from wayricad_runtime.fanout_families import FAMILIES
from wayricad_runtime.fanout_profiles import FANOUT_PATTERNS
from wayricad_runtime.routing import FanoutPlanner, plan_fanout


def point(x, y):
    return api.VECTOR2I(api.FromMM(x), api.FromMM(y))


def fixture(kind):
    """Return an isolated native footprint with spacious synthetic pads."""
    board = api.BOARD()
    for a, b in (((0, 0), (40, 0)), ((40, 0), (40, 40)),
                 ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        edge = api.PCB_SHAPE(board)
        edge.SetShape(api.SHAPE_T_SEGMENT)
        edge.SetStart(point(*a))
        edge.SetEnd(point(*b))
        edge.SetLayer(api.Edge_Cuts)
        board.Add(edge)
    fp = api.FOOTPRINT(board)
    fp.SetReference('J1' if kind == 'connector' else 'U1')
    fp.SetPosition(point(20, 20))
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    board.Add(fp)
    if kind == 'grid':
        positions = [(x, y) for y in (-3.6, -1.2, 1.2, 3.6)
                     for x in (-3.6, -1.2, 1.2, 3.6)]
    elif kind == 'connector':
        positions = [(x, y) for y in (-1, 1) for x in (-3, 0, 3)]
    else:
        positions = [(x, y) for x in (-4, 4) for y in (-2.4, -.8, .8, 2.4)]
        positions += [(x, y) for y in (-4, 4) for x in (-2.4, -.8, .8, 2.4)]
    for number, (x, y) in enumerate(positions, 1):
        net = api.NETINFO_ITEM(board, 'SIGNAL_' + str(number))
        board.Add(net)
        pad = api.PAD(fp)
        pad.SetNumber(str(number))
        pad.SetPosition(point(20 + x, 20 + y))
        pad.SetSize(point(.65, .65))
        pad.SetShape(api.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(api.PAD_ATTRIB_SMD)
        layers = api.LSET()
        layers.AddLayer(api.F_Cu)
        pad.SetLayerSet(layers)
        pad.SetNet(net)
        fp.Add(pad)
        if kind == 'connector':
            pad.SetSize(point(1.4, 1.4))
            pad.SetDrillSize(point(.8, .8))
            pad.SetAttribute(api.PAD_ATTRIB_PTH)
            pad.SetLayerSet(api.LSET.AllCuMask())
    if kind == 'connector':
        shape = api.PCB_SHAPE(fp)
        shape.SetShape(api.SHAPE_T_RECT)
        shape.SetStart(point(15, 17))
        shape.SetEnd(point(25, 23))
        shape.SetLayer(api.F_CrtYd)
        fp.Add(shape)
        fp.BuildCourtyardCaches()
    return board, fp


def slug(name):
    return name.lower().replace(' / ', '-').replace('/', '-').replace(' + ', '-').replace(' ', '-')


def render(style, destination):
    grid = FAMILIES['BGA/LGA / grid']
    kind = 'connector' if style == 'Connector edge' else 'grid' if style in grid or style == 'Via-in-pad' else 'perimeter'
    board, fp = fixture(kind)
    planner = FanoutPlanner(board, api, dict(pattern=style, length=.9,
        launch_length=.35, stagger_pitch=.65, spread_pitch=2.05,
        width=.15, clearance=.15, via_diameter=.5, via_drill=.2,
        escape_angle=30, add_vias=kind != 'connector', scope='Reference wildcard', ref=fp.GetReference()))
    values = planner._dimensions()
    pads = list(fp.Pads())
    if kind == 'connector':
        plans, rejected = plan_fanout(board, api, values)
        assert not rejected and len(plans) == len(pads), rejected
        paths = [plan.path for plan in plans]
    else:
        paths = [planner._paths([(fp, pad)], '', values, style, i)[0]
                 for i, pad in enumerate(pads)]
    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=130)
    fig.patch.set_facecolor('#f7fafc')
    ax.set_facecolor('#f7fafc')
    ax.add_patch(Rectangle((15, 17) if kind == 'connector' else (15.4, 15.4),
                           10 if kind == 'connector' else 9.2,
                           6 if kind == 'connector' else 9.2,
                           fill=False, edgecolor='#94a3b8', linestyle='--', linewidth=1.1))
    for pad in pads:
        pos = pad.GetPosition()
        x, y = api.ToMM(pos.x), api.ToMM(pos.y)
        ax.add_patch(Circle((x, y), api.ToMM(pad.GetSize().x) / 2,
                           facecolor='#e7c87b', edgecolor='#95722b', linewidth=.7, zorder=4))
        if kind == 'connector':
            ax.add_patch(Circle((x, y), .4, facecolor='#f7fafc', edgecolor='#95722b', zorder=5))
    for path in paths:
        xy = [(api.ToMM(p.x), api.ToMM(p.y)) for p in path]
        ax.plot(*zip(*xy), color='#008a92', linewidth=2.5, solid_capstyle='round', zorder=3)
        if kind != 'connector':
            ax.add_patch(Circle(xy[-1], .25, facecolor='#008a92', zorder=6))
            ax.add_patch(Circle(xy[-1], .10, facecolor='#f7fafc', zorder=7))
    ax.set_aspect('equal')
    ax.set_xlim(12.5, 27.5)
    ax.set_ylim(27, 13)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(style, fontsize=15, fontweight='bold', color='#12334b', pad=12)
    fig.text(.5, .055, 'Gold: pads   |   Teal: constructed escape / via   |   Dashed: footprint context',
             ha='center', fontsize=9, color='#334155')
    fig.text(.5, .018, 'Synthetic geometry illustration; not a clearance-checked routing plan.',
             ha='center', fontsize=8, color='#526477')
    fig.subplots_adjust(top=.86, bottom=.12, left=.04, right=.96)
    fig.savefig(destination, metadata={'Software': 'WayriCAD fanout catalogue renderer'})
    plt.close(fig)
    return dict(style=style, file=destination.name, fixture=kind, settings=values,
                paths_mm=[[[api.ToMM(p.x), api.ToMM(p.y)] for p in path] for path in paths])


def main():
    destination = ROOT / 'fanout_generator_plugin' / 'style-gallery'
    destination.mkdir(exist_ok=True)
    styles = (*FANOUT_PATTERNS, 'Via-in-pad')
    assert set(FANOUT_PATTERNS) == {s for family in FAMILIES.values() for s in family}
    records = [render(style, destination / (slug(style) + '.png')) for style in styles]
    sources = ('routing.py', 'perimeter_escape.py', 'connector_escape.py', 'fanout_profiles.py')
    provenance = dict(kicad_version=api.Version(), renderer=Path(__file__).name,
        source_sha256={name: hashlib.sha256((ROOT / 'wayricad_runtime' / name).read_bytes()).hexdigest()
                       for name in sources}, illustrations=records)
    (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    print(f'Rendered {len(records)} production-geometry illustrations.')


if __name__ == '__main__':
    main()
