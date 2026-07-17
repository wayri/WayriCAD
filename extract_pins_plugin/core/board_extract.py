"""Compatibility extraction layer for the original board-analysis features."""

from __future__ import annotations

import fnmatch
from typing import Any, Dict, Iterable, List, Sequence

from .data_extractor import DataExtractor


def _matches(value: str, patterns: str) -> bool:
    values = [part.strip().lower() for part in patterns.split(",") if part.strip()]
    return not values or any(fnmatch.fnmatchcase(value.lower(), pattern) for pattern in values)


def _properties(footprint: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        for field in footprint.GetFields():
            result[str(field.GetName())] = str(field.GetText())
    except Exception:
        pass
    return result


def _protocol(net_name: str) -> str:
    tokens = {token.upper() for token in str(net_name).split("_") if token}
    labels = ("SPI", "I2C", "I3C", "UART", "CAN", "LIN", "USB", "JTAG", "SWD", "QSPI", "SDIO", "MDIO", "RMII", "MIPI", "LVDS", "TM", "TC", "TA", "TD", "CA", "CD")
    return next((label for label in labels if label in tokens or str(net_name).upper().startswith(label)), "")


def extract_board_pin_rows(
    board: Any,
    reference_filter: str = "",
    value_filter: str = "",
    net_filter: str = "",
    property_filter: str = "",
    include_power: bool = True,
    selected_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return filtered pin/property rows while preserving the v2 extractor fields."""
    if board is None:
        return []
    extractor = DataExtractor(board)
    selected = set()
    if selected_only:
        try:
            selected = {item.GetReference() for item in board.GetSelection() if hasattr(item, "GetReference")}
        except Exception:
            selected = set()
    rows: List[Dict[str, Any]] = []
    for footprint in extractor.footprints:
        reference = str(footprint.GetReference())
        value = str(footprint.GetValue())
        props = _properties(footprint)
        if selected_only and reference not in selected:
            continue
        if not _matches(reference, reference_filter) or not _matches(value, value_filter):
            continue
        if property_filter:
            if "=" in property_filter:
                key, expected = property_filter.split("=", 1)
                if not _matches(props.get(key.strip(), ""), expected):
                    continue
            elif not any(_matches(text, property_filter) for text in props.values()):
                continue
        for pad in footprint.Pads():
            net = pad.GetNet() if hasattr(pad, "GetNet") else None
            net_name = str(net.GetNetname()) if net else ""
            if not _matches(net_name, net_filter):
                continue
            net_type = extractor.classify_net(net_name) if net_name else "unconnected"
            if not include_power and net_type != "signal":
                continue
            rows.append({
                "Reference": reference,
                "Value": value,
                "Pad": str(pad.GetPadName() if hasattr(pad, "GetPadName") else pad.GetNumber()),
                "Net Name": net_name,
                "Net Type": net_type,
                "Power Net": "Yes" if net_type != "signal" and net_name else "No",
                "Protocol": _protocol(net_name),
                "Properties": "; ".join(f"{key}={val}" for key, val in sorted(props.items()) if val),
                "Layer": str(footprint.GetLayerName()),
            })
    return sorted(rows, key=lambda row: (DataExtractor.natural_sort_key(row["Reference"]), DataExtractor.natural_sort_key(row["Pad"])))


def protocol_color(protocol: str, net_type: str) -> str:
    colors = {
        "SPI": "#d9eaff", "I2C": "#d9f4e3", "UART": "#fff1c9", "CAN": "#f6d9e8",
        "USB": "#dce4ff", "JTAG": "#eadcff", "TM": "#d8f0ff", "TC": "#ffe0d1",
    }
    if protocol in colors:
        return colors[protocol]
    return {"ground": "#e4e4e4", "supply": "#ffe7b8", "power": "#ffd2d2"}.get(net_type, "#ffffff")
