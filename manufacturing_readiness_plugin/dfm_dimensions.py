"""Dimension overlays from native geometry, never inferred marker distances."""
from __future__ import annotations
import math


def track_width_dimensions(tracks, object_ids, to_mm, *, limit=500):
    wanted = set(object_ids); items = []; omitted = 0
    for track in tracks:
        identity = str(track.m_Uuid.AsString())
        if identity not in wanted or track.GetClass() != 'PCB_TRACK': continue
        a, b = track.GetStart(), track.GetEnd()
        x1, y1, x2, y2, width = map(to_mm, (a.x, a.y, b.x, b.y, track.GetWidth()))
        length = math.hypot(x2-x1, y2-y1)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2, width)) or width <= 0 or length <= 0: continue
        if len(items) >= limit:
            omitted += 1; continue
        cx, cy = (x1+x2)/2, (y1+y2)/2
        nx, ny = -(y2-y1)/length*width/2, (x2-x1)/length*width/2
        items.append(dict(uuid=identity, kind='track_width', actual_mm=width,
                          layer=getattr(track, 'GetLayer', lambda: None)(),
                          start_mm=[cx-nx, cy-ny], end_mm=[cx+nx, cy+ny]))
    return dict(items=items, omitted=omitted,
                notice='Arrows show native straight-track width. Distances between DRC marker positions are not copper clearances. '
                       'Pads, arcs and clearance gaps use KiCad reported dimensions until exact dimension geometry is available.')
