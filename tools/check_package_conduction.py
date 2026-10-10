"""Bounded native PI/contact/thermal acceptance using generated public geometry.

Run with KiCad's Python. Optional extracted PCM plugin roots exercise the same
workflow without source-package imports. This is a numerical/GUI acceptance
fixture, not a qualified component or solder material model.
"""
import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading


def load_package(root, fallback):
    if root is None:
        return fallback
    root=root.resolve()
    spec=importlib.util.spec_from_file_location(fallback+'_entry',root/'quickmain.py')
    entry=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    return entry.package()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi-root',type=Path)
    parser.add_argument('--thermal-root',type=Path)
    parser.add_argument('--output',type=Path,default=Path('.native-temp/package-conduction'))
    parser.add_argument('--no-ui',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if bool(args.pi_root)!=bool(args.thermal_root):
        parser.error('Supply both extracted plugin roots, or neither.')
    if args.pi_root:
        # Avoid either source plugin or the source shared runtime. Both archives
        # must contain the shared contact editor and physical model themselves.
        sys.path[:]=[p for p in sys.path if p and not Path(p).resolve().is_relative_to(root)]
    else:
        sys.path.insert(0,str(root))
    pi_package=load_package(args.pi_root,'quick_pi_plugin')
    thermal_package=load_package(args.thermal_root,'quick_therm_plugin')
    pi=importlib.import_module('.service',pi_package)
    therm=importlib.import_module('.service',thermal_package)
    losses=importlib.import_module('.copper_loss_import',thermal_package)
    pi_report=importlib.import_module('.report',pi_package)
    thermal_report=importlib.import_module('.report',thermal_package)
    from wayricad_runtime.package_conduction import normalize_paths
    from wayricad_runtime.package_contact_editor import paths_from_rows
    if args.pi_root:
        assert Path(pi.__file__).resolve().is_relative_to(args.pi_root.resolve())
        assert Path(therm.__file__).resolve().is_relative_to(args.thermal_root.resolve())
        assert not Path(sys.modules['wayricad_runtime'].__file__).resolve().is_relative_to(root/'wayricad_runtime')
        for plugin in (args.pi_root,args.thermal_root):
            for name in ('package_conduction.py','package_contact_editor.py'):
                assert (plugin/'wayricad_runtime'/name).is_file()
            assert (plugin/'help.html').is_file()
    import pcbnew as p
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    board=p.BOARD();net=p.NETINFO_ITEM(board,'VCC');board.Add(net)
    point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
    for start,end in (((0,0),(30,0)),((30,0),(30,15)),((30,15),(0,15)),((0,15),(0,0))):
        edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start));edge.SetEnd(point(*end));edge.SetLayer(p.Edge_Cuts)
        edge.SetWidth(p.FromMM(.05));board.Add(edge)
    track=p.PCB_TRACK(board);track.SetStart(point(5,7.5));track.SetEnd(point(25,7.5))
    track.SetWidth(p.FromMM(1));track.SetLayer(p.F_Cu);track.SetNet(net);board.Add(track)
    for ref,x in (('J1',5),('U1',25)):
        fp=p.FOOTPRINT(board);fp.SetReference(ref);fp.SetPosition(point(x,7.5));board.Add(fp)
        pad=p.PAD(fp);pad.SetNumber('1');pad.SetPosition(point(x,7.5));pad.SetSize(point(1,1))
        pad.SetShape(p.PAD_SHAPE_RECT);pad.SetAttribute(p.PAD_ATTRIB_SMD)
        layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);pad.SetNet(net);fp.Add(pad)
    path=output/'contact-demo.kicad_pcb';p.SaveBoard(str(path),board)
    stackup='''(stackup (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4"))
      (layer "B.Cu" (type "copper") (thickness 0.035)))'''
    path.write_text(path.read_text(encoding='utf-8').replace('(setup\n','(setup\n'+stackup+'\n',1),encoding='utf-8')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    contacts=[{'id':ref+'-lead-solder','reference':ref,'pad_number':'1','layer_id':p.F_Cu,
        'port':port,'segments':[
            {'shape':'rectangular','length_mm':1,'width_mm':.3,'thickness_mm':.1,
             'rho_ohm_m':2e-8,'k_w_mk':200,'material':'illustrative test lead','evidence':'acceptance fixture'},
            {'shape':'spherical_ball','length_mm':.2,'diameter_mm':.4,
             'rho_ohm_m':1.3e-7,'k_w_mk':50,'material':'illustrative test solder','evidence':'acceptance fixture'}]}
        for ref,port in (('J1','source'),('U1','sink:U1.1'))]
    request={'action':'solve','board_path':str(path),'net':'VCC','source_terminal':'J1.1',
        'sink_terminal':'U1.1','source_voltage':3.3,'sink_current':2,'edge_mm':.4,
        'source_current_limit':3,'sink_min_voltage':3,'package_conduction':contacts}
    bundle=pi.execute(request);result=bundle['result']
    assert result['feasibility']['operating_point_valid'] is True
    assert result['energy_relative_error']<1e-7 and result['max_nodal_residual_A']<1e-7
    assert len(result['package_contacts'])==2
    assert abs(result['package_contacts'][0]['current_A']-2)<1e-7
    assert abs(result['package_contacts'][1]['current_A']+2)<1e-7
    expected=4*sum(row['electrical_resistance_ohm'] for row in normalize_paths(contacts,physics='electrical'))
    assert abs(result['package_power_W']-expected)<1e-10
    pi_report.write_report(output/'pi-contact.html',bundle)
    disk_bundle=json.loads((output/'pi-contact.json').read_text(encoding='utf-8'))
    imported=losses.import_losses(disk_bundle,before)
    thermal_contacts=[row['definition'] for row in result['package_contacts']]
    thermal_request={'action':'quick_therm','board_path':str(path),'expected_source_sha256':before,
        'environment':'air','ambient_c':20,'references':['J1','U1'],'input_mode':'manual',
        'manual_values':{'J1':{'power_w':.1},'U1':{'power_w':.2}},'thermal_model_kind':'multilayer',
        'copper_loss_binding':imported,'thermal_network_settings':{
            'dielectric_k_w_mk':.3,'copper_k_w_mk':385,'via_plating_mm':.025,
            'grid_cells_long_axis':36,'board_emissivity':.85,'board_airflow_m_s':0,
            'package_conduction':thermal_contacts,'copper_loss_sources':imported['sources'],
            'package_joule_losses':imported['package_joule_losses'],
            'component_storage':{ref:{'temperature_kind':'body','resistance_k_per_w':0,'capacity_j_k':.2}
                for ref in ('J1','U1')}},
        'transient_settings':{'duration_s':1,'timestep_s':.05,'initial_c':20,
            'copper_volumetric_capacity_j_m3k':3.45e6,'dielectric_volumetric_capacity_j_m3k':1.8e6}}
    thermal=therm.execute(thermal_request);network=thermal['thermal_network']
    total=.3+result['conductor_power_W']+result['package_power_W']
    assert abs(network['heat_balance']['input_w']-total)<1e-9
    assert abs(network['heat_balance']['residual_w'])<1e-4
    assert network['transient']['max_energy_residual_w']<1e-7
    assert len(network['package_conduction'])==2
    for contact in network['package_conduction']:
        assert abs(contact['heat_flow_to_board_w']-contact['heat_flow_from_package_w']-
                   contact['electrical_joule_heat_w'])<1e-10
    thermal_report.write_report(output/'thermal-contact.html',thermal)
    assert 'illustrative test solder' in (output/'thermal-contact.html').read_text(encoding='utf-8')
    evidence={'kicad':p.GetBuildVersion(),'python':sys.version.split()[0],
        'isolated_plugins':bool(args.pi_root),'source_unchanged':True,'package_loss_w':expected,
        'copper_loss_w':result['conductor_power_W'],'thermal_input_w':total,
        'pi_energy_relative_error':result['energy_relative_error'],
        'thermal_residual_w':network['heat_balance']['residual_w'],
        'transient_max_energy_residual_w':network['transient']['max_energy_residual_w'],
        'frames':len(network['transient']['frames'])}
    if not args.no_ui:
        import wx
        import wx.grid
        from unittest.mock import patch
        from wayricad_runtime.package_contact_editor import COLUMNS
        pi_ui=importlib.import_module('.ui',pi_package)
        thermal_ui=importlib.import_module('.ui',thermal_package)
        app=wx.App(False);wx.LogStderr()

        def capture(frame,name,canvas=None):
            frame.Layout()
            if canvas:canvas.draw()
            if not isinstance(frame,wx.Dialog):
                wx.CallLater(100,app.ExitMainLoop);app.MainLoop()
            frame.Update()
            w,h=frame.GetClientSize();bitmap=wx.Bitmap(w,h,24);dc=wx.MemoryDC(bitmap)
            dc.Blit(0,0,w,h,wx.ClientDC(frame),0,0);dc.SelectObject(wx.NullBitmap)
            bitmap.ConvertToImage().SaveFile(str(output/name),wx.BITMAP_TYPE_PNG)

        checks=[]
        def edit_contact_table(physics):
            dialog=next(w for w in wx.GetTopLevelWindows() if isinstance(w,wx.Dialog)
                        and w.GetTitle()=='Lead / solder / BGA contacts')
            grid=next(c for c in dialog.GetChildren() if isinstance(c,wx.grid.Grid))
            assert grid.GetCellValue(0,3)=='F.Cu'
            col=COLUMNS.index('rho Ω·m' if physics=='electrical' else 'k W/m/K')
            old=grid.GetCellValue(0,col);grid.SetCellValue(0,col,'nan')
            dialog.ProcessWindowEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
            assert dialog.IsModal()
            capture(dialog,'contacts-'+physics+'.png')
            grid.SetCellValue(0,col,old)
            dialog.ProcessWindowEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
            checks.append(physics)

        with patch.object(pi_ui.QuickPIFrame,'_inspect'):
            pi_frame=pi_ui.QuickPIFrame(None,path)
        pi_frame.inventory=pi.execute({'action':'inspect','board_path':str(path)})
        pi_frame._busy=False;pi_frame.net.Set(pi_frame.inventory['nets'])
        assert pi_frame.net.SetStringSelection('VCC')
        pi_frame._set_terminals()
        assert pi_frame.source.SetStringSelection('J1.1')
        assert pi_frame.sink.SetStringSelection('U1.1')
        pi_frame.voltage.ChangeValue('3.3');pi_frame.current.ChangeValue('2')
        pi_frame._package_conduction=contacts
        pi_frame.SetSize((1400,900));pi_frame.Show();pi_frame._accept_result(copy.deepcopy(bundle),request,'solve')
        for _ in range(3):app.Yield()
        edit_timer=wx.CallLater(50,lambda:edit_contact_table('electrical'))
        pi_frame.on_package_contacts()
        edit_timer.Stop()
        assert checks==['electrical'],pi_frame.status.GetLabel()
        assert len(pi_frame._package_conduction)==2
        # Editing invalidates old results as intended; accept a fresh result for capture.
        pi_frame._accept_result(copy.deepcopy(bundle),request,'solve')
        assert pi_frame.bundle.get('result')
        capture(pi_frame,'pi-contact-window.png')
        pi_frame.Hide()
        print('Native PI window and contact editor checked.',flush=True)
        with patch.object(thermal_ui.QuickThermFrame,'_inspect'):
            thermal_frame=thermal_ui.QuickThermFrame(None,path)
        print('Native thermal window created.',flush=True)
        thermal_frame.inventory=therm.execute({'action':'inspect','board_path':str(path)})
        thermal_frame._busy=False;thermal_frame.therm_refs.Set(['J1','U1'])
        thermal_frame.therm_inputs.load(thermal_frame.inventory,{},thermal_request['manual_values'],['J1','U1'],{})
        thermal_frame.therm_inputs._notify()
        thermal_frame._package_contacts=thermal_contacts;thermal_frame._package_contacts_board_sha=before
        thermal_frame._component_storage=thermal_request['thermal_network_settings']['component_storage']
        thermal_frame._component_storage_board_sha=before
        thermal_frame.SetSize((1400,900));thermal_frame.Show()
        edit_timer=wx.CallLater(50,lambda:edit_contact_table('thermal'))
        thermal_frame._edit_package_contacts()
        edit_timer.Stop()
        assert checks==['electrical','thermal'],thermal_frame.status.GetLabel()
        assert len(thermal_frame._package_contacts)==2
        thermal_frame.therm_time_enabled.SetValue(True);thermal_frame._transient_setup_changed()
        thermal_frame.therm_time_duration.ChangeValue('1');thermal_frame.therm_time_step.ChangeValue('.05')
        thermal_frame._accept_therm(thermal)
        thermal_frame.therm_time_slider.SetValue(len(network['transient']['frames'])-1)
        thermal_frame._scrub_thermal_time()
        capture(thermal_frame,'thermal-contact-window.png',thermal_frame.therm_canvas)
        evidence['native_editor_validation']=checks
        assert checks==['electrical','thermal']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    (output/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence),flush=True)
    if not args.no_ui:
        thermal_frame.Destroy();pi_frame.Destroy();app.Yield()


if __name__=='__main__':
    watchdog=threading.Timer(120,lambda:os._exit(3));watchdog.daemon=True;watchdog.start()
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc();sys.stderr.flush();os._exit(1)
    sys.stdout.flush();os._exit(0)
