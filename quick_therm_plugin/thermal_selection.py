"""Exact component navigation with confirmed multi-selection and rollback."""
from wayricad_runtime.analysis_selection import _origin, identity, select_origin


def select_origin_components(board_path, footprint_ids, *, expected_sha256=None,
                             focus=True, additive=False, launch_context=None):
    """Select reviewed footprint UUIDs atomically; no geometry writes."""
    return select_origin(board_path, footprint_ids, expected_sha256=expected_sha256,
                         focus=focus, additive=additive, footprints_only=True, return_details=True,
                         launch_context=launch_context)


def select_origin_component(board_path, footprint_id, *, expected_sha256=None, focus=True,
                            launch_context=None):
    """Compatibility wrapper for one reviewed component and explicit focus status."""
    result = select_origin_components(board_path, [footprint_id],
                                     expected_sha256=expected_sha256, focus=focus, launch_context=launch_context)
    return dict(selected_id=result['selected_ids'][0], focus=result['focus'])


def retained_references(previous, current):
    """Map unambiguous old references to the same physical footprints."""
    from collections import Counter

    def by_id(rows):
        counts = Counter(row['reference'] for row in rows)
        ids = Counter(row.get('id') for row in rows)
        return {row['id']: row['reference'] for row in rows
                if row.get('id') and ids[row['id']] == 1 and counts[row['reference']] == 1}

    old, new = by_id(previous), by_id(current)
    return {old[identifier]: new[identifier] for identifier in old.keys() & new.keys()}


def selected_origin_component_ids(board_path, *, expected_sha256=None, launch_context=None):
    """Map selected footprints or their pads back to all matching component rows."""
    from wayricad_runtime.analysis_selection import _selection_ids
    options = {} if launch_context is None else {'launch_context': launch_context}
    _, board = _origin(board_path, expected_sha256, **options)
    chosen = _selection_ids(board.get_selection())
    if not chosen:return []
    return sorted(identity(fp) for fp in board.get_footprints()
                  if identity(fp) in chosen or any(identity(pad) in chosen for pad in
                      getattr(getattr(fp, 'definition', None), 'pads', ())))
