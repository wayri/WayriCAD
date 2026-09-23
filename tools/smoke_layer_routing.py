"""Native WebView bridge and native project round-trip on a disposable fixture."""
import argparse
import json
from pathlib import Path
import runpy
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--net-groups',action='store_true')
    args=parser.parse_args();args.output=args.output.resolve();args.output.parent.mkdir(parents=True,exist_ok=True)
    import wx
    from protocol_constraint_composer_plugin.studio_ui import ConstraintStudioFrame
    from protocol_constraint_composer_plugin.constraint_studio import routing_profiles as rp
    helper=runpy.run_path(str(ROOT/'tests/test_layer_routing.py'))
    app=wx.App(False);frame=ConstraintStudioFrame(board_path=str(helper['BOARD']))
    frame.w=helper['fixture']();frame.refresh_rules();frame.refresh_netclasses();frame.refresh_settings()
    frame.Show();started=time.monotonic();phase=0
    result={'status':'running','errors':[]}
    def script(code):
        ok,value=frame.visual.view.RunScript(code)
        if not ok:raise RuntimeError(value)
        return value
    def finish():
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        frame.w.saved_state=frame.w.state();frame.Destroy();app.ExitMainLoop()
    def check():
        nonlocal phase
        try:
            if time.monotonic()-started>45:raise TimeoutError('Layer routing UI did not complete')
            if not frame.visual or not frame.visual.ready:wx.CallLater(250,check);return
            if phase==0:
                if script("String(!!state && pending.size===0)").strip('"')!='true':wx.CallLater(250,check);return
                d=helper['profile'](frame.w)
                picker=''
                if args.net_groups:
                    d.update(name='CAN1',protocol='CAN',scope='nets',nets=[])
                    picker="document.querySelector('[data-routing-net=\"D1\"]').click();document.querySelector('[data-routing-net=\"D2\"]').click();"
                script("window.routingDone=false;window.routingErrors=[];window.addEventListener('error',e=>routingErrors.push(e.message));window.addEventListener('unhandledrejection',e=>routingErrors.push(String(e.reason)));view='routing';render();routingDraft="+json.dumps(d)+";render();"+picker+"void 0;")
                assert script("String(!!document.querySelector('.routing-tabs') && document.querySelectorAll('.routing-preview-card').length===2)").strip('"')=='true'
                before=script("document.querySelector('.routing-preview-svg rect').getAttribute('width')")
                script("const input=document.querySelector('[data-routing-row=\"0\"][data-routing-field=\"width\"]');input.value=String(Number(input.value)*1.5);input.dispatchEvent(new Event('input',{bubbles:true}));void 0;")
                after=script("document.querySelector('.routing-preview-svg rect').getAttribute('width')")
                assert before!=after,(before,after)
                result['layer_preview']='passed'
                script("document.querySelector('[data-routing-calc=\"0\"]').click();void 0;")
                phase=1
            elif phase==1:
                if script("String(pending.size===0 && !!routingMessage)").strip('"')!='true':wx.CallLater(250,check);return
                assert 'Approximate' in script('routingMessage')
                result['width_estimator']='passed'
                script("document.querySelector('[data-routing-action=\"stage\"]').click();document.querySelector('#routing-reviewed').checked=true;document.querySelector('#dialog-form').requestSubmit();void 0;")
                phase=2
            elif phase==2:
                if not rp.native_profiles(frame.w):wx.CallLater(250,check);return
                assert len(rp.native_profiles(frame.w)[0]['layer_entries'])==2
                assert not rp.issues(frame.w)
                if args.net_groups:
                    assert frame.w.metadata['routing_profiles']['CAN1']['nets']==['D1','D2']
                    result['native_net_picker']='passed'
                    assert script("String(!!document.querySelector('[data-routing-tab=\"CAN1\"]'))").strip('"')=='true'
                    script("document.querySelector('[data-routing-tab-new]').click();document.querySelector('[data-routing-tab=\"CAN1\"]').click();void 0;")
                    assert script('routingDraft.name').strip('"')=='CAN1'
                    result['protocol_tabs']='passed'
                result['native_bridge_stage']='passed'
                out=args.output.parent/'native-roundtrip';out.mkdir(exist_ok=True)
                for ext,raw in frame.w.outputs().items():(out/('routing'+ext)).write_bytes(raw)
                script("setTimeout(async()=>{await action('undo');window.routingDone=true;},0);void 0;")
                phase=3
            else:
                if script('String(window.routingDone && pending.size===0)').strip('"')!='true':wx.CallLater(250,check);return
                assert not rp.native_profiles(frame.w)
                result['undo']='passed'
                result['errors']=json.loads(script('JSON.stringify(window.routingErrors)'))
                assert not result['errors']
                result['status']='passed';finish();return
            wx.CallLater(300,check)
        except Exception:
            result.update(status='failed',traceback=traceback.format_exc());finish()
    wx.CallLater(500,check);app.MainLoop();print(json.dumps(result,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
