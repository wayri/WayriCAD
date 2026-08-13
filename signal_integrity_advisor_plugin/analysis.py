"""Protocol-aware I2C pull-up and routed-impedance checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from .measurement import PathMeasurement, TraceMeasurementEngine
except ImportError:  # pragma: no cover - source-tree development fallback
    from trace_impedance_plugin.measurement import PathMeasurement, TraceMeasurementEngine


PROTOCOL_PRESETS: Dict[str, Dict[str, float]] = {
    "Custom single-ended": {"target": 50.0, "tolerance": 10.0, "differential": 0.0},
    "Custom differential": {"target": 100.0, "tolerance": 10.0, "differential": 1.0},
    "CAN / CAN FD": {"target": 120.0, "tolerance": 10.0, "differential": 1.0},
    "Ethernet 100/1000BASE-T": {"target": 100.0, "tolerance": 10.0, "differential": 1.0},
    "Generic RF": {"target": 50.0, "tolerance": 10.0, "differential": 0.0},
    "RS-485": {"target": 120.0, "tolerance": 10.0, "differential": 1.0},
    "SerDes (editable)": {"target": 100.0, "tolerance": 10.0, "differential": 1.0},
    "USB 2.x": {"target": 90.0, "tolerance": 10.0, "differential": 1.0},
    "USB 3.x": {"target": 90.0, "tolerance": 10.0, "differential": 1.0},
    "USB4 (editable)": {"target": 85.0, "tolerance": 10.0, "differential": 1.0},
}


@dataclass
class PullupResult:
    voltage_v: float
    bus_capacitance_pf: float
    rise_time_ns: float
    sink_current_ma: float
    low_level_v: float
    minimum_ohm: float
    maximum_ohm: float
    recommended_ohm: Optional[float]
    status: str
    note: str


@dataclass
class ImpedanceResult:
    primary: PathMeasurement
    mate: Optional[PathMeasurement]
    target_ohm: float
    tolerance_percent: float
    measured_ohm: float
    error_percent: float
    status: str
    skew_mm: float
    stub_warning: str


class SignalIntegrityEngine:
    """Thin validation layer over KiWay's geometry-aware measurement engine."""

    E24 = (10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91)

    def __init__(self, board: Any) -> None:
        self.measurement = TraceMeasurementEngine(board)

    @staticmethod
    def i2c_pullup(voltage_v: float, capacitance_pf: float, rise_time_ns: float,
                   sink_current_ma: float, low_level_v: float) -> PullupResult:
        if min(voltage_v, capacitance_pf, rise_time_ns, sink_current_ma) <= 0:
            raise ValueError("Voltage, capacitance, rise time, and sink current must be positive.")
        minimum = (voltage_v - low_level_v) / (sink_current_ma / 1000.0)
        maximum = (rise_time_ns * 1e-9) / (0.8473 * capacitance_pf * 1e-12)
        candidates = SignalIntegrityEngine._e24_between(minimum, maximum)
        recommended = candidates[len(candidates) // 2] if candidates else None
        if minimum > maximum:
            status = "FAIL"
            note = "No resistor satisfies both sink-current and rise-time limits; reduce bus capacitance, speed, or voltage burden."
        else:
            status = "PASS"
            note = "Choose a standard value inside the range, then verify total device, connector, and trace capacitance."
        return PullupResult(voltage_v, capacitance_pf, rise_time_ns, sink_current_ma,
                            low_level_v, minimum, maximum, recommended, status, note)

    @staticmethod
    def _e24_between(low: float, high: float) -> List[float]:
        values = []
        for decade in range(0, 7):
            multiplier = 10 ** decade
            values.extend(base * multiplier for base in SignalIntegrityEngine.E24 if low <= base * multiplier <= high)
        return sorted(values)

    def validate_impedance(self, net: str, start: str, end: str, reference: str,
                           frequency_mhz: float, target: float, tolerance: float,
                           mate_net: str = "", mate_start: str = "", mate_end: str = "") -> ImpedanceResult:
        primary = self.measurement.measure(net, start, end, frequency_mhz, reference)
        mate = None
        if mate_net:
            mate = self.measurement.measure(mate_net, mate_start, mate_end, frequency_mhz, reference)
        measured = primary.impedance_ohm if mate is None else primary.impedance_ohm + mate.impedance_ohm
        error = abs(measured - target) / max(target, 1e-9) * 100.0
        unresolved = any("not resolved" in note.lower() or "no connected" in note.lower() for note in primary.notes)
        status = "UNRESOLVED" if unresolved else ("PASS" if error <= tolerance else "FAIL")
        skew = abs(primary.length_mm - mate.length_mm) if mate else 0.0
        stub = self._stub_warning(primary)
        return ImpedanceResult(primary, mate, target, tolerance, measured, error, status, skew, stub)

    @staticmethod
    def _stub_warning(path: PathMeasurement) -> str:
        if path.zone_count:
            return "Copper-zone participation requires return-path review and a field solver."
        if path.layer_changes > 0:
            return "Layer changes/vias can introduce discontinuities; inspect reference-plane transitions."
        return "No automatic stub condition detected; branched net topology still requires visual review."
