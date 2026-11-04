"""Embedded KiView interaction with a data-only, source-checked native bridge."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path

import wx
import wx.html2

from .canvas_model import draft_point, draft_region, markers_from_rows
from .model import anchor, scope


class WebDesignCanvas(wx.Panel):
    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner
        self.surface = self  # Existing draft repaint callers need no renderer knowledge.
        self.host = self.browser = None
        self.documents = None
        self.path = self.digest = self.document_id = None
        self.ready = False
        self.theme = getattr(owner, 'review_theme', 'light')
        self.pending = None
        self._generation = 0
        self.markers = []
        self.positions = {}
        self.selected_id = None
        layout = wx.BoxSizer(wx.VERTICAL)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        from .widgets import ActionButton
        for label, handler in [('Open…', self.open_design), ('Design options', self.options_menu)]:
            button = ActionButton(self, label, handler, compact=True)
            actions.Add(button, 0, wx.RIGHT | wx.BOTTOM, 4)
        self.status = wx.StaticText(self, label='Saved design', style=wx.ST_ELLIPSIZE_END)
        self.status.SetMinSize((0, -1))
        actions.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        layout.Add(actions, 0, wx.EXPAND | wx.ALL, 5)
        self.view_area = wx.Panel(self)
        self.view_layout = wx.BoxSizer(wx.VERTICAL)
        self.view_area.SetSizer(self.view_layout)
        layout.Add(self.view_area, 1, wx.EXPAND)
        self.SetSizer(layout)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroyed)
        bundled = Path(__file__).parent / 'web/vendor'
        configured = os.environ.get('WAYRICAD_REVIEW_VIEWER_ROOT')
        if configured or bundled.is_dir():
            try:
                self.start_viewer(Path(configured) if configured else bundled)
            except (ValueError, OSError, RuntimeError) as error:
                self.status.SetLabel('KiView unavailable: ' + str(error))
        else:
            self.status.SetLabel('Choose the KiView viewer asset directory to enable PCB, schematic and 3D views.')

    def start_viewer(self, root):
        from .web_host import ReviewWebHost
        self.close()
        self.ready = False
        host = ReviewWebHost(root)
        try:
            backend = wx.html2.WebViewBackendEdge if wx.Platform == '__WXMSW__' else wx.html2.WebViewBackendDefault
            if not wx.html2.WebView.IsBackendAvailable(backend):
                raise RuntimeError('A modern WebView backend is required; install the system WebView2 runtime on Windows.')
            browser = wx.html2.WebView.New(self.view_area, backend=backend, style=wx.BORDER_NONE)
            if not browser.AddScriptMessageHandler('wayricadHost'):
                browser.Destroy()
                raise RuntimeError('This WebView does not support the Review message bridge.')
        except Exception:
            host.close()
            raise
        self.host, self.browser = host, browser
        self.view_layout.Add(browser, 1, wx.EXPAND)
        browser.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.navigating)
        browser.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
        browser.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.message)
        browser.LoadURL(host.url)
        self.view_area.Layout()

    def choose_assets(self, event=None):
        with wx.DirDialog(self, 'Choose KiView source or installed viewer assets') as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.start_viewer(Path(dialog.GetPath()))
                except (ValueError, OSError, RuntimeError) as error:
                    self.status.SetLabel('KiView unavailable: ' + str(error))

    def options_menu(self, event=None):
        with wx.Menu() as menu:
            for label, handler in [('Reload saved design', self.reload), ('Review this file', self.review_file),
                                   ('Locate comment in KiCad', self.locate_main), ('Viewer assets…', self.choose_assets)]:
                item = menu.Append(wx.ID_ANY, label)
                menu.Bind(wx.EVT_MENU, handler, item)
            self.PopupMenu(menu)

    def navigating(self, event):
        if not self.host or event.GetURL() not in (self.host.url, 'about:blank'):
            event.Veto()

    def _call(self, method, payload):
        if self.browser and self.ready:
            # JSON is data in a fixed invocation, never an executable callback.
            encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
            self.browser.RunScript(f'window.wayricadReview.{method}({encoded});')

    def set_theme(self, theme):
        if theme not in ('light', 'dark'):
            raise ValueError('Choose light or dark theme.')
        self.theme = theme
        self._call('setTheme', theme)

    def open_design(self, event=None):
        with wx.FileDialog(self, 'Open saved review project or design',
                           wildcard='KiCad projects and designs|*.kicad_pro;*.kicad_pcb;*.kicad_sch',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                path = Path(dialog.GetPath())
                if path.suffix == '.kicad_pro':
                    path = next((path.with_suffix(suffix) for suffix in ('.kicad_pcb', '.kicad_sch')
                                 if path.with_suffix(suffix).is_file()), path)
                self.load(path)

    def reload(self, event=None):
        session = self.owner.session
        path = self.path or (getattr(session, 'path', None) if session else None) or self.owner.board_path
        if path:
            self.load(path)
        else:
            self.status.SetLabel('Open a saved project or design first.')

    def load(self, path):
        from .web_documents import ReviewDocuments
        if self.owner.busy or self.owner.closed:
            self.status.SetLabel('Finish the current operation, then reload the design.')
            return
        self._generation += 1
        generation = self._generation
        def operation():
            from .saved_positions import saved_positions
            documents = ReviewDocuments(path)
            requested = Path(path).resolve()
            identifier = next(entry['id'] for entry in documents.entries() if documents.path_for(entry['id']) == requested)
            payload = documents.load(identifier)
            return documents, identifier, payload, saved_positions(payload['source'])
        def complete(result):
            if generation != self._generation or self.owner.closed:
                return
            self.documents, identifier, payload, positions = result
            self.apply_document(identifier, payload, positions=positions)
        self.owner.task(operation, complete, 'Opening interactive saved design…', on_error=self.failed)

    def apply_document(self, identifier, payload, *, positions=None):
        from .saved_positions import saved_positions
        self.document_id = identifier
        self.path = self.documents.path_for(identifier)
        self.digest = payload['source_sha256']
        self.positions = saved_positions(payload['source']) if positions is None else positions
        self.selected_id = None
        session = self.owner.session
        payload['scope'] = session.scope if self.can_anchor(quiet=True) else None
        self.pending = payload
        if self.ready:
            self._call('setDocument', payload)
        if self.browser:
            self.status.SetLabel('Saved design · edit in KiCad')

    def can_anchor(self, quiet=False):
        session = self.owner.session
        if session and hasattr(session, 'require_authorization'):
            try:
                session.require_authorization()
            except RuntimeError:
                if quiet:
                    return False
                raise
        ready = bool(self.path and self.digest and session and session.status == 'synced'
                     and getattr(session, 'path', None) == self.path
                     and getattr(session, 'digest', None) == self.digest)
        if not ready and not quiet:
            raise ValueError('Use Review this file and refresh its matching saved revision before placing comments.')
        return ready

    def sync_review(self):
        self.markers = []
        session = self.owner.session
        if self.can_anchor(quiet=True):
            try:
                self.documents.assert_current(self.document_id, self.digest)
                self.markers, unplaced = markers_from_rows(session.rows, session.scope, session.status, self.positions)
                self._call('setComments', dict(scope=session.scope, status=session.status,
                           path=self.document_id, source_sha256=self.digest,
                           markers=[asdict(marker) for marker in self.markers], selected_id=self.selected_id))
            except (ValueError, OSError) as error:
                self.failed(str(error))
        else:
            self._call('setComments', dict(scope=None, status='unverified', markers=[],
                       path=self.document_id, source_sha256=self.digest))
        self.sync_draft()

    def sync_draft(self):
        target = getattr(self.owner, 'target', None)
        draft = None
        if target and self.can_anchor(quiet=True):
            try:
                self.documents.assert_current(self.document_id, self.digest)
                checked = anchor(target)
                if scope(checked) == scope(self.owner.session.scope):
                    key = checked.get('uuid') or checked.get('objectId')
                    if 'position' not in checked and 'area' not in checked and key in self.positions:
                        checked = dict(checked, position=self.positions[key])
                if scope(checked) == scope(self.owner.session.scope) and ('position' in checked or 'area' in checked):
                    draft = checked
            except (ValueError, OSError, TypeError):
                pass
        self._call('setDraft', draft)

    def _check_message(self, value):
        if not self.documents or value.get('path') != self.document_id or value.get('source_sha256') != self.digest:
            raise ValueError('Ignored an event from an older or different design view.')
        self.documents.assert_current(self.document_id, self.digest)

    def message(self, event):
        if (self.owner.closed or not self.host or not self.browser
                or event.GetEventObject() is not self.browser
                or self.browser.GetCurrentURL() != self.host.url):
            return
        raw = event.GetString()
        if not isinstance(raw, str) or len(raw) > 256*1024:
            return
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                return
            kind = value.get('type')
            if kind == 'ready':
                self.ready = True
                self._call('setTheme', self.theme)
                if self.pending:
                    self._call('setDocument', self.pending)
                return
            if kind == 'error':
                self.status.SetLabel(str(value.get('message', 'Viewer error'))[:1000])
                return
            self._check_message(value)
            if kind == 'documentReady':
                self.sync_review()
                if getattr(self.owner, 'session', None) and hasattr(self.owner, 'populate'):
                    self.owner.populate()
            elif kind == 'objectSelected':
                item = value.get('item')
                if isinstance(item, dict):
                    label = item.get('reference') or item.get('ref') or item.get('kind') or 'Design item'
                    self.status.SetLabel('Selected in independent view: ' + str(label)[:150])
            elif kind == 'requestDocument':
                identifier = value.get('id')
                payload = self.documents.load(identifier)
                self.apply_document(identifier, payload)
            elif kind == 'requestView':
                target = value.get('view')
                entries = [entry for entry in self.documents.entries() if entry['kind'] == target]
                if entries:
                    self.apply_document(entries[0]['id'], self.documents.load(entries[0]['id']))
                else:
                    self.status.SetLabel('Open the corresponding saved ' + str(target) + ' file first.')
            elif kind == 'focusThread':
                self.can_anchor()
                identifier = value.get('comment_id')
                if any(marker.comment_id == identifier for marker in self.markers):
                    row = next((row for row in self.owner.session.rows if row['id'] == identifier), None)
                    if row:
                        self.selected_id = identifier
                        self.owner.focus_thread(row)
            elif kind == 'draftAnchor':
                self.can_anchor()
                proposed = value.get('anchor', {})
                if 'area' in proposed:
                    area = proposed['area']
                    target = draft_region(self.owner.session.scope, *(area[key] for key in ('x', 'y', 'width', 'height')))
                else:
                    point = proposed['position']
                    target = draft_point(self.owner.session.scope, point['x'], point['y'])
                self.owner.set_target(target)
                self.owner.compose.SetFocus()
                self.status.SetLabel('Unpublished comment marker · write a message, then Send message.')
        except (ValueError, OSError, KeyError, TypeError, StopIteration, RecursionError) as error:
            self.failed(str(error))

    def review_file(self, event=None):
        if not self.path or not self.owner.session:
            self.status.SetLabel('Connect a provider conversation in Settings first.')
            return
        try:
            relative = self.path.relative_to(Path(self.owner.values['root']).resolve()).as_posix()
            values = dict(self.owner.values, file=relative)
            self.owner.connect(values, canvas_path=self.path)
        except (ValueError, KeyError) as error:
            self.failed(str(error))

    def focus_comment(self, identifier):
        self.sync_review()
        if self.ready and any(marker.comment_id == identifier for marker in self.markers):
            self.selected_id = identifier
            self._call('focusComment', identifier)
            return True
        return False

    def locate_main(self, event=None):
        marker = next((marker for marker in self.markers if marker.comment_id == self.selected_id), None)
        if not marker or not marker.anchor.get('uuid'):
            self.status.SetLabel('Native PCB navigation requires an object-linked comment; use the canvas for point/region comments.')
            return
        session, identifier = self.owner.session, self.selected_id
        self.owner.task(lambda: session.locate(identifier), lambda result: self.status.SetLabel('Selected in originating PCB Editor'),
                        'Locating saved object…', authorization=getattr(session, 'require_authorization', None))

    def failed(self, message):
        self.markers = []
        self._call('setComments', dict(scope=None, status='stale', markers=[],
                   path=self.document_id, source_sha256=self.digest))
        self.status.SetLabel(str(message)[:1000])

    def close(self):
        self._generation += 1
        self.ready = False
        if self.browser:
            self.view_layout.Detach(self.browser)
            self.browser.Destroy()
            self.browser = None
        if self.host:
            self.host.close()
            self.host = None

    def destroyed(self, event):
        if event.GetEventObject() is self:
            self._generation += 1
            self.ready = False
            self.browser = None
            if self.host:
                self.host.close()
                self.host = None
        event.Skip()
