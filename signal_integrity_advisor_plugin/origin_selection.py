"""Cross-selection restricted to the editor that opened this saved snapshot."""
from wayricad_runtime.analysis_selection import select_origin as _select, selected_origin_ids


def select_origin(board, identifiers=(), net=None, **options):
    """Use the shared exact, confirmed selection transaction and optional focus."""
    options.setdefault('focus', True)
    return _select(board, identifiers, net, **options)
