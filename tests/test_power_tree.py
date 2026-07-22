from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from extract_pins_plugin.core.data_extractor import DataExtractor
from extract_pins_plugin.core.power_tree import PowerTreeAnalyzer, generate_power_tree_svg
from extract_pins_plugin.core.signal_flow import SignalFlowAnalyzer


class FakeNet:
    def __init__(self, name, code):
        self.name = name
        self.code = code

    def GetNetname(self):
        return self.name

    def GetNetCode(self):
        return self.code


class FakePad:
    def __init__(self, number, net, function=""):
        self.number = number
        self.net = net
        self.function = function

    def GetNet(self):
        return self.net

    def GetNetCode(self):
        return self.net.code

    def GetPadName(self):
        return self.number

    def GetPinFunction(self):
        return self.function

    def GetName(self):
        return self.function


class FakeField:
    def __init__(self, name, text):
        self.name = name
        self.text = text

    def GetName(self):
        return self.name

    def GetText(self):
        return self.text


class FakeFootprint:
    def __init__(self, reference, value, pads, description=""):
        self.reference = reference
        self.value = value
        self.pads = pads
        self.description = description

    def GetReference(self):
        return self.reference

    def GetValue(self):
        return self.value

    def Pads(self):
        return self.pads

    def GetFields(self):
        return [FakeField("Description", self.description)]

    def GetFPID(self):
        return "Package_Test:Fake"

    def GetLayerName(self):
        return "F.Cu"


class FakeBoard:
    def __init__(self, footprints):
        self.footprints = footprints

    def GetFootprints(self):
        return self.footprints


def make_board():
    rail_48 = FakeNet("48VDC", 1)
    switch = FakeNet("SW_NODE", 2)
    rail_3v3 = FakeNet("3V3", 3)
    return FakeBoard(
        [
            FakeFootprint("J1", "Power Input", [FakePad("1", rail_48)]),
            FakeFootprint(
                "U1",
                "TPS5430",
                [FakePad("1", rail_48, "VIN"), FakePad("2", switch, "SW")],
                "Buck step-down regulator",
            ),
            FakeFootprint("L1", "10uH", [FakePad("1", switch), FakePad("2", rail_3v3)], "Power filter inductor"),
            FakeFootprint("U2", "MCU", [FakePad("8", rail_3v3, "VDD")]),
        ]
    )


class PowerTreeTests(unittest.TestCase):
    def test_user_signal_override_beats_default_voltage_patterns(self):
        extractor = DataExtractor(make_board())
        self.assertEqual(extractor.classify_net("48VDC"), "supply")
        extractor.configure_net_patterns(
            power_net_patterns=["VDD*"],
            supply_net_patterns=["VDD*"],
            signal_net_patterns=["48V*"],
        )
        self.assertEqual(extractor.classify_net("48VDC"), "signal")
        self.assertEqual(DataExtractor.convert_wildcard_to_regex("PWR_?"), "PWR_.")

    def test_power_tree_follows_buck_and_filter_to_load_rail(self):
        result = PowerTreeAnalyzer(DataExtractor(make_board())).analyze()
        routes = {
            (row["Source Net"], row["Component"], row["Destination Net"])
            for row in result["edges"]
        }
        self.assertIn(("48VDC", "U1", "SW_NODE"), routes)
        self.assertIn(("SW_NODE", "L1", "3V3"), routes)
        self.assertIn("48VDC", result["roots"])
        rail_3v3 = next(row for row in result["nodes"] if row["Net"] == "3V3")
        self.assertIn("U2", rail_3v3["Loads"])
        svg = generate_power_tree_svg(result)
        self.assertEqual(ET.fromstring(svg).tag, "{http://www.w3.org/2000/svg}svg")

    def test_signal_flow_consolidates_repeated_pad_routes(self):
        rail = FakeNet("48VDC", 1)
        board = FakeBoard(
            [
                FakeFootprint("J1", "Input", [FakePad("1", rail), FakePad("2", rail)]),
                FakeFootprint("U1", "Buck", [FakePad("3", rail), FakePad("4", rail)]),
            ]
        )
        analyzer = SignalFlowAnalyzer(DataExtractor(board))
        rows = analyzer.summarize_source_destination_table(
            ["J1"], ["U1"], include_power=True
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Source Pin"], "1, 2")
        self.assertEqual(rows[0]["Destination Pin"], "3, 4")
        self.assertEqual(rows[0]["Connection Count"], 4)


if __name__ == "__main__":
    unittest.main()
