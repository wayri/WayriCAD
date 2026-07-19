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


if __name__ == "__main__":
    unittest.main()
