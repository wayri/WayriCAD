from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from portable_web_export_plugin.exporter import (
    ExportSelection,
    build_export,
    scan_project,
    write_export_document,
)
from portable_web_export_plugin.cli import main as cli_main


BOARD = '''(kicad_pcb (version 20240108) (generator pcbnew)
  (uuid 11111111-1111-1111-1111-111111111111)
  (footprint "Package_QFP:LQFP-48" (layer "F.Cu")
    (uuid 22222222-2222-2222-2222-222222222222)
    (property "Reference" "U1") (property "Value" "MCU")
    (model "${KIPRJMOD}/models/demo.wrl")))
'''
SCHEMATIC = '''(kicad_sch (version 20231120) (generator eeschema)
  (uuid aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa)
  (symbol (lib_id "MCU:Demo") (uuid bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb)
    (property "Reference" "U1") (property "Value" "MCU")))
'''


class PortableExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "demo.kicad_pcb").write_text(BOARD, encoding="utf-8")
        (self.root / "demo.kicad_sch").write_text(SCHEMATIC, encoding="utf-8")
        (self.root / "models").mkdir()
        (self.root / "models" / "demo.wrl").write_text("#VRML V2.0 utf8\n", encoding="utf-8")
        self.package = self.root / "plugin"
        vendor = self.package / "vendor" / "kicad-webview"
        vendor.mkdir(parents=True)
        (vendor / "kicad-webview.min.js").write_text(
            "window.KiCadWebView={Viewer:class{loadFiles(){return Promise.resolve()} addEventListener(){} setView(){return Promise.resolve()} dispose(){}}};",
            encoding="utf-8",
        )
        (vendor / "LICENSE").write_text("MPL-2.0", encoding="utf-8")
        (vendor / "THIRD-PARTY-NOTICES.md").write_text("notices", encoding="utf-8")
        files = []
        for name in ("kicad-webview.min.js", "LICENSE", "THIRD-PARTY-NOTICES.md"):
            data = (vendor / name).read_bytes()
            import hashlib
            files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        (vendor / "RELEASE.json").write_text(json.dumps({"version": "0.1.0-beta.2", "files": files}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_preserves_saved_component_identities_and_models(self):
        scan = scan_project(self.root / "demo.kicad_pcb")
        self.assertEqual(["U1"], [item.reference for item in scan.components])
        self.assertEqual("22222222-2222-2222-2222-222222222222", scan.components[0].stable_id)
        self.assertEqual(("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",), scan.components[0].schematic_uuids)
        self.assertTrue(scan.models[0].supported)

    def test_export_is_offline_revision_scoped_and_contains_tracking(self):
        scan = scan_project(self.root / "demo.kicad_pcb")
        document, manifest = build_export(
            scan,
            ExportSelection(
                schematic_paths=tuple(scan.schematics),
                model_sources=tuple(model.source for model in scan.models if model.supported),
            ),
            self.package,
        )
        self.assertIn("connect-src 'none'", document)
        self.assertIn("Apply group", document)
        self.assertIn("Export progress JSON", document)
        self.assertIn("Allow explicit revision migration", document)
        self.assertIn('id="wayricad-export-metadata"', document)
        metadata_match = re.search(
            r'<script type="application/json" id="wayricad-export-metadata">(.*?)</script>',
            document,
        )
        self.assertIsNotNone(metadata_match)
        self.assertEqual(manifest, json.loads(metadata_match.group(1)))
        self.assertIn(f'<meta name="wayricad-document-id" content="{manifest["documentId"]}">', document)
        self.assertIn(manifest["documentId"], document)
        self.assertIn(manifest["generatedAt"], document)
        self.assertEqual(64, len(manifest["sourceFiles"][0]["sha256"]))
        self.assertIn(manifest["projectId"], manifest["storageKey"])
        self.assertIn(manifest["revisionId"], manifest["storageKey"])
        self.assertIn("models/", document)

    def test_different_board_bytes_produce_a_different_revision(self):
        scan = scan_project(self.root / "demo.kicad_pcb")
        selection = ExportSelection(schematic_paths=tuple(scan.schematics))
        _, first = build_export(scan, selection, self.package)
        (self.root / "demo.kicad_pcb").write_text(BOARD + "\n", encoding="utf-8")
        changed = scan_project(self.root / "demo.kicad_pcb")
        _, second = build_export(changed, selection, self.package)
        self.assertNotEqual(first["revisionId"], second["revisionId"])

    def test_reviewed_document_is_written_without_regeneration(self):
        scan = scan_project(self.root / "demo.kicad_pcb")
        document, manifest = build_export(
            scan,
            ExportSelection(schematic_paths=tuple(scan.schematics)),
            self.package,
        )
        destination = self.root / "review.html"
        write_export_document(document, destination)
        written = destination.read_text(encoding="utf-8")
        self.assertEqual(document, written)
        self.assertIn(manifest["documentId"], written)

    def test_cli_exports_saved_project_and_manifest(self):
        output = self.root / "cli-review.html"
        manifest = self.root / "cli-review.json"
        self.assertEqual(0, cli_main([
            str(self.root / "demo.kicad_pcb"), str(output),
            "--no-3d", "--manifest", str(manifest),
        ]))
        self.assertTrue(output.is_file())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual("WayriCAD Portable Web Export 0.1.0", payload["exporter"])


if __name__ == "__main__":
    unittest.main()
