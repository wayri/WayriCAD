"""Offline connector report behavior; no KiCad or wx runtime required."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "core" / "connector_report.py"
SPEC = importlib.util.spec_from_file_location("connector_report", SOURCE)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class Box:
    def GetWidth(self):
        return 8_000_000

    def GetHeight(self):
        return 4_500_000


class Footprint:
    def GetBoundingBox(self):
        return Box()


def _data():
    return {
        "J1": {
            "general_properties": {"Value": "USB <connector>", "Layer": "F.Cu", "Position": "(10mm, 20mm)"},
            "pins": [
                {"Pad Name/Number": "1", "Pin Function": "CAN_TX", "Net Name": "CAN_H", "Net Type": "signal"},
                {"Pad Name/Number": "2", "Net Name": "LOCAL", "Net Type": "signal"},
            ],
        },
        "U1": {
            "general_properties": {"Value": "Controller", "Layer": "F.Cu"},
            "pins": [
                {"Pad Name/Number": "7", "Net Name": "CAN_H", "Net Type": "signal"},
                {"Pad Name/Number": "8", "Net Name": "", "Net Type": ""},
            ],
        },
    }


def test_common_nets_require_distinct_components():
    data = _data()
    data["J1"]["pins"].append({"Pad Name/Number": "3", "Net Name": "LOCAL"})
    rows = report.common_net_rows(data)
    assert rows == [{"net": "CAN_H", "endpoints": [("J1", "1"), ("U1", "7")], "component_count": 2}]


def test_report_is_self_contained_escaped_and_shows_geometry():
    html = report.render_connector_report(_data(), {"J1": Footprint()})
    assert "CAN_H" in html and "J1:1, U1:7" in html
    assert "8.00 × 4.50 mm" in html
    assert "PIN 1" in html
    assert "CAN_TX" in html
    assert "USB &lt;connector&gt;" in html
    assert "<connector>" not in html
    assert "selectNet" in html and "No net selected" in html
    assert "Footprint dimensions unavailable" in html
    assert "https://" not in html and "http://" not in html
