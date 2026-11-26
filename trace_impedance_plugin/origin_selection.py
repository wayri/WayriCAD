"""Bind Trace RLC's input scopes to exact items in the originating PCB Editor."""

from collections import Counter, defaultdict
import hashlib
from pathlib import Path

from wayricad_runtime.analysis_selection import SavedSelectionReader, select_origin
from wayricad_runtime.context import LaunchContext
from wayricad_runtime.editor_refresh import source_stamp


def _uuid(item):
    return item.m_Uuid.AsString().casefold()


def saved_pick(board, identifiers, *, route=False):
    """Resolve selected UUIDs on the snapshot without choosing arbitrary endpoints."""
    wanted = {str(value).casefold() for value in identifiers}
    if not wanted:
        raise ValueError("Select pads, tracks, vias or zones in PCB Editor first.")
    labels = Counter()
    selected = defaultdict(list)
    for footprint in board.GetFootprints():
        reference = str(footprint.GetReference())
        for pad in footprint.Pads():
            net = str(pad.GetNetname())
            label = f'{reference}.{pad.GetNumber()}'
            labels[net, label] += 1
            identifier = _uuid(pad)
            if identifier in wanted:
                selected[identifier].append((net, label))
    for collection in (board.GetTracks(), board.Zones()):
        for item in collection:
            identifier = _uuid(item)
            if identifier in wanted:
                selected[identifier].append((str(item.GetNetname()), None))
    if any(len(selected.get(identifier, ())) != 1 for identifier in wanted):
        raise ValueError("Some selected items are missing from the saved PCB or are not copper items. "
                         "Save and reopen the board, or select only saved pads, tracks, vias or zones.")
    rows = [values[0] for values in selected.values()]
    nets = sorted({net for net, _ in rows})
    if not all(nets):
        raise ValueError("The PCB selection includes copper with no assigned net.")
    if not route:
        return nets
    if len(nets) != 1:
        raise ValueError("Select items on one net for a path, or use All nets / Bundles for multiple nets.")
    pads = sorted((net, label) for net, label in rows if label is not None)
    if len(pads) > 2:
        raise ValueError("Select at most two endpoint pads for one route.")
    if any(labels[pad] != 1 for pad in pads):
        raise ValueError("A selected pad has an ambiguous saved reference and pad number.")
    return nets[0], [label for _, label in pads]


class TerminalIndex:
    def __init__(self, board):
        self.by_id = defaultdict(list)
        self.by_label = defaultdict(list)
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                uid = pad.m_Uuid.AsString()
                key = str(pad.GetNetname()), f"{fp.GetReference()}.{pad.GetNumber()}"
                self.by_label[key].append(uid)
                self.by_id[uid].append(key)

    def ids(self, net, labels):
        return [rows[0] if len(rows) == 1 else None
                for rows in (self.by_label.get((net, label), ()) for label in labels)]

    def restore(self, old_net, ids, names):
        keys = []
        for uid in ids:
            entries = self.by_id.get(uid, ())
            key = entries[0] if len(entries) == 1 else None
            keys.append(key if key and len(self.by_label[key]) == 1 else None)
        nets = {key[0] for key in keys if key}
        net = nets.pop() if len(nets) == 1 else old_net
        if net not in names:
            net = ""
        return net, [key[1] if key and key[0] == net else "" for key in keys]


class OriginSelection:
    """Read or cross-select against the native analysis window's saved revision."""

    def __init__(self, path, *, launch_context=None, stamp=None):
        self.path = Path(path).resolve()
        self.launch_context = launch_context or LaunchContext.capture()
        self.stamp = source_stamp(self.path) if stamp is None else stamp
        self.reader = None

    @property
    def available(self):
        return bool(self.launch_context.socket and self.launch_context.token
                    and self.stamp and self.stamp[0][1])

    def check_source(self):
        if source_stamp(self.path) != self.stamp:
            raise ValueError("Saved PCB/project/rules changed. Wait for the saved PCB to reload before using PCB selection.")

    def _reader(self):
        self.check_source()
        if self.reader is None:
            if not self.available:
                raise ValueError("Open this tool from the originating PCB Editor to use its selection.")
            digest = hashlib.sha256()
            with self.path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            self.check_source()
            self.reader = SavedSelectionReader(self.path, expected_sha256=digest.hexdigest(),
                                               launch_context=self.launch_context)
        return self.reader

    def read(self):
        identifiers = self._reader().read()
        self.check_source()
        return identifiers

    def locate(self, identifiers):
        reader = self._reader()
        result = select_origin(self.path, identifiers=identifiers, expected_sha256=reader.expected_sha256,
                               focus=True, return_details=True, launch_context=self.launch_context)
        self.check_source()
        return result

    def select_net(self, net):
        reader = self._reader()
        result = select_origin(self.path, net=net, expected_sha256=reader.expected_sha256,
                               focus=True, return_details=True, launch_context=self.launch_context)
        self.check_source()
        return result
