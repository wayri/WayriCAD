"""Opt-in KiCad 10 end-to-end PCB-only import and stale transaction tests."""
import importlib
import copy
import os
from pathlib import Path
import tempfile
import unittest

from test_sections_native import PACKAGE, make_fixture, sx, model

b=importlib.import_module(PACKAGE+'.board_layout')


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_LAYOUT')=='1','Opt-in native PCB-only import')
class NativeBoardLayoutTests(unittest.TestCase):
    def test_standalone_schematic_is_materialized_and_imported_without_source_project(self):
        selection=importlib.import_module(PACKAGE+'.source_selection')
        insertion=importlib.import_module(PACKAGE+'.insertion')
        with tempfile.TemporaryDirectory(prefix='fusion-standalone-test-') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            project=Path(source.project);project.unlink();project.with_suffix('.kicad_pcb').unlink()
            schematic=project.with_suffix('.kicad_sch');before=b.fingerprint(base/'source')
            standalone=model.SourceSpec(str(schematic),'Standalone',variant='<Default>')
            sources=selection.materialize_selection(standalone,{'whole_project':True,'sheet_paths':[],
                'max_depth':None,'include_layout':False},base/'source-copy')
            plan=insertion.preview_import(target.project,sources,False,base/'candidate')
            self.assertTrue(plan['report']['target_existing_geometry_preserved'])
            self.assertEqual(before,b.fingerprint(base/'source'))
            self.assertEqual((base/'candidate/board.kicad_pcb').read_bytes(),(base/'target/board.kicad_pcb').read_bytes())

    def test_board_only_import_preserves_target_schematic_and_routes_and_checks_parity(self):
        import pcbnew
        with tempfile.TemporaryDirectory(prefix='fusion-layout-test-') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            target_pcb=Path(target.project).with_suffix('.kicad_pcb');source_pcb=Path(source.project).with_suffix('.kicad_pcb')
            native=pcbnew.LoadBoard(str(target_pcb));native.SetCopperLayerCount(4)
            for drawing in list(native.GetDrawings()):
                if drawing.GetLayer()==pcbnew.Edge_Cuts:native.Remove(drawing)
            for start,end in (((-2,-2),(100,-2)),((100,-2),(100,100)),((100,100),(-2,100)),((-2,100),(-2,-2))):
                edge=pcbnew.PCB_SHAPE(native);edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
                edge.SetStart(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in start]));edge.SetEnd(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in end]))
                edge.SetLayer(pcbnew.Edge_Cuts);edge.SetWidth(pcbnew.FromMM(.05));native.Add(edge)
            pcbnew.SaveBoard(str(target_pcb),native)
            # The general section fixture has a deliberately dangling via on
            # B.Cu. A second copper plane supplies its opposite-side connection.
            source_tree=sx.load(source_pcb)
            zone=copy.deepcopy(sx.children(source_tree,'zone')[0])
            sx.put(zone,'layer',sx.q('B.Cu'));sx.put(zone,'uuid',sx.q(b.new_uuid()))
            source_tree.append(zone);sx.save(source_pcb,source_tree)
            before=b.fingerprint(base/'target');source_before=source_pcb.read_bytes()
            plan=b.preview_layout_import(target.project,source_pcb,base/'candidate',alias='Module',x_mm=35,y_mm=5)
            self.assertTrue(plan['report']['native_target_parity_verified'])
            self.assertTrue(plan['report']['native_drc_no_new_findings'])
            self.assertEqual(before,b.fingerprint(base/'target'));self.assertEqual(source_before,source_pcb.read_bytes())
            for relative in ('board.kicad_sch','child.kicad_sch','board.kicad_pro'):
                self.assertEqual((base/'target'/relative).read_bytes(),(base/'candidate'/relative).read_bytes())
            board=pcbnew.LoadBoard(str(base/'candidate/board.kicad_pcb'))
            imported=next(fp for fp in board.GetFootprints() if fp.GetReference()=='Module_R1')
            self.assertTrue(imported.GetAttributes() & pcbnew.FP_BOARD_ONLY)
            self.assertEqual(board.GetCopperLayerCount(),4)
            self.assertTrue(all(pad.GetNetname().startswith('/Module/') for pad in imported.Pads()))
            self.assertTrue(all(via.GetViaType()==pcbnew.VIATYPE_THROUGH for via in board.GetTracks() if isinstance(via,pcbnew.PCB_VIA)))
            # Source byte mutation must invalidate even a successfully checked candidate.
            source_pcb.write_bytes(source_before+b'\n')
            with self.assertRaisesRegex(model.MergeError,'dependency changed'):b.apply_layout_import(plan)
            self.assertEqual(before,b.fingerprint(base/'target'));source_pcb.write_bytes(source_before)
            result=b.apply_layout_import(plan)
            self.assertEqual(b.fingerprint(base/'target'),plan['candidate_hashes'])
            self.assertTrue(Path(result['backup_directory']).is_dir())

    def test_overlapping_import_cannot_pass_native_acceptance(self):
        with tempfile.TemporaryDirectory(prefix='fusion-layout-collision-') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source')
            before=b.fingerprint(base/'target')
            with self.assertRaises(model.MergeError):
                b.preview_layout_import(target.project,Path(source.project).with_suffix('.kicad_pcb'),base/'candidate',x_mm=-2,y_mm=-2)
            self.assertEqual(before,b.fingerprint(base/'target'));self.assertFalse((base/'candidate').exists())
