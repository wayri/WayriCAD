import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


graph_module = load_module(
    "kiway_mapper_graph_test",
    ROOT / "extract_pins_plugin" / "core" / "schematic_graph.py",
)
mapper_module = load_module(
    "kiway_controller_mapper_test",
    ROOT / "extract_pins_plugin" / "core" / "controller_connector_mapper.py",
)


class ControllerConnectorMapperTests(unittest.TestCase):
    def parser_for(self, components, nets):
        component_xml = "\n".join(
            f'<comp ref="{ref}"><value>{value}</value></comp>'
            for ref, value in components
        )
        net_xml = []
        for code, name, endpoints in nets:
            nodes = "\n".join(
                f'<node ref="{ref}" pin="{pin}" pinfunction="{function}"/>'
                for ref, pin, function in endpoints
            )
            net_xml.append(f'<net code="{code}" name="{name}">{nodes}</net>')
        xml = (
            "<?xml version=\"1.0\"?><export><components>"
            + component_xml
            + "</components><nets>"
            + "\n".join(net_xml)
            + "</nets></export>"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(xml)
            path = handle.name
        try:
            parser = graph_module.SchematicGraphParser(schematic_paths=[path])
            parser.build()
            return parser
        finally:
            Path(path).unlink(missing_ok=True)

    def test_series_passive_path_reports_all_pin_and_net_transitions(self):
        parser = self.parser_for(
            [("U1", "MCU"), ("R1", "33R"), ("J1", "Connector")],
            [
                ("1", "MCU_TX", [("U1", "10", "UART_TX"), ("R1", "1", "")]),
                ("2", "HARNESS_TX", [("R1", "2", ""), ("J1", "4", "TX")]),
            ],
        )
        rules = mapper_module.parse_traversal_rules(
            mapper_module.DEFAULT_PASSIVE_RULE_TEXT
        )
        mapper = mapper_module.ControllerConnectorMapper(parser)
        rows = mapper.trace(["U1"], ["J1"], rules)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("U1", row["Source Reference"])
        self.assertEqual("10", row["Source Pin"])
        self.assertEqual("J1", row["Connector Reference"])
        self.assertEqual("4", row["Connector Pin"])
        self.assertEqual("MCU_TX -> HARNESS_TX", row["Net Sequence"])
        self.assertEqual("R1.1->R1.2", row["Pin Transitions"])
        self.assertEqual("Resolved", row["Status"])
        self.assertEqual("High", row["Confidence"])

    def test_capacitor_is_not_crossed_by_safe_defaults(self):
        parser = self.parser_for(
            [("U1", "MCU"), ("C1", "100n"), ("J1", "Connector")],
            [
                ("1", "SIGNAL", [("U1", "1", "GPIO"), ("C1", "1", "")]),
                ("2", "GROUND", [("C1", "2", ""), ("J1", "1", "GND")]),
            ],
        )
        rules = mapper_module.parse_traversal_rules(
            mapper_module.DEFAULT_PASSIVE_RULE_TEXT
        )
        rows = mapper_module.ControllerConnectorMapper(parser).trace(
            ["U1"], ["J1"], rules
        )
        self.assertEqual([], rows)

    def test_mosfet_and_bjt_paths_require_conditional_opt_in(self):
        parser = self.parser_for(
            [
                ("U1", "Controller"),
                ("Q1", "MOSFET"),
                ("Q2", "NPN"),
                ("J1", "Connector"),
            ],
            [
                ("1", "DRIVE", [("U1", "1", "DRIVE"), ("Q1", "1", "D")]),
                ("2", "SWITCHED", [("Q1", "2", "S"), ("Q2", "1", "C")]),
                ("3", "OUTPUT", [("Q2", "2", "E"), ("J1", "8", "OUT")]),
                ("4", "GATE", [("Q1", "3", "G")]),
                ("5", "BASE", [("Q2", "3", "B")]),
            ],
        )
        rules = mapper_module.parse_traversal_rules(
            "Q* | D-S | active | MOSFET state must be verified\n"
            "Q* | C-E | active | BJT bias must be verified"
        )
        mapper = mapper_module.ControllerConnectorMapper(parser)
        self.assertEqual([], mapper.trace(["U1"], ["J1"], rules))

        rows = mapper.trace(
            ["U1"], ["J1"], rules, include_conditional=True
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Conditional", rows[0]["Status"])
        self.assertEqual("Q1, Q2", rows[0]["Active Devices"])
        self.assertIn("Q1.1->Q1.2", rows[0]["Pin Transitions"])
        self.assertIn("Q2.1->Q2.2", rows[0]["Pin Transitions"])
        self.assertNotIn("Q1.3", rows[0]["Ordered Path"])
        self.assertNotIn("Q2.3", rows[0]["Ordered Path"])

    def test_active_rule_fails_closed_without_matching_pin_metadata(self):
        parser = self.parser_for(
            [("U1", "Controller"), ("Q1", "MOSFET"), ("J1", "Connector")],
            [
                ("1", "A", [("U1", "1", ""), ("Q1", "1", "")]),
                ("2", "B", [("Q1", "2", ""), ("J1", "1", "")]),
            ],
        )
        rules = mapper_module.parse_traversal_rules("Q* | D-S | active | reviewed")
        rows = mapper_module.ControllerConnectorMapper(parser).trace(
            ["U1"], ["J1"], rules, include_conditional=True
        )
        self.assertEqual([], rows)

    def test_multiple_pin_pair_routes_are_marked_ambiguous(self):
        parser = self.parser_for(
            [("U1", "Controller"), ("U9", "Switch"), ("J1", "Connector")],
            [
                ("1", "IN", [("U1", "1", ""), ("U9", "1", "IN")]),
                ("2", "OUT_A", [("U9", "2", "A"), ("J1", "1", "")]),
                ("3", "OUT_B", [("U9", "3", "B"), ("J1", "1", "")]),
            ],
        )
        rules = mapper_module.parse_traversal_rules(
            "U9 | IN-A,IN-B | active | switch state is unknown"
        )
        rows = mapper_module.ControllerConnectorMapper(parser).trace(
            ["U1"], ["J1"], rules, include_conditional=True
        )
        self.assertEqual(2, len(rows))
        self.assertEqual({"Ambiguous"}, {row["Status"] for row in rows})
        self.assertEqual({"Low"}, {row["Confidence"] for row in rows})

    def test_rule_parser_rejects_wildcard_pin_pairs(self):
        with self.assertRaises(ValueError):
            mapper_module.parse_traversal_rules("Q* | *-* | active")


if __name__ == "__main__":
    unittest.main()
