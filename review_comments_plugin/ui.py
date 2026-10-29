"""Compact native comment pane; settings and network work stay outside the editor loop."""
from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import webbrowser
from urllib.parse import urlsplit

import wx

from .model import MARKER, anchor, run, scope
from .providers import Provider, login_command, verify_login
from .session import ReviewSession, atomic_json, data_home


class Settings(wx.Dialog):
    def __init__(self, parent, values):
        super().__init__(parent, title='Review settings', size=(650, 630), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.values = dict(values)
        outer = wx.BoxSizer(wx.VERTICAL)
        scroll = wx.ScrolledWindow(self)
        scroll.SetScrollRate(10, 10)
        grid = wx.FlexGridSizer(cols=2, vgap=9, hgap=10)
        grid.AddGrowableCol(1)
        self.fields = {}
        for key, label, default in [('provider', 'Provider: github / gitlab', 'github'), ('host', 'GitLab HTTPS origin', 'https://gitlab.com'),
                ('repository', 'Repository / project', ''), ('root', 'Local Git worktree', ''),
                ('ref', 'Saved revision (full commit ID)', ''), ('file', 'Design path in repository', ''),
                ('kind', 'Comments: issue / pull / merge_request', 'issue'), ('number', 'Issue / PR / MR number', '1'),
                ('discussionNumber', 'GitHub Discussion number', '1')]:
            grid.Add(wx.StaticText(scroll, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(scroll, value=str(values.get(key, default)))
            field.SetToolTip(label)
            self.fields[key] = field
            grid.Add(field, 1, wx.EXPAND)
        scroll.SetSizer(grid)
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 12)
        info = wx.StaticText(self, label='The saved design must match the commit. Authentication stays in gh/glab.\nComments and anchors are published to the selected provider conversation.\nUnsaved editor changes are outside the saved-revision review.\nGitHub Projects / GitLab boards open in the provider; no local work board is created.')
        info.Wrap(610)
        outer.Add(info, 0, wx.EXPAND | wx.ALL, 12)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in [('Browser login…', self.login), ('Open work board', self.board), ('Help', self.help)]:
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 6)
        outer.Add(actions, 0, wx.LEFT | wx.RIGHT, 12)
        self.login_status = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 75))
        outer.Add(self.login_status, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, self.accept, id=wx.ID_OK)

    def read(self):
        values = {key: field.GetValue().strip() for key, field in self.fields.items()}
        values['number'] = int(values['number'])
        values['discussionNumber'] = int(values['discussionNumber'])
        if values['discussionNumber'] < 1:
            raise ValueError('Choose a positive GitHub Discussion number.')
        Provider(values)
        return values

    def accept(self, event):
        try:
            self.values = self.read()
            # The parent opens/validates source in a worker before saving settings.
            self.EndModal(wx.ID_OK)
        except Exception as error:
            wx.MessageBox(str(error), 'Review settings', wx.OK | wx.ICON_WARNING, self)

    def board(self, event):
        try:
            webbrowser.open(Provider(self.read()).board_url)
        except Exception as error:
            self.login_status.SetValue(str(error))

    def help(self, event):
        webbrowser.open((Path(__file__).parent / 'help.html').as_uri())

    def login(self, event):
        try:
            provider = self.fields['provider'].GetValue().strip().casefold()
            if provider not in ('github', 'gitlab'):
                raise ValueError('Choose GitHub or GitLab first.')
            origin = self.fields['host'].GetValue().strip()
            command = login_command(provider, origin)
        except Exception as error:
            self.login_status.SetValue(str(error))
            return
        button = event.GetEventObject()
        button.Disable()
        cancelled = threading.Event()
        self._login_cancel = cancelled
        self.login_status.SetValue('Checking the existing CLI connection first. A browser opens only if needed; a rejected stored GitLab session is replaced for this CLI host only. Phone and browser sessions are separate.\n')

        def append(message):
            if self and not self.IsBeingDeleted():
                # Login commands never request a token argument or print auth-token output.
                self.login_status.AppendText(message[:4096])

        def worker():
            try:
                from .auth_flow import connect_plan, clear_rejected_gitlab_login
                plan = connect_plan(provider, origin)
                if cancelled.is_set():
                    return
                if plan['action'] == 'connected':
                    wx.CallAfter(append, '\nConnected: the existing CLI session was verified. No sign-in was needed.')
                    return
                if plan['action'] == 'blocked':
                    raise RuntimeError('Connection check: ' + plan['category'] + '. Existing credentials were not changed.')
                if plan['action'] == 'repair-rejected':
                    wx.CallAfter(append, '\nReplacing only the rejected GitLab CLI connection for this host. Browser, phone and GitHub sessions are unchanged.')
                    if not clear_rejected_gitlab_login(origin, cancelled=cancelled.is_set):
                        wx.CallAfter(append, '\nConnected: the CLI session is now valid; it was not replaced.')
                        return
                if cancelled.is_set():
                    return
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self._login_process = process
                if cancelled.is_set():
                    process.kill()
                    return
                timer = threading.Timer(600, process.kill)
                timer.start()
                try:
                    wx.CallAfter(append, '\nComplete approval in the browser opened by the official CLI. Waiting…')
                    for line in process.stdout:
                        # Do not echo authorization URLs/state, private profile
                        # details or credential/debug output into the pane.
                        if provider == 'github' and 'one-time code' in line.lower():
                            match = re.search(r'\b[A-Z0-9]{4}-[A-Z0-9]{4}\b', line)
                            if match:
                                wx.CallAfter(append, '\nGitHub device code: ' + match.group(0))
                    code = process.wait()
                    if code == 0:
                        verify_login(provider, origin)
                        wx.CallAfter(append, '\nConnected: the stored CLI session was verified with the provider API.')
                    else:
                        wx.CallAfter(append, '\nLogin did not complete. Approve the official provider CLI application in the same computer browser. Phone sign-in is separate.\n' + ' '.join(command))
                finally:
                    timer.cancel()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                wx.CallAfter(append, 'Sign-in: ' + str(error))
            finally:
                wx.CallAfter(lambda: button.Enable() if self and not self.IsBeingDeleted() else None)
        threading.Thread(target=worker, daemon=True).start()

    def cancel_login(self):
        cancelled = getattr(self, '_login_cancel', None)
        if cancelled is not None:
            cancelled.set()
        process = getattr(self, '_login_process', None)
        if process is not None and process.poll() is None:
            process.kill()


def initial_settings(board_path=None):
    config = data_home() / 'settings.json'
    values = {}
    if config.is_file() and config.stat().st_size < 64000:
        try:
            loaded = json.loads(config.read_text(encoding='utf-8'))
            values = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            values = {}
    if board_path:
        try:
            path = Path(board_path).resolve()
            root = Path(run(['git', 'rev-parse', '--show-toplevel'], cwd=path.parent))
            current = path.relative_to(root).as_posix()
            if values.get('root') != str(root) or values.get('file') != current:
                values = dict(root=str(root), file=current, ref=run(['git', 'rev-parse', 'HEAD'], cwd=root))
                remote = run(['git', 'remote', 'get-url', 'origin'], cwd=root)
                match = re.fullmatch(r'git@([^:]+):(.+?)(?:\.git)?', remote)
                parsed = urlsplit(remote) if not match else None
                hostname = match[1] if match else parsed.hostname
                repository = match[2] if match else parsed.path.lstrip('/').removesuffix('.git')
                if hostname == 'github.com':
                    values.update(provider='github', repository=repository)
                elif hostname:
                    values.update(provider='gitlab', host='https://' + hostname, repository=repository)
        except (ValueError, OSError, subprocess.SubprocessError):
            values = {}
    return values


class ReviewPane(wx.Frame):
    def __init__(self, board_path=None, settings=None):
        super().__init__(None, title='WayriCAD Review', size=(610, 780))
        self.SetIcon(wx.Icon(str(Path(__file__).parent / 'icon.png'), wx.BITMAP_TYPE_PNG))
        self.SetMinSize((420, 440))
        self.board_path = Path(board_path).resolve() if board_path else None
        self.values = settings if settings is not None else initial_settings(board_path)
        self.session = None
        self.busy = False
        self.closed = False
        self.target = None
        self.generation = 0
        self.highlighted_authors = set()
        self.pending_attachments = []
        panel = wx.Panel(self)
        main = wx.BoxSizer(wx.VERTICAL)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in [('Settings', self.settings), ('Open in GitHub / GitLab', self.open_provider), ('Refresh', self.refresh)]:
            button = wx.Button(panel, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            toolbar.Add(button, 0, wx.RIGHT, 5)
        main.Add(toolbar, 0, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(panel, label='Choose Settings to connect a provider conversation.')
        main.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.participants = wx.Choice(panel, choices=['All participants'])
        self.participants.SetSelection(0)
        self.participants.SetToolTip('Filter by comment author. This does not indicate online presence.')
        self.participants.Bind(wx.EVT_CHOICE, lambda event: self.populate())
        people = wx.BoxSizer(wx.HORIZONTAL)
        people.Add(self.participants, 1, wx.EXPAND)
        highlight = wx.Button(panel, label='Highlight…')
        highlight.SetToolTip('Choose multiple authors to highlight. Observed authors are not online presence.')
        highlight.Bind(wx.EVT_BUTTON, self.highlight_people)
        people.Add(highlight, 0, wx.LEFT, 5)
        main.Add(people, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        split = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        self.comments = wx.ListCtrl(split, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for title, width in [('Participant', 120), ('Comment', 350)]:
            self.comments.InsertColumn(self.comments.GetColumnCount(), title, width=width)
        self.comments.Bind(wx.EVT_LIST_ITEM_SELECTED, self.selected)
        self.detail = wx.TextCtrl(split, style=wx.TE_MULTILINE | wx.TE_READONLY)
        split.SplitHorizontally(self.comments, self.detail, 230)
        split.SetMinimumPaneSize(75)
        main.Add(split, 1, wx.EXPAND | wx.ALL, 8)
        targetbar = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in [('Use selected object', self.capture), ('Region…', self.region), ('Locate comment', self.locate)]:
            button = wx.Button(panel, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            targetbar.Add(button, 0, wx.RIGHT, 5)
        main.Add(targetbar, 0, wx.LEFT | wx.RIGHT, 8)
        self.target_label = wx.StaticText(panel, label='New comment: file scope. Select an object or define a region to add location.')
        main.Add(self.target_label, 0, wx.EXPAND | wx.ALL, 8)
        self.compose = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 100))
        self.compose.SetHint('Write a comment, or select a comment and reply. Paste text here.')
        main.Add(self.compose, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sendbar = wx.BoxSizer(wx.HORIZONTAL)
        self.reply = wx.CheckBox(panel, label='Reply to selected comment')
        sendbar.Add(self.reply, 1, wx.ALIGN_CENTER_VERTICAL)
        for title, handler in [('Paste image…', self.image), ('Post comment', self.post)]:
            button = wx.Button(panel, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            sendbar.Add(button, 0, wx.LEFT, 5)
        main.Add(sendbar, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(main)
        self.visible_rows = []
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.refresh, self.timer)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_ACTIVATE, self.activation)
        if self.values.get('repository'):
            wx.CallAfter(self.connect, dict(self.values))

    def close(self, event):
        if self.session:
            try:
                self.session.draft(self.compose.GetValue(), self.target or self.session.scope, self.images_for(self.compose.GetValue()))
            except (ValueError, OSError):
                if wx.MessageBox('The draft could not be saved locally. Close anyway?', 'Unpublished draft', wx.YES_NO | wx.NO_DEFAULT, self) != wx.YES:
                    return
        self.closed = True
        self.generation += 1
        self.timer.Stop()
        self.Destroy()

    def task(self, operation, complete, label='Working…', *, foreground=False, on_error=None):
        if self.busy or self.closed:
            return False
        self.busy = True
        if hasattr(self, 'activity'):
            self.activity.Show()
            self.activity.Start()
        generation = self.generation
        self.status.SetLabel(label)
        def worker():
            try:
                result, error = operation(), None
            except Exception as exc:
                result, error = None, str(exc)
            wx.CallAfter(done, result, error)
        def done(result, error):
            if self.closed or generation != self.generation:
                return
            self.busy = False
            if hasattr(self, 'activity'):
                self.activity.Stop()
                self.activity.Hide()
            if error:
                self.status.SetLabel(error)
                self.status.Wrap(max(350, self.GetClientSize().width - 25))
                if on_error:
                    on_error(error)
            elif foreground and (not self.IsShown() or self.IsIconized() or not self.IsActive()):
                self.status.SetLabel('Paused; provider response will display when this pane becomes active.')
            else:
                complete(result)
            if self.session:
                self.timer.StartOnce(self.session.interval_seconds * 1000)
            self.Layout()
        threading.Thread(target=worker, daemon=True).start()
        return True

    def settings(self, event=None):
        if self.busy:
            return
        with Settings(self, self.values) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.connect(dialog.values)

    def connect(self, values):
        self.timer.Stop()
        outgoing = self.session
        outgoing_text = self.compose.GetValue()
        outgoing_target = self.target
        outgoing_images = self.images_for(outgoing_text)
        def operation():
            if outgoing:
                outgoing.draft(outgoing_text, outgoing_target or outgoing.scope, outgoing_images)
            session = ReviewSession(values)
            if self.board_path and session.path != self.board_path:
                raise ValueError('Design differs from the launching editor. Use its own Review action.')
            atomic_json(data_home() / 'settings.json', values)
            session.cached()
            return session
        def ready(session):
            self.values, self.session, self.target = values, session, None
            draft = session.draft()
            self.compose.SetValue(draft['text'] if draft else '')
            self.pending_attachments = draft.get('attachments', []) if draft else []
            if draft:
                self.target = draft['anchor']
            self.target_label.SetLabel('New comment: file scope. Select an object or define a region to add location.')
            if self.target:
                self.set_target(self.target)
            self.populate()
            self.refresh()
        self.task(operation, ready, 'Checking saved design revision…')

    def refresh(self, event=None):
        if not self.session or self.busy or self.closed:
            return
        if self.IsIconized() or not self.IsShown() or not self.IsActive():
            self.status.SetLabel('Paused while review pane is inactive; last sync: ' + (self.session.synced_at or 'none'))
            self.timer.StartOnce(8000)
            return
        self.task(self.session.refresh, lambda result: self.populate(), 'Updating provider comments…', foreground=True,
                  on_error=getattr(self, 'refresh_failed', None))

    def activation(self, event):
        event.Skip()
        if event.GetActive() and self.session and not self.busy:
            wx.CallAfter(self.refresh)

    def populate(self):
        current = self.participants.GetStringSelection()
        self.participants.Set(['All participants'] + self.session.participants)
        self.participants.SetStringSelection(current if current in ['All participants'] + self.session.participants else 'All participants')
        author = self.participants.GetStringSelection()
        selected = self.row()
        selected_id = selected['id'] if selected else None
        self.comments.DeleteAllItems()
        self.visible_rows = [r for r in self.session.rows if author == 'All participants' or r['author'] == author]
        for i, row in enumerate(self.visible_rows):
            body = MARKER.sub('', row['body']).strip()
            self.comments.InsertItem(i, row['author'])
            self.comments.SetItem(i, 1, body.replace('\n', ' ')[:250])
            if row['author'] in self.highlighted_authors:
                palette = [(36, 158, 170), (218, 151, 39), (132, 102, 201), (48, 160, 95)]
                tint = palette[hashlib.sha256(row['author'].encode()).digest()[0] % len(palette)]
                base = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
                self.comments.SetItemBackgroundColour(i, wx.Colour(*[round(.75 * base[c] + .25 * tint[c]) for c in range(3)]))
            if row['id'] == selected_id:
                self.comments.Select(i)
        self.status.SetLabel(self.session.status + ' · ' + str(len(self.session.rows)) + ' comments · ' + (self.session.synced_at or 'not refreshed')
            + (' · ' + self.session.cache_warning if self.session.cache_warning else ''))

    def highlight_people(self, event=None):
        if not self.session:
            return
        names = self.session.participants
        with wx.MultiChoiceDialog(self, 'Highlight comments by these authors. This is not online presence.', 'Highlight participants', names) as dialog:
            dialog.SetSelections([i for i, name in enumerate(names) if name in self.highlighted_authors])
            if dialog.ShowModal() == wx.ID_OK:
                self.highlighted_authors = {names[i] for i in dialog.GetSelections()}
                self.populate()

    def row(self):
        i = self.comments.GetFirstSelected()
        return self.visible_rows[i] if 0 <= i < len(self.visible_rows) else None

    def selected(self, event):
        row = self.row()
        if row:
            self.detail.SetValue(row['author'] + ' · ' + row['updatedAt'] + '\n\n' + MARKER.sub('', row['body']).strip()
                + '\n\n' + ('Location available for saved revision.' if row.get('anchors') else 'No matching saved-revision anchor.'))

    def open_provider(self, event=None):
        if self.session:
            row = self.row()
            # Never launch an arbitrary URL taken from a locally editable cache.
            url = self.session.provider.web_url
            if row and not row.get('root') and str(row.get('id', '')).isdigit():
                url += ('#issuecomment-' if self.session.provider.provider == 'github' else '#note_') + row['id']
            webbrowser.open(url)

    def capture(self, event=None):
        if not self.session:
            return
        def operation():
            from wayricad_runtime.analysis_selection import selected_origin_ids
            values = selected_origin_ids(self.session.path, expected_sha256=self.session.digest)
            if len(values) != 1:
                raise ValueError('Select one design object in the originating PCB Editor, or use Region for a group.')
            if values[0].lower() not in self.session.path.read_text(encoding='utf-8').lower():
                raise ValueError('Selected object is not in the saved revision. Commit or choose a matching revision first.')
            return anchor(dict(self.session.scope, uuid=values[0], kind='object'))
        self.task(operation, self.set_target, 'Reading the originating PCB selection…')

    def set_target(self, target):
        self.target = target
        self.target_label.SetLabel('New comment: ' + (target.get('uuid') or ('region ' + str(target['area']) if target.get('area') else 'file scope')))
        self.target_label.Wrap(max(350, self.GetClientSize().width - 25))

    def region(self, event=None):
        if not self.session or self.busy:
            return
        with wx.TextEntryDialog(self, 'Region x, y, width, height in mm (board-top XY).\nA drawn native overlay is not available in this adapter.', 'Review region', '0, 0, 10, 10') as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    values = [float(p.strip()) for p in dialog.GetValue().split(',')]
                    if len(values) != 4:
                        raise ValueError('Enter four numbers.')
                    self.set_target(anchor(dict(self.session.scope, area=dict(zip(('x', 'y', 'width', 'height'), values)), kind='region')))
                except ValueError as error:
                    self.status.SetLabel(str(error))

    def locate(self, event=None):
        row = self.row()
        if row and self.session:
            self.task(lambda: self.session.locate(row['id']), lambda result: self.status.SetLabel('Selected in PCB Editor; focus: ' + result.get('focus', 'unknown')), 'Locating saved-revision object…')

    def post(self, event=None):
        if not self.session or self.busy:
            return
        draft = self.compose.GetValue()
        text = draft
        row = self.row() if self.reply.GetValue() else None
        if self.reply.GetValue() and row is None:
            self.status.SetLabel('Choose the comment to reply to.')
            return
        target = self.target or (row['anchors'][0] if row and len(row.get('anchors', [])) == 1 else self.session.scope)
        if row:
            text = '> Reply to ' + row['author'] + ' (' + row['url'] + ')\n\n' + text
        try:
            self.session.draft(draft, target, self.images_for(draft))
        except (ValueError, OSError) as error:
            self.status.SetLabel('Could not preserve the draft: ' + str(error))
            return
        def completed(identifier):
            if self.compose.GetValue() == draft:
                self.compose.Clear()
            try:
                self.pending_attachments = self.images_for(self.compose.GetValue())
                self.session.draft(self.compose.GetValue(), self.target or self.session.scope, self.pending_attachments)
            except (ValueError, OSError):
                self.status.SetLabel('Published, but draft cache could not be updated; check the provider before reposting.')
                return
            self.status.SetLabel('Published comment ' + identifier + '. Updating…')
            self.refresh()
        images = self.images_for(draft)
        self.task(lambda: self.session.publish(text, target, reply_to=row['id'] if row else None, attachments=images), completed, 'Publishing to provider…')

    def images_for(self, text):
        return [value for value in self.pending_attachments if value['url'] in text]

    def image(self, event=None):
        if not self.session or self.busy:
            return
        if self.session.provider.provider == 'github':
            wx.MessageBox('GitHub does not expose a supported public image-upload API. Paste the image or screenshot into the GitHub browser editor, post it there, then Refresh here. Your text draft remains here.', 'Attach screenshot', wx.OK, self)
            self.open_provider()
            return
        if len(self.images_for(self.compose.GetValue())) >= 4:
            self.status.SetLabel('At most four screenshot attachments are supported. Remove an image link to replace it.')
            return
        bitmap = wx.BitmapDataObject()
        if not wx.TheClipboard.Open():
            return
        try:
            ok = wx.TheClipboard.GetData(bitmap)
        finally:
            wx.TheClipboard.Close()
        if not ok:
            self.status.SetLabel('Copy an image or screenshot to the clipboard first.')
            return
        image = bitmap.GetBitmap().ConvertToImage()
        normalization = min(1024 / image.GetWidth(), 1024 / image.GetHeight(), 1)
        if normalization < 1:
            image.Rescale(max(1, int(image.GetWidth() * normalization)), max(1, int(image.GetHeight() * normalization)))
        stream = io.BytesIO()
        image.SaveFile(stream, wx.BITMAP_TYPE_PNG)
        with wx.Dialog(self, title='Review screenshot before GitLab upload', size=(620, 500), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) as dialog:
            layout = wx.BoxSizer(wx.VERTICAL)
            scale = min(580 / image.GetWidth(), 350 / image.GetHeight(), 1)
            image.Rescale(max(1, int(image.GetWidth() * scale)), max(1, int(image.GetHeight() * scale)))
            layout.Add(wx.StaticBitmap(dialog, bitmap=wx.Bitmap(image)), 1, wx.ALL | wx.ALIGN_CENTER, 8)
            layout.Add(wx.StaticText(dialog, label='Check for private paths or credentials. Uploading sends this image to GitLab.'), 0, wx.ALL, 8)
            layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
            dialog.SetSizer(layout)
            if dialog.ShowModal() != wx.ID_OK:
                return
        def attached(receipt):
            self.attachment_received(receipt)
        self.task(lambda: self.session.provider.upload_png(stream.getvalue()), attached, 'Uploading screenshot to GitLab…')

    def attachment_received(self, receipt):
        self.pending_attachments.append(receipt['attachment'])
        self.compose.AppendText('\n' + receipt['markdown'])
        self.status.SetLabel('Image uploaded to GitLab; Post comment publishes the text and image reference.')


