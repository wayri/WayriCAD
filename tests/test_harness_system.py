from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from harness_workbench_plugin.analysis import (
    HarnessBundle, HarnessSplice, PinRecord, VirtualLoad, apply_bundle,
    apply_splice, connector_correspondence, harness_bom, load_pin_documents,
    net_map_rows, parse_connector_rules, pin_map_rows, universal_harness_svg,
    virtual_load_records,
)


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


if __name__ == "__main__":
    unittest.main()
