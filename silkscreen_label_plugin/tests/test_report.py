"""Offline HTML report safety and native preview geometry coverage."""
import unittest

from silkscreen_label_plugin.report import render_report


class ReportRenderingTests(unittest.TestCase):
    def test_bottom_reading_view_mirrors_about_the_actual_board_centre(self):
        from silkscreen_label_plugin.report import _svg
        geometry=dict(board_mm=[7,3,10,8],features=[])
        self.assertIn('translate(24.0000 0) scale(-1 1)',_svg(geometry,'bottom','after'))
        self.assertNotIn('scale(-1 1)',_svg(geometry,'top','after'))

    def test_glyph_hole_is_a_compound_evenodd_path_not_a_separately_filled_ring(self):
        from silkscreen_label_plugin.report import _svg
        geometry=dict(board_mm=[0,0,10,8],features=[dict(kind='glyph-after',side='top',label='O',paths=[
            dict(points=[[1,1],[4,1],[4,5],[1,5]],closed=True),
            dict(points=[[2,2],[3,2],[3,4],[2,4]],closed=True)])])
        svg=_svg(geometry,'top','after')
        self.assertEqual(svg.count('<path '),1)
        self.assertEqual(svg.count('M '),2)
        self.assertIn('fill-rule="evenodd"',svg)

    def test_report_escapes_user_labels_and_is_standalone_sortable_html(self):
        payload={
            'source_sha256':'abc123',
            'stats':{'eligible':2,'placed':1,'unresolved':1,'reviewed':2},
            'rejected':[('<script>alert(1)</script>','Ambiguous <owner>')],
            'skipped':[],
            'review_geometry':{
                'board_mm':[0,0,10,8],
                'features':[{'kind':'board','side':'both','label':'Board','paths':[
                    {'points':[[0,0],[10,0],[10,8],[0,8]],'closed':True}]}],
                'outcomes':[{'id':'1','side':'top','label':'<script>alert(1)</script>',
                    'status':'UNRESOLVED','candidate_checks':4,'before_courtyard_gap_mm':0.2,
                    'courtyard_gap_mm':0.15,'before_body_hull_gap_mm':0.4,'body_hull_gap_mm':None,
                    'before_pad_gap_mm':0.0,'after_pad_gap_mm':None,'before_association_warning':'Another component is nearer','association_warning':'Ambiguous association'}]
            }
        }
        html=render_report(payload)
        self.assertIn('Before —',html);self.assertIn('After — proposed only',html)
        self.assertIn('Top side',html);self.assertIn('Bottom side',html)
        self.assertIn('cursor:pointer',html)
        self.assertIn('localeCompare',html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('NOT RUN',html)
        self.assertIn('Physical 3D body clearance is not computed',html)
        self.assertIn('footprint-hull gap',html)
        self.assertIn('missing courtyard distance is unknown',html)
        self.assertNotIn('footprint-hull fallback',html)
        self.assertIn('<td>0.150</td>',html)
        self.assertIn('Before: Another component is nearer',html)
        self.assertIn('After: Ambiguous association',html)
        self.assertNotIn('https://',html)


try:
    import test_placement as fixture
except ImportError:
    fixture=None

@unittest.skipIf(fixture is None or fixture.api is None,'Native KiCad bindings required.')
class NativeReportGeometryTests(unittest.TestCase):
    def test_native_capture_contains_board_body_pad_glyph_and_two_face_outcomes(self):
        from silkscreen_label_plugin.placement import plan
        from silkscreen_label_plugin.report import capture_geometry, render_report
        case=fixture.PlacementTests();case.setUp()
        preview=plan(case.board,fixture.api,dict(leaders=False))
        geometry=capture_geometry(case.board,preview,fixture.api)
        kinds={feature['kind'] for feature in geometry['features']}
        self.assertIn('board',kinds);self.assertIn('body',kinds)
        self.assertIn('pad',kinds);self.assertIn('glyph-before',kinds)
        self.assertIn('glyph-after',kinds)
        self.assertTrue(geometry['outcomes'])
        self.assertIn(geometry['outcomes'][0]['side'],('top','bottom'))
        self.assertEqual(preview.source_fingerprint,
                         __import__('silkscreen_label_plugin.placement',fromlist=['fingerprint']).fingerprint(case.board,fixture.api))
        html=render_report({'source_sha256':'synthetic','stats':preview.stats,
            'rejected':preview.rejected,'skipped':preview.skipped,'review_geometry':geometry})
        self.assertEqual(html.count('<svg '),4)
        self.assertIn('top '+str(sum(row['side']=='top' for row in geometry['outcomes'])),html)
        self.assertIn('Bottom side',html)

    def test_testpoint_create_update_and_restore_project_prospective_glyphs(self):
        try:
            import test_net_annotations as net_fixture
        except ImportError:
            self.skipTest('Native test-point fixture unavailable.')
        case=net_fixture.NetAnnotationTests();case.setUp()
        api=net_fixture.api
        from silkscreen_label_plugin.report import capture_geometry
        from silkscreen_label_plugin.placement import apply

        def check_reviewed_positions(review,geometry):
            for change in review.changes:
                expected=change.box
                label=(change.preview_item or change.item).GetShownText(False)
                feature=next(f for f in geometry['features'] if f['kind']=='glyph-after' and f['label']==label)
                points=[point for path in feature['paths'] for point in path['points']]
                self.assertTrue(points)
                self.assertGreaterEqual(min(x for x,y in points),api.ToMM(expected.GetLeft())-.000002)
                self.assertLessEqual(max(x for x,y in points),api.ToMM(expected.GetRight())+.000002)
                self.assertGreaterEqual(min(y for x,y in points),api.ToMM(expected.GetTop())-.000002)
                self.assertLessEqual(max(y for x,y in points),api.ToMM(expected.GetBottom())+.000002)

        created=case.plan()
        geom=capture_geometry(case.board,created,api)
        check_reviewed_positions(created,geom)
        outcome=geom['outcomes'][0]
        self.assertEqual(outcome['label'],'TP1 / /Power/3V3_TEST')
        labels=[(feature['kind'],feature['label']) for feature in geom['features']]
        self.assertIn(('glyph-after','/Power/3V3_TEST'),labels)
        self.assertIn(('context-before','Preserved visible text'),labels)
        self.assertNotIn(('context-glyph','Preserved visible text'),labels)
        self.assertTrue(any(row.get('courtyard_gap_mm') is not None for row in created.outcomes))
        self.assertTrue(any(row.get('before_courtyard_gap_mm') is not None for row in created.outcomes))
        apply(case.board,api,created)

        case.net('/Power/UPDATED_TESTPOINT_NET')
        updated=case.plan()
        geom=capture_geometry(case.board,updated,api)
        check_reviewed_positions(updated,geom)
        labels=[(feature['kind'],feature['label']) for feature in geom['features']]
        self.assertIn(('glyph-before','/Power/3V3_TEST'),labels)
        self.assertIn(('glyph-after','/Power/UPDATED_TESTPOINT_NET'),labels)
        apply(case.board,api,updated)

        restored=case.plan(testpoint_net_names=False,references=False,testpoint_pattern='')
        self.assertFalse(case.reference.IsVisible())
        geom=capture_geometry(case.board,restored,api)
        check_reviewed_positions(restored,geom)
        labels=[(feature['kind'],feature['label']) for feature in geom['features']]
        self.assertIn(('glyph-before','/Power/UPDATED_TESTPOINT_NET'),labels)
        self.assertIn(('glyph-after','TP1'),labels)
        self.assertFalse(any(kind=='context-glyph' and label=='Preserved visible text'
                             for kind,label in labels))


if __name__=='__main__':unittest.main()
