from __future__ import annotations

import json
import re
import tempfile
import unittest
import hashlib
import base64
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

from portable_web_export_plugin.exporter import (
    ExportSelection,
    build_export,
    scan_project,
    write_export_document,
    assert_scan_current,
    VIEWER_VERSION, VIEWER_ARCHIVE_SHA256,
    load_viewer_assets, _render_html,
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
        for name in ("LICENSING.md", "THREE-LICENSE", "FZSTD-LICENSE",
                     "SPIKE-ENGINE-NOTICE.md", "SOURCE-PROVENANCE.json",
                     "licenses/Pocket-KiView-Source-Available-1.0.txt"):
            path = vendor/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Test legal notice', encoding='utf-8')
        files = []
        for path in sorted(vendor.rglob('*')):
            if not path.is_file():
                continue
            name = path.relative_to(vendor).as_posix()
            data = (vendor / name).read_bytes()
            import hashlib
            files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        (vendor / "PINNED-DISTRIBUTION.json").write_text(json.dumps({
            "kind": "wayricad-integration-pin", "version": VIEWER_VERSION,
            "upstreamArchiveSHA256": VIEWER_ARCHIVE_SHA256, "files": files}), encoding="utf-8")

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
        metadata = json.loads((Path(__file__).parents[1] / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "WayriCAD Portable Web Export " + metadata["versions"][0]["version"],
            payload["exporter"],
        )

    def test_cli_rejects_manifest_model_alias_before_writing_html(self):
        import contextlib
        import io
        output = self.root/'not-created.html'
        model = self.root/'models/demo.wrl'
        original = model.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli_main([str(self.root/'demo.kicad_pcb'), str(output), '--manifest', str(model)])
        self.assertEqual(error.exception.code,2)
        self.assertFalse(output.exists())
        self.assertEqual(model.read_bytes(),original)

    def test_original_and_bundled_board_hashes_are_not_conflated(self):
        board = self.root/'demo.kicad_pcb'
        original = board.read_bytes()
        scan = scan_project(board)
        document, manifest = build_export(scan, ExportSelection(
            schematic_paths=tuple(scan.schematics),
            model_sources=tuple(model.source for model in scan.models)), self.package)
        record = next(row for row in manifest['sourceFiles'] if row['path'] == board.name)
        self.assertEqual(record['sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(record['transformed'])
        self.assertNotEqual(record['sha256'], record['bundledSha256'])
        payload = json.loads(re.search(r'const BUNDLED=(.*?);\n', document).group(1))
        bundled = base64.b64decode(next(row['base64'] for row in payload if row['path'] == board.name))
        self.assertEqual(record['bundledSha256'], hashlib.sha256(bundled).hexdigest())
        self.assertEqual(board.read_bytes(), original)
        self.assertEqual(record['bytes'], len(original))
        self.assertEqual(record['bundledBytes'], len(bundled))

    def test_stale_board_sheet_and_model_require_rescan(self):
        for name in ('demo.kicad_pcb','demo.kicad_sch','models/demo.wrl'):
            with self.subTest(name=name):
                scan = scan_project(self.root/'demo.kicad_pcb')
                source = self.root/name
                original = source.read_bytes()
                source.write_bytes(original+b'\n')
                with self.assertRaisesRegex(ValueError,'changed since scan'):
                    build_export(scan, ExportSelection(schematic_paths=tuple(scan.schematics)), self.package)
                with self.assertRaises(ValueError):
                    assert_scan_current(scan)
                source.write_bytes(original)

    def test_atomic_unique_temporary_preserves_exact_bytes_and_other_writers(self):
        destination = self.root/'review.html'
        preexisting = self.root/'review.html.tmp'
        preexisting.write_bytes(b'other owner')
        documents = ['<!doctype html>\r\n'+str(index)*2000 for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(lambda text: write_export_document(text,destination),documents))
        self.assertIn(destination.read_bytes(), [text.encode() for text in documents])
        self.assertEqual(preexisting.read_bytes(),b'other owner')
        self.assertEqual(list(self.root.glob('.review.html.*.tmp')),[])
        old = destination.read_bytes()
        with patch('portable_web_export_plugin.exporter.os.replace',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                write_export_document('replacement',destination)
        self.assertEqual(destination.read_bytes(),old)
        self.assertEqual(list(self.root.glob('.review.html.*.tmp')),[])

    def test_source_destination_and_hardlink_alias_rejected(self):
        source = self.root/'demo.kicad_pcb'
        with self.assertRaises(ValueError):
            write_export_document('unsafe',source)
        alias = self.root/'alias.html'
        os.link(source,alias)
        with self.assertRaisesRegex(ValueError,'alias'):
            write_export_document('unsafe',alias,protected_sources=[source])
        self.assertEqual(source.read_text(),BOARD)

    def test_malicious_design_labels_and_script_end_tags_are_inert(self):
        scan = scan_project(self.root/'demo.kicad_pcb')
        scan.components[0] = __import__('dataclasses').replace(scan.components[0],
            reference='<img src=x onerror=bad()>',value='</ScRiPt><script>bad()</script>')
        document, manifest = build_export(scan,ExportSelection(schematic_paths=tuple(scan.schematics)),self.package)
        self.assertNotIn('<img src=x onerror=bad()>',document)
        self.assertIn('\\u003cimg src=x',document)
        html = _render_html("const text='</ScRiPt><img src=x>';",'notice',[],manifest)
        self.assertNotIn('</ScRiPt>',html)
        self.assertIn("<\\/script><img",html)
        self.assertIn("line.textContent = String(value",document)

    def test_duplicate_schematic_references_do_not_guess_crossprobe(self):
        schematic = self.root/'demo.kicad_sch'
        schematic.write_text(SCHEMATIC.replace(')))','))') +
            '(symbol (uuid cccccccc-cccc-cccc-cccc-cccccccccccc) (property "Reference" "U1")))')
        scan = scan_project(self.root/'demo.kicad_pcb')
        self.assertEqual(scan.components[0].schematic_uuids,())

    def test_real_vendor_pin_and_legal_assets_verify(self):
        package = Path(__file__).resolve().parents[1]
        script, notices = load_viewer_assets(package)
        self.assertGreater(len(script),1_000_000)
        self.assertIn('Integration-authored',notices)
        self.assertIn('668f973db5e931ff',notices)


if __name__ == "__main__":
    unittest.main()
