import json,runpy,sys,traceback,time,faulthandler
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
  frame.notebook.SetSelection((4,5,6)[index])
  view=getattr(frame,name)
  dom=view.RunScript("String(document.querySelectorAll('svg').length)")
  count=str(dom[1]).strip('"')
  loaded=bool(dom[0] and count.isdigit() and int(count)>0)
  result.setdefault('webviews',{})[name]={'class':type(view).__name__,'svg_loaded':loaded,'url':view.GetCurrentURL(),'dom_svg_count':dom}
  if not loaded and time.monotonic()<deadline:
   (frame.OnICChartPreview,frame.OnDiagramPreview,frame.OnBuildPowerTree)[index](None)
   wx.CallLater(700,check_views,frame,index);return
  assert loaded,'Native WebView did not load generated SVG: '+name
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
