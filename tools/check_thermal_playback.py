"""Bounded native transient air/vacuum playback and installed-package check.

Uses the public thermal demo, real worker service, wx controls and computed
frames. Pass --plugin-root for an isolated PCM plugins directory.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plugin-root',type=Path)
    parser.add_argument('--output',type=Path,default=Path('.native-temp/thermal-playback'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    if args.plugin_root:
        sys.path[:]=[str(args.plugin_root.resolve()),*[entry for entry in sys.path if entry and 'kiWay' not in entry]]
        import quickmain
        package=quickmain.package()
    else:
        sys.path.insert(0,str(root));package='quick_therm_plugin'
    import wx
    ui=importlib.import_module('.ui',package)
    QuickThermFrame=ui.QuickThermFrame
    execute=importlib.import_module('.service',package).execute
    write_report=importlib.import_module('.report',package).write_report
    if args.plugin_root:assert Path(ui.__file__).resolve().is_relative_to(args.plugin_root.resolve())
    source=root/'quick_therm_plugin/examples/thermal-demo.kicad_pcb'
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    args.output.mkdir(parents=True,exist_ok=True)
    target=(args.output/'thermal-transient-demo.kicad_pcb').resolve()
    # Declare the public fixture's assumed stackup for this numerical check.
    # The original demonstration PCB and user boards are never rewritten.
    stackup='''(stackup
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4"))
      (layer "B.Cu" (type "copper") (thickness 0.035)))'''
    target.write_text(source.read_text(encoding='utf-8').replace('(setup\n','(setup\n'+stackup+'\n',1),encoding='utf-8')
    original=hashlib.sha256(target.read_bytes()).hexdigest()
    app=wx.App(False)
    # Keep sandbox-denied preference logging from opening a second modal loop.
    diagnostic_log=wx.LogStderr();wx.Log.SetActiveTarget(diagnostic_log)
    watchdog=threading.Timer(90,lambda:os._exit(2));watchdog.daemon=True;watchdog.start()
    inventory=execute({'action':'inspect','board_path':str(target)})
    with patch.object(QuickThermFrame,'_inspect'):
        frame=QuickThermFrame(None,target);frame.Show()
        for _ in range(3):app.Yield()
        frame.inventory=inventory;frame.therm_refs.Set(inventory['component_references'])
        restored_field_mapping=importlib.import_module('.quick_therm',package).restored_field_mapping
        mapping=restored_field_mapping(inventory['field_names'])
        for ctrl,key in ((frame.therm_power,'power_w'),(frame.therm_ja,'theta_ja_air_k_per_w'),
                         (frame.therm_jb,'theta_jb_k_per_w'),(frame.therm_jc,'theta_jc_k_per_w')):
            ctrl.Set(['',*inventory['field_names']]);ctrl.SetValue(mapping[key])
        frame.therm_inputs.load(inventory,mapping,{},['C1','C2','C3','J1'],{})
        frame.therm_inputs._notify()
        frame.therm_time_enabled.SetValue(True)
        event=wx.CommandEvent(wx.EVT_CHECKBOX.typeId,frame.therm_time_enabled.GetId())
        event.SetEventObject(frame.therm_time_enabled)
        frame.therm_time_enabled.GetEventHandler().ProcessEvent(event)
        assert frame.therm_model_enabled.GetValue() and frame.therm_model_kind.GetSelection()==1
        assert not frame.therm_transient_pane.IsCollapsed()
        frame.therm_dielectric_k.ChangeValue('.3');frame.therm_plating.ChangeValue('.025')
        frame.therm_grid.SetValue(24);frame.therm_emissivity.ChangeValue('.8')
        frame.therm_time_duration.ChangeValue('10');frame.therm_time_step.ChangeValue('.5')
        frame.therm_power_schedule.ChangeValue('{"C2":[[0,1],[4,0]]}')
        frame.therm_schedule_interpolation.SetSelection(1)
        def edit_steps():
            import wx.grid
            dialog=next(w for w in wx.GetTopLevelWindows() if w.GetTitle()=='Transient power steps')
            if not dialog.IsModal():
                wx.CallLater(50,edit_steps);return
            grid=next(child for child in dialog.GetChildren() if isinstance(child,wx.grid.Grid))
            row=next(i for i in range(grid.GetNumberRows()) if grid.GetCellValue(i,0)=='C2')
            grid.SetCellValue(row,3,'4');grid.SetCellValue(row,4,'0')
            event=wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK)
            dialog.GetEventHandler().ProcessEvent(event)
        def open_steps():
            wx.CallLater(80,edit_steps);frame._edit_power_steps();app.ExitMainLoop()
        wx.CallLater(50,open_steps);app.MainLoop()
        assert json.loads(frame.therm_power_schedule.GetValue())['C2']==[[0,1],[4,0]]
        requests=[];evidence={}
        def run(request,finished,message):
            requests.append(request);finished(execute(request))
        def capture(name):
            frame.Layout();frame.therm_canvas.draw()
            for _ in range(3):app.Yield()
            frame.Update();width,height=frame.GetClientSize()
            bitmap=wx.Bitmap(width,height,24);memory=wx.MemoryDC(bitmap)
            memory.Blit(0,0,width,height,wx.ClientDC(frame),0,0);memory.SelectObject(wx.NullBitmap)
            bitmap.ConvertToImage().SaveFile(str(args.output/name),wx.BITMAP_TYPE_PNG)
        try:
            for environment in (0,1):
                frame.therm_env.SetSelection(environment);frame._thermal_environment_changed()
                assert frame.therm_air_board.IsEnabled()==(environment==0)
                with patch.object(frame,'_job',run):frame.on_quick_therm()
                assert frame.thermal_bundle,frame.therm_status.GetLabel()
                frame.status.SetLabel('Transient study ready.')
                frames=frame._thermal_frames();network=frame.thermal_bundle['thermal_network']
                assert frames[0]['time_s']==0 and frames[-1]['time_s']==10
                assert max(frames[-1]['temperatures_c'])>max(frames[0]['temperatures_c'])
                assert network['transient']['max_energy_residual_w']<1e-7
                if environment==1:
                    assert requests[-1]['thermal_network_settings']['board_h_w_m2k']==0
                    assert not frame.therm_air_board.IsEnabled()
                frame._set_thermal_view('3D overview');frame.therm_canvas.draw()
                ax=frame.therm_figure.axes[0];ax.view_init(elev=37,azim=-24)
                ax.set_xlim((5,55));limits=ax.get_xlim()
                norm=(ax._thermal_norm.vmin,ax._thermal_norm.vmax)
                if environment==1:capture('vacuum-initial.png')
                frame._toggle_thermal_playback();assert frame._thermal_playing
                # Allow the actual wx timer to advance a computed stored frame.
                # wx timers are dispatched by the native event loop, not Yield
                # alone on this Windows/wx build. Keep the loop bounded.
                wx.CallLater(800,app.ExitMainLoop)
                app.MainLoop()
                assert frame.therm_result_time.GetSelection()>1,('wx timer did not advance',frame._thermal_playing,
                    frame._thermal_timer.IsRunning(),frame._busy,frame.status.GetLabel(),len(frames))
                if not frame._thermal_playing:
                    assert frame.therm_result_time.GetSelection()==len(frames)
                    frame._toggle_thermal_playback()  # replay from the start
                frame._toggle_thermal_playback();assert not frame._thermal_timer.IsRunning()
                assert frame.therm_figure.axes[0].get_xlim()==limits
                assert frame.therm_figure.axes[0].elev==37 and frame.therm_figure.axes[0].azim==-24
                frame.therm_time_slider.SetValue(len(frames)-1)
                slider_event=wx.CommandEvent(wx.EVT_SLIDER.typeId,frame.therm_time_slider.GetId())
                frame.therm_time_slider.GetEventHandler().ProcessEvent(slider_event)
                ax=frame.therm_figure.axes[0]
                assert (ax._thermal_norm.vmin,ax._thermal_norm.vmax)==norm
                assert next(row for row in frame._display_network()['components'] if row['reference']=='C2')['power_w']==0
                frame._add_thermal_probe(30,20,'3D overview')
                assert frame.thermal_bundle['probes'][0]['temperature_c'] is not None
                capture(('vacuum' if environment else 'air')+'-heated.png')
                if environment==1:
                    write_report(args.output/'thermal-playback.html',frame.thermal_bundle)
                evidence['vacuum' if environment else 'air']={'frames':len(frames),
                    'initial_peak_c':max(frames[0]['temperatures_c']),
                    'final_peak_c':max(frames[-1]['temperatures_c']),
                    'max_energy_residual_w':network['transient']['max_energy_residual_w'],
                    'canvas_px':list(frame.therm_canvas.GetSize()),'fixed_scale_c':norm}
            completed_bundle=frame.thermal_bundle
            frame._toggle_thermal_playback();assert frame._thermal_playing
            frame._invalidate_thermal();assert not frame._thermal_timer.IsRunning()
            assert not frame.therm_play.IsEnabled() and not frame.therm_export.IsEnabled()
            assert hashlib.sha256(target.read_bytes()).hexdigest()==original
            assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
            evidence['source_unchanged']=True
            (args.output/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
            print(json.dumps(evidence),flush=True)
            frame._accept_therm(completed_bundle);frame._toggle_thermal_playback()
            frame.Close();assert not frame._thermal_timer.IsRunning();app.Yield()
            watchdog.cancel()
        finally:
            if not frame._closed:frame.Close()


if __name__=='__main__':
    try:main();sys.stdout.flush();sys.stderr.flush();os._exit(0)
    except BaseException:
        import traceback
        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
