"""Integrity and sampling gates for the published real-result gallery."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import unittest

import numpy as np


class AntennaGalleryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.gallery = cls.root / 'examples/quick_emerge/research_antennas/images/dense'
        cls.receipt = json.loads((cls.gallery / 'provenance.json').read_bytes())
        cls.raw = (cls.gallery / cls.receipt['samples_file']).read_bytes()
        cls.data = json.loads(gzip.decompress(cls.raw))

    def test_original_sample_custody_and_density(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.receipt['samples_sha256'])
        self.assertNotIn('source', self.data)
        self.assertEqual(self.data['config'], self.receipt['config'])
        self.assertGreaterEqual(len(self.data['frequencies_hz']), 21)
        field = self.data['field']
        self.assertGreaterEqual(len(field['x_mm']), 161)
        self.assertGreaterEqual(len(field['y_mm']), 161)
        self.assertEqual(np.shape(field['norm_e_v_m']), (len(field['y_mm']), len(field['x_mm'])))

    def test_images_match_receipt_and_are_not_thumbnails(self):
        self.assertEqual(len(self.receipt['screenshots']), 12)
        for image in self.receipt['screenshots']:
            with self.subTest(image=image['file']):
                self.assertEqual(Path(image['file']).name, image['file'])
                raw = (self.gallery / image['file']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), image['sha256'])
                self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', raw[16:24])
                self.assertGreaterEqual(width, 1000)
                self.assertGreaterEqual(height, 650)

    def test_polarization_matches_independent_ellipse_svd(self):
        pol = self.data['radiation']['boresight_polarization']
        ex, ey = complex(*pol['ex_ri']), complex(*pol['ey_ri'])
        singular = np.linalg.svd([[ex.real, -ex.imag], [ey.real, -ey.imag]], compute_uv=False)
        ar = 20*np.log10(singular[0]/singular[1])
        self.assertAlmostEqual(ar, self.receipt['polarization_analysis']['axial_ratio_db'], places=4)

    def test_primary_readmes_use_dense_evidence(self):
        for path in ('quick_emerge_plugin/README.md', 'examples/quick_emerge/research_antennas/README.md'):
            with self.subTest(path=path):
                text = (self.root / path).read_text(encoding='utf-8')
                self.assertIn('images/dense/wlan-field-slice.png', text)
                self.assertIn('161 x 161', text)
                self.assertNotIn('](images/wlan-field-slice.png)', text)
                self.assertIn('images/dense/interactive-results.html', text)

    def test_offline_interactive_viewer_has_scales_and_original_probes(self):
        text = (self.gallery / 'interactive-results.html').read_text(encoding='utf-8')
        for identifier in ('radiation3d', 'field3d', 's11', 'phase', 'field', 'polarization'):
            self.assertIn('id="plot-' + identifier + '"', text)
        self.assertIn('relative radius', text)
        self.assertTrue('V/m' in text or r'V\u002fm' in text, 'Field units missing')
        self.assertIn('GHz', text)
        self.assertIn(self.receipt['samples_sha256'], text)
        self.assertNotIn('<script src=', text)


if __name__ == '__main__':
    unittest.main()
