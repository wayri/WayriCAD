import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wayricad_mechanical.editor_link import finding_footprints, locate_report


class MechanicalEditorLinkTests(TestCase):
    def test_mixed_finding_resolves_only_primary_uuid(self):
        report = dict(board=dict(components=[dict(ref='U1@abcd',uuid='a', source_ref='U1')]),
                      bodies=[dict(ref='Other:U1',kind='comparison_component')])
        self.assertEqual(finding_footprints(report,dict(refs=['U1@abcd','Other:U1'])),
                         (['a'],['Other:U1']))
        with self.assertRaisesRegex(ValueError,'no primary-board footprint'):
            finding_footprints(report,dict(refs=['Other:U1','U1']))

    def test_duplicate_ref_or_scene_name_collision_is_rejected(self):
        report = dict(board=dict(components=[dict(ref='PCB',uuid='a')]),
                      bodies=[dict(ref='PCB',kind='board')])
        with self.assertRaisesRegex(ValueError,'no unique'):
            finding_footprints(report,dict(refs=['PCB']))
        report['bodies'] = []
        report['board']['components'].append(dict(ref='PCB',uuid='b'))
        with self.assertRaisesRegex(ValueError,'no unique'):
            finding_footprints(report,dict(refs=['PCB']))

    def test_saved_source_and_origin_required_for_navigation(self):
        report = dict(board_path='board.kicad_pcb',board_sha256='digest')
        with patch('wayricad_mechanical.editor_link.select_origin') as select:
            locate_report(report,['a'],'origin')
            select.assert_called_once_with('board.kicad_pcb',identifiers=['a'],expected_sha256='digest',
                                          footprints_only=True,focus=True,return_details=True,launch_context='origin')
            for invalid in (dict(report,source_kind='live editor snapshot'), dict(report,board_sha256='')):
                with self.assertRaises(ValueError):
                    locate_report(invalid,['a'],'origin')
            self.assertEqual(select.call_count,1)
