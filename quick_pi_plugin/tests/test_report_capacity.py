"""Dense static reports preserve geometry/data while bounding artist lifetimes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import weakref
from unittest.mock import patch
import numpy as np
from quick_pi_plugin import report
from quick_pi_plugin.barrel import drill_contour
from quick_pi_plugin.tests.test_report import bundle as strip_bundle
from quick_pi_plugin.tests.test_slot_report import slot


def dense_bundle(count=1100):
    """Display-only via context on an independently solved analytical strip."""
    bundle=strip_bundle()
    bundle['geometry']['layers'].append({'id':31,'name':'B.Cu','z_mm':1.6,'polygons':[]})
    bundle['geometry']['vias']=[
        {'id':str(i),'x_mm':.1+(i%100)*.098,'y_mm':.08+(i//100)*.075,
         'layers':[0],'diameter_mm':.04,'drill_mm':.02}
        for i in range(count)]
    for angle in (0,45,90):
        barrel=slot(angle,(2+angle/30,.5));barrel['id']='slot-'+str(angle)
        land={'outer':[[barrel['x_mm']-1.3,0],[barrel['x_mm']+1.3,0],
                       [barrel['x_mm']+1.3,1],[barrel['x_mm']-1.3,1]],'holes':[]}
        bundle['geometry']['vias'].append(dict(barrel,layers=[0,31],polygons={'0':[land]}))
        bundle['mesh']['vias'].append(barrel)
        bundle['result']['vias'].append({'id':barrel['id'],'current_density_A_mm2':1000.})
    return bundle


class ReportCapacityTests(unittest.TestCase):
    def test_metric_budget_style_and_explicit_extended_request(self):
        bundle=strip_bundle()
        metrics,style,large=report._static_report_plan(bundle)
        self.assertEqual(len(metrics),7);self.assertEqual(style,'smooth');self.assertFalse(large)
        class LargeTriangles:
            def __len__(self):return 100001
        bundle['mesh']['triangles']=LargeTriangles()
        self.assertEqual(report._static_report_plan(bundle),(('drop','density','loss'),'cells',True))
        bundle['report_options']={'extended_snapshots':True}
        self.assertEqual(len(report._static_report_plan(bundle)[0]),7)
        self.assertEqual(report._static_report_plan(bundle)[1],'cells')
        for options in ({'extended_snapshots':1},{'extended_snapshots':'yes'},{'unknown':True},[]):
            bundle['report_options']=options
            with self.subTest(options=options),self.assertRaises(ValueError):report._static_report_plan(bundle)

    def test_dense_geometry_collections_keep_all_circles_slots_and_drill_paths(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.collections import PatchCollection
        from matplotlib.path import Path as DrawingPath
        bundle=dense_bundle();before=copy.deepcopy(bundle)
        figure=Figure(figsize=(5,3));FigureCanvasAgg(figure)
        axes=report.draw_view(figure,bundle,layer=0,metric='density',field_style='cells')
        figure.canvas.draw()
        collections=[c for c in axes.collections if isinstance(c,PatchCollection)]
        # One copper face, 2 paths per circular via, 2 per slot context,
        # and an exact annulus outer/hole pair for each solved slot.
        self.assertEqual(sum(len(c.get_paths()) for c in collections),1+2200+6+6)
        self.assertEqual(len(axes.patches),0)
        self.assertEqual(len(collections),4)
        self.assertIs(axes.collections[0],collections[0])  # Copper under field.
        context=collections[1]
        self.assertIn(DrawingPath.CURVE4,context.get_paths()[0].codes)
        for barrel in bundle['mesh']['vias']:
            for prefix,offset,circumscribed in (('via-barrel:',.025,False),('via-drill:',0,True)):
                gid=prefix+barrel['id']
                collection=next(c for c in collections if gid in c._wayricad_patch_gids)
                path=collection.get_paths()[collection._wayricad_patch_gids.index(gid)]
                expected=np.asarray(drill_contour(barrel,offset,circumscribed=circumscribed))
                np.testing.assert_allclose(path.vertices[:-1],expected,rtol=0,atol=1e-14)
                self.assertTrue(set(path.codes)<={DrawingPath.MOVETO,DrawingPath.LINETO,DrawingPath.CLOSEPOLY})
        self.assertEqual(bundle,before)
        figure.clear()

    def test_large_report_three_snapshots_complete_json_and_interactive_fields(self):
        bundle=dense_bundle();before=copy.deepcopy(bundle)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>') as snapshot, \
             patch.object(report,'interactive_fields',wraps=report.interactive_fields) as interactive:
            paths=report.write_report(Path(directory)/'dense.html',bundle)
            self.assertEqual([call.args[2] for call in snapshot.call_args_list],['drop','density','loss'])
            self.assertTrue(all(call.args[3]=='cells' for call in snapshot.call_args_list))
            interactive.assert_called_once()
            html=Path(paths['html']).read_text(encoding='utf-8')
            self.assertIn('Solver cells style',html)
            self.assertNotIn('Additional potential, resistance, flow',html)
            self.assertEqual(json.loads(Path(paths['json']).read_text(encoding='utf-8')),bundle)
        self.assertEqual(bundle,before)

    def test_snapshot_releases_figure_cycles(self):
        references=[];native=report.draw_view
        def drawn(figure,*args,**kwargs):
            references.append(weakref.ref(figure));return native(figure,*args,**kwargs)
        with patch.object(report,'draw_view',new=drawn):
            image=report._report_snapshot(strip_bundle(),0,'drop','cells')
        self.assertIn('data:image/png;base64,',image)
        self.assertIsNone(references[0]())

    def test_shared_child_links_raw_parent_evidence_without_duplicate_arrays(self):
        child=strip_bundle()
        child['geometry']['net']='Supply ΔV / Ω'
        group={'name':'Ground Ω','status':'COMPLETED','return_conduction':child,'loads':[]}
        bundle={'batch':{'status':'COMPLETED','cases':[{'name':'Supply ΔV','status':'COMPLETED','electrical':child}],
                         'shared_returns':[group]},'report_options':{'extended_snapshots':True}}
        before=copy.deepcopy(bundle)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>') as snapshot:
            output=Path(directory)/'batch.html';paths=report.write_batch_report(output,bundle)
            parent=json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(parent,bundle)
            self.assertEqual(parent['batch']['cases'][0]['name'],'Supply ΔV')
            self.assertEqual(parent['batch']['shared_returns'][0]['name'],'Ground Ω')
            for relative,pointer in zip(paths['case_reports'],('/batch/cases/0/electrical','/batch/shared_returns/0/return_conduction')):
                linked=Path(directory)/relative
                descriptor=json.loads(linked.with_suffix('.json').read_text(encoding='utf-8'))
                self.assertNotIn('mesh',descriptor);self.assertNotIn('result',descriptor)
                self.assertNotIn('auxiliary_reversed_current_result',descriptor)
                reference=descriptor['evidence_reference']
                self.assertEqual(reference['json'],'../batch.json')
                self.assertEqual(reference['json_pointer'],pointer)
                resolved=parent
                for key in pointer.split('/')[1:]:
                    resolved=resolved[int(key)] if isinstance(resolved,list) else resolved[key]
                self.assertEqual(resolved,child)
                html=linked.read_text(encoding='utf-8')
                self.assertIn('child JSON is not a standalone numerical result',html)
            self.assertEqual(descriptor['evidence_reference']['sign_transforms']['/result/potential_V'],-1)
            self.assertEqual(descriptor['evidence_reference']['sign_transforms']['/result/vias/*/current_A'],-1)
            self.assertEqual(snapshot.call_count,14)
        self.assertEqual(bundle,before)

    def test_referenced_publication_preserves_custody_and_refuses_changed_source(self):
        bundle=strip_bundle()
        reference={'json':'../parent.json','json_pointer':'/batch/cases/0/electrical'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'):
            board=Path(directory)/'board.kicad_pcb';board.write_text('original')
            digest=hashlib.sha256(board.read_bytes()).hexdigest()
            bundle.update(board_path=str(board),source_sha256=digest)
            bundle['request']['board_path']=str(board)
            bundle['geometry'].update(source_path=str(board),source_sha256=digest,geometry_sha256='geometry-fixture')
            output=Path(directory)/'child.html'
            report.write_report(output,bundle,evidence_reference=reference)
            descriptor=json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(descriptor['source_custody']['bundle']['source_sha256'],digest)
            self.assertEqual(descriptor['source_custody']['geometry']['source_path'],str(board))
            self.assertEqual(descriptor['source_custody']['geometry']['geometry_sha256'],'geometry-fixture')
            original_html=output.read_bytes();original_json=output.with_suffix('.json').read_bytes()
            board.write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                report.write_report(output,bundle,evidence_reference=reference)
            self.assertEqual(output.read_bytes(),original_html)
            self.assertEqual(output.with_suffix('.json').read_bytes(),original_json)


if __name__=='__main__':unittest.main()
