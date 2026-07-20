"""pcbnew layout assist helpers for KiWay interface extraction."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set


class LayoutAssistant:
    """Create native KiCad groups for logical interfaces."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def create_interface_group(self, interface: Dict[str, Any], group_name: str = "") -> Any:
        """
        Create a KiCad PCB_GROUP containing all footprints in a logical interface.

        KiCad's Python API varies by major version, so this method uses feature
        checks for group creation and raises a clear error when groups are not
        available in the current pcbnew build.
        """
        try:
            import pcbnew
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pcbnew is required to create KiCad layout groups.") from exc

        group_cls = getattr(pcbnew, "PCB_GROUP", None)
        if group_cls is None:
            raise RuntimeError("This KiCad pcbnew API does not expose PCB_GROUP.")

        name = group_name or f"KiWay_{interface.get('name', 'Interface')}"
        footprints = self.interface_footprints(interface)
        if not footprints:
            raise ValueError(f"No board footprints matched interface group {name}.")

        group = group_cls(self.board)
        if hasattr(group, "SetName"):
            group.SetName(name)

        add_item = getattr(group, "AddItem", None) or getattr(group, "Add", None)
        if add_item is None:
            raise RuntimeError("PCB_GROUP exists but has no supported AddItem/Add method.")

        for fp in footprints:
            add_item(fp)

        board_add = getattr(self.board, "Add", None)
        if callable(board_add):
            board_add(group)

        refresh = getattr(pcbnew, "Refresh", None)
        if callable(refresh):
            refresh()

        return group

    def interface_footprints(self, interface: Dict[str, Any]) -> List[Any]:
        """Return the deterministic PCB footprint set represented by an interface."""
        refs = self._interface_references(interface)
        return sorted(
            (fp for fp in self.board.GetFootprints() if fp.GetReference() in refs),
            key=lambda fp: str(fp.GetReference()),
        )

    def _interface_references(self, interface: Dict[str, Any]) -> Set[str]:
        refs: Set[str] = set()
        for item in interface.get("pins", []):
            if isinstance(item, (list, tuple)) and item:
                refs.add(str(item[0]))
            elif isinstance(item, dict):
                ref = item.get("reference") or item.get("ref")
                if ref:
                    refs.add(str(ref))
        for ref in interface.get("references", []):
            refs.add(str(ref))
        return refs
