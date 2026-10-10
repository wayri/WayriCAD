"""Bounded native QuickTherm STEP/RC acceptance; uses public demo geometry."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plugin-root',type=Path)
    parser.add_argument('--output',type=Path,default=Path('.native-temp/component-heating'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    if args.plugin_root:
        sys.path[:]=[str(args.plugin_root.resolve()),*[p for p in sys.path if p and 'kiWay' not in p]]
        import quickmain
        package=quickmain.package()
    else:
        sys.path.insert(0,str(root));package='quick_therm_plugin'
    import pcbnew as p
    import wx
    models=importlib.import_module('.component_models',package)
    service=importlib.import_module('.service',package)
    review=importlib.import_module('.thermal_review',package)
    report=importlib.import_module('.report',package)
    ui=importlib.import_module('.ui',package)
    storage_inputs=importlib.import_module('.component_storage_inputs',package)
    if args.plugin_root:
        for module in (models,service,review,report,ui,storage_inputs):
            assert Path(module.__file__).resolve().is_relative_to(args.plugin_root.resolve()),module.__file__
    args.output.mkdir(parents=True,exist_ok=True);output=args.output.resolve()
    _,_,cad=models.discover()
    box=output/'validation-box.step'
    subprocess.run([cad,'-c',"import FreeCAD; import Part; Part.makeBox(4,2,3).exportStep("+repr(str(box))+")"],
                   check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    board=p.LoadBoard(str(root/'quick_therm_plugin/examples/thermal-demo.kicad_pcb'))
    footprints={fp.GetReference():fp for fp in board.GetFootprints()}
    for ref in ('C1','C2'):
        fp=footprints[ref];fp.Models().clear()
        model=p.FP_3DMODEL();model.m_Filename=str(box);fp.Models().push_back(model)
    footprints['C1'].SetOrientationDegrees(90)
    if not footprints['C2'].IsFlipped():footprints['C2'].Flip(footprints['C2'].GetPosition(),True)
    footprints['C2'].SetOrientationDegrees(0)
    path=output/'thermal-rc-demo.kicad_pcb';p.SaveBoard(str(path),board)
    stackup='''(stackup (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4"))
      (layer "B.Cu" (type "copper") (thickness 0.035)))'''
    path.write_text(path.read_text(encoding='utf-8').replace('(setup\n','(setup\n'+stackup+'\n',1),encoding='utf-8')
    before=hashlib.sha256(path.read_bytes()).hexdigest();model_before=hashlib.sha256(box.read_bytes()).hexdigest()
    request={'action':'quick_therm','board_path':str(path),'expected_source_sha256':before,
        'environment':'air','ambient_c':20,'references':['C1','C2'],'input_mode':'manual',
        'manual_values':{'C1':{'power_w':1},'C2':{'power_w':.5}},'board_power_only':True,
        'thermal_model_kind':'multilayer','thermal_network_settings':{
            'dielectric_k_w_mk':.3,'copper_k_w_mk':385,'via_plating_mm':.025,
            'grid_cells_long_axis':24,'board_emissivity':.85,'board_airflow_m_s':0,
            'component_storage':{'C1':{'temperature_kind':'body','resistance_k_per_w':10,'capacity_j_k':.2},
                                 'C2':{'temperature_kind':'junction','resistance_k_per_w':5,'capacity_j_k':.1}}},
        'transient_settings':{'duration_s':10,'timestep_s':.25,'initial_c':20,
            'copper_volumetric_capacity_j_m3k':3450000,'dielectric_volumetric_capacity_j_m3k':1800000,
            'schedule_interpolation':'step','power_schedules':{'C1':[[0,1],[4,0]]}}}
    # Use the real worker/STEP integration. Only runtime discovery is pinned to
    # the native executable already running this acceptance check.
    from unittest.mock import patch
    progress=[]
    def on_progress(item):
        assert item['stage'] and 0<=item['percent']<=100 and item['elapsed_s']>=0
        progress.append(item)
    request['load_step_models']=True
    with patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value=Path(sys.executable)):
        bundle=service.run_job(request,progress=on_progress)
    solids=bundle['board_thermal_view']['component_models']
    assert {'C1','C2'}<=set(solids['components']),solids
    assert any(item['stage']=='Read STEP component surfaces' for item in progress)
    thickness=p.ToMM(board.GetDesignSettings().GetBoardThickness())
    top=solids['components']['C1']['bounds_mm'];bottom=solids['components']['C2']['bounds_mm']
    assert abs(top[2]-thickness)<.1 and abs(top[5]-top[2]-3)<1e-4,('top Z',top,thickness)
    assert abs(bottom[2]-bottom[5]+3)<1e-4 and abs(bottom[5])<.1,('bottom Z',bottom,thickness)
    assert abs(top[3]-top[0]-2)<1e-4 and abs(top[4]-top[1]-4)<1e-4,('rotated XY',top)
    network=bundle['thermal_network'];frames=network['transient']['frames']
    first=review.transient_frame_network(network,0);final=review.transient_frame_network(network,len(frames)-1)
    assert all(row['component_temperature_c']==20 for row in first['components'])
    assert next(row for row in final['components'] if row['reference']=='C1')['junction_c'] is None
    assert all(row['component_temperature_c']>20 for row in final['components'])
    assert network['transient']['max_energy_residual_w']<1e-7
    app=wx.App(False);wx.LogStderr()
    with patch.object(ui.QuickThermFrame,'_inspect'):
        frame=ui.QuickThermFrame(None,path)
    frame.inventory=service.execute({'action':'inspect','board_path':str(path)})
    frame._busy=False;frame.status.SetLabel('Component heating ready.')
    frame.therm_refs.Set(frame.inventory['component_references'])
    frame.therm_inputs.load(frame.inventory,{},request['manual_values'],['C1','C2'],{})
    frame.therm_inputs._notify()
    frame.therm_time_enabled.SetValue(True);frame._transient_setup_changed()
    frame.therm_time_duration.SetValue('10');frame.therm_time_step.SetValue('.25')
    frame.SetSize((1400,900));frame.Show();frame._accept_therm(bundle);frame._set_thermal_view('3D overview')
    for _ in range(3):app.Yield()
    # Exercise the real modal table and its rejected-value path, not only its parser.
    import wx.grid
    table_check={}
    def edit_table():
        dialog=next(window for window in wx.GetTopLevelWindows()
                    if isinstance(window,wx.Dialog) and window.GetTitle()=='Component heating · thermal RC')
        grid=next(child for child in dialog.GetChildren() if isinstance(child,wx.grid.Grid))
        grid.SetCellValue(0,1,'1');grid.SetCellValue(0,3,'12');grid.SetCellValue(0,4,'nan')
        dialog.ProcessWindowEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
        table_check['invalid_kept_open']=dialog.IsModal()
        grid.SetCellValue(0,4,'.3');grid.SetCellValue(0,6,'20');grid.SetCellValue(0,7,'5')
        grid.SetCellValue(0,8,'.8');grid.SetCellValue(0,9,'1')
        dialog.ProcessWindowEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
    wx.CallLater(50,edit_table)
    edited=storage_inputs.edit_storage(frame,['C1'],{})
    assert table_check['invalid_kept_open'] and edited['C1']['capacity_j_k']==.3
    assert edited['C1']['contact_pad_number']=='1' and edited['C1']['exposed_area_mm2']==20
    def capture(name):
        frame.Layout();frame.therm_canvas.draw()
        wx.CallLater(60,app.ExitMainLoop);app.MainLoop()
        frame.Update()
        width,height=frame.GetClientSize();bitmap=wx.Bitmap(width,height,24);memory=wx.MemoryDC(bitmap)
        memory.Blit(0,0,width,height,wx.ClientDC(frame),0,0);memory.SelectObject(wx.NullBitmap)
        bitmap.ConvertToImage().SaveFile(str(output/name),wx.BITMAP_TYPE_PNG)
    assert frame.therm_figure.axes[0]._thermal_step_parts==sorted(solids['components'])
    capture('component-initial.png')
    frame.therm_time_slider.SetValue(len(frames)-1);frame._scrub_thermal_time()
    assert frame.therm_result_time.GetSelection()==len(frames)
    capture('component-final.png')
    report.write_report(output/'component-heating.html',bundle)
    html=(output/'component-heating.html').read_text(encoding='utf-8')
    assert 'vertices_mm' in html and 'storage_node' in html and 'validation-box.step' not in html
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert hashlib.sha256(box.read_bytes()).hexdigest()==model_before
    evidence={'loaded':sorted(solids['components']),'top_bounds_mm':top,'bottom_bounds_mm':bottom,
        'frames':len(frames),'max_energy_residual_w':network['transient']['max_energy_residual_w'],
        'final_components':final['components'],'source_unchanged':True,'model_unchanged':True}
    evidence['native_rc_table_validated']=True
    (output/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    frame.Destroy();app.Yield();print(json.dumps(evidence),flush=True)


if __name__=='__main__':
    import threading
    watchdog=threading.Timer(120,lambda:os._exit(3));watchdog.daemon=True;watchdog.start()
    main();sys.stdout.flush();os._exit(0)
