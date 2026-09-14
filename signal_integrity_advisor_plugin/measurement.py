"""Geometry-aware routed-path measurement and first-order RLC estimates."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from . import rlc_model as _rlc
except ImportError:  # Direct-file execution (tests/automation) has no package parent.
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("_wayricad_rlc_model", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rlc_model.py"))
    _rlc = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_rlc)


EPS0 = _rlc.EPS0
MU0 = _rlc.MU0
COPPER_RESISTIVITY = _rlc.COPPER_RESISTIVITY


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
class StackupLayer:
    """Normalized stackup row across KiCad API versions."""

    name: str
    kind: str = "unknown"
    thickness_mm: float = 0.0
    dielectric_height_mm: float = 0.20
    relative_permittivity: float = 4.2
    material: str = ""
    loss_tangent: float = 0.0


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
    reference_layer: str = ""
    stackup_source: str = ""
    dielectric_height_mm: float = 0.0
    relative_permittivity: float = 0.0
    copper_thickness_mm: float = 0.0
    average_width_mm: float = 0.0
    width_to_height: float = 0.0
    effective_permittivity: float = 0.0
    impedance_model: str = ""
    resistance_ac_ohm: float = 0.0
    propagation_delay_ns: float = 0.0
    board_items: List[Any] = field(default_factory=list, repr=False)
    status: str = "disconnected"
    impedance_valid: bool = False
    segments: List[Dict[str, Any]] = field(default_factory=list)
    ground_nets: List[str] = field(default_factory=list)
    zone_area_mm2: float = 0.0
    overlap_area_mm2: float = 0.0

    def as_report(self) -> Dict[str, Any]:
        """Numeric JSON report without live board object references."""
        result = {key: value for key, value in vars(self).items() if key != "board_items"}
        if not self.impedance_valid:
            result["impedance_ohm"] = None
        result["totals_complete"] = self.status == "ok"
        result["totals_scope"] = "Modeled sections only; not a complete equivalent circuit" if self.status == "partial" else self.status
        if self.status == "disconnected":
            for key in ("length_mm", "resistance_ohm", "resistance_ac_ohm", "capacitance_pf", "inductance_nh", "propagation_delay_ns"):
                result[key] = None
        return result

    def as_dict(self) -> Dict[str, Any]:
        rows = {
            "Net": self.net_name,
            "Start Pad": self.start_pad,
            "End Pad": self.end_pad,
            "Length (mm)": f"{self.length_mm:.3f}",
            "R DC (ohm)": f"{self.resistance_ohm:.6g}",
            "R AC @ est. freq (ohm)": f"{self.resistance_ac_ohm:.6g}" if self.resistance_ac_ohm else "-",
            "C (pF)": f"{self.capacitance_pf:.6g}",
            "L (nH)": f"{self.inductance_nh:.6g}",
            "Z0 estimate (ohm)": f"{self.impedance_ohm:.6g}" if self.impedance_valid else "Unknown / not a uniform transmission line",
            "Status": self.status,
            "Impedance Model": self.impedance_model or "Unresolved",
            "Avg trace width (mm)": f"{self.average_width_mm:.4g}" if self.average_width_mm else "-",
            "Width / height": f"{self.width_to_height:.4g}" if self.width_to_height else "-",
            "Effective Er": f"{self.effective_permittivity:.4g}" if self.effective_permittivity else "-",
            "Propagation delay (ns)": f"{self.propagation_delay_ns:.4g}" if self.propagation_delay_ns else "-",
            "Layer changes": str(self.layer_changes),
            "Vias": str(self.via_count),
            "Tracks": str(self.track_count),
            "Zones": str(self.zone_count),
            "Layers": ", ".join(self.layers),
            "Reference Layer Used": self.reference_layer,
            "Stackup Source": self.stackup_source,
            "Dielectric Height Used (mm)": f"{self.dielectric_height_mm:.4f}",
            "Relative Permittivity Used": f"{self.relative_permittivity:.4g}",
            "Copper Thickness Used (mm)": f"{self.copper_thickness_mm:.4f}",
            "Notes": "; ".join(self.notes),
        }
        if self.status == "disconnected":
            for key in ("Length (mm)", "R DC (ohm)", "R AC @ est. freq (ohm)", "C (pF)", "L (nH)", "Propagation delay (ns)"):
                rows[key] = "Unresolved"
        elif self.status == "partial":
            rows["Totals scope"] = "Modeled sections only; unresolved terms excluded"
        return rows


class TraceMeasurementEngine:
    """Measure connected PCB geometry and estimate distributed RLC values."""

    def __init__(self, board: Any) -> None:
        self.board = board
        self._geometry_cache = None
        self._stackup_cache = None

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
        layer = next((item for item in self.stackup_layers() if item.name == reference_layer), None)
        if layer:
            info.copper_thickness_mm = layer.thickness_mm or info.copper_thickness_mm
            info.dielectric_height_mm = layer.dielectric_height_mm or info.dielectric_height_mm
            info.relative_permittivity = layer.relative_permittivity or info.relative_permittivity
            info.source = "KiCad board stackup"
        return info

    def stackup_layers(self) -> List[StackupLayer]:
        """Read all board stackup layers with fallbacks for KiCad API variants."""
        if self._stackup_cache is not None:
            return self._stackup_cache
        settings = getattr(self.board, "GetStackupSettings", lambda: None)()
        raw = None
        if settings is not None:
            getter = getattr(settings, "GetStackup", None)
            if callable(getter):
                try:
                    raw = getter()
                except Exception:
                    raw = None
        rows: List[StackupLayer] = []
        if isinstance(raw, dict):
            iterable = raw.items()
        elif isinstance(raw, (list, tuple)):
            iterable = ((self._value(item, "name", "layer", default=""), item) for item in raw)
        else:
            iterable = ()
        for name, properties in iterable:
            name = str(name or self._value(properties, "name", "layer", default=""))
            if not name:
                continue
            kind = str(self._value(properties, "type", "layer_type", default="unknown"))
            thickness = self._number(self._value(properties, "thickness", "thickness_mm", default=0.0))
            if thickness > 10.0:
                thickness /= 1000.0
            er = self._number(self._value(properties, "epsilon_r", "er", "dielectric_constant", default=4.2)) or 4.2
            dielectric = self._number(self._value(properties, "dielectric_height", "height", "dielectric_mm", default=0.20)) or 0.20
            if dielectric > 10.0:
                dielectric /= 1000.0
            rows.append(StackupLayer(name=name, kind=kind, thickness_mm=thickness, dielectric_height_mm=dielectric, relative_permittivity=er, material=str(self._value(properties, "material", "material_name", default="")), loss_tangent=self._number(self._value(properties, "loss_tangent", "tan_delta", default=0.0))))
        if not rows:
            rows = self._stackup_from_board_file()
        if not rows:
            names = []
            for track in getattr(self.board, "GetTracks", lambda: [])():
                if hasattr(track, "GetLayer"):
                    names.append(self._layer_name(track.GetLayer()))
            for name in sorted(set(names), key=self._natural_key):
                rows.append(StackupLayer(name=name, kind="routed", thickness_mm=0.035))
        self._stackup_cache = rows
        return rows

    def _stackup_from_board_file(self) -> List[StackupLayer]:
        """Parse KiCad's stackup S-expression when the SWIG API is opaque."""
        path = str(getattr(self.board, "GetFileName", lambda: "")())
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return []
        start = text.find("(stackup")
        if start < 0:
            return []
        block = self._balanced_block(text, start)
        rows = []
        cursor = 0
        while True:
            layer_start = block.find("(layer", cursor)
            if layer_start < 0:
                break
            layer = self._balanced_block(block, layer_start)
            cursor = layer_start + len(layer)
            name_match = re.match(r'\(layer\s+(?:"([^"]+)"|([^\s()]+))', layer)
            if not name_match:
                continue
            name = name_match.group(1) or name_match.group(2)
            def token(key: str, default: str = "") -> str:
                match = re.search(rf'\({key}\s+(?:"([^"]*)"|([^\s()]+))', layer)
                return (match.group(1) or match.group(2)) if match else default
            kind = token("type", "unknown")
            thickness = self._number(token("thickness", "0"))
            er = self._number(token("epsilon_r", "4.2")) or 4.2
            rows.append(StackupLayer(
                name=name,
                kind=kind,
                thickness_mm=thickness,
                dielectric_height_mm=thickness if "copper" not in kind.lower() and not name.endswith(".Cu") else 0.0,
                relative_permittivity=er,
                material=token("material"),
                loss_tangent=self._number(token("loss_tangent", "0")),
            ))
        return rows

    @staticmethod
    def _balanced_block(text: str, start: int) -> str:
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return text[start:]

    def dielectric_to_reference(self, signal_layer: str, reference_layer: str) -> Tuple[float, float]:
        rows = self.stackup_layers()
        indices = {row.name: index for index, row in enumerate(rows)}
        if signal_layer not in indices or reference_layer not in indices:
            stack = self.stackup(reference_layer)
            return stack.dielectric_height_mm, stack.relative_permittivity
        low, high = sorted((indices[signal_layer], indices[reference_layer]))
        dielectrics = [row for row in rows[low + 1:high] if "copper" not in row.kind.lower() and not row.name.endswith(".Cu")]
        if not dielectrics:
            return 0.20, 4.2
        total = sum(row.thickness_mm or row.dielectric_height_mm for row in dielectrics)
        weighted_er = sum((row.thickness_mm or row.dielectric_height_mm) * row.relative_permittivity for row in dielectrics) / max(total, 1e-9)
        return total or 0.20, weighted_er or 4.2

    def topology_for_layers(self, layers: Iterable[str], reference_layer: str) -> str:
        """Display topology only; measurement additionally verifies plane coverage."""
        copper = [row.name for row in self.stackup_layers() if row.name.endswith(".Cu")]
        actual = list(layers)
        return "stripline" if copper and actual and all(layer in copper[1:-1] for layer in actual) else "microstrip"

    def via_span_mm(self, layer_a, layer_b):
        positions, z = {}, 0.
        for row in self.stackup_layers():
            if row.name.endswith(".Cu"):
                positions[row.name] = z + row.thickness_mm/2
            z += row.thickness_mm
        a, b = self._layer_name(layer_a), self._layer_name(layer_b)
        if a in positions and b in positions and positions[a] != positions[b]:
            return abs(positions[b]-positions[a])
        layers = self._geometry().layers
        thickness = mm(self.board.GetDesignSettings().GetBoardThickness())
        return thickness * abs(layers.index(layer_b)-layers.index(layer_a))/max(len(layers)-1,1)

    def available_layers(self) -> List[str]:
        """Return all actual stackup/routed layers, not a hard-coded subset."""
        names = [row.name for row in self.stackup_layers()]
        return list(dict.fromkeys(names))

    @staticmethod
    def _value(obj: Any, *names: str, default: Any = "") -> Any:
        for name in names:
            if isinstance(obj, dict) and name in obj:
                return obj[name]
            value = getattr(obj, name, None)
            if value is not None:
                return value() if callable(value) else value
        return default

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _geometry(self):
        if self._geometry_cache is None:
            try:
                from .copper_path import CopperGeometry
            except ImportError:
                import importlib.util
                spec = importlib.util.spec_from_file_location("_wayricad_copper_path", os.path.join(os.path.dirname(__file__), "copper_path.py"))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                CopperGeometry = module.CopperGeometry
            self._geometry_cache = CopperGeometry(self)
        return self._geometry_cache

    def ground_nets(self) -> List[str]:
        geometry = self._geometry()
        return sorted({island["net"] for island in geometry.islands if re.search(r"(?:^|[/_+\-])(GND|AGND|DGND|PGND|SGND|VSS|GROUND)(?:$|[_\-\d])", island["net"], re.I)})

    def zone_options(self, net_name=None) -> List[Dict[str, Any]]:
        return [{"id": z["id"], "net": z["net"], "layer": self._layer_name(z["layer"]), "area_mm2": z["area_mm2"], "island": z["island"]}
                for z in self._geometry().islands if net_name is None or z["net"] == net_name]

    def zone_terminals(self, zone_id) -> List[str]:
        geometry = self._geometry()
        zone = next((z for z in geometry.islands if z["id"] == zone_id), None)
        if zone is None:
            return []
        geometry.prepare_routing(zone['net'])
        poly=zone.get('routing_poly',zone['poly'])
        return sorted([key for key, pads in geometry.pads(zone["net"]).items()
                       if any(pad.IsOnLayer(zone["layer"]) and poly.Contains(pad.GetPosition()) for pad in pads)],key=self._natural_key)

    def _new_result(self, net, start, end, reference):
        result = PathMeasurement(net_name=net, start_pad=start, end_pad=end)
        result.reference_layer = reference
        result.ground_nets = self.ground_nets()
        result.stackup_source = "Embedded board stackup (saved PCB)" if self._stackup_from_board_file() else "Default estimate; board stackup unavailable"
        result.notes = ["Ground candidates use net names and actual filled coverage, not an electrical ground certification.",
                        "No field solve: skin loss excludes roughness; return-current distribution, coupling and via antipad capacitance are unresolved."]
        return result

    def measure(self, net_name: str, start_pad: str, end_pad: str, frequency_mhz: float = 100.0, reference_layer: str = "Auto") -> PathMeasurement:
        if not math.isfinite(frequency_mhz) or frequency_mhz < 0:
            raise ValueError("Frequency must be finite and non-negative.")
        self._geometry_cache = None  # live board edits must not reuse stale copper
        result = self._new_result(net_name, start_pad, end_pad, reference_layer)
        edges, notes = self._geometry().path(net_name, start_pad, end_pad)
        result.notes.extend(notes)
        if edges is None:
            result.notes.append("No connected finite-width path between these terminals. Check copper connectivity, zone fills and corridor width; aggregate net geometry is never substituted.")
            return result
        self._measure_edges(result, edges, frequency_mhz, reference_layer)
        return result

    def measure_zone(self, net_name, start_pad, end_pad, zone_id, reference_layer="Auto", frequency_mhz=100., corridor_width_mm=.2):
        if not math.isfinite(frequency_mhz) or frequency_mhz < 0:
            raise ValueError("Frequency must be finite and non-negative.")
        self._geometry_cache = None
        result = self._new_result(net_name, start_pad, end_pad, reference_layer)
        if not math.isfinite(corridor_width_mm) or corridor_width_mm <= 0:
            raise ValueError("Zone corridor width must be positive and finite.")
        geometry = self._geometry()
        geometry.prepare_routing(net_name)
        zone = next((z for z in geometry.islands if z["id"] == zone_id and z["net"] == net_name), None)
        if zone is None:
            raise ValueError("Select a filled island belonging to this net.")
        pads = geometry.pads(net_name)
        result.zone_area_mm2 = zone["area_mm2"]
        if start_pad == end_pad or start_pad not in pads or end_pad not in pads:
            result.notes.append("Select two distinct pads on this zone's net.")
            return result
        # Layer-specific pad ownership is mandatory, including plated through pads.
        candidates = [(a,b) for a in pads[start_pad] for b in pads[end_pad] if a.IsOnLayer(zone["layer"]) and b.IsOnLayer(zone["layer"])]
        for pa, pb in candidates:
            a, b = (pa.GetPosition().x,pa.GetPosition().y), (pb.GetPosition().x,pb.GetPosition().y)
            route=geometry.navigation(zone,corridor_width_mm).route(a,b)
            if route:
                edges=[dict(kind="zone", layer=zone["layer"], a=p,b=q,item=zone["item"],island=zone,
                            length_mm=math.hypot(q[0]-p[0],q[1]-p[1])/1e6, width_mm=corridor_width_mm,
                            geometry="filled-copper corridor") for p,q in zip(route,route[1:])]
                self._measure_edges(result,edges,frequency_mhz,reference_layer,full_zone=True)
                result.notes.append("Zone R/L uses a finite-width terminal corridor around actual voids, including connected pad copper and thermal spokes. It is not solved spreading resistance. Plane C uses full island/reference overlap once per reference; do not treat this as a single series RLC circuit.")
                return result
        result.notes.append("Selected terminals have no connected corridor of this width on the selected island/layer. Reduce corridor width if a real narrow spoke is the bottleneck; copper gaps are never bridged.")
        return result

    def _measure_edges(self, result, edges, frequency, reference, full_zone=False):
        geometry = self._geometry()
        rows = {row.name:row for row in self.stackup_layers()}
        result.status = "ok"
        track_ids, via_ids, zone_ids = set(), set(), set()
        overlap_seen=set()
        widths, impedances = [], []
        previous_layer = None
        merged = []
        for edge in edges:
            if edge.get("kind") == "via" and merged and merged[-1].get("kind") == "via" and edge["item"].m_Uuid == merged[-1]["item"].m_Uuid:
                merged[-1] = dict(merged[-1],length_mm=merged[-1]["length_mm"]+edge["length_mm"],end_layer=edge["end_layer"])
            else:
                merged.append(edge)
        for edge in merged:
            kind = edge.get("kind")
            if kind not in ("track", "via", "zone"):
                continue
            layer = self._layer_name(edge["layer"])
            length = edge["length_mm"]
            result.length_mm += length
            if layer not in result.layers:
                result.layers.append(layer)
            if previous_layer is not None and previous_layer != layer:
                result.layer_changes += 1
                result.status = "partial"  # plated-pad transition impedance is not modeled
            previous_layer = layer
            item = edge["item"]
            uid = str(item.m_Uuid.AsString())
            if item not in result.board_items:
                result.board_items.append(item)
            section = dict(kind=kind,layer=layer,length_mm=length,reference_layer="",reference_net="",
                           resistance_ohm=0.,inductance_nh=None,capacitance_pf=None,impedance_ohm=None,status="partial")
            section['geometry']=edge.get('geometry','barrel' if kind=='via' else 'straight')
            if 'a' in edge:
                section['start_mm']=[v/1e6 for v in edge['a']]
                section['end_mm']=[v/1e6 for v in edge['b']]
            copper = (rows[layer].thickness_mm if layer in rows else 0.) or .035
            result.copper_thickness_mm = copper
            if kind == "via":
                via_ids.add(uid)
                end_layer = self._layer_name(edge["end_layer"])
                section["end_layer"] = end_layer
                previous_layer = end_layer
                result.layer_changes += 1
                if end_layer not in result.layers:
                    result.layers.append(end_layer)
                model = _rlc.via_barrel(length, edge["drill_mm"])
                section.update(resistance_ohm=model["resistance_ohm"],inductance_nh=model["inductance_nh"],
                               model="Plated barrel: assumed 25 um plating; isolated partial inductance")
                result.status = "partial"
            else:
                (track_ids if kind == "track" else zone_ids).add(uid)
                width = edge["width_mm"]
                widths.append((width,length))
                section["width_mm"] = width
                section["resistance_ohm"] = _rlc.dc_resistance_per_m(width,copper) * length/1000
                result.resistance_ac_ohm += _rlc.ac_resistance_per_m(frequency,width,copper) * length/1000
                coverage_width=width+(.002 if section['geometry'].startswith('arc') else 0.)
                ref = geometry.reference(edge["layer"],edge["a"],edge["b"],coverage_width,reference,result.net_name)
                if ref:
                    height, name, er, island = ref
                    section.update(reference_layer=name,reference_net=island["net"],dielectric_height_mm=height,relative_permittivity=er)
                    result.dielectric_height_mm = height
                    result.relative_permittivity = er
                    result.reference_layer = name if result.reference_layer in ("Auto",name) else "Multiple (see sections)"
                    if kind == "zone":
                        source_poly = edge["island"]["poly"] if full_zone else geometry.corridor(edge["a"],edge["b"],width)
                        area = geometry.overlap(source_poly,island)
                        overlap_key=(edge['island']['id'],island['id'])
                        if full_zone:
                            if overlap_key in overlap_seen:area=0.
                            overlap_seen.add(overlap_key)
                        result.overlap_area_mm2 += area
                        section.update(inductance_nh=MU0*(height/1000)*(length/width)*1e9,
                                       capacitance_pf=EPS0*er*(area/1e6)/(height/1000)*1e12,
                                       model="Terminal corridor R/L; parallel-plate overlap C", overlap_area_mm2=area)
                        result.status = "partial"
                    else:
                        # Internal copper with one known plane is an asymmetric
                        # line, not automatically a symmetric stripline.
                        outer = edge["layer"] in (geometry.layers[0],geometry.layers[-1])
                        both = [] if outer else geometry.reference(edge["layer"],edge["a"],edge["b"],width,"Auto",result.net_name,all_matches=True)
                        by_layer = {r[1]:r for r in both}
                        symmetric = len(by_layer) == 2 and abs(max(r[0] for r in by_layer.values())-min(r[0] for r in by_layer.values())) < .01*height and abs(max(r[2] for r in by_layer.values())-min(r[2] for r in by_layer.values())) < .01*er
                        if outer or symmetric:
                            if symmetric and not outer:
                                height = sum(r[0] for r in by_layer.values())
                                result.dielectric_height_mm = height
                                section["reference_layer"] = " + ".join(by_layer)
                                section["dielectric_height_mm"] = height
                            try:
                                model = _rlc.solve(width,height,copper,er,length,frequency,"microstrip" if outer else "stripline")
                                section.update(inductance_nh=model["inductance_nh"],capacitance_pf=model["capacitance_pf"],
                                               impedance_ohm=model["z0_ohm"],model=model["model"],status="ok")
                                impedances.append((model["z0_ohm"],length))
                                result.propagation_delay_ns += model["propagation_delay_ns"]
                                result.width_to_height = model["width_to_height"]
                                result.effective_permittivity = model["effective_permittivity"]
                            except ValueError as exc:
                                section["model"] = str(exc)
                                result.status = "partial"
                        else:
                            section["model"] = "Internal layer: asymmetric/multiple-plane field model unresolved"
                            result.status = "partial"
                else:
                    section["model"] = "No adjacent named-ground filled reference covers this section"
                    result.status = "partial"
                if kind == "zone":
                    result.zone_area_mm2 = max(result.zone_area_mm2,edge["island"]["area_mm2"])
            result.resistance_ohm += section["resistance_ohm"]
            result.inductance_nh += section["inductance_nh"] or 0.
            result.capacitance_pf += section["capacitance_pf"] or 0.
            result.segments.append(section)
        result.track_count, result.via_count, result.zone_count = len(track_ids),len(via_ids),len(zone_ids)
        if not result.segments:
            result.status = "partial"
        if widths:
            result.average_width_mm = sum(w*l for w,l in widths)/max(sum(l for _,l in widths),1e-15)
        if impedances and result.status == "ok":
            values = [z for z,_ in impedances]
            # A nonuniform route has section impedances, not one characteristic impedance.
            result.impedance_valid = max(values)-min(values) <= .01*max(values)
            if result.impedance_valid:
                result.impedance_ohm = sum(z*l for z,l in impedances)/sum(l for _,l in impedances)
        result.impedance_model = "Per-section geometry; see segments"
        if result.status != "ok":
            result.notes.append("R/L/C totals include modeled sections only; unresolved terms are null in the section report. They are not a complete equivalent-circuit extraction.")
        if result.via_count:
            result.notes.append("Via capacitance needs antipad/reference geometry and is unknown. Barrel plating is assumed 25 um; inductance is isolated partial L, not return-loop L.")
        result.notes.append("Routing follows existing layer transitions without moving copper. Zone corridors include connected thermal copper at the stated width; general pad spreading impedance remains unmodeled.")

    def _layer_name(self, layer: Any) -> str:
        try:
            import pcbnew
            return str(pcbnew.LayerName(layer))
        except Exception:
            return str(layer or "unknown")

    @staticmethod
    def _natural_key(text: str) -> List[Any]:
        import re
        return [int(item) if item.isdigit() else item.lower() for item in re.split(r"(\d+)", str(text))]
