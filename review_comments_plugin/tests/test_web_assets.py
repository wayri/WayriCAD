from pathlib import Path
import os
import tempfile
import unittest

from review_comments_plugin.web_assets import (
    asset_manifest, discover_assets, required_paths, verify_assets, verify_module_closure,
)


class WebAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for name in required_paths(linked_models=True):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode('utf-8'))

    def test_exact_closure_and_receipt(self):
        manifest = asset_manifest(self.root, linked_models=True)
        self.assertEqual(tuple(item.path for item in manifest), required_paths(linked_models=True))
        paths = discover_assets(self.root)
        self.assertEqual(set(paths), set(required_paths(linked_models=True)))
        self.assertTrue(all(path.is_absolute() and path.is_file() for path in paths.values()))
        verify_assets(self.root, manifest)
        (self.root / 'extension/pcb-renderer.js').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_assets(self.root, manifest)

    def test_missing_asset_fails_closed(self):
        target = self.root / 'extension/owned-canvas.js'
        target.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            discover_assets(self.root)

    def test_linked_asset_fails_closed(self):
        target = self.root / 'extension/owned-canvas.js'
        target.unlink()
        try:
            target.symlink_to(self.root / 'extension/pcb-renderer.js')
        except OSError:
            self.skipTest('symlink creation is unavailable in this Windows environment')
        with self.assertRaisesRegex(ValueError, 'link'):
            discover_assets(self.root)

    def test_step_is_not_in_selected_closure(self):
        paths = discover_assets(self.root)
        self.assertNotIn('extension/step-worker.js', paths)
        self.assertNotIn('extension/vendor/occt/occt-import-js.wasm', paths)
        with self.assertRaisesRegex(ValueError, 'require'):
            required_paths(include_3d=False, linked_models=True)

    def test_relative_module_references_must_be_served(self):
        module = self.root / 'web-library/kicad-viewer.mjs'
        module.write_text("import './source-loader.mjs';\nimport('./three-runtime.mjs');\n", encoding='utf-8')
        asset_manifest(self.root, linked_models=True)
        module.write_text("import './unserved.mjs';\n", encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'outside the served subset'):
            asset_manifest(self.root, linked_models=True)

    def test_captured_bytes_are_checked_separately(self):
        files = {name: name.encode('utf-8') for name in required_paths(linked_models=True)}
        files['web-library/three-runtime.mjs'] = (
            b"new URL('../extension/vendor/spike-board3d.bundle.js', import.meta.url);"
        )
        verify_module_closure(files)
        files['web-library/source-loader.mjs'] = b"export * from './missing.mjs';"
        with self.assertRaisesRegex(ValueError, 'missing.mjs'):
            verify_module_closure(files)

    def test_moved_source_layout_preserves_import_urls_and_notices(self):
        modern = self.root / 'moved'
        for name in required_paths(linked_models=True, layout='modern'):
            source = ('src/' + name.removeprefix('web-library/') if name.startswith('web-library/')
                      else 'engine/' + name.removeprefix('extension/') if name.startswith('extension/')
                      else name)
            path = modern / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode('utf-8'))
        (modern / 'src/kicad-viewer.mjs').write_text(
            "import '../engine/pcb-renderer.js'; import './viewer-chrome.mjs'; import('./three-runtime.mjs');", encoding='utf-8')
        (modern / 'src/three-runtime.mjs').write_text(
            "new URL('../engine/vendor/spike-board3d.bundle.js', import.meta.url);", encoding='utf-8')
        manifest = asset_manifest(modern, linked_models=True)
        served = discover_assets(modern)
        self.assertEqual(set(served), set(required_paths(linked_models=True, layout='modern')))
        self.assertEqual(served['web-library/kicad-viewer.mjs'], modern / 'src/kicad-viewer.mjs')
        self.assertEqual(served['extension/repo-models.js'], modern / 'engine/repo-models.js')
        self.assertIn('licenses/Pocket-KiView-Source-Available-1.0.txt', served)
        verify_assets(modern, manifest)
        (modern / 'src/kicad-viewer.mjs').write_text("import '../engine/unknown.js';", encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'outside the served subset'):
            asset_manifest(modern, linked_models=True)

    @unittest.skipUnless(os.environ.get('WAYRICAD_KIVIEW_SOURCE_ROOT'), 'local KiView source not selected')
    def test_real_local_source_closure(self):
        root = Path(os.environ['WAYRICAD_KIVIEW_SOURCE_ROOT'])
        manifest = asset_manifest(root, linked_models=True)
        self.assertLess(sum(entry.bytes for entry in manifest), 3 * 1024 * 1024)
        self.assertEqual(len(discover_assets(root)), len(manifest))
        self.assertIn('web-library/source-loader.mjs', {entry.path for entry in manifest})
        self.assertIn('web-library/three-runtime.mjs', {entry.path for entry in manifest})
        from review_comments_plugin.web_host import _snapshot
        snapshot = _snapshot(root, Path(__file__).parents[1] / 'web')
        self.assertEqual(len(snapshot), len(manifest) + 3)
        self.assertLess(sum(map(len, snapshot.values())), 4 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
