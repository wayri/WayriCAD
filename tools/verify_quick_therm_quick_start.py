"""Exercise the real default GUI/worker flow with power and ambient only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-python',type=Path,required=True)
    parser.add_argument('--hold',action='store_true')
    parser.add_argument('--capture',type=Path)
    args=parser.parse_args()
    import wx
    from quick_therm_plugin.ui import QuickThermFrame
    board=ROOT/'quick_therm_plugin/examples/thermal-demo.kicad_pcb'
    before=hashlib.sha256(board.read_bytes()).hexdigest()
    app=wx.App.Get() or wx.App(False)
    state={'phase':'inspect','error':None};started=time.monotonic()
    with patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value=args.worker_python):
        frame=QuickThermFrame(None,board);frame.SetSize((1440,1000));frame.Show()
        def check():
            try:
                if state['phase']=='done':return
                if time.monotonic()-started>90:raise RuntimeError('Quick-start workflow exceeded 90 seconds: '+frame.status.GetLabel())
                if state['phase']=='inspect' and frame.inventory and not frame._busy:
                    assert frame.therm_model_enabled.GetValue(),'Default board model disabled'
                    expected=1 if frame.inventory.get('thermal_stackup',{}).get('available') else 0
                    assert frame.therm_model_kind.GetSelection()==expected,'Choose only supported saved geometry'
                    assert not frame.therm_step_models.GetValue(),'STEP must be optional for a board solve'
                    refs=['C1','C2'];powers={'C1':{'power_w':.25},'C2':{'power_w':.5}}
                    for ctrl in (frame.therm_power,frame.therm_ja,frame.therm_jb,frame.therm_jc,
                                 frame.therm_limit_min,frame.therm_limit_max):ctrl.SetValue('')
                    frame.manual_values=powers
                    frame.therm_inputs.load(frame.inventory,{},powers,refs,{})
                    frame._component_inputs_changed(frame.therm_inputs.export_state())
                    frame.therm_ambient.SetValue('25 C')
                    state['phase']='solve';frame.on_quick_therm()
                elif state['phase']=='solve' and not frame._busy:
                    if not frame.thermal_bundle:
                        raise RuntimeError('No result: '+frame.status.GetLabel()+' / '+frame.therm_status.GetLabel())
                    bundle=frame.thermal_bundle;network=bundle['thermal_network']
                    assert network['status']=='converged',network['status']
                    assert bundle['quick_therm']['ambient_c']==25
                    assert abs(bundle['quick_therm']['total_scoped_power_w']-.75)<1e-12
                    assert all(row.get('junction_c') is None for row in network['components'])
                    assert 'power sources modeled' in frame.therm_status.GetLabel()
                    assert 'Included power 0.75 W' in frame.therm_analytics.GetLabel()
                    assert hashlib.sha256(board.read_bytes()).hexdigest()==before,'Source was modified'
                    print(json.dumps({'status':'PASS','inputs':'C1=0.25 W; C2=0.5 W; ambient=25 C',
                        'model':'automatic supported board screening','junctions':'unknown without package data',
                        'heat_balance':network['heat_balance'],'source_unchanged':True}),flush=True)
                    frame._toggle_thermal_pane(frame.therm_setup_splitter,frame._therm_input_page,
                                              frame.therm_result_splitter,True,340)
                    frame.therm_setup_toggle.SetValue(True)
                    state['phase']='done'
                    if args.capture:
                        frame.main_panel.Layout();frame.Refresh();frame.Update();wx.Yield()
                        import ctypes
                        if ctypes.windll.user32.GetForegroundWindow()!=frame.GetHandle():
                            print('CAPTURE SKIPPED: test window is not foreground; no desktop/private content captured.',flush=True)
                        else:
                            size=frame.main_panel.GetClientSize();bitmap=wx.Bitmap(size.width,size.height)
                            memory=wx.MemoryDC(bitmap)
                            memory.Blit(0,0,size.width,size.height,wx.ClientDC(frame.main_panel),0,0)
                            memory.SelectObject(wx.NullBitmap);image=bitmap.ConvertToImage()
                            if image.HasAlpha():image.ClearAlpha()
                            args.capture.parent.mkdir(parents=True,exist_ok=True)
                            image.SaveFile(str(args.capture),wx.BITMAP_TYPE_PNG)
                            args.capture.with_suffix('.json').write_text(json.dumps({
                                'scope':'Actual native public-demo board screen; illustrative assumptions, not measured temperatures',
                                'source_sha256':before,'image_sha256':hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                                'inputs':powers,'ambient_c':25,'redaction':'None; public fixture basename only'},indent=2),encoding='utf-8')
                    if not args.hold:frame.Close()
            except Exception as exc:
                state['error']=str(exc);print('FAIL: '+str(exc),flush=True);frame.Close();return
            if state['phase']!='done':wx.CallLater(150,check)
        wx.CallLater(150,check);app.MainLoop()
    return 1 if state['error'] or state['phase']!='done' else 0


if __name__=='__main__':raise SystemExit(main())
