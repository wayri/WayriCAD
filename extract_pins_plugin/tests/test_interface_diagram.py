"""Selected-pin map behavior and HTML/SVG safety checks."""

import re
import unittest

from extract_pins_plugin.core.interface_diagram import (
    interface_net_rows, render_interface_html, render_interface_svg,
)


def component(value, *pins):
    return {"general_properties": {"Value": value}, "pins": [
        {"Pad Name/Number": pad, "Net Name": net, "Pin Function": function}
        for pad, net, function in pins
    ]}


class InterfaceDiagramTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "U1": component("MCU", ("1", "CAN_TX", "GPIO2"), ("2", "CAN_RX", "GPIO3"),
                            ("3", "SHARED", "GPIO4"), ("4", "", "GPIO5")),
            "J1": component("Conn", ("A1", "CAN_TX", "TX"), ("A2", "CAN_RX", "RX"),
                            ("A3", "SHARED", "SIG")),
            "U2": component("PHY", ("7", "SHARED", "IN")),
        }

    def test_exact_selected_connections_and_fanout(self):
        rows = interface_net_rows(self.data)
        by_net = {r["net"]: r for r in rows}
        self.assertEqual([(p["reference"], p["pad"]) for p in by_net["CAN_TX"]["endpoints"]],
                         [("J1", "A1"), ("U1", "1")])
        self.assertEqual(len(by_net["SHARED"]["endpoints"]), 3)
        self.assertNotIn("", by_net)
        self.assertEqual(by_net["CAN_TX"]["protocol"], "CAN")
        svg = render_interface_svg(self.data)
        self.assertEqual(svg.count('class="net-row"'), 3)
        self.assertIn('data-net="SHARED"', svg)
        self.assertIn('<rect x=', svg)
        self.assertIn('M460,161', svg)  # U1's CAN_TX connects at the left edge toward J1.
        self.assertIn('fill="#111923"', svg)  # KiCad's native SVG renderer ignores CSS fills.

    def test_selected_scope_and_missing_nets(self):
        only = {"U1": self.data["U1"]}
        svg = render_interface_svg(only)
        self.assertNotIn('class="net-row"', svg)
        html = render_interface_html(only)
        self.assertIn("one selected endpoint", html)
        self.assertIn("additional endpoints exist outside the selection", html)
        with self.assertRaises(ValueError):
            render_interface_svg(only, center_ref="U9")

    def test_explicit_protocol_override_and_determinism(self):
        override = {"CAN_*": "Vehicle bus"}
        rows = interface_net_rows(self.data, protocol_overrides=override)
        self.assertEqual([(r["net"], r["protocol"], r["protocol_inferred"]) for r in rows if r["net"].startswith("CAN")],
                         [("CAN_RX", "Vehicle bus", False), ("CAN_TX", "Vehicle bus", False)])
        result = render_interface_html(self.data, protocol_overrides=override, center_ref="U1")
        self.assertEqual(result, render_interface_html(dict(reversed(list(self.data.items()))),
                                                       protocol_overrides=override, center_ref="U1"))
        self.assertIn('data-protocol="Vehicle bus"', result)

    def test_escaping_dangerous_values(self):
        data = {"U<1": component('<img src=x onerror=alert(1)>',
                                  ('1" onclick="bad()', 'N<&"', '<script>alert(1)</script>')),
                "J2": component("socket", ("2", 'N<&"', "pin"))}
        html = render_interface_html(data, title='"<script>x</script>')
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('onclick="bad()', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('N&lt;&amp;&quot;', html)
        self.assertIn('data-net="N&lt;&amp;&quot;"', html)
        self.assertEqual(len(re.findall(r'<script>', html)), 1)

    def test_repeated_pad_numbers_preserve_rows(self):
        data = {"U1": component("IC", ("1", "A", ""), ("1", "A", "")),
                "J1": component("Conn", ("1", "A", ""))}
        svg = render_interface_svg(data)
        self.assertEqual(svg.count('data-pad="1"'), 3)
        self.assertEqual(len(interface_net_rows(data)[0]["endpoints"]), 3)


if __name__ == "__main__":
    unittest.main()
