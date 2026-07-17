"""Geometry-aware routed-path measurement and first-order RLC estimates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import networkx as nx
except ImportError:  # pragma: no cover - KiCad installations may omit it
    nx = None


EPS0 = 8.8541878128e-12
MU0 = 1.25663706212e-6
COPPER_RESISTIVITY = 1.724e-8


def mm(value: Any) -> float:
    return float(value) / 1_000_000.0


@dataclass
class StackupInfo:
    copper_thickness_mm: float = 0.035
    dielectric_height_mm: float = 0.20
    relative_permittivity: float = 4.2
    reference_layer: str = "F.Cu"
    source: str = "KiCad stackup/default estimate"


@dataclass
class PathMeasurement:
    net_name: str
    start_pad: str
    end_pad: str
    length_mm: float = 0.0
    resistance_ohm: float = 0.0
    capacitance_pf: float = 0.0
    inductance_nh: float = 0.0
    impedance_ohm: float = 0.0
    layer_changes: int = 0
    via_count: int = 0
    track_count: int = 0
    zone_count: int = 0
    layers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "Net": self.net_name,
            "Start Pad": self.start_pad,
            "End Pad": self.end_pad,
            "Length (mm)": f"{self.length_mm:.3f}",
            "R (ohm)": f"{self.resistance_ohm:.6g}",
            "C (pF)": f"{self.capacitance_pf:.6g}",
            "L (nH)": f"{self.inductance_nh:.6g}",
            "Z0 estimate (ohm)": f"{self.impedance_ohm:.6g}",
            "Layer changes": str(self.layer_changes),
            "Vias": str(self.via_count),
            "Tracks": str(self.track_count),
            "Zones": str(self.zone_count),
            "Layers": ", ".join(self.layers),
            "Notes": "; ".join(self.notes),
        }


class TraceMeasurementEngine:
    """Measure connected PCB geometry and estimate distributed RLC values."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def net_names(self) -> List[str]:
        names = set()
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                name = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
                if name:
                    names.add(name)
        return sorted(names, key=self._natural_key)

    def pads_for_net(self, net_name: str) -> List[str]:
        result = []
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if hasattr(pad, "GetNetname") and pad.GetNetname() == net_name:
                    result.append(f"{footprint.GetReference()}.{pad.GetNumber()}")
        return sorted(result, key=self._natural_key)

    def stackup(self, reference_layer: str = "F.Cu") -> StackupInfo:
        info = StackupInfo(reference_layer=reference_layer)
        try:
            settings = self.board.GetStackupSettings()
            get_thickness = getattr(settings, "GetLayerThickness", None)
            if callable(get_thickness):
                value = get_thickness(getattr(__import__("pcbnew"), reference_layer))
                if value:
                    info.copper_thickness_mm = mm(value)
                    info.source = "KiCad board stackup"
            get_material = getattr(settings, "GetDielectric", None)
            if callable(get_material):
                material = get_material(reference_layer)
                er = getattr(material, "epsilon_r", None) or getattr(material, "GetEpsilonR", lambda: None)()
                if er:
                    info.relative_permittivity = float(er)
        except Exception:
            pass
        return info

    def measure(self, net_name: str, start_pad: str, end_pad: str, frequency_mhz: float = 100.0, reference_layer: str = "F.Cu") -> PathMeasurement:
        stack = self.stackup(reference_layer)
        result = PathMeasurement(net_name=net_name, start_pad=start_pad, end_pad=end_pad)
        if nx is None:
            result.notes.append("Install networkx for routed-path traversal; fallback uses aggregate net geometry.")
        net_code = self._net_code(net_name)
        graph = nx.Graph() if nx is not None else None
        pad_positions: Dict[str, Any] = {}
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if not hasattr(pad, "GetNetname") or pad.GetNetname() != net_name:
                    continue
                key = f"{footprint.GetReference()}.{pad.GetNumber()}"
                pad_positions[key] = pad.GetPosition()
                if graph is not None:
                    graph.add_node(key)
        tracks = []
        for track in getattr(self.board, "GetTracks", lambda: [])():
            if self._item_net_code(track) != net_code:
                continue
            if not hasattr(track, "GetStart") or not hasattr(track, "GetEnd"):
                continue
            start = track.GetStart(); end = track.GetEnd()
            a = self._point_node(start); b = self._point_node(end)
            layer = self._layer_name(track.GetLayer() if hasattr(track, "GetLayer") else None)
            length = math.hypot(mm(end.x - start.x), mm(end.y - start.y))
            width = mm(track.GetWidth()) if hasattr(track, "GetWidth") else 0.20
            tracks.append((a, b, length, width, layer, track))
            if graph is not None:
                graph.add_edge(a, b, length=length, width=width, layer=layer, kind="track", item=track)
        for key, position in pad_positions.items():
            nearest = self._nearest_track_node(position, tracks)
            if nearest and graph is not None:
                graph.add_edge(key, nearest, length=0.0, width=0.20, layer=reference_layer, kind="pad")
        selected_edges = []
        if graph is not None and start_pad in graph and end_pad in graph:
            try:
                path = nx.shortest_path(graph, start_pad, end_pad, weight="length")
                selected_edges = [graph.get_edge_data(a, b) for a, b in zip(path, path[1:])]
            except nx.NetworkXNoPath:
                result.notes.append("No connected routed path was found between the selected pads.")
        if not selected_edges:
            selected_edges = [edge for edge in tracks]
            result.notes.append("Measurement uses all matching-net tracks because a start/end path was not resolved.")
        for edge in selected_edges:
            data = edge if isinstance(edge, dict) else {"length": edge[2], "width": edge[3], "layer": edge[4], "kind": "track", "item": edge[5]}
            if data.get("kind") != "track":
                continue
            length = float(data.get("length", 0.0)); width = max(float(data.get("width", 0.20)), 0.001)
            result.length_mm += length; result.track_count += 1
            if data.get("layer") and data["layer"] not in result.layers: result.layers.append(data["layer"])
            area = (width / 1000.0) * (stack.copper_thickness_mm / 1000.0)
            result.resistance_ohm += COPPER_RESISTIVITY * (length / 1000.0) / area
        result.layer_changes = max(0, len(result.layers) - 1)
        result.via_count = self._via_count(net_code, selected_edges)
        result.zone_count = self._zone_count(net_code)
        length_m = result.length_mm / 1000.0
        width_m = max((stack.copper_thickness_mm / 1000.0), 1e-9)
        height_m = max(stack.dielectric_height_mm / 1000.0, 1e-9)
        effective_width_m = max(sum(float((e.get("width", 0.20) if isinstance(e, dict) else e[3])) for e in selected_edges if (e.get("kind") if isinstance(e, dict) else "track") == "track") / max(result.track_count, 1) / 1000.0, width_m)
        capacitance_per_m = EPS0 * stack.relative_permittivity * effective_width_m / height_m
        inductance_per_m = MU0 * height_m / effective_width_m
        result.capacitance_pf = capacitance_per_m * length_m * 1e12
        result.inductance_nh = inductance_per_m * length_m * 1e9
        result.impedance_ohm = math.sqrt(inductance_per_m / max(capacitance_per_m, 1e-30))
        result.notes.append(f"First-order estimate at {frequency_mhz:g} MHz; validate critical nets with a field solver or TDR.")
        if result.zone_count:
            result.notes.append("Copper zones overlap this net; plane geometry and return path affect the estimate.")
        return result

    def _net_code(self, name: str) -> int:
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if hasattr(pad, "GetNetname") and pad.GetNetname() == name:
                    return int(pad.GetNetCode())
        return 0

    def _item_net_code(self, item: Any) -> int:
        return int(item.GetNetCode()) if hasattr(item, "GetNetCode") else 0

    def _point_node(self, point: Any) -> Tuple[int, int]:
        return int(point.x), int(point.y)

    def _nearest_track_node(self, position: Any, tracks: List[Tuple[Any, Any, float, float, str, Any]]) -> Optional[Any]:
        if not tracks: return None
        point = (position.x, position.y)
        return min((item for item in tracks), key=lambda item: min(self._distance(point, (item[0][0], item[0][1])), self._distance(point, (item[1][0], item[1][1]))))[0]

    def _distance(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _layer_name(self, layer: Any) -> str:
        try:
            import pcbnew
            return str(pcbnew.LayerName(layer))
        except Exception:
            return str(layer or "unknown")

    def _via_count(self, net_code: int, edges: Iterable[Any]) -> int:
        count = 0
        for via in getattr(self.board, "GetTracks", lambda: [])():
            if hasattr(via, "GetViaType") and self._item_net_code(via) == net_code:
                count += 1
        return count

    def _zone_count(self, net_code: int) -> int:
        return sum(1 for zone in getattr(self.board, "Zones", lambda: [])() if self._item_net_code(zone) == net_code)

    @staticmethod
    def _natural_key(text: str) -> List[Any]:
        import re
        return [int(item) if item.isdigit() else item.lower() for item in re.split(r"(\d+)", str(text))]

