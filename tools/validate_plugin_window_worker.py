import json,runpy,sys,traceback,time,faulthandler
if sys.platform == 'win32':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(0x0002)  # Crash in this owned probe must not leave a blocking error dialog.
from pathlib import Path
import wx
root=Path(sys.argv[1]);output=Path(sys.argv[2])
result={'status':'starting','errors':[]}
output.write_text(json.dumps(result))
faulthandler.dump_traceback_later(20)
deadline=time.monotonic()+30
app=wx.App(False)
def message(text,*args,**kwargs):
 result['errors'].append(str(text));return wx.ID_OK
wx.MessageBox=message
def finish():
 faulthandler.cancel_dump_traceback_later()
 output.write_text(json.dumps(result,indent=2))
 for w in list(wx.GetTopLevelWindows()):w.Close()
 wx.CallLater(500,app.ExitMainLoop)
def check_views(frame,index=0):
 try:
  name=('ic_visual_preview','diagram_preview','power_tree_preview')[index]
  result['phase']='checking '+name;output.write_text(json.dumps(result,indent=2))
  # Connector Preview occupies page 1; the visual pages are now 5, 6, 7.
  frame.notebook.SetSelection((5,6,7)[index])
  view=getattr(frame,name)
  (frame.OnICChartPreview,frame.OnDiagramPreview,frame.OnBuildPowerTree)[index](None)
  dimensions=view.rendered_size
  loaded=dimensions[0]>0 and dimensions[1]>0 and not view.render_error
  result.setdefault('visual_previews',{})[name]={'class':type(view).__name__,
    'rendered':loaded,'bitmap_size':dimensions,'error':view.render_error}
  assert loaded,'Native SVG preview did not render: '+name+' '+view.render_error
  if index<2:wx.CallLater(100,check_views,frame,index+1);return
  result['status']='passed' if not result['errors'] else 'failed'
 except Exception:result.update(status='failed',traceback=traceback.format_exc())
 finish()
def inspect():
 try:
  result['phase']='inspecting';output.write_text(json.dumps(result,indent=2))
  windows=list(wx.GetTopLevelWindows())
  result['windows']=[{'title':w.GetTitle(),'class':type(w).__name__} for w in windows]
  frame=next((w for w in windows if type(w).__name__ in ('PluginDialogV2','FanoutFrame')),None)
  assert frame is not None,'Expected plugin window was not constructed'
  result['footprints']=[f.GetReference() for f in frame.board.GetFootprints()]
  assert len(result['footprints'])==2,'Fixture data not loaded'
  if hasattr(frame,'OnPreviewExtraction'):
   frame.OnPreviewExtraction(None)
   result['preview_rows']=len(frame.preview_rows)
   assert result['preview_rows']>=2,'No extracted pin preview rows'
   result['connector_preview_text']=frame.connector_webview.ToText()[:300]
   assert 'J1' in result['connector_preview_text'],'Native connector preview did not display the extracted reference'
   frame.ic_combo.SetValue('U1')
   wx.CallLater(500,check_views,frame);return
  frame.preview(None,silent=True)
  result['fanout_plans']=len(frame.preview_plan)
  result['fanout_status']=frame.status.GetLabel()
  result['fanout_rejections']=list(getattr(frame,'plan_rejections',[]))
  assert frame.preview_plan,'Fanout produced no plans on selected fixture'
  result['status']='passed' if not result['errors'] else 'failed'
 except Exception:
  result.update(status='failed',traceback=traceback.format_exc())
 finish()
wx.CallLater(2500,inspect)
try:runpy.run_path(str(root/'ipc_entrypoint.py'),run_name='__main__')
except BaseException:
 result.update(status='failed',traceback=traceback.format_exc());output.write_text(json.dumps(result,indent=2))
if not output.exists():inspect()
