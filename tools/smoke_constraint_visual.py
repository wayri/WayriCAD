"""Exercise the real WebView message bridge and worksheet on disposable data."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import wx
    from protocol_constraint_composer_plugin.studio_ui import ConstraintStudioFrame
    result = {'status': 'running', 'errors': []}
    sys.excepthook = lambda t, v, tb: result['errors'].append(''.join(traceback.format_exception(t, v, tb)))
    app = wx.App(False)
    frame = ConstraintStudioFrame(board_path=str(ROOT / 'protocol_constraint_composer_plugin/examples/workflow_demo/workflow_demo.kicad_pcb'))
    frame.Show()
    start = time.monotonic()
    phase = 0

    def script(value):
        ok, text = frame.visual.view.RunScript(value)
        if not ok: raise RuntimeError('JavaScript execution failed: ' + text)
        return text

    def finish():
        if result['errors']: result['status'] = 'failed'
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        frame.Destroy(); wx.CallLater(200, app.ExitMainLoop)

    def check():
        nonlocal phase
        try:
            result['phase'] = phase
            if frame.visual and frame.visual.ready:
                result['dom_status'] = script("JSON.stringify({pending:pending.size,busy:document.body.classList.contains('busy'),value:document.querySelector('[data-value=\"min\"]')?.value,toast:document.querySelector('#toast')?.textContent,errors:window.testErrors})")
                result['model_value'] = frame.w.document.rules[-1].constraints[0].values
            args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
            if time.monotonic() - start > 40: raise TimeoutError('Visual workflow did not finish')
            if not frame.visual or not frame.visual.ready:
                wx.CallLater(250, check); return
            if phase == 0:
                ready = script("String(!!document.querySelector('#board-map') && !!state && pending.size===0)")
                if ready.strip('"') != 'true': wx.CallLater(200, check); return
                result['initial_rules'] = len(frame.w.document.rules)
                script("window.testErrors=[]; window.addEventListener('error',e=>testErrors.push(e.message)); window.addEventListener('unhandledrejection',e=>testErrors.push(String(e.reason))); window.testDone=false; setTimeout(async()=>{try { const input=document.querySelector('[data-value=\"min\"]'); window.testOriginal=input.value; input.value='0.11mm'; input.dispatchEvent(new Event('change',{bubbles:true})); }catch(e){testErrors.push(String(e));}},0); void 0;")
                phase = 1
            elif phase == 1:
                ready = script("String(pending.size===0 && !document.body.classList.contains('busy') && document.querySelector('[data-value=\"min\"]')?.value==='0.11mm')")
                if ready.strip('"') != 'true': wx.CallLater(200, check); return
                assert frame.w.document.rules[-1].constraints[0].values['min'] == '0.11mm'
                result['worksheet_edit'] = 'passed'
                script("setTimeout(async()=>{try{await action('undo');window.testDone=true;}catch(e){testErrors.push(String(e));}},0); void 0;")
                phase = 2
            elif phase == 2:
                if script('String(window.testDone && pending.size===0)').strip('"') != 'true': wx.CallLater(200, check); return
                assert frame.w.document.rules[-1].constraints[0].values['min'] != '0.11mm'
                result['undo'] = 'passed'
                script("window.testDone=false;setTimeout(async()=>{try { view='matrix';render();matrixDraft.cells=[{i:0,j:1,value:'0.3mm'}];await edit('matrix',matrixDraft);view='sets';render();if(document.querySelectorAll('[data-profile]').length!==6)throw Error('Missing constraint sets');view='review';reviewTab='diff';render();await loadReview();view='workspace';render();await inspect();window.testDone=true;}catch(e){testErrors.push(String(e));}},0);void 0;")
                phase = 3
            elif phase == 3:
                if script('String(window.testDone && pending.size===0)').strip('"') != 'true': wx.CallLater(200, check); return
                assert any(r.name.startswith('Matrix Main') for r in frame.w.document.rules)
                result['matrix_sets_review'] = 'passed'
                frame.visual.native('workbench')
                assert frame.workbench.IsShownOnScreen()
                frame.visual.native('help_page')
                assert frame.help_panel is not None
                frame.visual.show()
                result['native_tools_and_help'] = 'passed'
                phase = 4
            else:
                if script('String(pending.size===0)').strip('"') != 'true': wx.CallLater(200, check); return
                errors = json.loads(script('JSON.stringify(window.testErrors)'))
                result['errors'].extend(errors)
                result['status'] = 'passed' if not result['errors'] else 'failed'
                result['rows'] = int(script("String(document.querySelectorAll('tr[data-rule]').length)"))
                result['visible'] = frame.visual.view.IsShownOnScreen()
                result['view_size'] = list(frame.visual.view.GetSize())
                assert result['visible'] and result['view_size'][0] > 800 and result['view_size'][1] > 500
                finish(); return
            wx.CallLater(400, check)
        except Exception:
            result.update(status='failed', traceback=traceback.format_exc()); finish()
    wx.CallLater(500, check)
    app.MainLoop()
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
