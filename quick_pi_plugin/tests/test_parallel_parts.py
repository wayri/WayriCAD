"""Reviewed parallel stages use real net pairs and preserve each part's model."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest

from quick_pi_plugin.parallel_parts import candidates,suggested_resistance,stage_pads,with_parallel


def inventory():
    rows=[{'id':'s','label':'J1.1','reference':'J1','footprint_uuid':'source','net':'VIN'}]
    for ref,owner,nets,value in [('R1','r1',('VIN','OUT'),'100m'),('R2','r2',('OUT','VIN'),'200m'),
                                  ('C1','c1',('VIN','OUT'),'1uF'),('R3','r3',('VIN','OTHER'),'4R7')]:
        for n,net in enumerate(nets,1):rows.append(dict(id=ref+str(n),reference=ref,label=f'{ref}.{n}',net=net,footprint_uuid=owner,component_value=value))
    rows.append({'id':'l','label':'U1.1','reference':'U1','footprint_uuid':'sink','net':'OUT'})
    return {'terminals':rows,'nets':['VIN','OUT','OTHER']}


class ParallelPartTests(unittest.TestCase):
    def test_detects_exact_pair_including_reverse_pin_order(self):
        found=candidates(inventory(),'R11','R12')
        self.assertEqual([row['id'] for row in found],['C1','R2'])
        second=found[1];self.assertEqual((second['from_pad'],second['to_pad']),('R22','R21'))
        self.assertEqual(suggested_resistance(second),'200m')
        self.assertEqual(suggested_resistance(found[0]),'')
        self.assertEqual(suggested_resistance({'id':'R3','component_value':'4R7'}),'4.7')

    def test_incomplete_path_can_recommend_but_never_guesses_unknown_models(self):
        self.assertEqual(stage_pads(inventory(),'J1.1',[{'reference':'R1','model':'100m'}],0),('R11','R12'))
        self.assertEqual(suggested_resistance({'id':'L1','component_value':'10uH'}),'')
        self.assertEqual(suggested_resistance({'id':'R2','component_value':'unknown'}),'')

    def test_reviewed_request_contains_separate_electrical_branches(self):
        request={'series':[{'id':'R1','from_pad':'R11','to_pad':'R12','resistance_ohm':.1}]}
        staged=[{'reference':'R1','model':'100m','parallel':[{'footprint_uuid':'r2','model':'200m'}]}]
        result=with_parallel(request,staged,inventory())
        self.assertNotIn('parallel',request['series'][0])
        self.assertEqual(result['series'][0]['parallel'][0]['resistance_ohm'],.2)
        self.assertEqual(result['series'][0]['parallel'][0]['from_pad'],'R22')
        staged[0]['parallel'][0]['footprint_uuid']='missing'
        with self.assertRaisesRegex(ValueError,'no longer'):with_parallel(request,staged,inventory())


NATIVE=all(importlib.util.find_spec(name) for name in ('pcbnew','vtk','numpy','scipy'))


@unittest.skipUnless(NATIVE,'Native KiCad scientific runtime required')
class NativeParallelTests(unittest.TestCase):
    def test_native_parallel_review_selects_only_confirmed_parts(self):
        import wx
        from unittest.mock import patch
        from quick_pi_plugin.series_editor import SeriesPathDialog
        app=wx.GetApp() or wx.App(False);parent=wx.Frame(None)
        editor=SeriesPathDialog(parent,inventory(),'Example.kicad_pcb')
        try:
            editor.source.SetStringSelection('J1.1');editor.sink.SetStringSelection('U1.1')
            editor.branches=[{'reference':'R1','model':'100m'}];editor._changed()
            self.assertIn('Parallel parts (2)',editor.parallel_button.GetLabel())
            def choose(dialog):
                def walk(window):
                    yield window
                    for child in window.GetChildren():yield from walk(child)
                checks=[window for window in walk(dialog) if isinstance(window,wx.CheckBox)]
                next(window for window in checks if window.GetLabel().startswith('R2 ')).SetValue(True)
                return wx.ID_OK
            with patch.object(wx.Dialog,'ShowModal',choose):editor._parallel(None)
            request=editor._parsed()
            self.assertEqual([row['id'] for row in request['series'][0]['parallel']],['R2'])
            self.assertAlmostEqual(request['series'][0]['parallel'][0]['resistance_ohm'],.2)
        finally:
            editor.dialog.Destroy();parent.Destroy();app.Yield()

    def test_parallel_resistors_have_conservative_unequal_currents(self):
        import pcbnew as p
        from quick_pi_plugin.service import execute
        with tempfile.TemporaryDirectory() as raw:
            board=p.BOARD();board.SetCopperLayerCount(2);nets={}
            point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
            for name,x0,x1 in [('VIN',0,4.5),('OUT',5.5,10)]:
                net=p.NETINFO_ITEM(board,name);board.Add(net);nets[name]=net
                track=p.PCB_TRACK(board);track.SetStart(point(x0,.5));track.SetEnd(point(x1,.5));track.SetWidth(p.FromMM(3));track.SetLayer(p.F_Cu);track.SetNet(net);board.Add(track)
            for ref,pads in [('J1',[(1,0,.5,'VIN')]),('U1',[(1,10,.5,'OUT')]),
                             ('R1',[(1,4.5,0,'VIN'),(2,5.5,0,'OUT')]),
                             ('R2',[(1,4.5,1,'VIN'),(2,5.5,1,'OUT')])]:
                fp=p.FOOTPRINT(board);fp.SetReference(ref);board.Add(fp)
                for number,x,y,net in pads:
                    pad=p.PAD(fp);pad.SetNumber(str(number));pad.SetPosition(point(x,y));pad.SetSize(point(.5,.5));pad.SetShape(p.PAD_SHAPE_RECT);pad.SetAttribute(p.PAD_ATTRIB_SMD)
                    layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);pad.SetNet(nets[net]);fp.Add(pad)
            path=Path(raw)/'parallel.kicad_pcb';p.SaveBoard(str(path),board);before=hashlib.sha256(path.read_bytes()).hexdigest()
            part=dict(id='R2',from_pad='R2.1',to_pad='R2.2',resistance_ohm=.3)
            request=dict(action='solve',board_path=str(path),net='VIN',source_terminal='J1.1',sink_terminal='U1.1',source_voltage=3.3,sink_current=2,edge_mm=.5,
                         stackup_override=[dict(id=p.F_Cu,z_mm=.0175,thickness_mm=.035),dict(id=p.B_Cu,z_mm=1.5825,thickness_mm=.035)],
                         series=[dict(id='R1',from_pad='R1.1',to_pad='R1.2',resistance_ohm=.2,parallel=[part])])
            bundle=execute(request);result=bundle['result']
            self.assertEqual(len(result['components']),2)
            # Copper adds real lead/spreading loss; subtract its P/I voltage
            # equivalent before comparing the two ideal resistor branches.
            self.assertGreater(result['voltage_drop_V'],.24)
            self.assertAlmostEqual(result['voltage_drop_V']-result['conductor_power_W']/2,.24,delta=5e-5)
            currents=[row['current_A'] for row in result['components']]
            self.assertAlmostEqual(sum(currents),2,7)
            self.assertGreater(currents[0],currents[1])
            self.assertLess(result['energy_relative_error'],1e-6)
            self.assertAlmostEqual(result['source_current_A'],2,7)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            request['series'][0]['parallel'][0]['to_pad']='J1.1'
            with self.assertRaises(ValueError):execute(request)


if __name__=='__main__':unittest.main()
