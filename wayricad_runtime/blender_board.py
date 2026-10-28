"""Optional native saved-board context for Blender; never edits the PCB."""
from __future__ import annotations

import hashlib
from pathlib import Path


def source_board(bundle):
    """Return only an explicitly declared PCB source, never a global editor board."""
    for scope in (bundle, bundle.get('request', {}), bundle.get('geometry', {})):
        if not isinstance(scope, dict):continue
        for key in ('board_path', 'board', 'source_path'):
            value = scope.get(key)
            if isinstance(value, str) and Path(value).suffix.lower() == '.kicad_pcb':return Path(value)
    boards = [Path(path) for path, digest in (bundle.get('source_fingerprints') or {}).items()
              if digest and Path(path).suffix.lower() == '.kicad_pcb']
    if len(boards) == 1:return boards[0]
    return None


def native_context(path):
    """Collect closed edges, cutouts, drilled contours and footprint envelopes.

    Curves are display polygons at 0.02 mm chord tolerance. Envelopes use native
    footprint bounds excluding text, not package/STEP solids. No all-board copper
    extraction, mesh generation or numerical solve is performed.
    """
    import pcbnew as api
    if getattr(api, '_wayricad_ipc', False) or not hasattr(api, 'SHAPE_POLY_SET'):
        raise ImportError('Native KiCad Python is required for saved board context.')
    path = Path(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    board = api.LoadBoard(str(path))
    polygon = api.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(polygon, False):
        raise ValueError('Saved Edge.Cuts is not a closed outline; board context unavailable.')
    def ring(chain):
        return [[api.ToMM(chain.CPoint(i).x), api.ToMM(chain.CPoint(i).y)] for i in range(chain.PointCount())]
    outline = [{'outer_mm': ring(polygon.COutline(i)),
                'holes_mm': [ring(polygon.CHole(i, h)) for h in range(polygon.HoleCount(i))]}
               for i in range(polygon.OutlineCount())]
    if sum(len(row['outer_mm']) + sum(map(len, row['holes_mm'])) for row in outline) > 30_000:
        raise ValueError('Board outline exceeds visualization contour budget.')
    drills, components = [], []
    def hole(item):
        shape = item.GetEffectiveHoleShape()
        if not shape or shape.GetWidth() <= 0:return
        poly = api.SHAPE_POLY_SET()
        shape.TransformToPolygon(poly, api.FromMM(.02), api.ERROR_OUTSIDE)
        for i in range(poly.OutlineCount()):drills.append({'contour_mm': ring(poly.COutline(i))})
        if len(drills) > 10_000:raise ValueError('Board exceeds 10,000 drilled-contour budget.')
    for footprint in board.GetFootprints():
        if len(components) >= 5000:raise ValueError('Board exceeds 5,000 component-envelope budget.')
        box = footprint.GetBoundingBox(False, False)
        components.append({'reference': str(footprint.GetReference()),
                           'bbox_mm': [api.ToMM(box.GetLeft()), api.ToMM(box.GetTop()),
                                       api.ToMM(box.GetRight()), api.ToMM(box.GetBottom())],
                           'side': 'bottom' if footprint.GetLayer() == api.B_Cu else 'top'})
        for pad in footprint.Pads():hole(pad)
    for track in board.GetTracks():
        if track.GetClass() == 'PCB_VIA':hole(track)
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError('Saved board changed during Blender context extraction.')
    return {'board_thickness_mm': api.ToMM(board.GetDesignSettings().GetBoardThickness()),
            'outline': outline, 'drills': drills, 'components': components,
            'source_sha256': before, 'source_name': path.name}


def with_board_context(bundle):
    """Retain self-contained result geometry; add optional native context lazily."""
    if bundle.get('board_thermal_view'):return bundle, None
    path = source_board(bundle)
    if path is None:return bundle, 'No saved PCB path was supplied; only result geometry is shown.'
    try:context = native_context(path)
    except ImportError:
        return bundle, 'Saved-board context needs native KiCad Python; result geometry is retained without package/board context.'
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError) as exc:
        # Source hash custody is independently checked by the exporter. A
        # missing/unsupported display feature never becomes invented geometry.
        return bundle, 'Saved-board display context unavailable (' + type(exc).__name__ + '); result geometry is retained without invented context.'
    copied = dict(bundle);copied['board_thermal_view'] = context
    return copied, None
