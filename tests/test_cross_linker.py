import importlib.util
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "extract_pins_plugin"
    / "core"
    / "cross_linker.py"
)
SPEC = importlib.util.spec_from_file_location("kiway_cross_linker_test", MODULE_PATH)
cross_linker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cross_linker
SPEC.loader.exec_module(cross_linker)


class CrossProjectLinkerTests(unittest.TestCase):
    def setUp(self):
        self.importer = cross_linker.PinDocumentImporter()

    def _document(self, project, net, reference="J1", pin="1"):
        endpoints = self.importer.endpoints_from_rows(
            [{"Reference": reference, "Pin": pin, "Net Name": net}],
            project,
            f"{project}.csv",
        )
        return cross_linker.ImportedPinDocument(project, f"{project}.csv", endpoints)

    def test_exact_net_names_link_across_projects(self):
        linker = cross_linker.CrossProjectLinker(
            [self._document("DEMO_CTRL", "SPI1_CLK"), self._document("DEMO_SENSOR", "SPI1_CLK", "J2")]
        )
        links = linker.link()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["Match Method"], "Exact")
        self.assertEqual(links[0]["Confidence"], "High")

    def test_wildcard_capture_links_different_board_prefixes(self):
        rule = cross_linker.LinkRule("Board prefix", "wildcard", "DEMO_CTRL_*", "DEMO_SENSOR_*")
        linker = cross_linker.CrossProjectLinker(
            [
                self._document("DEMO_CTRL", "DEMO_CTRL_SPI1_CLK"),
                self._document("DEMO_SENSOR", "DEMO_SENSOR_SPI1_CLK", "J2"),
            ]
        )
        links = linker.link([rule], exact_match=False, normalized_match=False)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["Signal Key"], "SPI1_CLK")
        self.assertEqual(links[0]["Rule"], "Board prefix")

    def test_regex_named_capture_links_labels(self):
        rules = cross_linker.parse_link_rules(
            r"Harness | regex | ^SRC_(?P<signal>.+)$ | ^DST_(?P<signal>.+)$"
        )
        linker = cross_linker.CrossProjectLinker(
            [self._document("A", "SRC_CAN_RX"), self._document("B", "DST_CAN_RX", "J8")]
        )
        links = linker.link(rules, exact_match=False, normalized_match=False)
        self.assertEqual(links[0]["Signal Key"], "CAN_RX")
        self.assertEqual(links[0]["Match Method"], "Regex")

    def test_regex_rule_supports_alternation_with_double_pipe_delimiter(self):
        rules = cross_linker.parse_link_rules(
            r"Harness || regex || ^(?:SRC|SOURCE)_(?P<signal>.+)$ || ^DST_(?P<signal>.+)$"
        )
        linker = cross_linker.CrossProjectLinker(
            [self._document("A", "SOURCE_CAN_TX"), self._document("B", "DST_CAN_TX", "J9")]
        )
        links = linker.link(rules, exact_match=False, normalized_match=False)
        self.assertEqual(links[0]["Signal Key"], "CAN_TX")

    def test_one_to_many_links_are_marked_ambiguous(self):
        linker = cross_linker.CrossProjectLinker(
            [
                self._document("A", "RESET"),
                self._document("B", "RESET", "J2"),
                self._document("C", "RESET", "J3"),
            ]
        )
        links = linker.link()
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link["Status"] == "Ambiguous" for link in links))

    def test_power_links_are_opt_in(self):
        linker = cross_linker.CrossProjectLinker(
            [self._document("A", "GND"), self._document("B", "GND", "J2")]
        )
        self.assertEqual(linker.link(), [])
        self.assertEqual(linker.unmatched([]), [])
        self.assertEqual(len(linker.link(include_power=True)), 1)

    def test_csv_and_markdown_imports_are_normalized(self):
        csv_text = "Connector,Pin,Net Name,Sheet\nJ1,4,CAN_H,Interfaces\n"
        markdown_text = (
            "| TP Reference | TP Pin | Net Name | TP Sheet |\n"
            "|---|---|---|---|\n"
            "| TP1 | 1 | CAN_H | Debug |\n"
        )
        paths = []
        try:
            for suffix, content in ((".csv", csv_text), (".md", markdown_text)):
                with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
                    handle.write(content)
                    paths.append(handle.name)
            csv_doc = self.importer.load(paths[0], "Board A")
            md_doc = self.importer.load(paths[1], "Board B")
        finally:
            for path in paths:
                Path(path).unlink(missing_ok=True)
        self.assertEqual(csv_doc.endpoints[0].reference, "J1")
        self.assertEqual(md_doc.endpoints[0].reference, "TP1")
        linker = cross_linker.CrossProjectLinker([csv_doc, md_doc])
        links = linker.link()
        self.assertEqual(len(links), 1)
        svg = linker.harness_svg(links)
        self.assertEqual(ET.fromstring(svg).tag, "{http://www.w3.org/2000/svg}svg")


if __name__ == "__main__":
    unittest.main()
