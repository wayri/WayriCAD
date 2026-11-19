"""Native Run request construction without downloads or board writes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = r'''
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import wx
from quick_therm_plugin.ui import QuickThermFrame
from quick_therm_plugin import setup_file
app=wx.App(False)
with patch.object(QuickThermFrame,'_inspect'):
    frame=QuickThermFrame(None,Path(sys.argv[1])/'quick_therm_plugin/examples/thermal-demo.kicad_pcb')
    try:
        frame.inventory={'component_references':['U1','U2'],
            'components':[{'reference':'U1'},{'reference':'U2'}],
            'thermal_stackup':{'available':False},'source_sha256':'a'*64}
        frame.therm_refs.Set(['U1','U2'])
        frame.therm_inputs.load(frame.inventory,{}, {'U1':{'power_w':.5}},[],{})
        frame._component_inputs_changed(frame.therm_inputs.export_state())
        frame.therm_model_enabled.SetValue(False)
        frame.therm_model_kind.SetSelection(2)
        frame.therm_auto_mesh.SetValue(False)
        frame.therm_dielectric_k.ChangeValue('.7')
        frame.therm_k.ChangeValue('')
        frame.therm_ambient.ChangeValue('')
        requests=[]
        with patch.object(frame,'_job',lambda request,*args:requests.append(request)):
            frame.on_quick_therm()
        assert len(requests)==1,frame.therm_status.GetLabel()
        request=requests[-1]
        assert request['references']==['U1'],'Unknown U2 must not become zero power'
        assert request['board_power_only'] and request['ambient_c']==20
        assert request['thermal_network_settings']['mesh_mode']=='auto'
        assert request['thermal_network_settings']['board_k_w_mk']==.3
        assert frame.therm_dielectric_k.GetValue()=='.7','Edited materials must survive'
        assert frame.therm_model_kind.GetSelection()==0
        assert 'calculix_run' not in request,'Automatic runs must not need an external solver'
        # A reloaded supported stackup is reevaluated on the next Run.
        frame.inventory['thermal_stackup']['available']=True
        with patch.object(frame,'_job',lambda request,*args:requests.append(request)):
            frame.on_quick_therm()
        assert requests[-1]['thermal_model_kind']=='multilayer'
        assert requests[-1]['thermal_network_settings']['dielectric_k_w_mk']==.7
        # Explicit model/mesh actions leave automatic mode rather than being overwritten.
        frame.therm_auto_mesh.SetValue(False)
        frame._manual_mesh_changed(wx.CommandEvent(wx.EVT_CHECKBOX.typeId,frame.therm_auto_mesh.GetId()))
        assert not frame.therm_auto_setup.GetValue()
        with patch.object(frame,'_job',lambda request,*args:requests.append(request)):
            frame.on_quick_therm()
        assert requests[-1]['thermal_network_settings']['mesh_mode']=='manual'
        # Old saved studies retain their advanced choices; new studies round-trip the flag.
        state=setup_file.capture(frame)
        assert state['controls']['flags']['therm_auto_setup'] is False
        del state['controls']['flags']['therm_auto_setup']
        migrated=setup_file.validate(frame,state)
        assert migrated['controls']['flags']['therm_auto_setup'] is False
        assert 'therm_auto_setup' not in state['controls']['flags'],'Validation must not mutate input'
        setup_file.restore(frame,migrated)
        # An explicit scope with unknown power cannot be silently reduced.
        frame.therm_auto_setup.SetValue(True)
        frame.therm_inputs.model.set_included('U2',True)
        frame.therm_inputs._notify()
        count=len(requests)
        with patch.object(frame,'_job',lambda request,*args:requests.append(request)):
            frame.on_quick_therm()
        assert len(requests)==count and 'U2' in frame.status.GetLabel()
        # Advanced physics cannot silently fall back to a different model.
        frame.inventory['thermal_stackup']['available']=False
        frame.therm_time_enabled.SetValue(True)
        with patch.object(frame,'_job',lambda request,*args:requests.append(request)):
            frame.on_quick_therm()
        assert len(requests)==count and 'saved physical stackup' in frame.status.GetLabel()
    finally:
        frame.Destroy();app.Yield()
print('Native one-click Run checks passed')
'''


class OneClickRunTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('wx'), 'wxPython required')
    def test_automatic_run_and_advanced_study_safeguards(self):
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-B','-c',SCRIPT,str(root)],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('Native one-click Run checks passed',result.stdout)
