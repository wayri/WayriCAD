import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "extract_pins_plugin"
    / "core"
    / "schematic_graph.py"
)
SPEC = importlib.util.spec_from_file_location("kiway_schematic_graph_test", MODULE_PATH)
schematic_graph = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = schematic_graph
SPEC.loader.exec_module(schematic_graph)


class SheetInformationTests(unittest.TestCase):
    def test_native_sheet_path_and_user_alias_are_preserved(self):
        xml = """<?xml version="1.0"?>
<export>
  <components>
    <comp ref="U1">
      <value>MCU</value>
      <sheetpath names="/Control/Processor/" tstamps="/a/b/"/>
    </comp>
  </components>
  <nets>
    <net code="1" name="DEMO_CTRL_DEMO_SENSOR_SPI1_CLK_TD">
      <node ref="U1" pin="1" pinfunction="SPI_CLK"/>
    </net>
  </nets>
</export>
"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(xml)
            path = handle.name
        try:
            parser = schematic_graph.SchematicGraphParser(
                schematic_paths=[path],
                board_sequence=["DEMO_CTRL", "DEMO_SENSOR"],
                sheet_definitions=[
                    {
                        "name": "Main Controller",
                        "path_pattern": "/Control/*",
                        "reference_pattern": "U*",
                    }
                ],
            )
            parser.build()
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(
            parser.get_component_sheet("U1"),
            {"name": "Main Controller", "path": "/Control/Processor/"},
        )
        self.assertEqual(parser.components["U1"]["sheet_tstamps"], "/a/b/")
        self.assertEqual(parser.sheet_summary()[0]["Components"], 1)

    def test_reference_only_rule_supports_board_only_components(self):
        parser = schematic_graph.SchematicGraphParser(
            sheet_definitions=[
                schematic_graph.SheetDefinition("Connectors", "*", "J*")
            ]
        )
        self.assertEqual(
            parser.resolve_sheet("J4"),
            {"name": "Connectors", "path": "/"},
        )

    def test_wildcard_label_trace_resolves_endpoint_pins_through_series_part(self):
        xml = """<?xml version="1.0"?>
<export>
  <components>
    <comp ref="J1"><value>Harness</value></comp>
    <comp ref="R1"><value>1k</value></comp>
    <comp ref="U1"><value>MCU</value></comp>
    <comp ref="U2"><value>Unrelated</value></comp>
  </components>
  <nets>
    <net code="1" name="CABIN_TEMP_TM">
      <node ref="J1" pin="7" pinfunction="TEMP_OUT"/>
      <node ref="R1" pin="1"/>
    </net>
    <net code="2" name="ADC_TEMP_SENSE">
      <node ref="R1" pin="2"/>
      <node ref="U1" pin="42" pinfunction="ADC3_IN7"/>
    </net>
    <net code="3" name="OTHER_TM_INTERNAL">
      <node ref="U2" pin="1"/>
    </net>
  </nets>
</export>
"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(xml)
            path = handle.name
        try:
            parser = schematic_graph.SchematicGraphParser(schematic_paths=[path])
            parser.build()
            rows = parser.trace_matching_nets(
                ["*TM"],
                ["J1", "U1"],
                pass_through_patterns=["R*"],
            )
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(2, len(rows))
        endpoints = {(row["Endpoint Reference"], row["Endpoint Pin"]): row for row in rows}
        self.assertIn(("J1", "7"), endpoints)
        self.assertIn(("U1", "42"), endpoints)
        u1 = endpoints[("U1", "42")]
        self.assertEqual("ADC3_IN7", u1["Pin Function"])
        self.assertEqual("ADC_TEMP_SENSE", u1["Terminal Net"])
        self.assertEqual("R1", u1["Intermediate Components"])
        self.assertIn("R1.1", u1["Path"])
        self.assertIn("R1.2", u1["Path"])
        self.assertNotIn("U2", {row["Endpoint Reference"] for row in rows})


if __name__ == "__main__":
    unittest.main()
