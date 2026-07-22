from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from extract_pins_plugin.core.diagram_generator import SVGDiagramGenerator


class DiagramTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            {
                "Source Reference": "J1", "Source Value": "INPUT", "Source Pin": "1",
                "Destination Reference": "U1", "Destination Value": "MCU", "Destination Pin": "3",
                "Net Name": "48VDC", "Net Type": "supply", "Is Power Net": "Yes",
            },
            {
                "Source Reference": "J1", "Source Value": "INPUT", "Source Pin": "2",
                "Destination Reference": "U1", "Destination Value": "MCU", "Destination Pin": "4",
                "Net Name": "SPI_CLK", "Net Type": "signal", "Is Power Net": "No",
            },
            {
                "Source Reference": "J1", "Source Value": "INPUT", "Source Pin": "3",
                "Destination Reference": "U1", "Destination Value": "MCU", "Destination Pin": "5",
                "Net Name": "GND", "Net Type": "ground", "Is Power Net": "Yes",
            },
            # Duplicate pad-to-pad row must not duplicate a component card or net lane.
            {
                "Source Reference": "J1", "Source Value": "INPUT", "Source Pin": "1",
                "Destination Reference": "U1", "Destination Value": "MCU", "Destination Pin": "6",
                "Net Name": "48VDC", "Net Type": "supply", "Is Power Net": "Yes",
            },
        ]

    def test_topology_has_one_component_card_and_one_lane_per_net(self) -> None:
        svg = SVGDiagramGenerator().generate_signal_flow_diagram(self.rows)
        ET.fromstring(svg)
        self.assertEqual(2, svg.count('class="component"'))
        self.assertEqual(3, svg.count('class="net-row"'))
        self.assertNotIn(">Sources<", svg)
        self.assertNotIn(">Destinations<", svg)
        self.assertIn('data-net="48VDC"', svg)
        self.assertIn('data-net="SPI_CLK"', svg)
        self.assertIn('data-net="GND"', svg)

    def test_topology_uses_distinct_net_class_colors(self) -> None:
        generator = SVGDiagramGenerator()
        svg = generator.generate_signal_flow_diagram(self.rows)
        self.assertIn(generator.styles["signal_line"], svg)
        self.assertIn(generator.styles["power_line"], svg)
        self.assertIn(generator.styles["ground_line"], svg)


if __name__ == "__main__":
    unittest.main()
