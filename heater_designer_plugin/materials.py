"""Nominal electrical material models for uniform rectangular heater strips.

Bulk R = rho L/(width * thickness); film R = sheet_resistance L/width.
Dimensions stay fixed: thermal expansion, contacts, bend crowding, substrate,
oxidation and manufacturing tolerances are not modeled. These data are not
operating limits or a prediction for an unspecified commercial alloy/film.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    resistivity_ohm_m: float | None
    reference_c: float = 20.0
    tcr_per_k: float | None = None
    sheet_resistance_ohm_sq: float | None = None
    grade: str = "User supplied"
    source_url: str = ""
    applicability: str = "Measured properties of the actual conductor are required."
    # (temperature Celsius, resistance ratio relative to reference_c).
    temperature_factors: tuple[tuple[float, float], ...] = ()
    # Validity of a linear coefficient, not an operating-temperature limit.
    tcr_range_c: tuple[float, float] | None = None

    def __post_init__(self):
        _finite(self.reference_c, "Reference temperature")
        if (self.resistivity_ohm_m is None) == (self.sheet_resistance_ohm_sq is None):
            raise ValueError("Specify exactly one bulk resistivity or sheet resistance")
        if self.resistivity_ohm_m is not None:
            _positive(self.resistivity_ohm_m, "Bulk resistivity")
        if self.sheet_resistance_ohm_sq is not None:
            _positive(self.sheet_resistance_ohm_sq, "Sheet resistance")
        if self.tcr_per_k is not None:
            _finite(self.tcr_per_k, "TCR")
        if self.tcr_range_c is not None:
            low, high = self.tcr_range_c
            _finite(low, "TCR range minimum")
            _finite(high, "TCR range maximum")
            if low > self.reference_c or high < self.reference_c or low >= high:
                raise ValueError("TCR range must contain reference temperature")
        previous = float("-inf")
        for temperature, factor in self.temperature_factors:
            _finite(temperature, "Table temperature")
            _positive(factor, "Table resistance factor")
            if temperature <= previous:
                raise ValueError("Temperature table must be strictly increasing")
            previous = temperature
        if self.temperature_factors and (self.reference_c, 1.0) not in self.temperature_factors:
            raise ValueError("Temperature table must contain reference temperature with factor 1")


def _finite(value: float, label: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")


def _positive(value: float, label: str) -> None:
    _finite(value, label)
    if value <= 0:
        raise ValueError(f"{label} must be positive")


MATERIALS = MappingProxyType({
    "copper": Material(
        "copper", "Copper (annealed, 100% IACS)", 1.724e-8,
        tcr_per_k=0.00393, grade="Standard annealed copper, 100% IACS",
        source_url="https://help.copper.fyi/hc/en-us/article_attachments/14627231747484",
        applicability="Nominal annealed copper; linear coefficient valid from -100 to 200 C.",
        tcr_range_c=(-100.0, 200.0)),
    "nichrome80": Material(
        "nichrome80", "Nichrome 80 (Nikrothal 80)", 1.09e-6,
        grade="Kanthal Nikrothal 80 wire, NiCr 80/20",
        source_url="https://www.kanthal.com/products/datasheets/material-datasheets/wire/resistance-heating-wire-and-resistance-wire/nikrothal-80/",
        applicability="Manufacturer wire data; not generic NiCr or deposited-film data. Linear interpolation of Ct table.",
        temperature_factors=((20., 1.), (100., 1.01), (200., 1.02),
                             (300., 1.03), (400., 1.04), (500., 1.05),
                             (600., 1.04), (700., 1.04), (800., 1.04),
                             (900., 1.04), (1000., 1.05), (1100., 1.06), (1200., 1.07))),
    "inconel600": Material(
        "inconel600", "INCONEL alloy 600", 1.03e-6,
        grade="Special Metals INCONEL 600, UNS N06600",
        source_url="https://www.specialmetals.com/documents/technical-bulletins/inconel/inconel-alloy-600.pdf",
        applicability="Typical bulk alloy 600 values, not other INCONEL grades. Linear interpolation of Table 3.",
        temperature_factors=tuple((t, rho / 1.03) for t, rho in
                                  ((20., 1.03), (100., 1.04), (200., 1.05),
                                   (300., 1.07), (400., 1.09), (500., 1.12),
                                   (600., 1.13), (700., 1.13), (800., 1.13), (900., 1.15)))),
    "manganin": Material(
        "manganin", "MANGANIN (CuMn12Ni)", 4.3e-7,
        grade="Isabellenhuette MANGANIN, material 2.1362, annealed",
        source_url="https://www.isabellenhuette.com/de/fileadmin/Daten/Praezisionslegierungen/Datenblaetter_Widerstand/MANGANIN.pdf",
        applicability="Nominal resistivity +/-5%; parabolic R(T), TCR +/-10 ppm/K at 20–50 C. No unique TCR assumed; use measured custom data for temperature correction."),
    "constantan": Material(
        "constantan", "Constantan (ISOTAN CuNi44)", 4.9e-7,
        grade="Isabellenhuette ISOTAN, material 2.0842, annealed",
        source_url="https://www.isabellenhuette.com/hubfs/Files/Data-sheets/LE/Resistor/ISOTAN.pdf",
        applicability="Nominal resistivity +/-10%; TCR -80 to +40 ppm/K at 20–105 C. No unique TCR assumed; use measured custom data for temperature correction."),
})


def custom_bulk(resistivity_ohm_m: float, tcr_per_k: float | None = None,
                reference_c: float = 20.0) -> Material:
    """Create a user-supplied bulk/foil model with an optional linear TCR."""
    return Material("custom_bulk", "Custom bulk / foil", resistivity_ohm_m,
                    reference_c, tcr_per_k)


def custom_sheet(sheet_resistance_ohm_sq: float, tcr_per_k: float | None = None,
                 reference_c: float = 20.0) -> Material:
    """Create a film model; sheet resistance already includes film thickness."""
    return Material("custom_sheet", "Custom resistive film", None,
                    reference_c, tcr_per_k, sheet_resistance_ohm_sq)


def resistance_factor(material: Material, temperature_c: float | None = None) -> float:
    """Return R(T)/R(ref); reject unknown corrections and table extrapolation."""
    temperature = material.reference_c if temperature_c is None else temperature_c
    _finite(temperature, "Conductor temperature")
    if temperature == material.reference_c:
        return 1.0
    table = material.temperature_factors
    if table:
        if not table[0][0] <= temperature <= table[-1][0]:
            raise ValueError(f"{material.name} temperature is outside its resistance data table")
        for (t0, f0), (t1, f1) in zip(table, table[1:]):
            if t0 <= temperature <= t1:
                return f0 + (f1 - f0) * (temperature - t0) / (t1 - t0)
    if material.tcr_per_k is None:
        raise ValueError(f"{material.name} has no unique TCR; provide measured custom TCR or use reference temperature")
    if material.tcr_range_c is not None and not material.tcr_range_c[0] <= temperature <= material.tcr_range_c[1]:
        raise ValueError(f"{material.name} temperature is outside its linear TCR data range")
    factor = 1.0 + material.tcr_per_k * (temperature - material.reference_c)
    _positive(factor, "Temperature resistance factor")
    return factor


def segment_resistance_ohm(material: Material, length_mm: float, width_mm: float,
                           thickness_um: float | None = None,
                           temperature_c: float | None = None) -> float:
    """Resistance of one constant-width centerline segment; dimensions in mm/um."""
    _finite(length_mm, "Segment length")
    if length_mm < 0:
        raise ValueError("Segment length must be nonnegative")
    _positive(width_mm, "Segment width")
    factor = resistance_factor(material, temperature_c)
    squares = length_mm / width_mm
    if material.sheet_resistance_ohm_sq is not None:
        return material.sheet_resistance_ohm_sq * squares * factor
    if thickness_um is None:
        raise ValueError("Bulk / foil resistance requires conductor thickness")
    _positive(thickness_um, "Conductor thickness")
    return material.resistivity_ohm_m * squares / (thickness_um * 1e-6) * factor
