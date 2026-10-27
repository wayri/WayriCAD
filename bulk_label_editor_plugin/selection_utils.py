"""Small pcbnew selection adapter shared by WayriCAD result windows.

KiCad has changed selection APIs between releases, so this deliberately uses
the stable BOARD_ITEM.SetSelected interface and refreshes the canvas once.
"""

from __future__ import annotations

from typing import Any, Iterable

import pcbnew
from wayricad_runtime.geometry import item_id


def _items(board: Any) -> Iterable[Any]:
    for footprint in getattr(board, "GetFootprints", lambda: [])():
        yield footprint
        for reader in ("GraphicalItems", "GetFields"):
            yield from getattr(footprint, reader, lambda: ())()
        for reader in ("Reference", "Value"):
            method = getattr(footprint, reader, None)
            if callable(method):
                yield method()
        for pad in footprint.Pads():
            yield pad
    for collection_name in ("Groups", "GetTracks", "GetDrawings", "Zones"):
        for item in getattr(board, collection_name, lambda: [])():
            yield item


def select_items(board: Any, targets: Iterable[Any]) -> int:
    """Replace the PCB editor selection and return the selected item count."""
    targets = list({item_id(item): item for item in targets if item is not None}.values())
    raw = getattr(board, "raw", None)
    if raw is not None:
        from wayricad_runtime.ipc import uid
        previous = list(raw.get_selection())
        expected = {item_id(item) for item in targets}
        try:
            raw.clear_selection()
            if targets:
                raw.add_to_selection([item.raw for item in targets])
            if {uid(item) for item in raw.get_selection()} != expected:
                raise RuntimeError("KiCad did not confirm the requested selection.")
        except Exception:
            raw.clear_selection()
            if previous:
                raw.add_to_selection(previous)
            if {uid(item) for item in raw.get_selection()} != {uid(item) for item in previous}:
                raise RuntimeError("Selection failed and the previous selection could not be restored.")
            raise
        finally:
            board.invalidate_reads()
        return len(targets)
    target_ids = {item_id(item) for item in targets}
    for item in _items(board):
        selected = item_id(item) in target_ids
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
