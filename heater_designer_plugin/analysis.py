"""Geometry, electrical, and reduced-order thermal models for PCB heaters."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


COPPER_RESISTIVITY = 1.724e-8
COPPER_TCR = 0.00393


@dataclass(frozen=True)
class HeatZone:
    name: str
    x_percent: float
    y_percent: float
    radius_percent: float
    resistance_factor: float


@dataclass(frozen=True)
class HeaterSpec:
    width_mm: float = 80.0
    height_mm: float = 50.0
    trace_width_mm: float = 0.5
    spacing_mm: float = 0.5
    copper_um: float = 35.0
    voltage_v: float = 12.0
    layers: int = 1
    pattern: str = "Serpentine"
    zones: tuple[HeatZone, ...] = ()


@dataclass(frozen=True)
class ThermalSpec:
    ambient_c: float = 25.0
    board_k_w_mk: float = 0.30
    board_thickness_mm: float = 1.6
    convection_w_m2k: float = 10.0
    grid_x: int = 42
    grid_y: int = 28
    iterations: int = 500


@dataclass(frozen=True)
class Segment:
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float
    layer: int
    zone: str = "Uniform"

    @property
    def length_mm(self) -> float:
        return math.hypot(self.x2_mm - self.x1_mm, self.y2_mm - self.y1_mm)


@dataclass(frozen=True)
class ViaTransition:
    x_mm: float
    y_mm: float
    from_layer: int
    to_layer: int


@dataclass
class HeaterResult:
    spec: HeaterSpec
    segments: list[Segment]
    vias: list[ViaTransition]
    resistance_ohm: float
    current_a: float
    power_w: float
    watts_per_cm2: float
    zone_power_w: dict[str, float] = field(default_factory=dict)


@dataclass
class ThermalResult:
    temperatures_c: list[list[float]]
    minimum_c: float
    maximum_c: float
    average_c: float
    uniformity_c: float
    hotspot: tuple[int, int]
    heater: HeaterResult
    notes: list[str]


class HeaterEngine:
    """Generate manufacturable centerline geometry and a review-grade thermal map."""

    @staticmethod
    def generate(spec: HeaterSpec) -> HeaterResult:
        if min(spec.width_mm, spec.height_mm, spec.trace_width_mm, spec.copper_um, spec.voltage_v) <= 0:
            raise ValueError("Dimensions, copper thickness, and voltage must be positive.")
        if spec.spacing_mm < 0 or not 1 <= spec.layers <= 16:
            raise ValueError("Spacing must be non-negative and layers must be between 1 and 16.")
        pitch = spec.trace_width_mm + spec.spacing_mm
        if pitch <= 0 or spec.width_mm < 3 * pitch or spec.height_mm < 3 * pitch:
            raise ValueError("Heater area is too small for the selected width and spacing.")

        per_layer: list[list[Segment]] = []
        for layer in range(spec.layers):
            if spec.pattern == "Concentric spiral":
                base = HeaterEngine._spiral(spec, layer)
            else:
                base = HeaterEngine._serpentine(spec, layer, reverse=(layer % 2 == 1))
            per_layer.append([HeaterEngine._apply_zone(segment, spec) for segment in base])

        segments = [segment for layer in per_layer for segment in layer]
        vias: list[ViaTransition] = []
        for layer in range(spec.layers - 1):
            end = per_layer[layer][-1]
            vias.append(ViaTransition(end.x2_mm, end.y2_mm, layer, layer + 1))

        thickness_m = spec.copper_um * 1e-6
        resistance = sum(
            COPPER_RESISTIVITY * (segment.length_mm / 1000.0)
            / max((segment.width_mm / 1000.0) * thickness_m, 1e-15)
            for segment in segments
        )
        current = spec.voltage_v / max(resistance, 1e-12)
        zone_power: dict[str, float] = {}
        for segment in segments:
            r = COPPER_RESISTIVITY * (segment.length_mm / 1000.0) / ((segment.width_mm / 1000.0) * thickness_m)
            zone_power[segment.zone] = zone_power.get(segment.zone, 0.0) + current * current * r
        power = spec.voltage_v * current
        return HeaterResult(spec, segments, vias, resistance, current, power,
                            power / max(spec.width_mm * spec.height_mm / 100.0, 1e-9), zone_power)

    @staticmethod
    def resistance_at_temperature(result: HeaterResult, temperature_c: float) -> float:
        return result.resistance_ohm * (1.0 + COPPER_TCR * (temperature_c - 20.0))

    @staticmethod
    def _serpentine(spec: HeaterSpec, layer: int, reverse: bool = False) -> list[Segment]:
        margin = spec.trace_width_mm
        pitch = spec.trace_width_mm + spec.spacing_mm
        rows = max(2, int((spec.height_mm - 2 * margin) / pitch) + 1)
        y_values = [margin + index * (spec.height_mm - 2 * margin) / (rows - 1) for index in range(rows)]
        if reverse:
            y_values.reverse()
        left, right = margin, spec.width_mm - margin
        points: list[tuple[float, float]] = []
        for index, y in enumerate(y_values):
            row = [(left, y), (right, y)] if index % 2 == 0 else [(right, y), (left, y)]
            points.extend(row if not points else row)
        return [Segment(*a, *b, spec.trace_width_mm, layer) for a, b in zip(points, points[1:])]

    @staticmethod
    def _spiral(spec: HeaterSpec, layer: int) -> list[Segment]:
        pitch = spec.trace_width_mm + spec.spacing_mm
        left = bottom = spec.trace_width_mm
        right, top = spec.width_mm - left, spec.height_mm - bottom
        points: list[tuple[float, float]] = [(left, bottom)]
        while right - left > 2 * pitch and top - bottom > 2 * pitch:
            points.extend(((right, bottom), (right, top), (left, top)))
            left += pitch; bottom += pitch; right -= pitch; top -= pitch
            points.append((left, bottom))
        return [Segment(*a, *b, spec.trace_width_mm, layer) for a, b in zip(points, points[1:])]

    @staticmethod
    def _apply_zone(segment: Segment, spec: HeaterSpec) -> Segment:
        mx = (segment.x1_mm + segment.x2_mm) / 2.0
        my = (segment.y1_mm + segment.y2_mm) / 2.0
        selected: HeatZone | None = None
        for zone in spec.zones:
            cx, cy = spec.width_mm * zone.x_percent / 100.0, spec.height_mm * zone.y_percent / 100.0
            radius = min(spec.width_mm, spec.height_mm) * zone.radius_percent / 100.0
            if math.hypot(mx - cx, my - cy) <= radius:
                selected = zone
        if selected is None:
            return segment
        factor = max(0.25, min(4.0, selected.resistance_factor))
        width = max(0.08, segment.width_mm / factor)
        return Segment(segment.x1_mm, segment.y1_mm, segment.x2_mm, segment.y2_mm,
                       width, segment.layer, selected.name)

    @staticmethod
    def simulate(heater: HeaterResult, thermal: ThermalSpec) -> ThermalResult:
        if min(thermal.board_k_w_mk, thermal.board_thickness_mm, thermal.grid_x, thermal.grid_y) <= 0:
            raise ValueError("Thermal properties and grid dimensions must be positive.")
        nx, ny = max(8, thermal.grid_x), max(8, thermal.grid_y)
        q = [[0.0 for _ in range(nx)] for _ in range(ny)]
        thickness_m = heater.spec.copper_um * 1e-6
        current2 = heater.current_a * heater.current_a
        for segment in heater.segments:
            samples = max(2, int(segment.length_mm / max(heater.spec.trace_width_mm, 0.2)))
            resistance = COPPER_RESISTIVITY * (segment.length_mm / 1000.0) / ((segment.width_mm / 1000.0) * thickness_m)
            sample_power = current2 * resistance / samples
            for index in range(samples):
                t = (index + 0.5) / samples
                x = segment.x1_mm + (segment.x2_mm - segment.x1_mm) * t
                y = segment.y1_mm + (segment.y2_mm - segment.y1_mm) * t
                ix = min(nx - 1, max(0, int(x / heater.spec.width_mm * nx)))
                iy = min(ny - 1, max(0, int(y / heater.spec.height_mm * ny)))
                q[iy][ix] += sample_power

        dx = heater.spec.width_mm / 1000.0 / nx
        dy = heater.spec.height_mm / 1000.0 / ny
        cell_area = dx * dy
        lateral = thermal.board_k_w_mk * (thermal.board_thickness_mm / 1000.0)
        convection = max(0.0, thermal.convection_w_m2k) * cell_area * 2.0
        temperatures = [[thermal.ambient_c for _ in range(nx)] for _ in range(ny)]
        for _ in range(max(20, thermal.iterations)):
            for iy in range(ny):
                for ix in range(nx):
                    neighbors = []
                    if ix: neighbors.append(temperatures[iy][ix - 1])
                    if ix + 1 < nx: neighbors.append(temperatures[iy][ix + 1])
                    if iy: neighbors.append(temperatures[iy - 1][ix])
                    if iy + 1 < ny: neighbors.append(temperatures[iy + 1][ix])
                    conductance = lateral * len(neighbors)
                    temperatures[iy][ix] = (
                        lateral * sum(neighbors) + convection * thermal.ambient_c + q[iy][ix]
                    ) / max(conductance + convection, 1e-12)
        flat = [value for row in temperatures for value in row]
        maximum = max(flat); minimum = min(flat); average = sum(flat) / len(flat)
        hot_index = max(range(len(flat)), key=flat.__getitem__)
        notes = [
            "Steady-state 2D board-plane conduction with uniform two-sided convection.",
            "Copper spreading, radiation, enclosure airflow, adhesives, and attached masses require higher-fidelity validation.",
            f"Copper resistance at average temperature: {HeaterEngine.resistance_at_temperature(heater, average):.4f} ohm.",
        ]
        return ThermalResult(temperatures, minimum, maximum, average, maximum - minimum,
                             (hot_index % nx, hot_index // nx), heater, notes)
