from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from harness_workbench_plugin.analysis import (
    BoardSignalPath, HarnessBundle, HarnessLink, HarnessSplice, PinMapRow, PinRecord,
    VirtualLoad, apply_bundle, apply_splice, build_system_signal_paths,
    connector_correspondence, harness_bom, load_pin_documents, load_signal_path_csv,
    links_from_pin_map, load_pin_map_csv, net_map_rows, parse_connector_rules,
    pin_map_rows, system_signal_rows, universal_harness_svg, validate_pin_map,
    virtual_load_records,
)
from harness_workbench_plugin.report import interactive_harness_html


class HarnessSystemTests(unittest.TestCase):
    def test_ingests_fifty_projects_and_rejects_fifty_one(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); paths = []
            for index in range(51):
                path = root / f"board_{index:02d}.csv"; paths.append(path)
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=("project", "connector", "pin", "net"))
                    writer.writeheader(); writer.writerow({"project": f"DEMO_{index:02d}", "connector": "J1", "pin": "1", "net": "SIG"})
            self.assertEqual(50, len(load_pin_documents(paths[:50])))
            with self.assertRaisesRegex(ValueError, "limit is 50"):
                load_pin_documents(paths)

    def test_connector_rules_support_identity_offset_and_explicit_maps(self):
        records = [
            PinRecord("DEMO_A", "J1", "1", "A1"), PinRecord("DEMO_A", "J1", "2", "A2"),
            PinRecord("DEMO_B", "J2", "1", "B1"), PinRecord("DEMO_B", "J2", "2", "B2"),
            PinRecord("DEMO_C", "J3", "3", "C3"), PinRecord("DEMO_C", "J3", "4", "C4"),
        ]
        identity = connector_correspondence(records, parse_connector_rules("DEMO_A:J1 -> DEMO_B:J2"))
        self.assertEqual([("1", "1"), ("2", "2")],
                         [(link.source.pin, link.destination.pin) for link in identity])
        mapped = connector_correspondence(
            records, parse_connector_rules("DEMO_A:J1 -> DEMO_C:J3 [map=1:4,2:3]"))
        self.assertEqual([("1", "4"), ("2", "3")],
                         [(link.source.pin, link.destination.pin) for link in mapped])
        offset = connector_correspondence(
            records, parse_connector_rules("DEMO_A:J1 -> DEMO_C:J3 [offset=2]"))
        self.assertEqual([("1", "3"), ("2", "4")],
                         [(link.source.pin, link.destination.pin) for link in offset])

    def test_virtual_load_bundle_splice_maps_bom_and_svg(self):
        source = PinRecord("DEMO_CTRL", "J1", "1", "MOTOR_POS",
                           connector_part="CONN-A", contact_part="CONTACT-A")
        load = virtual_load_records([VirtualLoad("LOADS", "MOTOR_A", "1", "MOTOR_POS",
                                                 current_a=3.5, connector_part="LOAD-CONN")])[0]
        links = connector_correspondence(
            [source, load], parse_connector_rules("DEMO_CTRL:J1 -> LOADS:MOTOR_A"))
        bundle = HarnessBundle("MOTOR", [links[0].wire_id], "18", "Overall shield",
                               "Braided sleeve", 2.0, 15)
        splice = HarnessSplice("S01", [links[0].wire_id], part_number="SPLICE-01")
        apply_bundle(links, bundle); apply_splice(links, splice)
        self.assertEqual("MOTOR", links[0].bundle); self.assertEqual("S01", links[0].splice)
        self.assertEqual("MOTOR", pin_map_rows(links)[0]["Bundle"])
        self.assertEqual("3.500", net_map_rows(links)[0]["Loads (A)"])
        bom = harness_bom([source, load], links, [bundle], [splice])
        self.assertTrue(any(row["Category"] == "Wire" and row["Description"].startswith("AWG 18") for row in bom))
        self.assertTrue(any(row["Part Number"] == "SPLICE-01" for row in bom))
        svg = universal_harness_svg(links)
        self.assertEqual(1, svg.count(">J1</text>")); self.assertEqual(1, svg.count(">MOTOR_A</text>"))
        self.assertIn("MOTOR_POS", svg)

    def test_explicit_table_mapping_supports_non_corresponding_and_one_to_many_pins(self):
        records = [
            PinRecord("DEMO_CTRL", "J1", "1", "UART_TX"),
            PinRecord("DEMO_IO", "J7", "8", "RX_A"),
            PinRecord("DEMO_IO", "J7", "12", "RX_B"),
        ]
        rows = [
            PinMapRow("DEMO_CTRL", "J1", "1", "DEMO_IO", "J7", "8", bundle="DATA"),
            PinMapRow("DEMO_CTRL", "J1", "1", "DEMO_IO", "J7", "12", splice="S01"),
        ]
        links = links_from_pin_map(records, rows)
        self.assertEqual(["8", "12"], [link.destination.pin for link in links])
        self.assertTrue(all(link.status == "linked" for link in links))
        self.assertTrue(any("splice" in issue.lower() for issue in validate_pin_map(records, rows)))

    def test_mapping_csv_round_trip_input_columns(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "mapping.csv"
            path.write_text(
                "source_project,source_connector,source_pin,destination_project,destination_connector,destination_pin,awg,length_m\n"
                "DEMO_A,J1,A1,DEMO_B,J2,17,26,1.75\n",
                encoding="utf-8",
            )
            rows = load_pin_map_csv(path)
        self.assertEqual("A1", rows[0].source_pin)
        self.assertEqual("17", rows[0].destination_pin)
        self.assertEqual("26", rows[0].gauge_awg)
        self.assertEqual(1.75, rows[0].length_m)

    def test_end_to_end_ic_path_preserves_series_components_and_reverses_destination(self):
        link = HarnessLink(
            PinRecord("DEMO_CTRL", "J1", "3", "UART3_TX"),
            PinRecord("DEMO_SENSOR", "J2", "8", "UART_RX"),
            "W00003", bundle="DATA-A",
        )
        paths = [
            BoardSignalPath(
                "DEMO_CTRL", "U1", "STM32 controller", "21", "USART3_TX", "UART3_TX_RAW",
                "J1", "3", "UART3_TX", "UART3_TX_RAW -> UART3_TX", "R12",
                "R12.1->R12.2", ordered_path="U1.21 -> [UART3_TX_RAW] -> R12.1 -> R12.2 -> [UART3_TX] -> J1.3",
            ),
            BoardSignalPath(
                "DEMO_SENSOR", "U3", "UART peripheral", "5", "UART_RX", "UART_RX_LOCAL",
                "J2", "8", "UART_RX", "UART_RX_LOCAL -> UART_RX", "R7",
                "R7.1->R7.2", status="Conditional", confidence="Conditional",
                ordered_path="U3.5 -> [UART_RX_LOCAL] -> R7.1 -> R7.2 -> [UART_RX] -> J2.8",
            ),
        ]
        result = build_system_signal_paths([link], paths, "U1", "U3")
        self.assertEqual(1, len(result))
        row = result[0]
        self.assertEqual("UART", row.protocol)
        self.assertEqual("Conditional", row.status)
        self.assertIn("DEMO_CTRL: R12", row.inline_components)
        self.assertIn("DEMO_SENSOR: R7", row.inline_components)
        self.assertLess(row.ordered_path.index("J2.8"), row.ordered_path.index("U3.5"))
        self.assertEqual("DATA-A", system_signal_rows(result)[0]["Bundle"])

    def test_endpoint_wildcards_do_not_reintroduce_filtered_paths_as_partial(self):
        link = HarnessLink(PinRecord("DEMO_A", "J1", "1", "SIG"),
                           PinRecord("DEMO_B", "J2", "1", "SIG"), "W00001")
        paths = [
            BoardSignalPath("DEMO_A", "U1", "Controller", "1", "TX", "SIG",
                            "J1", "1", "SIG"),
            BoardSignalPath("DEMO_B", "U2", "Peripheral", "2", "RX", "SIG",
                            "J2", "1", "SIG"),
        ]
        self.assertEqual([], build_system_signal_paths(
            [link], paths, source_patterns="MCU*", destination_patterns="U*", include_partial=True))

    def test_controller_map_csv_loader_and_interactive_html(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "DEMO_CTRL.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "Source Reference", "Source Value", "Source Pin", "Source Pin Function", "Source Net",
                    "Connector Reference", "Connector Pin", "Connector Net", "Net Sequence",
                    "Inline Components", "Pin Transitions", "Status", "Confidence", "Ordered Path"))
                writer.writeheader(); writer.writerow({
                    "Source Reference": "U1", "Source Value": "Controller", "Source Pin": "9",
                    "Source Pin Function": "SPI3_SCK", "Source Net": "SPI_RAW", "Connector Reference": "J1",
                    "Connector Pin": "4", "Connector Net": "SPI_CLK", "Net Sequence": "SPI_RAW -> SPI_CLK",
                    "Inline Components": "R4", "Pin Transitions": "R4.1->R4.2", "Status": "Resolved",
                    "Confidence": "High", "Ordered Path": "U1.9 -> [SPI_RAW] -> R4.1 -> R4.2 -> [SPI_CLK] -> J1.4"})
            loaded = load_signal_path_csv(path)
        self.assertEqual("DEMO_CTRL", loaded[0].project)
        self.assertEqual("R4", loaded[0].inline_components)
        link = HarnessLink(PinRecord("DEMO_CTRL", "J1", "4", "SPI_CLK"),
                           PinRecord("DEMO_IO", "J2", "7", "SPI_CLK"), "W00004", bundle="SPI-BUS")
        systems = build_system_signal_paths([link], loaded, include_partial=True)
        html = interactive_harness_html([link.source, link.destination], [link],
                                        [HarnessBundle("SPI-BUS", ["W00004"])], system_paths=systems)
        self.assertIn("KiWay Interactive Harness", html)
        self.assertIn("wheel", html)
        self.assertIn("drag nodes", html)
        self.assertIn("SPI-BUS", html)
        self.assertIn("Harness BoM", html)
        self.assertIn("Sort this column", html)
        self.assertNotIn("https://", html)


if __name__ == "__main__":
    unittest.main()
