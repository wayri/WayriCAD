"""Small pcbnew selection adapter shared by KiWay result windows.

KiCad has changed selection APIs between releases, so this deliberately uses
the stable BOARD_ITEM.SetSelected interface and refreshes the canvas once.
"""

from __future__ import annotations

from typing import Any, Iterable

import pcbnew


def _items(board: Any) -> Iterable[Any]:
    for footprint in getattr(board, "GetFootprints", lambda: [])():
        yield footprint
        for pad in footprint.Pads():
            yield pad
    for collection_name in ("GetTracks", "GetDrawings", "Zones"):
        for item in getattr(board, collection_name, lambda: [])():
            yield item


def select_items(board: Any, targets: Iterable[Any]) -> int:
    """Replace the PCB editor selection and return the selected item count."""
    target_ids = {id(item) for item in targets if item is not None}
    for item in _items(board):
        selected = id(item) in target_ids
        if selected:
            setter = getattr(item, "SetSelected", None)
            if callable(setter):
                try:
                    setter()
                except TypeError:
                    setter(True)
        else:
            clearer = getattr(item, "ClearSelected", None)
            if callable(clearer):
                clearer()
            else:
                setter = getattr(item, "SetSelected", None)
                if callable(setter):
                    try:
                        setter(False)
                    except TypeError:
                        pass
    if hasattr(pcbnew, "Refresh"):
        pcbnew.Refresh()
    return len(target_ids)


def footprint(board: Any, reference: str) -> Any:
    for item in getattr(board, "GetFootprints", lambda: [])():
        if str(item.GetReference()) == str(reference):
            return item
    return None


def pads_on_net(board: Any, net_name: str) -> list[Any]:
    return [
        pad
        for item in getattr(board, "GetFootprints", lambda: [])()
        for pad in item.Pads()
        if str(getattr(pad, "GetNetname", lambda: "")()) == str(net_name)
    ]
