"""Exact component navigation with confirmed multi-selection and rollback."""
from wayricad_runtime.analysis_selection import _origin, identity, select_origin


def select_origin_components(board_path, footprint_ids, *, expected_sha256=None,
                             focus=True, additive=False):
    """Select reviewed footprint UUIDs atomically; no geometry writes."""
    return select_origin(board_path, footprint_ids, expected_sha256=expected_sha256,
                         focus=focus, additive=additive, footprints_only=True, return_details=True)


def select_origin_component(board_path, footprint_id, *, expected_sha256=None, focus=True):
    """Compatibility wrapper for one reviewed component and explicit focus status."""
    result = select_origin_components(board_path, [footprint_id],
                                     expected_sha256=expected_sha256, focus=focus)
    return dict(selected_id=result['selected_ids'][0], focus=result['focus'])


def selected_origin_component_ids(board_path, *, expected_sha256=None):
    """Map selected footprints or their pads back to all matching component rows."""
    _, board = _origin(board_path, expected_sha256)
    chosen = {identity(item) for item in board.get_selection()}
    if not chosen:return []
    return sorted(identity(fp) for fp in board.get_footprints()
                  if identity(fp) in chosen or any(identity(pad) in chosen for pad in
                      getattr(getattr(fp, 'definition', None), 'pads', ())))
