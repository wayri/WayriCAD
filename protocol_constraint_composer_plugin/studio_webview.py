"""Native, local-only visual shell sharing the original specialist workspaces."""
from __future__ import annotations
import json
from pathlib import Path
import wx
import wx.html2
from wayricad_runtime.local_webview import new_webview
from . import studio_model
from .constraint_studio.ui import ConditionDialog

MUTATIONS = {'save_rule', 'set_value', 'toggle', 'duplicate', 'delete', 'move', 'matrix', 'profile', 'netclass', 'setting', 'routing_profile', 'routing_remove'}
PAGES = {'workbench', 'rule_page', 'matrix_page', 'netclass_page', 'settings_page', 'profile_panel', 'reports_panel', 'advanced_panel', 'help_page', 'review_page'}


class VisualWorkspace:
    def __init__(self, frame):
        self.frame = frame
        self.url = Path(__file__).with_name('web').joinpath('index.html').as_uri()
        self.ready = False
        self.connected = False
        self.failed = False
        self.last_navigation = ''
        self.last_loaded = ''
        self.last_error = ''
        self.native_menu = frame.GetMenuBar()
        self.view = new_webview(frame)
        if not self.view.AddScriptMessageHandler('wayricad'):
            self.view.Destroy()
            raise RuntimeError('This WebView does not support native messaging.')
        self.back = wx.Button(frame, label='← Back to visual workspace')
        self.back.Bind(wx.EVT_BUTTON, lambda event: self.show())
        frame.GetSizer().Insert(0, self.back, 0, wx.ALL, 10)
        frame.GetSizer().Add(self.view, 1, wx.EXPAND)
        self.view.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.navigate)
        self.view.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
        self.view.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.loaded)
        self.view.Bind(wx.html2.EVT_WEBVIEW_ERROR, self.load_error)
        self.view.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.message)
        self.show()
        self.view.LoadURL(self.url)
        self.startup_timer = wx.CallLater(10000, self.check_connection)
        frame.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)

    def _destroyed(self, event):
        if event.GetEventObject() is self.frame:
            self.startup_timer.Stop()
            self.frame = None
        event.Skip()

    def check_connection(self):
        try:
            if not self.frame or self.frame.IsBeingDeleted() or self.connected: return
        except RuntimeError:  # The native frame was destroyed before this callback ran.
            return
        self.failed = True
        self.native('workbench'); self.back.Hide()
        reason = (' ' + self.last_error) if self.last_error else ''
        self.frame.SetStatusText('Embedded visual workspace could not start.' + reason +
                                 ' The complete native worksheet and help remain available.')
        self.frame.Layout()

    def navigate(self, event):
        self.last_navigation = event.GetURL()
        if self.last_navigation not in (self.url, 'about:blank'):
            event.Veto()
        else:
            event.Skip()

    def load_error(self, event):
        self.last_error = event.GetString() or event.GetURL()
        if not self.connected:
            wx.CallAfter(self.check_connection)
        event.Skip()

    def loaded(self, event):
        self.last_loaded = event.GetURL()
        if self.view.GetCurrentURL() == self.url and not self.ready:
            self.ready = True
            self.view.RunScriptAsync('setTimeout(() => window.studio.connect(), 0); void 0;')

    def show(self):
        if self.failed:
            self.native('workbench'); self.back.Hide(); return
        f = self.frame
        f.collect(); f.GetSizer().ShowItems(False); self.view.Show()
        if f.GetMenuBar() is not None: f.SetMenuBar(None)
        f.GetStatusBar().Hide(); f.Layout()
        if self.ready: self.view.RunScriptAsync('setTimeout(() => window.studio.refresh(), 0); void 0;')

    def native(self, page):
        if page not in PAGES: raise ValueError('Unknown specialist workspace')
        f = self.frame
        f.collect(); f.GetSizer().ShowItems(True)
        self.view.Hide(); self.back.Show(); f.GetStatusBar().Show()
        if f.GetMenuBar() is None: f.SetMenuBar(self.native_menu)
        f.select_page(getattr(f, page)); f.Layout()

    def state(self):
        f = self.frame; f.collect()
        value = studio_model.snapshot(f.w)
        value.update(last_export=str(f.last_export or ''), native_report=f.native_text.GetValue(),
                     worker_busy=bool(f.worker and f.worker.is_alive()), can_undo=bool(f.undo_stack), can_redo=bool(f.redo_stack))
        return value

    def replace(self, trial):
        f = self.frame
        f.checkpoint(); f.w = trial; f.index = None; f.editing = None
        f.refresh_rules(); f.refresh_netclasses(); f.refresh_settings()
        f.workbench.refresh(); f.profile_panel.refresh()

    def dispatch(self, method, args):
        f = self.frame; f.collect()
        if method == 'snapshot':
            self.connected = True
            return self.state()
        if method in MUTATIONS:
            self.replace(studio_model.mutation(f.w, method, args)); return self.state()
        if method == 'inspect': return studio_model.inspect_scope(f.w, args)
        if method == 'routing_estimate':
            if args.get('revision') != f.w.state(): raise ValueError('Workspace changed; refresh before calculating')
            return studio_model.routing_profiles.estimate(f.w, args)
        if method == 'review': return {'diff': f.w.review(), 'rules': f.w.document.emit()}
        if method == 'matrix_preview': return '\n\n'.join(rule.emit() for rule in studio_model.compile_matrix(args))
        if method == 'native': self.native(args['page'])
        elif method == 'condition':
            with ConditionDialog(f, str(args.get('expression', '')), f.w.context, f.w.netclasses) as dialog:
                return dialog.result if dialog.ShowModal() == wx.ID_OK else None
        elif method == 'open': f.open_board(None)
        elif method == 'undo': f.undo(None)
        elif method == 'redo': f.redo(None)
        elif method == 'bga': f.bga(None)
        elif method == 'protocols': f.open_protocols(None)
        elif method == 'export': f.export(None)
        elif method == 'native_drc': f.run_native(None)
        elif method == 'copy-rules': f.copy_rules(None)
        elif method == 'help': self.native('help_page'); f.open_help('start')
        else: raise ValueError('Unknown visual workspace operation')
        return None

    def message(self, event):
        identifier = None
        try:
            if self.view.GetCurrentURL() != self.url: raise ValueError('Only the local workspace can call the engine')
            raw = event.GetString()
            if len(raw) > 2_000_000: raise ValueError('Workspace request is too large')
            data = json.loads(raw); identifier = data.get('id')
            if type(identifier) is not int: raise ValueError('Invalid request identifier')
            if not isinstance(data.get('args', {}), dict): raise ValueError('Invalid request arguments')
            result = {'ok': True, 'value': self.dispatch(data['method'], data.get('args', {}))}
        except Exception as exc:
            result = {'ok': False, 'error': str(exc)}
        script = 'window.studio.receive(' + json.dumps(identifier) + ',' + json.dumps(result, ensure_ascii=True, allow_nan=False) + '); void 0;'
        # Never nest synchronous ExecuteScript calls in WebView2 callbacks.
        wx.CallAfter(self.reply, script)

    def reply(self, script):
        if self.view and not self.view.IsBeingDeleted(): self.view.RunScriptAsync(script)
