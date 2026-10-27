"""Read the originating PCB's nets and members without importing GUI bindings.

Net names are electrical identities, not editable drawing text. This inventory
does not rename nets, alter connectivity or retain IPC reads between refreshes.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass


class InventoryError(RuntimeError):
    """The board could not provide a complete, usable net inventory."""


@dataclass(frozen=True)
class NetRow:
    """One named net, member counts and stable IDs for PCB cross-selection."""

    name: str
    pads: int
    tracks: int
    vias: int
    zones: int
    member_ids: tuple[str, ...]
    terminals: tuple[str, ...]

    @property
    def members(self):
        return self.pads + self.tracks + self.vias + self.zones


def _read(label, reader):
    try:
        return list(reader())
    except Exception as exc:
        raise InventoryError(f"Cannot read {label} from the originating PCB: {exc}") from exc


def _identity(item):
    value = getattr(item, "m_Uuid", None)
    if value is None and callable(getattr(item, "GetUuid", None)):
        value = item.GetUuid()
    if value is None:
        raise InventoryError("A connected PCB item has no UUID; cross-selection cannot be verified.")
    identifier = str(value.AsString() if callable(getattr(value, "AsString", None)) else value)
    if not identifier:
        raise InventoryError("A connected PCB item has an empty UUID.")
    return identifier


def _names(board):
    # The facade's startup net_names cache is deliberately not authoritative:
    # another editor action can create or rename nets while this window is open.
    raw = getattr(board, "raw", None)
    if raw is not None:
        reader = getattr(raw, "get_nets", None)
        if not callable(reader):
            raise InventoryError("This PCB IPC runtime cannot list live nets. Update the plugin/runtime.")
        nets = _read("live net names", reader)
        try:
            return [str(net.name) for net in nets]
        except AttributeError as exc:
            raise InventoryError("The PCB API returned an unsupported net record.") from exc
    reader = getattr(board, "GetNetsByName", None)
    if not callable(reader):
        raise InventoryError("This editor does not expose PCB nets. Open Bulk Label Editor from PCB Editor.")
    try:
        nets = reader()
        return [str(net.GetNetname()) for net in nets.values()]
    except Exception as exc:
        raise InventoryError(f"Cannot read PCB net names: {exc}") from exc


def collect_nets(board):
    """Return all named PCB nets, sorted by name, with one read per collection.

    Include named but currently unused nets. Ignore the unconnected empty net.
    Tracks include straight and arc segments; vias are counted separately.
    Rule areas are excluded because they are not electrically connected zones.
    IPC reads share a bounded synchronous snapshot, released before returning.
    Any failed collection raises InventoryError rather than reporting zero nets.
    """
    snapshot = getattr(board, "read_snapshot", None)
    try:
        with snapshot() if callable(snapshot) else nullcontext():
            records = {name: dict(pads=0, tracks=0, vias=0, zones=0, ids=set(), terminals=set())
                       for name in _names(board) if name}

            def add(item, kind, terminal=None):
                name = str(item.GetNetname())
                if not name:
                    return
                row = records.setdefault(name, dict(pads=0, tracks=0, vias=0, zones=0,
                                                   ids=set(), terminals=set()))
                identifier = _identity(item)
                if identifier in row["ids"]:
                    raise InventoryError("The PCB returned a duplicate connected-item UUID.")
                row[kind] += 1
                row["ids"].add(identifier)
                if terminal is not None:
                    row["terminals"].add(terminal)

            for footprint in _read("footprints", board.GetFootprints):
                reference = str(footprint.GetReference())
                for pad in _read(f"pads of {reference}", footprint.Pads):
                    add(pad, "pads", f"{reference}.{pad.GetNumber()}")
            for track in _read("tracks and vias", board.GetTracks):
                native_class = str(getattr(track, "GetClass", lambda: type(track).__name__)())
                add(track, "vias" if native_class in {"PCB_VIA", "VIA", "Via"} else "tracks")
            for zone in _read("zones", board.Zones):
                if not bool(zone.GetIsRuleArea()):
                    add(zone, "zones")
            return [NetRow(name, row["pads"], row["tracks"], row["vias"], row["zones"],
                           tuple(sorted(row["ids"])), tuple(sorted(row["terminals"])))
                    for name, row in sorted(records.items(), key=lambda pair: (pair[0].casefold(), pair[0]))]
    except InventoryError:
        raise
    except Exception as exc:
        raise InventoryError(f"Cannot complete the PCB net inventory: {exc}") from exc


def select_nets(board, names):
    """Resolve the requested nets afresh and replace selection without edits.

    IPC uses one bulk query plus one selection update, never one editor request
    per pad/track. Native boards compare stable UUIDs instead of wrapper IDs.
    """
    from .selection_utils import select_items
    names = set(names)
    if not names:
        raise ValueError("Select at least one named net.")
    if names - set(_names(board)):
        raise ValueError("A selected net was removed; reload the PCB and nets.")
    raw = getattr(board, "raw", None)
    if raw is not None:
        members = raw.get_items_by_net([board.types.Net(name=name) for name in sorted(names)])
        targets = [board.wrap(item) for item in members
                   if getattr(getattr(item, "net", None), "name", "") in names]
    else:
        snapshot = getattr(board, "read_snapshot", None)
        with snapshot() if callable(snapshot) else nullcontext():
            candidates = [pad for fp in board.GetFootprints() for pad in fp.Pads()]
            candidates.extend(board.GetTracks())
            candidates.extend(zone for zone in board.Zones() if not zone.GetIsRuleArea())
            targets = [item for item in candidates if str(item.GetNetname()) in names]
    if not targets:
        raise ValueError("These named nets have no selectable copper items. Selection unchanged.")
    return select_items(board, targets)
