"""Native-input contracts for simultaneous loads and stale result clearing."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from quick_pi_plugin.ui import QuickPIFrame,load_values
except ImportError:
    QuickPIFrame=None

_native_app=None


def control(value,selection=-1):
    return SimpleNamespace(GetValue=lambda:value,GetSelection=lambda:selection)


def frame():
    return SimpleNamespace(board_path='example.kicad_pcb',net=control('VCC'),edge=control('.5'),plating=control('.025'),
        source=control('A',0),sink=control('B',1),voltage=control('3.3'),current=control('.8'),
        source_current_limit=control('2'),sink_min_voltage=control('3.1'),sink_max_voltage=control('3.4'),
        temperature=control('20'),ambient=control('20'),limit=control('105'),pulse=control('1'),
        load_mode=control('',0),model_dimension=control('',0),
        _terminals=[{'id':'A'},{'id':'B'},{'id':'C'}],_series_request=None,
        _extra_sinks=[{'terminal':'C','current_A':.6,'min_voltage_V':3}])


@unittest.skipIf(QuickPIFrame is None,'native wx runtime required')
class MultisinkInputTests(unittest.TestCase):
    def test_simultaneous_loads_and_source_limits(self):
        request=QuickPIFrame._request(frame(),'solve')
        self.assertEqual(request['source_current_limit'],2)
        self.assertEqual(request['source_terminal'],'A')
        self.assertEqual(request['sinks'],[{'terminal':'B','current_A':.8,'min_voltage_V':3.1,'max_voltage_V':3.4},
                                          {'terminal':'C','current_A':.6,'min_voltage_V':3}])
        self.assertNotIn('sink_terminal',request);self.assertNotIn('sink_current',request)

    def test_unlimited_and_zero_source_budget_are_distinct(self):
        f=frame();f.source_current_limit=control('')
        self.assertNotIn('source_current_limit',QuickPIFrame._request(f,'solve'))
        f.source_current_limit=control('0');self.assertEqual(QuickPIFrame._request(f,'solve')['source_current_limit'],0)
        f.source_current_limit=control('-1')
        with self.assertRaisesRegex(ValueError,'nonnegative'):QuickPIFrame._request(f,'solve')

    def test_duplicate_and_source_loads_are_rejected(self):
        for identifier in ('A','B'):
            f=frame();f._extra_sinks=[{'terminal':identifier,'current_A':1}]
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):QuickPIFrame._request(f,'solve')

    def test_sink_values_and_optional_limits_are_bounded(self):
        self.assertEqual(load_values('B','1'),{'terminal':'B','current_A':1})
        self.assertEqual(load_values('B','1','0',''),{'terminal':'B','current_A':1,'min_voltage_V':0})
        for values in [('0','',''),('nan','',''),('1','2','1'),('1','-1',''),('1','','inf')]:
            with self.subTest(values=values),self.assertRaises(ValueError):load_values('B',*values)

    def test_series_path_keeps_single_load_bounds_and_rejects_extras(self):
        f=frame();f._series_request={'series':[{'id':'R1'}],'net':'VCC','source_terminal':'A','sink_terminal':'B'}
        with self.assertRaisesRegex(ValueError,'Additional sinks'):QuickPIFrame._request(f,'solve')
        f._extra_sinks=[];request=QuickPIFrame._request(f,'solve')
        self.assertEqual(request['sink_min_voltage'],3.1);self.assertEqual(request['sink_max_voltage'],3.4)
        self.assertEqual(request['source_current_limit'],2);self.assertNotIn('sinks',request)

    def test_input_change_clears_result_and_convergence_and_updates_markers(self):
        f=frame();f.bundle={'result':{'old':True},'convergence':{'old':True},'request':{}};f._inspection={'old':True}
        messages=[];draws=[];f._buttons=lambda:None;f._draw=lambda **kwargs:draws.append(kwargs)
        f.summary=SimpleNamespace(SetLabel=messages.append)
        f.metric=SimpleNamespace(GetSelection=lambda:0,Set=lambda values:None,SetSelection=lambda index:None)
        QuickPIFrame._invalidate(f)
        self.assertNotIn('result',f.bundle);self.assertNotIn('convergence',f.bundle);self.assertIsNone(f._inspection)
        self.assertEqual([row['terminal'] for row in f.bundle['request']['sinks']],['B','C'])
        self.assertTrue(draws)

    def test_selection_includes_source_and_every_sink_by_uuid_or_label(self):
        chosen=[]
        f=SimpleNamespace(bundle={'request':{'source_terminal':'A','sinks':[{'terminal':'B'},{'terminal':'C.1'}]},
                                 'geometry':{'terminals':[{'id':'A'},{'id':'B'},{'id':'C','label':'C.1'},{'id':'D'}]}},
                          _select_ids=chosen.extend)
        QuickPIFrame._select_terminals(f)
        self.assertEqual(chosen,['A','B','C'])

    def test_series_refine_rebuilds_request_from_current_inputs(self):
        edges=[];actions=[];messages=[]
        f=SimpleNamespace(edge=SimpleNamespace(GetValue=lambda:'.5',SetValue=edges.append),
                          model_dimension=control('',0),
                          bundle={'request':{'series':[{'id':'R1'}],'source_current_limit':2}},
                          _analyze=actions.append,status=SimpleNamespace(SetLabel=messages.append))
        QuickPIFrame._refine(f)
        self.assertEqual(edges,['0.25']);self.assertEqual(actions,['solve']);self.assertEqual(messages,[])

    def test_native_load_editor_adds_updates_removes_and_invalidates(self):
        import wx
        global _native_app
        _native_app=wx.GetApp() or wx.App(False)
        window=wx.Frame(None);invalidations=[]
        window._busy=False;window._series_request=None;window._extra_sinks=[]
        window._terminals=[{'id':name,'label':name+'.1'} for name in ('A','B','C')]
        window.source=wx.Choice(window,choices=['A','B','C']);window.source.SetSelection(0)
        window.sink=wx.Choice(window,choices=['A','B','C']);window.sink.SetSelection(1)
        window.loads_button=wx.Button(window);window._invalidate=lambda:invalidations.append(True)
        try:
            def drive(dialog):
                children=dialog.GetChildren();pad=next(item for item in children if isinstance(item,wx.Choice))
                table=next(item for item in children if isinstance(item,wx.ListCtrl))
                current,minimum,maximum=[item for item in children if isinstance(item,wx.TextCtrl)]
                def click(label):
                    button=next(item for item in children if isinstance(item,wx.Button) and item.GetLabel()==label)
                    button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,button.GetId()))
                pad.SetSelection(2);current.ChangeValue('.6');minimum.ChangeValue('3');maximum.ChangeValue('3.4');click('Add sink')
                self.assertEqual(table.GetItemCount(),1);self.assertEqual(table.GetItemText(0,1),'0.6')
                table.Select(0);current.ChangeValue('.4');click('Update selected')
                self.assertEqual(table.GetItemText(0,1),'0.4')
                table.Select(0);click('Remove selected');self.assertEqual(table.GetItemCount(),0)
                click('Add sink');self.assertEqual(table.GetItemCount(),1)
                return wx.ID_OK
            with patch.object(wx.Dialog,'ShowModal',drive):QuickPIFrame.on_loads(window)
            self.assertEqual(window._extra_sinks,[{'terminal':'C','current_A':.4,'min_voltage_V':3,'max_voltage_V':3.4}])
            self.assertEqual(invalidations,[True])
        finally:
            window.Destroy();wx.CallLater(50,_native_app.ExitMainLoop);_native_app.MainLoop()


if __name__=='__main__':unittest.main()
