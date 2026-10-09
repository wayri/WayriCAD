"""Check/capture the real native workspace using the public saved-board fixture.

Run with KiCad Python. --package-root can point at an extracted PCM plugins/
directory to verify independent deployment. Outputs contain no private board.
"""
import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch


def check(args):
    root=Path(__file__).resolve().parents[1]
    plugin=Path(args.package_root).resolve() if args.package_root else root/'mechanical_check_plugin'
    sys.path[:0]=[str(plugin/'src'),str(plugin)]
    if not args.package_root:sys.path.insert(0,str(root))
    import wx
    from OpenGL import GL, GLU
    from wayricad_mechanical.ui import Window
    from wayricad_mechanical.runner import run
    from wayricad_mechanical.config import validate
    from wayricad_mechanical.measurement_service import MeasurementSession
    from wayricad_mechanical.inspection_state import measurement_text
    import wayricad_mechanical, wayricad_runtime
    if args.package_root:
        assert Path(wayricad_mechanical.__file__).is_relative_to(plugin)
        assert Path(wayricad_runtime.__file__).is_relative_to(plugin)
    board=root/'mechanical_check_plugin/tests/fixtures/validation-fixture.kicad_pcb'
    before=hashlib.sha256(board.read_bytes()).hexdigest()
    session=MeasurementSession()
    result=run(board,validate({'mode':args.mode,'project_name':'Mechanical Check demonstration',
                               'top_height_mm':2,'bottom_height_mm':.05,'proximity_warning_mm':20}),
               measurement_session=session)
    app=wx.App(False);wx.Log.EnableLogging(False)
    window=Window(str(board));window.config=result['rules']
    for key,control in window.numbers.items():control.SetValue(result['rules'][key])
    window.mode.SetSelection(0 if args.mode=='quick2d' else 1)
    window.result=result;window.scene.set_report(result);window.refresh_result();window.show_step(3)
    window.measurement_session=session
    screen=wx.Display().GetClientArea()
    window.SetSize((min(1200,screen.width-40),min(820,screen.height-40)))
    window.SetPosition((screen.x+20,screen.y+20));window.Show();window.Raise()
    scene=window.scene

    def settle():
        for _ in range(6):app.Yield();window.Update();time.sleep(.025)

    deadline=time.monotonic()+8
    while not scene.index.ready and time.monotonic()<deadline:settle()
    assert scene.index.ready
    settle();scene.fit();settle()
    width,height=window.GetClientSize();cw,ch=scene.GetClientSize()
    assert cw/width>.65 and ch/height>.70,(cw,ch,width,height)
    assert not scene.grid and not scene.ghost
    assert window.get_config()['proximity_warning_mm']==20
    height_issues=[issue for issue in result['findings'] if issue['rule']=='height.maximum']
    warning_issues=[issue for issue in result['findings'] if issue['rule'].endswith('proximity_warning')]
    assert warning_issues,'Fixture should exercise the configured proximity warning'
    assert scene.orthographic==(args.mode=='quick2d')
    if args.mode=='quick2d':
        assert not height_issues,'2D envelopes cannot establish part height'
        assert 'heights unchecked' in window.geometry_mode.GetLabel()
        with patch('wayricad_mechanical.ui.discover',return_value={'freecad_python':None}):
            window.show_3d()
        assert window.step==0 and 'FreeCAD' in window.status.GetLabel()
        window.show_step(3)
        with patch('wayricad_mechanical.ui.discover',return_value={'freecad_python':'available'}),patch.object(window,'start') as start:
            window.show_3d();start.assert_called_once()
        window.mode.SetSelection(0)
    else:
        assert height_issues and any(issue['side']=='top' for issue in height_issues)
        assert all(math.isclose(issue['excess_mm'],issue['measured']-issue['limit'],abs_tol=1e-7) for issue in height_issues)
        assert window.view_3d.GetLabel()=='3D view'
        assert any(body['kind']=='board' and body['bounds'][5]>body['bounds'][2] for body in result['bodies'])
        window.view('top');settle();window.show_3d();settle()
        assert not scene.orthographic and scene.pitch<1.5
    window.view('top');scene.fit();settle()
    # Native drag handlers alter the camera without losing the scene/index.
    previous=(scene.yaw,scene.pitch)
    scene.drag=(wx.Point(100,100),False)
    motion=wx.MouseEvent(wx.wxEVT_MOTION);motion.SetPosition(wx.Point(140,125))
    scene.motion(motion);scene.drag=None;settle()
    assert (scene.yaw,scene.pitch)!=previous
    window.view('top');scene.fit();settle()
    # Use real ray picks, avoiding assumptions about a model's bounding-box center.
    hits=[]
    scene.SetCurrent(scene.context)
    model=GL.glGetDoublev(GL.GL_MODELVIEW_MATRIX);projection=GL.glGetDoublev(GL.GL_PROJECTION_MATRIX)
    viewport=GL.glGetIntegerv(GL.GL_VIEWPORT);scale=scene.GetContentScaleFactor()
    for ref in ('C3','J1'):
        body=next(item for item in result['bodies'] if item['ref']==ref)
        for face in body['mesh']['faces']:
            point=[sum(body['mesh']['vertices'][index][axis] for index in face)/3 for axis in range(3)]
            pixel=GLU.gluProject(*point,model,projection,viewport)
            hit=scene.pick(wx.Point(round(pixel[0]/scale),round(scene.GetClientSize().height-pixel[1]/scale)))
            if hit and hit['reference']==ref:hits.append(hit);break
        assert len(hits)==('C3','J1').index(ref)+1,ref
    scene.set_mode('points');scene.inspection.click(hits[0])
    ruler=scene.inspection.click(hits[1]);window.point_ruler(ruler)
    assert math.isclose(ruler['distance_mm'],math.dist(*ruler['points']))
    feature_kinds=[]
    if args.mode=='exact3d':
        def query():
            window.measure_selected_parts(None)
            deadline=time.monotonic()+15
            while window.measuring and time.monotonic()<deadline:settle()
            assert not window.measuring,window.measure_readout.GetValue()
            active=scene.inspection.active
            assert active and active['type']=='feature_ruler',window.measure_readout.GetValue()
            feature_kinds.append(active['measurement_kind'])
            return active
        for mode,kind in ((3,'edge_edge'),(5,'center_center')):
            window.measure_mode.SetSelection(mode);window.change_measure_mode(None)
            window.part_a.SetValue('C1');window.part_b.SetValue('C3')
            assert query()['measurement_kind']==kind
        centers=scene.inspection.active
        bodies={b['ref']:b for b in result['bodies']}
        assert math.isclose(centers['distance_mm'],math.dist(bodies['C1']['inspection']['center_mm'],
                                                           bodies['C3']['inspection']['center_mm']),abs_tol=1e-6)
        window.measure_mode.SetSelection(4);window.change_measure_mode(None)
        scene.inspection.click(hits[0]);window.scene_picked(hits[0]);window.part_b.SetValue('J1')
        assert query()['measurement_kind']=='point_edge'
        # Select visible CAD edges at actual projected curve sample locations.
        window.measure_mode.SetSelection(3);window.change_measure_mode(None);settle()
        selected=None
        for edge in bodies['C3']['inspection']['edges']:
            samples=edge.get('points',[])
            for a,b in zip(samples,samples[1:]):
                point=[(x+y)/2 for x,y in zip(a,b)]
                pixel=GLU.gluProject(*point,model,projection,viewport)
                selected=scene.pick_edge(wx.Point(round(pixel[0]/scale),round(scene.GetClientSize().height-pixel[1]/scale)))
                if selected and selected['reference']=='C3':break
            if selected and selected['reference']=='C3':break
        assert selected and selected['reference']=='C3','No visible C3 CAD edge could be picked'
        assert scene.inspection.click(selected) is None
        assert scene.inspection.feature_pair[0]['edge_index']==selected['edge_index']
        scene.hover_hit=selected
        window.part_a.SetValue('C1');window.part_b.SetValue('C3');assert query()['measurement_kind']=='edge_edge'
    for first,second in [('C2','C3'),('C1','C3')]:
        scene.set_measurement(session.measure(result,first,second))
    scene.refs={'C1','C3'}
    window.measure_readout.SetValue('Selected part gap:\n'+measurement_text(scene.inspection.active))
    if args.mode=='exact3d':
        scene.set_measurement(result['feature_rulers'][-1])
        window.measure_readout.SetValue('CAD edge ruler:\n'+measurement_text(scene.inspection.active))
        scene.hover_hit=None
    window.status.SetLabel('Saved analysis · drag to orbit · right-drag to pan · wheel to zoom')
    if args.mode=='exact3d':window.show_3d()
    else:scene.fit()
    settle()
    rectangles=list(scene.label_rectangles.values())
    assert 1<=len(rectangles)<=3+len(height_issues)
    if args.mode=='exact3d':
        assert any(key[0]=='height' for key in scene.label_rectangles),'Height excess labels missing from native viewport'
    for index,a in enumerate(rectangles):
        for b in rectangles[index+1:]:assert a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1]
    assert GL.glGetError()==GL.GL_NO_ERROR
    output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
    canvas=scene.snapshot();assert not canvas.HasAlpha()
    canvas.SaveFile(str(output/f'{args.mode}-canvas.png'),wx.BITMAP_TYPE_PNG)
    # Capture only our bounded, visible native client area. PrintWindow gives
    # damaged backgrounds/GL pixels on some Windows/wx combinations.
    width,height=window.GetClientSize();bitmap=wx.Bitmap(width,height)
    memory=wx.MemoryDC(bitmap);memory.Blit(0,0,width,height,wx.ClientDC(window),0,0)
    memory.SelectObject(wx.NullBitmap)
    bitmap.ConvertToImage().SaveFile(str(output/f'{args.mode}-workspace.png'),wx.BITMAP_TYPE_PNG)
    if args.mode=='exact3d':
        # The actual transient popup contains saved geometry dimensions, not defaults.
        scene.set_mode('select');window.scene_picked(hits[0]);settle()
        popup=window.part_inspector;assert popup and popup.IsShown()
        from wayricad_mechanical.part_inspector import dimension_rows
        rows=dict(dimension_rows(bodies['C3']))
        assert 'mm' in rows['X extent'] and rows['Solid volume']!='Unavailable'
        # Render this non-GL popup's own native children. A desktop DC can be
        # clipped by popup redirection, even when the card is visibly open.
        popup.Refresh();popup.Update();settle()
        pw,ph=popup.GetSize();pb=wx.Bitmap(pw,ph);memory=wx.MemoryDC(pb)
        if os.name=='nt':
            assert ctypes.windll.user32.PrintWindow(int(popup.GetHandle()),int(memory.GetHDC()),2)
        else:memory.Blit(0,0,pw,ph,wx.ClientDC(popup.GetChildren()[0]),0,0)
        memory.SelectObject(wx.NullBitmap)
        image=pb.ConvertToImage();assert len(set(bytes(image.GetData())))>5,'Blank dimensions card capture'
        image.SaveFile(str(output/'part-dimensions.png'),wx.BITMAP_TYPE_PNG)
        popup.Dismiss()
        # Exercise the real waiver action while supplying a synthetic review
        # reason through its dialog. Existing engineering rulers must survive.
        active=scene.inspection.active
        issue=height_issues[0]
        for reason in ('Reviewed synthetic fixture',''):
            for row in range(window.list.GetItemCount()):window.list.Select(row,False)
            window.list.Select(window.filtered.index(issue));settle()
            with patch('wayricad_mechanical.ui.wx.TextEntryDialog') as dialog:
                entry=dialog.return_value.__enter__.return_value
                entry.ShowModal.return_value=wx.ID_OK;entry.GetValue.return_value=reason
                window.waive(None)
            settle()
            assert (issue in scene.inspection.alerts.get(issue['refs'][0],[]))==(not bool(reason))
            assert scene.inspection.active is active
    assert hashlib.sha256(board.read_bytes()).hexdigest()==before
    evidence={'mode':args.mode,'canvas':[canvas.GetWidth(),canvas.GetHeight()],
              'window':[width,height],'labels':len(rectangles),'solid_bodies':len(result['bodies']),
              'source_unchanged':True,'ray_picks':len(hits),'gl_error':0,'feature_tools':feature_kinds}
    evidence.update(height_violations=len(height_issues),proximity_warnings=len(warning_issues))
    (output/f'{args.mode}-checks.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    session.close();window._closing=True;window.reset_measurement_session();window.Hide();window.Destroy();app.Yield()
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('quick2d','exact3d'),default='quick2d')
    parser.add_argument('--package-root')
    parser.add_argument('--output-dir',default='.native-temp/mechanical-workspace')
    status=0
    try:check(parser.parse_args())
    except BaseException:traceback.print_exc();status=1
    sys.stdout.flush();sys.stderr.flush();os._exit(status)
