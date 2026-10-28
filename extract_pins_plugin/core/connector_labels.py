"""Reviewed connector label lists and native KiCad schematic clipboard objects.

This module has no editor, wx or scientific-runtime dependency. It generates
annotation objects only; it neither assigns schematic pins nor edits PCB nets.
Pin numbers describe the chosen list order, not a connector's mating contract.
"""

from __future__ import annotations

import csv
from io import StringIO
import math
import string
from typing import Any, Iterable, Mapping
import unicodedata
from uuid import uuid4


MAX_LABELS = 2000
MAX_TEXT_BYTES = 2_000_000
SEQUENCES = ("sequential", "row-major", "column-major", "odd-even", "serpentine")
KINDS = ("global", "local", "hierarchical")
SHAPES = ("input", "output", "bidirectional", "tri_state", "passive")


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    value = value.strip()
    if not value and not empty:
        raise ValueError(f"{name} is empty. Enter a name or omit that row.")
    if len(value) > 512 or any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError(f"{name} must be at most 512 characters without control characters or line breaks.")
    return value


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    pins = set()
    for index, row in enumerate(rows):
        if index >= MAX_LABELS:
            raise ValueError(f"A label set is limited to {MAX_LABELS} rows.")
        if not isinstance(row, Mapping):
            raise ValueError("Each label row must contain pin and label text.")
        pin = _text(row.get("pin"), f"Row {index + 1} pin")
        label = _text(row.get("label"), f"Row {index + 1} label")
        if pin in pins:
            raise ValueError(f"Duplicate pin {pin!r}. Each assignment must identify one pin.")
        pins.add(pin)
        result.append(dict(row, pin=pin, label=label))
    if not result:
        raise ValueError("Enter or select at least one label.")
    return result


def numbering(count: int, sequence: str = "sequential", start: int = 1,
              step: int = 1, columns: int = 2) -> list[str]:
    """Return pin IDs for row-major input cells under the selected numbering.

    ``columns`` is the physical grid width. Column-major numbers down each
    column; serpentine reverses alternate rows. Odd-even puts the odd numeric
    IDs before the even IDs. Negative steps support descending numbering.
    An incomplete final row contains only its actual cells, never phantom pins.
    """
    count = _integer(count, "Label count", 1, MAX_LABELS)
    start = _integer(start, "First pin", 0, 1_000_000_000)
    step = _integer(step, "Numbering step", -1_000_000, 1_000_000)
    columns = _integer(columns, "Grid columns", 1, MAX_LABELS)
    if not step:
        raise ValueError("Numbering step cannot be zero.")
    if sequence not in SEQUENCES:
        raise ValueError("Unknown numbering sequence: " + str(sequence))
    values = [start + index * step for index in range(count)]
    if min(values) < 0 or max(values) > 1_000_000_000:
        raise ValueError("Generated pin numbers must be between zero and 1,000,000,000.")
    if sequence == "odd-even":
        values = [value for value in values if value % 2] + [value for value in values if not value % 2]
    elif sequence in ("column-major", "serpentine"):
        if sequence == "column-major":
            order = [index for column in range(min(columns, count))
                     for index in range(column, count, columns)]
        else:
            order = []
            for row, offset in enumerate(range(0, count, columns)):
                cells = list(range(offset, min(offset + columns, count)))
                order.extend(reversed(cells) if row % 2 else cells)
        assigned = [0] * count
        for value, index in zip(values, order):
            assigned[index] = value
        values = assigned
    return [str(value) for value in values]


def parse_pin_text(text: str, columns: str = "auto", sequence: str = "row-major",
                   start: int = 1, step: int = 1, header: bool = False,
                   pin_numbers: Iterable[str] | None = None,
                   grid_columns: int = 2) -> list[dict[str, str]]:
    """Parse one label column or explicit pin/name pairs from CSV, TSV or lines.

    ``columns`` is ``auto``, ``labels`` or ``pin-label``. Auto requires every
    nonblank record to have the same width (one or two fields). Headers are
    skipped only when explicitly requested. Optional ``pin_numbers`` binds a
    one-column paste to an already reviewed connector pin order; its length
    must match exactly. No row is silently truncated or assigned twice.
    """
    if not isinstance(text, str) or len(text) > MAX_TEXT_BYTES or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Pasted text must be at most 2 MB of UTF-8 text.")
    if columns not in ("auto", "labels", "pin-label"):
        raise ValueError("Column mode must be auto, labels or pin-label.")
    if not isinstance(header, bool):
        raise ValueError("Header selection must be true or false.")
    text = text.removeprefix("\ufeff")
    # Tabs are the native spreadsheet paste separator. CSV Sniffer is used
    # only to select a delimiter; the strict reader retains quoted fields.
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else "," if "," in sample else ";" if ";" in sample else ","
    try:
        records = []
        for row in csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True):
            if not row or not any(cell.strip() for cell in row):
                continue
            records.append(row)
            if len(records) > MAX_LABELS + int(header):
                raise ValueError(f"A label set is limited to {MAX_LABELS} rows.")
    except csv.Error as exc:
        raise ValueError("Cannot parse the pasted delimited text: " + str(exc)) from exc
    if header:
        records = records[1:]
    if not records:
        raise ValueError("The pasted text has no label records.")
    widths = {len(row) for row in records}
    expected = 1 if columns == "labels" else 2 if columns == "pin-label" else next(iter(widths))
    if widths != {expected} or expected not in (1, 2):
        raise ValueError("Use one label column or two columns containing pin and label; every record must match.")
    if expected == 2:
        if pin_numbers is not None:
            raise ValueError("Explicit two-column pin assignments cannot also use a selected pin sequence.")
        return _rows({"pin": row[0], "label": row[1]} for row in records)
    if pin_numbers is None:
        pins = numbering(len(records), sequence, start, step, grid_columns)
    else:
        pins = []
        for pin in pin_numbers:
            pins.append(pin)
            if len(pins) > MAX_LABELS:
                raise ValueError(f"A pin sequence is limited to {MAX_LABELS} rows.")
        if len(pins) != len(records):
            raise ValueError("The label count must exactly match the selected connector pin count.")
    return _rows({"pin": pin, "label": row[0]} for pin, row in zip(pins, records))


def format_labels(rows: Iterable[Mapping[str, Any]], prefix: str = "", suffix: str = "",
                  template: str = "{label}", case: str = "unchanged",
                  ref: str = "") -> list[dict[str, Any]]:
    """Apply reviewed, literal modifiers without evaluating arbitrary code.

    Template fields are limited to ``{label}``, ``{pin}`` and ``{ref}``.
    Modifiers change generated labels only; electrical values and source data
    are untouched. The original label is retained for preview comparison.
    """
    rows = _rows(rows)
    prefix = _text(prefix, "Prefix", empty=True)
    suffix = _text(suffix, "Suffix", empty=True)
    ref = _text(ref, "Reference", empty=True)
    if not isinstance(template, str) or len(template) > 512:
        raise ValueError("Label template must be at most 512 characters.")
    if case not in ("unchanged", "upper", "lower"):
        raise ValueError("Case must be unchanged, upper or lower.")
    formatter = string.Formatter()
    try:
        fields = list(formatter.parse(template))
    except ValueError as exc:
        raise ValueError("Invalid label template: " + str(exc)) from exc
    for _literal, field, spec, conversion in fields:
        if field is not None and (field not in ("label", "pin", "ref") or spec or conversion):
            raise ValueError("Use only {label}, {pin} and {ref} template fields, without formatting or conversions.")
    result = []
    for row in rows:
        label = prefix + formatter.vformat(template, (), dict(label=row["label"], pin=row["pin"], ref=ref)) + suffix
        if case == "upper":
            label = label.upper()
        elif case == "lower":
            label = label.lower()
        label = _text(label, "Generated label for pin " + row["pin"])
        result.append(dict(row, original_label=row.get("original_label", row["label"]), label=label))
    return result


def label_warnings(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Describe intentional same-name net connections without prohibiting them."""
    names: dict[str, list[str]] = {}
    for row in _rows(rows):
        names.setdefault(row["label"], []).append(row["pin"])
    return [f"Label {name!r} is shared by pins {', '.join(pins)}; same-name labels connect those nets."
            for name, pins in names.items() if len(pins) > 1]


def _finite(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(name + " must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + " must be a finite number.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return number


def _quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _number(value: float) -> str:
    return format(value, ".10g")


def schematic_labels(rows: Iterable[Mapping[str, Any]], kind: str = "global",
                     orientation: int = 0, pitch_mm: float = 2.54,
                     text_size_mm: float = 1.27, origin: tuple[float, float] = (0, 0),
                     shape: str = "bidirectional") -> str:
    """Generate pasteable KiCad label objects with fresh UUIDs and no wires.

    ``origin`` and pitch are millimetres. Pin assignments stay in the preview;
    the schematic receives label text only, positioned one pitch apart along
    Y (0/180°) or X (90/270°). The user reviews and pastes at the intended pin
    anchors; generating labels does not establish actual pin connectivity.
    """
    rows = _rows(rows)
    if kind not in KINDS:
        raise ValueError("Label kind must be global, local or hierarchical.")
    if isinstance(orientation, bool) or orientation not in (0, 90, 180, 270):
        raise ValueError("Label angle must be 0, 90, 180 or 270 degrees.")
    if shape not in SHAPES:
        raise ValueError("Unsupported global/hierarchical label shape.")
    pitch = _finite(pitch_mm, "Label pitch (mm)", 0.25, 100)
    size = _finite(text_size_mm, "Text size (mm)", 0.25, 10)
    if not isinstance(origin, (tuple, list)) or len(origin) != 2:
        raise ValueError("Origin must contain X and Y in millimetres.")
    x0, y0 = [_finite(value, "Origin (mm)", -100_000, 100_000) for value in origin]
    if max(abs(x0), abs(y0)) + pitch * (len(rows) - 1) > 100_000:
        raise ValueError("Label positions exceed the supported coordinate range; reduce pitch or count.")
    tag = {"global": "global_label", "local": "label", "hierarchical": "hierarchical_label"}[kind]
    justification = "right" if orientation in (180, 270) else "left"
    objects = []
    for index, row in enumerate(rows):
        x = x0 + (index * pitch if orientation in (90, 270) else 0)
        y = y0 + (index * pitch if orientation in (0, 180) else 0)
        form = "" if kind == "local" else f" (shape {shape})"
        objects.append(f"({tag} {_quote(row['label'])}{form}"
                       f" (at {_number(x)} {_number(y)} {orientation})"
                       f" (effects (font (size {_number(size)} {_number(size)})) (justify {justification}))"
                       f' (uuid "{uuid4()}"))')
    return "\n".join(objects) + "\n"


def full_schematic(rows: Iterable[Mapping[str, Any]], **options: Any) -> str:
    """Wrap the same generated objects in an independently parseable schematic.

    This file is useful for review/native export. It has no symbols, wires or
    project mutation, and therefore does not prove intended connector wiring.
    """
    options.setdefault("origin", (30, 30))
    return ('(kicad_sch (version 20250114) (generator "wayricad")\n'
            f' (uuid "{uuid4()}") (paper "A4") (lib_symbols)\n'
            + schematic_labels(rows, **options) + ')\n')
