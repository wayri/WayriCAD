"""Bounded native Review WebView smoke check against an authorized saved board."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board', type=Path)
    parser.add_argument('--check-3d', action='store_true')
    parser.add_argument('--check-back-pads', action='store_true', help='Use back-pad-pick.kicad_pcb.')
    args = parser.parse_args()
    board = args.board.resolve()
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    import wx
    from review_comments_plugin.web_canvas import WebDesignCanvas
    app = wx.App(False)
    args.check_3d |= args.check_back_pads
    state = dict(loaded=False, requested=False, rotated=False, rendered_3d=False, back_pads=None, error=None)
    requested_3d = requested_bottom = False

    class Canvas(WebDesignCanvas):
        def message(self, event):
            super().message(event)
            value = json.loads(event.GetString())
            if value.get('type') == 'documentReady':
                state['loaded'] = True
            elif value.get('type') == 'error':
                state['error'] = value.get('message')

    owner = SimpleNamespace(closed=False, busy=False, session=None, target=None,
                            review_theme='light', review_variant='*')
    owner.task = lambda operation, complete, message, **kwargs: complete(operation())
    frame = wx.Frame(None, title='WayriCAD Review source-pin validation', size=(1100, 760))
    canvas = Canvas(frame, owner)
    layout = wx.BoxSizer(wx.VERTICAL)
    layout.Add(canvas, 1, wx.EXPAND)
    frame.SetSizer(layout)
    started = time.monotonic()

    def tick():
        nonlocal requested_3d, requested_bottom
        try:
            if state['error']:
                raise RuntimeError(state['error'])
            if canvas.ready and not state['requested']:
                state['requested'] = True
                canvas.load(board)
            if state['loaded'] and not state['rotated']:
                ok, result = canvas.browser.RunScript("""(() => {
                  const viewer = window.wayricadReview.viewer;
                  const camera = viewer.renderer.viewport.camera;
                  const button = document.getElementById('rotate');
                  if (button.disabled) return false;
                  const start = camera.quarterTurns;
                  const position = {x: camera.center.x + 1, y: camera.center.y + 2};
                  const before = camera.world_to_screen(position);
                  button.click();
                  const after = camera.world_to_screen(position);
                  const roundTrip = camera.screen_to_world(after);
                  const rotated = camera.quarterTurns === (start + 1) % 4 &&
                    Math.hypot(after.x - before.x, after.y - before.y) > 0.001 &&
                    Math.hypot(roundTrip.x - position.x, roundTrip.y - position.y) < 1e-6;
                  for (let i = 0; i < 3; i++) button.click();
                  return rotated && camera.quarterTurns === start;
                })()""")
                if not ok or result.strip().lower() != 'true':
                    raise RuntimeError('Native Review drawing rotation did not round-trip.')
                state['rotated'] = True
            if state['rotated'] and args.check_3d:
                if not requested_3d:
                    requested_3d = True
                    canvas.browser.RunScript("""void window.wayricadReview.setView('3d').then(
                      value => window.review3dCheck = {ready: value},
                      error => window.review3dCheck = {error: String(error)}
                    );""")
                ok, result = canvas.browser.RunScript("""(() => {
                  const viewer = window.wayricadReview.viewer;
                  return JSON.stringify({...(window.review3dCheck || {}), view: viewer.view,
                    projector: typeof viewer.renderer?.projectAnchor === 'function'});
                })()""")
                if ok:
                    check = json.loads(result)
                    if isinstance(check, str):
                        check = json.loads(check)
                    if check.get('error'):
                        raise RuntimeError(check['error'])
                    if 'ready' in check:
                        if not check['ready'] or check['view'] != '3d' or not check['projector']:
                            raise RuntimeError('Native Review 3D did not expose its registered projector: '+str(check))
                        state['rendered_3d'] = True
            if state['rotated'] and (not args.check_3d or state['rendered_3d']):
                if args.check_back_pads:
                    if not requested_bottom:
                        requested_bottom = True
                        canvas.browser.RunScript("""(() => {
                          const r = window.wayricadReview.viewer.renderer;
                          window.reviewBottomReady = false;
                          if (!r.setView('bottom')) return;
                          requestAnimationFrame(() => requestAnimationFrame(() => {
                            window.reviewBottomReady = true;
                          }));
                        })()""")
                    ok, ready = canvas.browser.RunScript('Boolean(window.reviewBottomReady)')
                    if not ok or ready.strip().lower() != 'true':
                        if time.monotonic()-started > 60:
                            raise TimeoutError('Native Review bottom camera did not settle.')
                        wx.CallLater(100, tick)
                        return
                    ok, result = canvas.browser.RunScript("""(() => {
                      try {
                      const v = window.wayricadReview.viewer, r = v.renderer;
                      const surface = r.host?.shadowRoot?.querySelector('canvas');
                      if (!surface) throw Error('Missing bottom pick surface');
                      r.setSelectionMode('pin');
                      let hit;
                      v.addEventListener('select', e => {hit=e.detail.item;});
                      return JSON.stringify([[15,18],[24,13],[15,18]].map(([x,y]) => {
                        const p = r.projectAnchor({position:{x,y},side:'back'});
                        if (!p) {
                          const box=surface.getBoundingClientRect();
                          throw Error('Saved back pad is outside the view: '+JSON.stringify({
                            x,y,width:box.width,height:box.height,camera:r.getCameraState(),
                            board:[r.board.width,r.board.height],projectCenter:r.projectAnchor({position:{x:20,y:15},side:'back'})
                          }));
                        }
                        hit=null;
                        surface.dispatchEvent(new MouseEvent('contextmenu',
                          {clientX:p.x,clientY:p.y,button:0,bubbles:true,cancelable:true}));
                        return hit?.netName ?? hit?.net ?? null;
                      }));
                      } catch (e) { return JSON.stringify({error:String(e)}); }
                    })()""")
                    if not ok:
                        raise RuntimeError('Back pad picking failed: '+str(result))
                    picks = json.loads(result)
                    if isinstance(picks, str):
                        picks = json.loads(picks)
                    if picks != ['BACK_FIRST', 'BACK_SECOND', 'BACK_FIRST']:
                        raise RuntimeError('Incorrect saved back-pad picks: '+str(picks))
                    state['back_pads'] = picks
                assert canvas.digest == digest
                assert not canvas.can_anchor(quiet=True), 'Read-only preview must not authorize publication'
                assert hashlib.sha256(board.read_bytes()).hexdigest() == digest
                canvas.close()
                frame.Destroy()
                return
            if time.monotonic()-started > 60:
                raise TimeoutError('Native Review viewer did not acknowledge the document: '+canvas.status.GetLabel())
            wx.CallLater(100, tick)
        except Exception as error:
            state['error'] = str(error)
            canvas.close()
            frame.Destroy()

    frame.Show()
    wx.CallLater(100, tick)
    app.MainLoop()
    print(json.dumps(dict(status='FAIL' if state['error'] else 'PASS', **state,
                          source_sha256=digest, source_unchanged=hashlib.sha256(board.read_bytes()).hexdigest()==digest)))
    return int(bool(state['error']) or not state['loaded'])


if __name__ == '__main__':
    raise SystemExit(main())
