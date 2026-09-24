"""Geometry, electrical, and reduced-order thermal models for PCB heaters."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace


COPPER_RESISTIVITY = 1.724e-8
COPPER_TCR = 0.00393
ORGANIC_DEFAULT_POINTS = ((8.0, 10.0), (92.0, 10.0), (92.0, 28.0),
                          (8.0, 28.0), (8.0, 46.0), (92.0, 46.0),
                          (92.0, 64.0), (8.0, 64.0), (8.0, 82.0),
                          (92.0, 82.0))
GRADIENT_AXES = ("Uniform", "Left to right", "Right to left",
                 "Bottom to top", "Top to bottom")


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
    organic_points_percent: tuple[tuple[float, float], ...] = ORGANIC_DEFAULT_POINTS
    gradient_axis: str = "Uniform"
    gradient_ratio: float = 1.0


@dataclass(frozen=True)
class ThermalSpec:
    ambient_c: float = 25.0
    board_k_w_mk: float = 0.30
    board_thickness_mm: float = 1.6
    convection_w_m2k: float = 10.0
    grid_x: int = 42
    grid_y: int = 28
    iterations: int = 500
    sensor_clearance_mm: float = 0.1


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


@dataclass(frozen=True)
class SensorMarker:
    kind: str
    role: str
    x_mm: float
    y_mm: float
    estimated_c: float
    copper_clearance_mm: float


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
    gradient_delta_c: float = 0.0
    sensors: list[SensorMarker] = field(default_factory=list)


class HeaterEngine:
    """Generate manufacturable centerline geometry and a review-grade thermal map."""

    @staticmethod
    def generate(spec: HeaterSpec) -> HeaterResult:
        if not all(math.isfinite(v) for v in (spec.width_mm, spec.height_mm, spec.trace_width_mm,
                                               spec.spacing_mm, spec.copper_um, spec.voltage_v,
                                               spec.gradient_ratio)):
            raise ValueError("Heater dimensions and gradient values must be finite.")
        if min(spec.width_mm, spec.height_mm, spec.trace_width_mm, spec.copper_um, spec.voltage_v) <= 0:
            raise ValueError("Dimensions, copper thickness, and voltage must be positive.")
        if spec.spacing_mm < 0 or not 1 <= spec.layers <= 16:
            raise ValueError("Spacing must be non-negative and layers must be between 1 and 16.")
        if spec.gradient_axis not in GRADIENT_AXES or not 0.5 <= spec.gradient_ratio <= 4.0:
            raise ValueError("Choose a supported gradient direction and a heat-bias ratio from 0.5 to 4.")
        pitch = spec.trace_width_mm + spec.spacing_mm
        if pitch <= 0 or spec.width_mm < 3 * pitch or spec.height_mm < 3 * pitch:
            raise ValueError("Heater area is too small for the selected width and spacing.")

        if spec.pattern == "Concentric spiral":
            base = HeaterEngine._spiral(spec, 0)
        elif spec.pattern in ("Serpentine", "Zoned raster"):
            base = HeaterEngine._serpentine(spec, 0)
        elif spec.pattern == "Organic path":
            base = HeaterEngine._organic(spec)
        else:
            raise ValueError("Choose a supported heater pattern.")
        if not base:
            raise ValueError("The selected pattern produced no copper path.")
        per_layer: list[list[Segment]] = []
        for layer in range(spec.layers):
            ordered = (base if layer % 2 == 0 else
                       [Segment(s.x2_mm, s.y2_mm, s.x1_mm, s.y1_mm, s.width_mm, layer)
                        for s in reversed(base)])
            per_layer.append([HeaterEngine._apply_zone(replace(segment, layer=layer), spec)
                              for segment in ordered])
            if spec.pattern == "Organic path":
                for segment in per_layer[-1]:
                    margin = segment.width_mm/2
                    for x, y in ((segment.x1_mm, segment.y1_mm),
                                 (segment.x2_mm, segment.y2_mm)):
                        if not (margin <= x <= spec.width_mm-margin and
                                margin <= y <= spec.height_mm-margin):
                            raise ValueError("Width-biased organic copper extends beyond the heater area.")
                HeaterEngine._check_organic_clearance(per_layer[-1], spec.spacing_mm,
                                                       2*(spec.trace_width_mm+spec.spacing_mm))

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
    def _organic(spec: HeaterSpec) -> list[Segment]:
        controls = spec.organic_points_percent
        if len(controls) < 3 or len(controls) > 100:
            raise ValueError("Organic path needs 3 to 100 ordered control points.")
        margin = spec.trace_width_mm / 2.0
        points = []
        for x_percent, y_percent in controls:
            if not all(math.isfinite(v) and 0 <= v <= 100 for v in (x_percent, y_percent)):
                raise ValueError("Organic control points must have X% and Y% from 0 to 100.")
            x, y = spec.width_mm * x_percent / 100.0, spec.height_mm * y_percent / 100.0
            if not margin <= x <= spec.width_mm - margin or not margin <= y <= spec.height_mm - margin:
                raise ValueError("Organic path must leave half a trace width at the heater edge.")
            if points and math.hypot(x-points[-1][0], y-points[-1][1]) < spec.trace_width_mm:
                raise ValueError("Adjacent organic control points are too close.")
            points.append((x, y))
        # Chaikin corner cutting keeps the route inside the control polygon's
        # convex hull; unlike an interpolating spline, it cannot overshoot the PCB.
        for _ in range(2):
            rounded = [points[0]]
            for a, b in zip(points, points[1:]):
                rounded.extend(((0.75*a[0]+0.25*b[0], 0.75*a[1]+0.25*b[1]),
                                (0.25*a[0]+0.75*b[0], 0.25*a[1]+0.75*b[1])))
            rounded.append(points[-1])
            points = rounded
        sampled = [points[0]]
        step = max(1.0, spec.trace_width_mm + spec.spacing_mm)
        for a, b in zip(points, points[1:]):
            count = max(1, math.ceil(math.dist(a, b) / step))
            sampled.extend((a[0]+(b[0]-a[0])*i/count, a[1]+(b[1]-a[1])*i/count)
                           for i in range(1, count+1))
        segments = [Segment(*a, *b, spec.trace_width_mm, 0)
                    for a, b in zip(sampled, sampled[1:]) if math.dist(a, b) > 1e-8]
        HeaterEngine._check_organic_clearance(segments, spec.spacing_mm,
                                               2*(spec.trace_width_mm+spec.spacing_mm))
        return segments

    @staticmethod
    def _point_segment_distance(x, y, segment: Segment) -> float:
        dx, dy = segment.x2_mm-segment.x1_mm, segment.y2_mm-segment.y1_mm
        t = max(0.0, min(1.0, ((x-segment.x1_mm)*dx+(y-segment.y1_mm)*dy)
                            / max(dx*dx+dy*dy, 1e-18)))
        return math.hypot(x-segment.x1_mm-t*dx, y-segment.y1_mm-t*dy)

    @staticmethod
    def _check_organic_clearance(segments: list[Segment], spacing_mm: float,
                                 local_skip_mm: float) -> None:
        mid_lengths = []
        length = 0.0
        for segment in segments:
            mid_lengths.append(length + segment.length_mm/2)
            length += segment.length_mm
        for i, first in enumerate(segments):
            for j in range(i+2, len(segments)):
                second = segments[j]
                required = (first.width_mm+second.width_mm)/2+spacing_mm
                if mid_lengths[j]-mid_lengths[i] < local_skip_mm:
                    continue
                a,b=(first.x1_mm,first.y1_mm),(first.x2_mm,first.y2_mm)
                c,d=(second.x1_mm,second.y1_mm),(second.x2_mm,second.y2_mm)
                def cross(p,q,r):
                    return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
                crossing = cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0
                # All segments are short after sampling. Endpoint-to-segment
                # distance also catches near returns without a full DRC engine.
                gap = 0.0 if crossing else min(HeaterEngine._point_segment_distance(x, y, other)
                                               for x, y, other in ((first.x1_mm, first.y1_mm, second),
                                                                   (first.x2_mm, first.y2_mm, second),
                                                                   (second.x1_mm, second.y1_mm, first),
                                                                   (second.x2_mm, second.y2_mm, first)))
                if gap + 1e-7 < required:
                    raise ValueError("Organic path doubles back inside the selected trace spacing. Move control points farther apart.")

    @staticmethod
    def _gradient_position(x: float, y: float, spec: HeaterSpec) -> float:
        if spec.gradient_axis == "Left to right": return x/spec.width_mm
        if spec.gradient_axis == "Right to left": return 1.0-x/spec.width_mm
        if spec.gradient_axis == "Bottom to top": return y/spec.height_mm
        if spec.gradient_axis == "Top to bottom": return 1.0-y/spec.height_mm
        return 0.0

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
        region_factor = selected.resistance_factor if selected else 1.0
        position = HeaterEngine._gradient_position(mx, my, spec)
        gradient_factor = (1.0 + (spec.gradient_ratio-1.0)*position
                           if spec.gradient_ratio >= 1.0 else
                           1.0 + (1.0/spec.gradient_ratio-1.0)*(1.0-position))
        factor = max(0.25, min(4.0, region_factor*gradient_factor))
        width = max(0.08, segment.width_mm / factor)
        return Segment(segment.x1_mm, segment.y1_mm, segment.x2_mm, segment.y2_mm,
                       width, segment.layer, selected.name if selected else "Uniform")

    @staticmethod
    def simulate(heater: HeaterResult, thermal: ThermalSpec, *, recommend_sensors: bool = True) -> ThermalResult:
        if (not all(math.isfinite(v) for v in (thermal.ambient_c, thermal.board_k_w_mk,
                                               thermal.board_thickness_mm, thermal.convection_w_m2k,
                                               thermal.sensor_clearance_mm)) or
                min(thermal.board_k_w_mk, thermal.board_thickness_mm, thermal.grid_x, thermal.grid_y) <= 0 or
                thermal.sensor_clearance_mm < 0):
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
        if maximum > 180.0:
            notes.append("Predicted temperature exceeds 180 C. The simple model is outside a safe design range; review power and materials before placement or fabrication.")
        gradient = HeaterEngine._thermal_gradient(temperatures, heater.spec.gradient_axis)
        markers = HeaterEngine._sensor_markers(heater, thermal, temperatures, average) if recommend_sensors else []
        if recommend_sensors:
            if not markers:
                notes.append("No sensor marker fits the selected copper keepaway; reduce it or revise the path.")
            else:
                notes.append("Sensor positions are thermal sampling suggestions, not footprint clearance or control-loop validation.")
        return ThermalResult(temperatures, minimum, maximum, average, maximum - minimum,
                             (hot_index % nx, hot_index // nx), heater, notes, gradient, markers)

    @staticmethod
    def _thermal_gradient(grid: list[list[float]], axis: str) -> float:
        if axis == "Uniform": return 0.0
        ny, nx = len(grid), len(grid[0])
        x_band, y_band = max(1, nx//6), max(1, ny//6)
        if axis in ("Left to right", "Right to left"):
            left = sum(v for row in grid for v in row[:x_band])/(ny*x_band)
            right = sum(v for row in grid for v in row[-x_band:])/(ny*x_band)
            return right-left if axis == "Left to right" else left-right
        bottom = sum(v for row in grid[:y_band] for v in row)/(y_band*nx)
        top = sum(v for row in grid[-y_band:] for v in row)/(y_band*nx)
        return top-bottom if axis == "Bottom to top" else bottom-top

    @staticmethod
    def _sensor_markers(heater: HeaterResult, thermal: ThermalSpec,
                        grid: list[list[float]], average: float) -> list[SensorMarker]:
        spec = heater.spec
        ny, nx = len(grid), len(grid[0])
        edge = max(0.5, spec.trace_width_mm/2 + thermal.sensor_clearance_mm)
        candidates = []
        for iy, row in enumerate(grid):
            y = (iy+0.5)*spec.height_mm/ny
            if y < edge or y > spec.height_mm-edge: continue
            for ix, temperature in enumerate(row):
                x = (ix+0.5)*spec.width_mm/nx
                if x < edge or x > spec.width_mm-edge: continue
                clearance = min(HeaterEngine._point_segment_distance(x, y, segment)
                                - segment.width_mm/2 for segment in heater.segments)
                if clearance >= thermal.sensor_clearance_mm:
                    candidates.append((x, y, temperature, clearance))
        if not candidates:
            return []
        hot = max(candidates, key=lambda item: (item[2], item[3]))
        separation = min(spec.width_mm, spec.height_mm)*0.15
        separated = [item for item in candidates if math.hypot(item[0]-hot[0], item[1]-hot[1]) >= separation]
        control = min(separated or candidates,
                      key=lambda item: (abs(item[2]-average), -item[3],
                                        -math.hypot(item[0]-hot[0], item[1]-hot[1])))
        markers = [SensorMarker("PTC", "hotspot / safety", *hot)]
        if control != hot:
            markers.append(SensorMarker("NTC", "representative control", *control))
        return markers

    @staticmethod
    def tune_gradient(spec: HeaterSpec, thermal: ThermalSpec,
                      target_delta_c: float) -> ThermalResult:
        """Choose the closest heat-bias ratio under the declared simple model.

        A sampled search is used because fixed-voltage current changes with
        resistance, so temperature difference need not be monotonic in ratio.
        """
        if spec.gradient_axis == "Uniform" or not math.isfinite(target_delta_c) or target_delta_c <= 0:
            raise ValueError("Choose a gradient direction and a positive target temperature difference.")
        coarse = replace(thermal, grid_x=min(24, thermal.grid_x),
                         grid_y=min(16, thermal.grid_y), iterations=min(150, thermal.iterations))
        trials = []
        def evaluate(ratio):
            result = HeaterEngine.simulate(HeaterEngine.generate(replace(spec, gradient_ratio=ratio)),
                                           coarse, recommend_sensors=False)
            trials.append(result)
            return result
        samples = [evaluate(ratio) for ratio in (0.5, 0.75, 1.0, 2.0, 3.0, 4.0)]
        crossings = [(a, b) for a, b in zip(samples, samples[1:])
                     if (a.gradient_delta_c-target_delta_c)*(b.gradient_delta_c-target_delta_c) <= 0]
        if crossings:
            lower, upper = min(crossings, key=lambda pair:
                               min(abs(pair[0].gradient_delta_c-target_delta_c),
                                   abs(pair[1].gradient_delta_c-target_delta_c)))
            for _ in range(12):
                middle = evaluate((lower.heater.spec.gradient_ratio+upper.heater.spec.gradient_ratio)/2)
                if abs(middle.gradient_delta_c-target_delta_c) <= max(0.25, 0.05*target_delta_c):
                    break
                if (lower.gradient_delta_c-target_delta_c)*(middle.gradient_delta_c-target_delta_c) <= 0:
                    upper = middle
                else:
                    lower = middle
        chosen = min(trials, key=lambda result: abs(result.gradient_delta_c-target_delta_c))
        def full(ratio):
            return HeaterEngine.simulate(HeaterEngine.generate(replace(spec, gradient_ratio=ratio)),
                                         thermal, recommend_sensors=False)
        selected = full(chosen.heater.spec.gradient_ratio)
        full_trials = [selected]
        if selected.heater.spec.gradient_ratio != 1.0:
            baseline = full(1.0)
            full_trials.append(baseline)
            low, high = sorted((baseline, selected), key=lambda value: value.gradient_delta_c)
            for _ in range(2):
                if abs(selected.gradient_delta_c-target_delta_c) <= max(0.25, 0.05*target_delta_c):
                    break
                if not low.gradient_delta_c <= target_delta_c <= high.gradient_delta_c:
                    break
                span = high.gradient_delta_c-low.gradient_delta_c
                if span < 1e-9:break
                ratio = low.heater.spec.gradient_ratio + (target_delta_c-low.gradient_delta_c)*(
                    high.heater.spec.gradient_ratio-low.heater.spec.gradient_ratio)/span
                candidate = full(ratio)
                full_trials.append(candidate)
                selected = min(full_trials, key=lambda result: abs(result.gradient_delta_c-target_delta_c))
                if candidate.gradient_delta_c < target_delta_c:low = candidate
                else:high = candidate
        best_ratio = min(full_trials, key=lambda result: abs(result.gradient_delta_c-target_delta_c)).heater.spec.gradient_ratio
        best = HeaterEngine.simulate(HeaterEngine.generate(replace(spec, gradient_ratio=best_ratio)), thermal)
        error = abs(best.gradient_delta_c-target_delta_c)
        best.notes.append(f"Requested directional temperature difference: {target_delta_c:.1f} C; "
                          f"model estimate: {best.gradient_delta_c:.1f} C at heat-bias ratio "
                          f"{best.heater.spec.gradient_ratio:.4f}.")
        if error > max(1.0, 0.15*target_delta_c):
            best.notes.append("Target is not reached within the allowed trace-width bias; revise supply, geometry or thermal assumptions.")
        return best
