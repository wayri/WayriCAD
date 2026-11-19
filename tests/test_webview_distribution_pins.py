"""Both independently installed viewers retain the same audited source build."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SHA256 = '9a811d850854a5db8bf834213bcd2394af0f6d3c6ab8481b44257bca5b106e45'
SOURCE_COMMIT = '470e9d1638b8f2af0af7e26928a04b1ad459b8eb'
SOURCE_URL = 'https://github.com/wayri/kicad-webview/tree/'+SOURCE_COMMIT


class WebViewDistributionTests(unittest.TestCase):
    def test_independent_assets_match_declared_release_and_licenses(self):
        for package, filename, entry in (
            ('review_comments_plugin', 'REVIEW-PIN.json', 'kivi-viewer.js'),
            ('portable_web_export_plugin', 'PINNED-DISTRIBUTION.json', 'kicad-webview.min.js'),
        ):
            with self.subTest(package=package):
                base = ROOT / package / 'vendor/kicad-webview'
                pin = json.loads((base / filename).read_text(encoding='utf-8'))
                self.assertEqual(pin['version'], '0.8.0')
                self.assertEqual(pin.get('source_commit', pin.get('sourceCommit')), SOURCE_COMMIT)
                self.assertEqual(pin.get('distribution_kind', pin.get('distributionKind')), 'source-preview')
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
