"""Both independently installed viewers retain the same audited upstream release."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SHA256 = '668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4'
SOURCE_URL = 'https://github.com/wayri/kicad-webview/tree/v0.6.0'


class WebViewDistributionTests(unittest.TestCase):
    def test_independent_assets_match_declared_release_and_licenses(self):
        for package, filename, entry in (
            ('review_comments_plugin', 'REVIEW-PIN.json', 'kivi-viewer.js'),
            ('portable_web_export_plugin', 'PINNED-DISTRIBUTION.json', 'kicad-webview.min.js'),
        ):
            with self.subTest(package=package):
                base = ROOT / package / 'vendor/kicad-webview'
                pin = json.loads((base / filename).read_text(encoding='utf-8'))
                self.assertEqual(pin['version'], '0.6.0')
                self.assertEqual(pin.get('source_archive_sha256', pin.get('upstreamArchiveSHA256')), ARCHIVE_SHA256)
                self.assertEqual(pin.get('source_url', pin.get('matchingSourceURL')), SOURCE_URL)
                records = pin['files']
                if isinstance(records, list):
                    self.assertEqual(len(records), len({record['path'] for record in records}))
                    records = {record['path']: record for record in records}
                self.assertIn(entry, records)
                for required in ('LICENSE', 'LICENSING.md', 'THIRD-PARTY-NOTICES.md',
                                 'THREE-LICENSE', 'FZSTD-LICENSE', 'SOURCE-PROVENANCE.json'):
                    self.assertIn(required, records)
                for name, record in records.items():
                    path = PurePosixPath(name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertNotIn('node_modules', path.parts)
                    self.assertNotIn('fixtures', path.parts)
                    data = (base / path).read_bytes()
                    self.assertEqual(len(data), record['bytes'], name)
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'], name)
                self.assertIn('Mozilla Public License Version 2.0', (base / 'LICENSE').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
