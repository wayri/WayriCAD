"""Detached component inputs for native QuickTherm review; no board access.

Saved properties are immutable evidence. ``manual_values`` stores only explicit
overrides, including None for an explicit blank. ``effective_values`` merges
these with parsed saved fields for a worker request without inventing zeros.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Mapping

from .quick_therm import parse_field_quantity
from .thermal_review import parse_temperature


QUANTITIES = ("power_w", "theta_ja_air_k_per_w", "theta_jb_k_per_w",
              "theta_jc_k_per_w", "minimum_c", "maximum_c")
LIMIT_QUANTITIES = frozenset(("minimum_c", "maximum_c"))
_LIMIT_ALIASES={
    'minimum_c':{'tmin','tminc','mintj','mintjc','tjmin','tjminc','minimumjunctiontemperaturec'},
    'maximum_c':{'tmax','tmaxc','maxtj','maxtjc','tjmax','tjmaxc','maximumjunctiontemperaturec'},
}


def restored_temperature_mapping(field_names,previous=None):
    """Preserve an explicit choice or use one unambiguous junction-limit alias."""
    names=list(dict.fromkeys(map(str,field_names)));previous=previous or {};mapping={}
    for key,aliases in _LIMIT_ALIASES.items():
        if previous.get(key) in names:
            mapping[key]=previous[key];continue
        matches=[name for name in names if re.sub(r'[\s_()\-/°]','',name.casefold()) in aliases]
        mapping[key]=matches[0] if len(matches)==1 else ''
    return mapping

QUANTITY_LABELS = {
    "power_w": "Power", "theta_ja_air_k_per_w": "RθJA",
    "theta_jb_k_per_w": "RθJB", "theta_jc_k_per_w": "RθJC",
    "minimum_c": "Min Tj", "maximum_c": "Max Tj",
}


def parse_input(raw, quantity):
    """Parse an input using the established units; a blank remains unknown."""
    if quantity not in QUANTITIES:
        raise ValueError(f"Unsupported component input: {quantity}")
    if raw is None or not str(raw).strip():
        return None
    return (parse_temperature(raw) if quantity in LIMIT_QUANTITIES
            else parse_field_quantity(raw, quantity))


@dataclass(frozen=True)
class ComponentInputCell:
    value: float | None
    text: str
    source: str
    source_field: str | None = None
    source_raw: str | None = None
    issue: str | None = None


class ComponentInputsModel:
    """Editable copy of an inventory, scope and manual overrides.

    Inventory may be a components list or {'components': [...],
    'component_references': [...]}. Components use reference/value/side/properties.
    Extracted rows with values/source_fields are supported too. Temperature limit
    mappings remain separate from thermal mappings, matching worker contracts.
    """

    def __init__(self, inventory=None, field_map=None, manual_values=None,
                 selected_references=None, limit_field_map=None):
        inventory = inventory or {}
        if isinstance(inventory, Mapping):
            components = inventory.get("components", [])
            references = inventory.get("component_references", [])
        else:
            components, references = inventory, []
        self.components = {}
        for component in components:
            row = deepcopy(dict(component))
            reference = str(row.get("reference", "")).strip()
            if not reference or "*" in reference:
                continue
            if reference in self.components:
                raise ValueError(f"Duplicate footprint reference: {reference}")
            self.components[reference] = row
        for reference in references:
            reference = str(reference).strip()
            if reference and "*" not in reference:
                self.components.setdefault(reference, {"reference": reference})
        self.references = sorted(self.components)
        self._manual = {ref: deepcopy(dict(values)) for ref, values in
                        (manual_values or {}).items() if ref in self.components}
        self._selected = set(selected_references or ()) & set(self.references)
        self._mapping = {}
        self._saved = {}
        self.set_mappings(field_map, limit_field_map)

    def set_mappings(self, field_map=None, limit_field_map=None):
        """Reparse local saved evidence only when mappings change, never on search."""
        mapping = {**dict(field_map or {}), **dict(limit_field_map or {})}
        if set(mapping) - set(QUANTITIES):
            raise ValueError("Unsupported component field mapping.")
        self._mapping = {key: str(name) for key, name in mapping.items() if name}
        self._saved = {}
        for reference, row in self.components.items():
            properties = row.get("properties", row.get("fields", {})) or {}
            for quantity in QUANTITIES:
                name = self._mapping.get(quantity)
                raw = properties.get(name) if name else None
                # Extracted rows already carry reviewed quantity/source mappings.
                if name is None and quantity in row.get("values", {}):
                    raw = row["values"][quantity]
                    name = row.get("source_fields", {}).get(quantity)
                issue = None
                try:
                    value = parse_input(raw, quantity)
                except ValueError as exc:
                    value, issue = None, str(exc)
                self._saved[reference, quantity] = ComponentInputCell(
                    value, "" if raw is None else str(raw),
                    "Saved field" if name else "Unknown", name,
                    None if raw is None else str(raw), issue)

    def cell(self, reference, quantity):
        saved = self._saved[reference, quantity]
        overrides = self._manual.get(reference, {})
        if quantity not in overrides:
            return saved
        raw = overrides[quantity]
        try:
            value, issue = parse_input(raw, quantity), None
        except ValueError as exc:
            value, issue = None, str(exc)
        return ComponentInputCell(value, "" if raw is None else str(raw),
                                  "Manual override", saved.source_field,
                                  saved.source_raw, issue)

    def set_value(self, reference, quantity, raw):
        """Validate one edit before storing it; no environment can disable RθJB."""
        if reference not in self.components:
            raise ValueError(f"Unknown component: {reference}")
        value = parse_input(raw, quantity)
        self._manual.setdefault(reference, {})[quantity] = value

    def restore_saved(self, references, quantities=QUANTITIES):
        for reference in references:
            overrides = self._manual.get(reference, {})
            for quantity in quantities:
                overrides.pop(quantity, None)
            if not overrides:
                self._manual.pop(reference, None)

    def set_included(self, reference, included):
        if reference not in self.components:
            raise ValueError(f"Unknown component: {reference}")
        (self._selected.add if included else self._selected.discard)(reference)

    def select_all(self, references=None, included=True):
        """Scope is explicit: omitted references means all, provided means subset."""
        for reference in self.references if references is None else references:
            self.set_included(reference, included)

    def selected_references(self):
        return [ref for ref in self.references if ref in self._selected]

    def is_included(self, reference):
        return reference in self._selected

    def visible_references(self, search="", included_only=False):
        words = str(search).casefold().split()
        result = []
        for reference in self.references:
            row = self.components[reference]
            haystack = " ".join(str(row.get(key, "")) for key in
                                ("reference", "value", "side")).casefold()
            if ((not included_only or reference in self._selected)
                    and all(word in haystack for word in words)):
                result.append(reference)
        return result

    def row_status(self, reference):
        cells = {key: self.cell(reference, key) for key in QUANTITIES}
        issues = [f"{QUANTITY_LABELS[key]}: {cell.issue}" for key, cell in cells.items()
                  if cell.issue]
        lower, upper = cells["minimum_c"].value, cells["maximum_c"].value
        if lower is not None and upper is not None and lower > upper:
            issues.append("Minimum Tj exceeds maximum Tj")
        if issues:
            return "; ".join(issues)
        if cells["power_w"].value is None:
            return "Power unknown"
        if cells["theta_jb_k_per_w"].value is None:
            return "Power entered; RθJB unknown"
        return "Power and RθJB entered"

    def source_summary(self, reference):
        cells = [self.cell(reference, key) for key in QUANTITIES]
        fields = sorted({cell.source_field for cell in cells if cell.source_field})
        saved = "Saved: " + ", ".join(fields) if fields else "No mapped saved fields"
        manual = [QUANTITY_LABELS[key] for key in QUANTITIES
                  if key in self._manual.get(reference, {})]
        return saved + ("; manual: " + ", ".join(manual) if manual else "")

    def manual_values(self):
        return deepcopy(self._manual)

    def effective_values(self, selected_only=True, include_limits=True):
        """Detached values; unknowns absent, invalid scoped cells rejected."""
        self.validate(selected_only)
        references = self.selected_references() if selected_only else self.references
        quantities = QUANTITIES if include_limits else QUANTITIES[:4]
        return {ref: {key: cell.value for key in quantities
                      if (cell := self.cell(ref, key)).value is not None}
                for ref in references}

    def validate(self, selected_only=True):
        """Reject invalid mapped/entered values and inverted limits; allow unknowns."""
        references = self.selected_references() if selected_only else self.references
        for ref in references:
            for key in QUANTITIES:
                cell = self.cell(ref, key)
                if cell.issue:
                    raise ValueError(f"{ref} {QUANTITY_LABELS[key]}: {cell.issue}")
            lo, hi = self.cell(ref, "minimum_c").value, self.cell(ref, "maximum_c").value
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{ref}: minimum Tj exceeds maximum Tj.")

    def export_state(self):
        """Return all overrides, including hidden rows, and complete checked scope."""
        return {"manual_values": self.manual_values(),
                "references": self.selected_references(),
                "manual_limits": {
                    ref: {key: value for key, value in values.items()
                          if key in LIMIT_QUANTITIES}
                    for ref, values in self._manual.items()
                    if any(key in LIMIT_QUANTITIES for key in values)}}
