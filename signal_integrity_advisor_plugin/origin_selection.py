"""Cross-selection restricted to the editor that opened this saved snapshot."""
from pathlib import Path


def select_origin(board,identifiers=(),net=None):
    from wayricad_runtime.context import connect,saved_board
    client=connect()
    if saved_board(client)!=Path(board.GetFileName()).resolve():raise RuntimeError('Originating editor changed boards; reopen the tool.')
    raw=client.get_board();wanted=set(identifiers);items=[]
    for fp in raw.get_footprints():
        if fp.id.value in wanted:items.append(fp)
        for pad in fp.definition.pads:
            if pad.id.value in wanted or (net and pad.net.name==net):items.append(pad)
    for item in [*raw.get_tracks(),*raw.get_vias()]:
        if item.id.value in wanted or (net and item.net.name==net):items.append(item)
    if not items:raise ValueError('Reviewed items no longer exist in the originating editor. Refresh the saved snapshot.')
    raw.clear_selection();raw.add_to_selection(items)
    return len(items)
