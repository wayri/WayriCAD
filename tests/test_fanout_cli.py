"""CLI review must preserve the real segmented fanout rather than its chord."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from wayricad_runtime.cli import execute, write_svg


class FanoutCliTests(unittest.TestCase):
    def test_settings_expose_patterns_angles_and_interface_profiles_without_pcbnew(self):
        result=execute(Namespace(kind='fanout',operation='settings',board=None))
        self.assertIn('45-degree spread',result['choices']['pattern'])
        self.assertIn('Custom-angle spread',result['choices']['pattern'])
        self.assertIn('Board absolute',result['choices']['angle_mode'])
        for family in ('DDR','GDDR','SERDES','PCIe','PCI','PXI','LVDS'):
            self.assertIn(family,result['profiles'])
        self.assertEqual('Auto differential pairs',result['profiles']['PCIe']['pair_mode'])
        self.assertNotIn('width',result['profiles']['PCIe'])

    def test_svg_contains_exact_bend_points_and_pair_measurement(self):
        document={'kind':'fanout','candidates':[dict(reference='U1',pad='1',net='TX_P',
            start_mm=[0,0],end_mm=[2,1],path_mm=[[0,0],[1,0],[2,1]],length_mm=2.4142,
            width_mm=.15,via_diameter_mm=.5,via_drill_mm=.25,add_track=True,add_via=True,
            start_via=False,pair_id='U1:TX') ]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'preview.svg'
            write_svg(document,path)
            root=ET.parse(path).getroot()
            lines=root.findall('{http://www.w3.org/2000/svg}g/{http://www.w3.org/2000/svg}polyline')
            self.assertEqual(len(lines),1)
            self.assertEqual(lines[0].attrib['points'],'0,0 1,0 2,1')
            self.assertEqual(lines[0].attrib['stroke-width'],'0.15')
            self.assertIn('pair U1:TX',path.read_text(encoding='utf-8'))
            self.assertIn('2.4142 mm',path.read_text(encoding='utf-8'))
