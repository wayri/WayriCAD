"""Native extraction/meshing/solver integration for reviewed grouped series pads."""
import importlib.util
from pathlib import Path
import hashlib
import tempfile
import unittest
from quick_pi_plugin.service import execute

NATIVE=all(importlib.util.find_spec(name) for name in ('pcbnew','vtk','numpy','scipy'))


@unittest.skipUnless(NATIVE,'Native KiCad scientific runtime required')
class NativeGroupedSeriesTests(unittest.TestCase):
    def test_total_current_once_and_unrelated_gate_excluded(self):
        import pcbnew as p
        from quick_pi_plugin.service import execute
        board=p.BOARD();board.SetCopperLayerCount(2);nets={}
        point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
        for name in ('VIN','OUT','GATE'):
            net=p.NETINFO_ITEM(board,name);board.Add(net);nets[name]=net
        for name,x0,x1 in [('VIN',0,4.5),('OUT',5.5,10)]:
            track=p.PCB_TRACK(board);track.SetStart(point(x0,1.5));track.SetEnd(point(x1,1.5));track.SetWidth(p.FromMM(4));track.SetLayer(p.F_Cu);track.SetNet(nets[name]);board.Add(track)
        for ref,pads in [('J1',[(1,0,.5,'VIN'),(2,0,2.5,'VIN')]),('U1',[(1,10,.5,'OUT'),(2,10,2.5,'OUT')]),
                         ('Q1',[(1,4.5,.5,'VIN'),(2,4.5,2.5,'VIN'),(3,5.5,.5,'OUT'),(4,5.5,2.5,'OUT'),(5,5,6,'GATE')])]:
            fp=p.FOOTPRINT(board);fp.SetReference(ref);board.Add(fp)
            for number,x,y,net in pads:
                pad=p.PAD(fp);pad.SetNumber(str(number));pad.SetPosition(point(x,y));pad.SetSize(point(.5,.5));pad.SetShape(p.PAD_SHAPE_RECT);pad.SetAttribute(p.PAD_ATTRIB_SMD)
                layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);pad.SetNet(nets[net]);fp.Add(pad)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'grouped-series.kicad_pcb';p.SaveBoard(str(path),board)
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        request=dict(action='solve',board_path=str(path),net='VIN',source_terminal='J1.1',source_terminals=['J1.1','J1.2'],
                     sink_terminal='U1.1',sink_terminals=['U1.1','U1.2'],source_voltage=3.3,sink_current=2,edge_mm=.5,
                     stackup_override=[dict(id=p.F_Cu,z_mm=.0175,thickness_mm=.035),dict(id=p.B_Cu,z_mm=1.5825,thickness_mm=.035)],
                     series=[dict(id='Q1',from_pad='Q1.1',to_pad='Q1.3',from_pads=['Q1.1','Q1.2'],to_pads=['Q1.3','Q1.4'],resistance_ohm=.1)])
        bundle=execute(request);result=bundle['result']
        assert abs(result['source_current_A']-2)<1e-7
        assert abs(result['components'][0]['current_A']-2)<1e-7
        assert abs(result['components'][0]['power_W']-.4)<1e-7
        assert result['voltage_drop_V']>.2
        assert abs(result['voltage_drop_V']-result['conductor_power_W']/2-.2)<1e-6
        assert result['energy_relative_error']<1e-6
        assert len(bundle['terminal_units']['source_terminals'])==2
        assert len(bundle['terminal_units']['loads'][0]['terminals'])==2
        assert len(bundle['terminal_units']['series'][0]['from_terminals'])==2
        assert all(t.get('label')!='Q1.5' for t in bundle['geometry']['terminals'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        request['series'][0]['from_pads'].append('Q1.5')
        try:execute(request)
        except ValueError as error:assert 'one exact component and net' in str(error)
        else:raise AssertionError('Gate mixed into current group')


if __name__ == "__main__":unittest.main()
