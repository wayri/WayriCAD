"""Native messenger-style review cards with separate provider Discussions."""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import webbrowser

import wx
import wx.html

from .model import MARKER, anchor, scope
from .session import ReviewSession, atomic_json, data_home
from .ui import ReviewPane, initial_settings
from .widgets import ActionButton
from .composer_ui import Composer

INK = '#253047'
MUTED = '#65738b'
ACCENT = '#087f8c'
BACKGROUND = '#f4f6fa'
LINE = '#e3e8ef'
IMAGE = re.compile(r'!\[[^\]]*\]\(https://[^\s)]+\)')


def message_text(row):
    text = MARKER.sub('', row['body']).strip()
    if row.get('parentId'):
        text = re.sub(r'^> Reply to [^\n]+\n\s*\n', '', text)
    return IMAGE.sub('Screenshot attached', text).strip() or '(No message text)'


def short_time(value):
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone()
        # wx can switch the Windows C locale; keep strftime's format ASCII.
        return moment.strftime('%d %b') + ' · ' + moment.strftime('%H:%M')
    except (ValueError, TypeError, AttributeError):
        return value if isinstance(value, str) else ''


def font(window, size=10, *, bold=False):
    result = window.GetFont()
    result.SetPointSize(size)
    if bold:
        result.SetWeight(wx.FONTWEIGHT_BOLD)
    window.SetFont(result)


class MessageBody(wx.html.HtmlWindow):
    """Resource-free formatted messages; long bodies keep their own scrollbar."""
    def __init__(self, parent, text):
        super().__init__(parent, style=wx.html.HW_SCROLLBAR_AUTO | wx.BORDER_NONE)
        self.text = text
        self.Bind(wx.html.EVT_HTML_LINK_CLICKED, lambda event: None)
        self.SetLabel(text)

    def SetLabel(self, text):
        from .composer_format import preview_html, MAX_TEXT
        self.text = text
        # External conversations may contain much longer posts; keep exact
        # text available in the provider, rather than rendering unbounded HTML.
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT-100] + '\n\n[Long message: open the provider to read the complete text.]'
        self.SetPage(preview_html(text))

    def GetLabel(self):
        return self.text

    def Wrap(self, width):
        self.SetSize((max(160, width), 450))
        self.SetLabel(self.text)
        content = self.GetInternalRepresentation()
        self.SetMinSize((0, min(450, max(40, content.GetHeight()+12 if content else 40))))


class MessageCard(wx.Panel):
    """One readable message, with its own Reply and engineering-location actions."""
    def __init__(self, parent, row, owner, *, reply=False):
        super().__init__(parent)
        self.row, self.owner = row, owner
        self.SetBackgroundColour('#ffffff')
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        layout = wx.BoxSizer(wx.HORIZONTAL)
        avatar = wx.Panel(self, size=(34, 34))
        avatar.SetMinSize((34, 34))
        colors = ['#087f8c', '#7461b4', '#aa6b25', '#377652', '#a85469']
        color = colors[hashlib.sha256(row['author'].encode()).digest()[0] % len(colors)]
        avatar.SetBackgroundColour(color)
        av = wx.BoxSizer(wx.VERTICAL)
        initial = wx.StaticText(avatar, label=(row['author'][:2] or '?').upper())
        initial.SetForegroundColour('#ffffff')
        font(initial, 10, bold=True)
        av.AddStretchSpacer()
        av.Add(initial, 0, wx.ALIGN_CENTER_HORIZONTAL)
        av.AddStretchSpacer()
        avatar.SetSizer(av)
        layout.Add(avatar, 0, wx.ALL, 12)
        content = wx.BoxSizer(wx.VERTICAL)
        head = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        author = wx.StaticText(self, label=row['author'][:24] + ('…' if len(row['author']) > 24 else ''))
        author.SetToolTip(row['author'])
        author.SetForegroundColour(INK)
        font(author, 10, bold=True)
        head.Add(author, 0, wx.ALIGN_CENTER_VERTICAL)
        timestamp = wx.StaticText(self, label=short_time(row.get('updatedAt', '')))
        timestamp.SetForegroundColour(MUTED)
        font(timestamp, 8)
        head.Add(timestamp, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 10)
        if row.get('root'):
            kind = wx.StaticText(self, label='TOPIC')
            kind.SetForegroundColour(MUTED)
            font(kind, 8, bold=True)
            head.Add(kind, 0, wx.ALIGN_CENTER_VERTICAL)
        content.Add(head, 0, wx.EXPAND | wx.TOP | wx.RIGHT, 12)
        if reply:
            quoted = wx.StaticText(self, label='↳ Reply in thread')
            quoted.SetForegroundColour(ACCENT)
            font(quoted, 8)
            content.Add(quoted, 0, wx.TOP, 4)
        text = message_text(row)
        # Attachments remain explicit user-opened provider links, not arbitrary
        # automatic remote image fetches from third-party comment text.
        self.body = MessageBody(self, text or '(No message text)')
        self.body.SetForegroundColour(INK)
        font(self.body, 10)
        content.Add(self.body, 0, wx.EXPAND | wx.TOP | wx.RIGHT, 8)
        actions = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.actions = actions
        reply_button = ActionButton(self, 'Reply', compact=True)
        reply_button.SetBackgroundColour('#ffffff')
        reply_button.SetForegroundColour(ACCENT)
        reply_button.Bind(wx.EVT_BUTTON, lambda event: owner.begin_reply(row))
        actions.Add(reply_button, 0, wx.RIGHT | wx.BOTTOM, 8)
        thread = ActionButton(self, 'View thread' if getattr(owner, 'reply_counts', {}).get(row['id']) or row.get('parentId') else 'Focus message', compact=True)
        thread.SetToolTip('Show this message and its replies without changing your draft')
        thread.Bind(wx.EVT_BUTTON, lambda event: owner.focus_thread(row))
        actions.Add(thread, 0, wx.RIGHT | wx.BOTTOM, 8)
        locations = row.get('anchors', [])
        if len(locations) == 1:
            target = locations[0]
            label = target.get('reference') or target.get('netName') or ('Region' if target.get('area') else 'Design item')
            location = ActionButton(self, '⌖ ' + label[:40], compact=True)
            location.SetBackgroundColour('#edf6f7')
            location.SetForegroundColour(ACCENT)
            location.SetToolTip('Locate this provider-anchored item in the originating PCB Editor')
            location.Bind(wx.EVT_BUTTON, lambda event: owner.locate_row(row))
            actions.Add(location, 0, wx.RIGHT | wx.BOTTOM, 8)
        provider = ActionButton(self, 'Open ↗', compact=True)
        provider.SetBackgroundColour('#ffffff')
        provider.SetForegroundColour(MUTED)
        provider.Bind(wx.EVT_BUTTON, lambda event: owner.open_row(row))
        actions.Add(provider, 0, wx.RIGHT | wx.BOTTOM, 8)
        if IMAGE.search(row['body']):
            screenshot = ActionButton(self, 'Screenshot ↗', compact=True)
            screenshot.SetBackgroundColour('#ffffff')
            screenshot.SetForegroundColour(ACCENT)
            screenshot.Bind(wx.EVT_BUTTON, lambda event: owner.open_row(row))
            actions.Add(screenshot, 0, wx.BOTTOM, 8)
        content.Add(actions, 0, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 8)
        layout.Add(content, 1, wx.EXPAND | wx.RIGHT, 12)
        self.SetSizer(layout)
        self.highlighted = row['author'] in owner.highlighted_authors

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(BACKGROUND))
        dc.Clear()
        dc.SetPen(wx.Pen(ACCENT if self.highlighted else LINE, 2 if self.highlighted else 1))
        dc.SetBrush(wx.Brush('#ffffff'))
        width, height = self.GetClientSize()
        dc.DrawRoundedRectangle(1, 1, max(1, width - 2), max(1, height - 2), 10)

    def wrap(self, width):
        # Reset before wrapping: repeatedly wrapping existing line breaks otherwise
        # accumulates narrow layouts when the user enlarges the pane again.
        self.body.SetLabel(message_text(self.row))
        self.body.Wrap(max(160, width - 95))
        self.body.InvalidateBestSize()
        self.GetSizer().Layout()


class ConversationPane(ReviewPane):
    """Cards replace the table/detail split; source and publication guards are shared."""
    def __init__(self, board_path=None, settings=None):
        wx.Frame.__init__(self, None, title='WayriCAD Review', size=(1080, 880))
        self.SetMinSize((640, 660))
        self.SetIcon(wx.Icon(str(Path(__file__).parent / 'icon.png'), wx.BITMAP_TYPE_PNG))
        self.board_path = Path(board_path).resolve() if board_path else None
        self.values = settings if settings is not None else initial_settings(board_path)
        self.session = None
        self.busy = self.closed = False
        self.target = None
        self.generation = 0
        self.highlighted_authors = set()
        self.pending_attachments = []
        self._thumbnails = {}
        self.reply_to = None
        self.thread_root = None
        self.reply_counts = {}
        self._author_names = []
        self._workflow_manual = False
        self.active_tab = 0
        self.cards = []
        self.window_start = None
        self.render_signature = None
        self.resize_call = None
        root = wx.Panel(self)
        self.content_panel = root
        root.SetBackgroundColour(BACKGROUND)
        outer = wx.BoxSizer(wx.VERTICAL)
        header_panel = wx.Panel(root)
        header_panel.SetBackgroundColour('#ffffff')
        header = wx.BoxSizer(wx.HORIZONTAL)
        icon = wx.StaticBitmap(header_panel, bitmap=wx.Bitmap(str(Path(__file__).parent / 'resources/icon-48.png')))
        header.Add(icon, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)
        titles = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(header_panel, label='Review workspace')
        title.SetForegroundColour(INK)
        font(title, 18, bold=True)
        titles.Add(title)
        self.context = wx.StaticText(header_panel, label='Connect a saved design to its review conversation.', style=wx.ST_ELLIPSIZE_END)
        self.context.SetForegroundColour(MUTED)
        self.context.SetMinSize((0, -1))
        titles.Add(self.context, 0, wx.EXPAND | wx.TOP, 3)
        header.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.activity = wx.ActivityIndicator(header_panel)
        self.activity.Hide()
        header.Add(self.activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.workflow_button = ActionButton(header_panel, 'Workflow', self.toggle_workflow, compact=True)
        header.Add(self.workflow_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        header.Add(ActionButton(header_panel, 'Settings', self.settings, compact=True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        header_panel.SetSizer(header)
        outer.Add(header_panel, 0, wx.EXPAND | wx.BOTTOM, 12)
        body = wx.BoxSizer(wx.HORIZONTAL)
        self.sidebar = wx.Panel(root)
        self.sidebar.SetBackgroundColour('#ffffff')
        self.sidebar.SetMinSize((208, -1))
        steps = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self.sidebar, label='REVIEW WORKFLOW')
        label.SetForegroundColour(MUTED)
        font(label, 8, bold=True)
        steps.Add(label, 0, wx.ALL, 16)
        for title, detail, action, handler in [
                ('1  Connect', 'Choose the saved design, provider and conversation.', 'Set up review', self.settings),
                ('2  Add context', 'Attach a selected PCB object or a board region.', 'Use PCB selection', self.capture),
                ('3  Discuss', 'Reply, attach evidence and inspect the published thread.', 'Open in provider', self.open_provider)]:
            heading = wx.StaticText(self.sidebar, label=title)
            heading.SetForegroundColour(INK)
            font(heading, 11, bold=True)
            steps.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            explanation = wx.StaticText(self.sidebar, label=detail)
            explanation.SetForegroundColour(MUTED)
            explanation.Wrap(175)
            steps.Add(explanation, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            steps.Add(ActionButton(self.sidebar, action, handler, compact=True), 0, wx.EXPAND | wx.ALL, 12)
        steps.AddStretchSpacer()
        help_button = ActionButton(self.sidebar, 'Help & shortcuts', lambda event: webbrowser.open((Path(__file__).parent / 'help.html').as_uri()), compact=True)
        steps.Add(help_button, 0, wx.EXPAND | wx.ALL, 12)
        self.sidebar.SetSizer(steps)
        body.Add(self.sidebar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        panel = wx.Panel(root)
        panel.SetBackgroundColour(BACKGROUND)
        main = wx.BoxSizer(wx.VERTICAL)
        utility = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText('Search people, references, nets and messages')
        self.search.Bind(wx.EVT_TEXT, lambda event: self.populate())
        utility.Add(self.search, 1, wx.RIGHT | wx.EXPAND, 8)
        utility.Add(ActionButton(panel, 'People', self.highlight_people, compact=True), 0, wx.RIGHT, 6)
        utility.Add(ActionButton(panel, 'Refresh', self.refresh, compact=True), 0)
        main.Add(utility, 0, wx.EXPAND | wx.BOTTOM, 10)
        filters = wx.WrapSizer(wx.HORIZONTAL)
        self.anchored_filter = wx.CheckBox(panel, label='With design context')
        self.anchored_filter.Bind(wx.EVT_CHECKBOX, self.filters_changed)
        filters.Add(self.anchored_filter, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.BOTTOM, 10)
        self.author_filter = wx.Choice(panel, choices=['All people'])
        self.author_filter.SetMinSize((150, -1))
        self.author_filter.SetSelection(0)
        self.author_filter.SetToolTip('Filter by the author of a provider message')
        self.author_filter.Bind(wx.EVT_CHOICE, self.filters_changed)
        filters.Add(self.author_filter, 0, wx.RIGHT | wx.BOTTOM, 8)
        self.clear_filter_button = ActionButton(panel, 'Clear filters', self.clear_filters, compact=True)
        filters.Add(self.clear_filter_button, 0, wx.BOTTOM, 8)
        main.Add(filters, 0, wx.EXPAND)
        self.thread_banner = wx.Panel(panel)
        self.thread_banner.SetBackgroundColour('#e7f2f4')
        thread_layout = wx.BoxSizer(wx.HORIZONTAL)
        self.thread_label = wx.StaticText(self.thread_banner, label='', style=wx.ST_ELLIPSIZE_END)
        self.thread_label.SetMinSize((0, -1))
        self.thread_label.SetForegroundColour(ACCENT)
        thread_layout.Add(self.thread_label, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        thread_layout.Add(ActionButton(self.thread_banner, 'All messages', self.clear_thread, compact=True), 0, wx.ALL, 4)
        self.thread_banner.SetSizer(thread_layout)
        self.thread_banner.Hide()
        main.Add(self.thread_banner, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.status = wx.StaticText(panel, label='Not connected · your draft stays local', style=wx.ST_ELLIPSIZE_END)
        self.status.SetForegroundColour(MUTED)
        font(self.status, 9)
        main.Add(self.status, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        self.splitter.SetMinimumPaneSize(250)
        self.tabs = wx.Notebook(self.splitter)
        self.feeds = []
        for name in ('Comments', 'Discussions'):
            page = wx.Panel(self.tabs)
            page.SetBackgroundColour(BACKGROUND)
            box = wx.BoxSizer(wx.VERTICAL)
            feed = wx.ScrolledWindow(page, style=wx.VSCROLL)
            feed.SetBackgroundColour(BACKGROUND)
            feed.SetScrollRate(0, 8)
            feed.SetSizer(wx.BoxSizer(wx.VERTICAL))
            feed.Bind(wx.EVT_SIZE, self.resize_cards)
            box.Add(feed, 1, wx.EXPAND)
            page.SetSizer(box)
            self.tabs.AddPage(page, name)
            self.feeds.append(feed)
        self.tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGING, self.tab_changing)
        self.tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.tab_changed)
        compose_panel = wx.Panel(self.splitter)
        compose_panel.SetBackgroundColour('#ffffff')
        compose_layout = wx.BoxSizer(wx.VERTICAL)
        self.reply_banner = wx.Panel(compose_panel)
        self.reply_banner.SetBackgroundColour('#e7f2f4')
        reply_layout = wx.BoxSizer(wx.HORIZONTAL)
        self.reply_label = wx.StaticText(self.reply_banner, label='', style=wx.ST_ELLIPSIZE_END)
        self.reply_label.SetMinSize((0, -1))
        self.reply_label.SetForegroundColour(ACCENT)
        reply_layout.Add(self.reply_label, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        reply_layout.Add(ActionButton(self.reply_banner, 'Cancel reply', lambda event: self.cancel_reply(), compact=True), 0, wx.ALL, 4)
        self.reply_banner.SetSizer(reply_layout)
        self.reply_banner.Hide()
        compose_layout.Add(self.reply_banner, 0, wx.EXPAND)
        self.target_label = wx.StaticText(compose_panel, label='', style=wx.ST_ELLIPSIZE_END)
        self.target_label.SetForegroundColour(ACCENT)
        self.target_label.Hide()
        compose_layout.Add(self.target_label, 0, wx.EXPAND | wx.ALL, 8)
        self.composer = Composer(compose_panel, self)
        self.compose = self.composer.editor
        self.attachments_label = self.composer.attachments
        self.send = self.composer.send
        compose_layout.Add(self.composer, 1, wx.EXPAND)
        compose_panel.SetSizer(compose_layout)
        self.splitter.SplitHorizontally(self.tabs, compose_panel, 410)
        self.splitter.SetSashGravity(1.0)
        main.Add(self.splitter, 1, wx.EXPAND)
        panel.SetSizer(main)
        body.Add(panel, 1, wx.EXPAND | wx.RIGHT, 12)
        outer.Add(body, 1, wx.EXPAND | wx.BOTTOM, 12)
        root.SetSizer(outer)
        frame_layout = wx.BoxSizer(wx.VERTICAL)
        frame_layout.Add(root, 1, wx.EXPAND)
        self.SetSizer(frame_layout)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.refresh, self.timer)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_ACTIVATE, self.activation)
        self.Bind(wx.EVT_CHAR_HOOK, self.shortcuts)
        self.Bind(wx.EVT_SIZE, self.workspace_size)
        wx.CallAfter(self.initial_composer_size)
        self.show_empty('Start a design review', 'Connect your saved design, select an issue or discussion, then add a message or a PCB location.')
        if self.values.get('repository'):
            wx.CallAfter(self.connect, dict(self.values))

    def toggle_workflow(self, event=None):
        self._workflow_manual = True
        self.sidebar.Show(not self.sidebar.IsShown())
        self.workflow_button.set_active(self.sidebar.IsShown())
        self.Layout()

    def workspace_size(self, event):
        event.Skip()
        if hasattr(self, 'sidebar') and not self._workflow_manual:
            self.sidebar.Show(self.GetClientSize().width >= 920)
            self.workflow_button.set_active(self.sidebar.IsShown())

    def shortcuts(self, event):
        code = event.GetKeyCode()
        if event.ControlDown() and code == ord('F'):
            self.search.SetFocus()
            self.search.SelectAll()
        elif event.ControlDown() and event.ShiftDown() and code == ord('P'):
            self.composer.toggle_preview()
        elif code == wx.WXK_ESCAPE:
            if self.composer.book.GetSelection() == 1:self.composer.show_editor()
            elif self.reply_to:self.cancel_reply()
            elif self.thread_root:self.clear_thread()
            elif self.search.GetValue() or self.anchored_filter.GetValue() or self.author_filter.GetSelection() > 0:self.clear_filters()
            else:event.Skip()
        else:event.Skip()

    def filters_changed(self, event=None):
        self.window_start, self.render_signature = None, None
        self.populate(force=True)

    def clear_filters(self, event=None):
        self.search.ChangeValue('')
        self.anchored_filter.SetValue(False)
        self.author_filter.SetSelection(0)
        self.filters_changed()

    def focus_thread(self, row):
        if not self.session or row['id'] not in {r['id'] for r in self.session.rows}:
            return
        by_id = {r['id']: r for r in self.session.rows}
        root, seen = by_id[row['id']], set()
        while root.get('parentId') in by_id and root['id'] not in seen:
            seen.add(root['id'])
            root = by_id[root['parentId']]
        self.thread_root = root['id']
        self.window_start, self.render_signature = None, None
        self.populate(force=True)

    def clear_thread(self, event=None):
        self.thread_root = None
        self.window_start, self.render_signature = None, None
        self.populate(force=True)

    def thread_rows(self, rows):
        if self.thread_root is None:return rows
        if not any(row['id'] == self.thread_root for row in rows):
            self.thread_root = None
            return rows
        children = {}
        for row in rows:children.setdefault(row.get('parentId'), []).append(row['id'])
        included, pending = set(), [self.thread_root]
        while pending:
            identifier = pending.pop()
            if identifier in included:continue
            included.add(identifier)
            pending.extend(children.get(identifier, []))
        return [row for row in rows if row['id'] in included]

    def settings(self, event=None):
        if self.busy:
            return
        from .settings_ui import ReviewSetup
        with ReviewSetup(self, self.values) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.connect(dialog.values)

    def initial_composer_size(self):
        if not self.closed:
            self.Layout()
            self.splitter.SetSashPosition(-330)
            self.splitter.GetWindow2().Layout()

    @property
    def feed(self):
        return self.feeds[self.tabs.GetSelection()]

    def Layout(self):
        result = wx.Frame.Layout(self)
        if hasattr(self, 'content_panel'):
            self.content_panel.Layout()
        return result

    def tab_changing(self, event):
        if self.busy:
            event.Veto()
            self.status.SetLabel('Finishing the current operation before changing conversations…')
        else:
            event.Skip()

    def tab_changed(self, event):
        event.Skip()
        self.render_signature, self.window_start = None, None
        if self.values.get('repository'):
            self.connect(dict(self.values))

    def connect(self, values):
        if self.busy or self.closed:
            return
        self.timer.Stop()
        outgoing, text, target = self.session, self.compose.GetValue(), self.target
        images = list(self.pending_attachments)
        previous_tab = self.active_tab
        requested_tab = self.tabs.GetSelection()
        active = dict(values)
        if self.tabs.GetSelection() == 1:
            if values.get('provider', 'github') != 'github':
                self.tabs.ChangeSelection(previous_tab)
                self.status.SetLabel('Discussions uses GitHub Discussions. GitLab notes remain in Comments; change provider in Settings to use Discussions.')
                return
            try:
                number = int(values.get('discussionNumber', 1))
                if number < 1:
                    raise ValueError()
            except (ValueError, TypeError):
                self.tabs.ChangeSelection(previous_tab)
                self.status.SetLabel('Choose a positive GitHub Discussion number in Settings.')
                return
            active.update(kind='discussion', number=number)
        self.compose.Disable()
        self.send.Disable()
        def operation():
            if outgoing:
                outgoing.draft(text, target or outgoing.scope, images)
            session = ReviewSession(active)
            if self.board_path and session.path != self.board_path:
                raise ValueError('The review design differs from the launching editor. Reopen Review from the intended PCB.')
            atomic_json(data_home() / 'settings.json', values)
            session.cached()
            return session
        def ready(session):
            self.values, self.session = values, session
            self.active_tab = requested_tab
            self.reply_to = None
            self.thread_root = None
            self.thread_banner.Hide()
            self.reply_banner.Hide()
            self.target = None
            draft = session.draft()
            self.compose.SetValue(draft['text'] if draft else (text if outgoing is None else ''))
            self.compose.Enable()
            self.send.Enable()
            self.pending_attachments = draft.get('attachments', []) if draft else []
            if draft:
                self.target = draft['anchor']
            self.target_label.Hide()
            if self.target and (self.target.get('uuid') or self.target.get('area')):
                self.set_target(self.target)
            self.update_attachments()
            self.context.SetLabel(session.scope['repository'] + '  ·  ' + ('Discussion' if session.provider.kind == 'discussion' else 'Review')
                                  + ' #' + str(session.provider.number) + '  ·  saved ' + session.scope['ref'][:8])
            self.render_signature, self.window_start = None, None
            self.populate(force=True)
            self.refresh()
        def failed(error):
            self.session = outgoing
            self.tabs.ChangeSelection(previous_tab)
            self.compose.Enable()
            self.send.Enable()
            if outgoing:
                self.render_signature = None
                self.populate(force=True)
            else:
                self.show_empty('Conversation unavailable', error + '\nOpen the provider and choose a conversation in Settings.')
            self.status.SetLabel(error)
        self.show_empty('Connecting…', 'Checking the saved design and provider conversation.')
        if not self.task(operation, ready, 'Checking saved revision…', on_error=failed):
            self.compose.Enable()
            self.send.Enable()

    def show_empty(self, title, message, *, action_label=None, action_handler=None):
        self.feed.GetSizer().Clear(delete_windows=True)
        self.cards = []
        heading = wx.StaticText(self.feed, label=title)
        heading.SetForegroundColour(INK)
        font(heading, 14, bold=True)
        self.feed.GetSizer().Add(heading, 0, wx.ALL, 24)
        text = wx.StaticText(self.feed, label=message)
        text.SetForegroundColour(MUTED)
        text.Wrap(max(250, self.feed.GetClientSize().width - 48))
        self.feed.GetSizer().Add(text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        action = ActionButton(self.feed, action_label or ('Open provider' if self.session else 'Connect a review'),
                              action_handler or (self.open_provider if self.session else self.settings))
        self.feed.GetSizer().Add(action, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        self.feed.FitInside()

    def populate(self, force=False):
        if not self.session:
            return
        all_rows = self.session.rows
        rows = self.thread_rows(all_rows)
        self.reply_counts = {}
        for row in all_rows:
            if row.get('parentId'):self.reply_counts[row['parentId']] = self.reply_counts.get(row['parentId'], 0) + 1
        selected = self.author_filter.GetSelection()
        author = self._author_names[selected-1] if 0 < selected <= len(self._author_names) else None
        people = sorted({row['author'] for row in all_rows}, key=str.casefold)
        if people != self._author_names:
            self.author_filter.SetItems(['All people'] + people)
            self._author_names = people
            self.author_filter.SetSelection(people.index(author)+1 if author in people else 0)
            if author not in people:author = None
        if author:rows = [row for row in rows if row['author'] == author]
        if self.anchored_filter.GetValue():rows = [row for row in rows if row.get('anchors')]
        query = self.search.GetValue().strip().casefold()
        if query:
            rows = [r for r in rows if query in (r['body'] + ' ' + r['author'] + ' ' + json.dumps(r.get('anchors', []))).casefold()]
        filtering = bool(query or author or self.anchored_filter.GetValue())
        self.clear_filter_button.Enable(filtering)
        root = next((row for row in all_rows if row['id'] == self.thread_root), None)
        self.thread_banner.Show(root is not None)
        self.thread_label.SetLabel(('Thread · ' + root['author'] + ' · ' + message_text(root).replace('\n', ' ')[:90]) if root else '')
        self.search.SetDescriptiveText('Search this thread' if root else 'Search people, references, nets and messages')
        self.composer.update_state()
        self.Layout()
        signature = hashlib.sha256(json.dumps([rows, sorted(self.highlighted_authors), self.window_start, self.thread_root, query, author, self.anchored_filter.GetValue()], sort_keys=True).encode()).hexdigest()
        self.status.SetLabel(self.session.status + '  ·  ' + str(len(rows)) + (' matches' if filtering else ' messages')
                            + (' in this thread' if root else '')
                            + ('  ·  ' + short_time(self.session.synced_at) if self.session.synced_at else ''))
        if signature == self.render_signature and not force:
            return
        previous = self.feed.GetViewStart()
        near_bottom = previous[1] * 8 + self.feed.GetClientSize().height >= self.feed.GetVirtualSize().height - 40
        self.feed.Freeze()
        try:
            self.feed.GetSizer().Clear(delete_windows=True)
            self.cards = []
            start = max(0, len(rows) - 80) if self.window_start is None else min(self.window_start, max(0, len(rows) - 1))
            visible = rows[start:start + 80]
            if start:
                older = wx.Button(self.feed, label='Earlier messages', style=wx.BU_EXACTFIT)
                older.Bind(wx.EVT_BUTTON, lambda event: self.page_messages(max(0, start - 80)))
                self.feed.GetSizer().Add(older, 0, wx.ALL | wx.ALIGN_CENTER, 10)
            for row in visible:
                reply = bool(row.get('parentId'))
                card = MessageCard(self.feed, row, self, reply=reply)
                self.cards.append(card)
                self.feed.GetSizer().Add(card, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 22 if reply else 10)
            if start + len(visible) < len(rows):
                newer = wx.Button(self.feed, label='Latest messages ↓', style=wx.BU_EXACTFIT)
                newer.Bind(wx.EVT_BUTTON, lambda event: self.page_messages(None))
                self.feed.GetSizer().Add(newer, 0, wx.ALL | wx.ALIGN_CENTER, 10)
            if not visible:
                if filtering:
                    self.show_empty('No matching messages', 'Try another person, design-context filter or search. Your draft is unchanged.',
                                    action_label='Clear filters', action_handler=self.clear_filters)
                else:
                    self.show_empty('Start the conversation', 'Write a message below, or attach a selected design item.\nComments are published to the configured provider conversation.')
            self.wrap_cards()
            self.render_signature = signature
            if near_bottom and self.window_start is None:
                self.feed.Scroll(-1, self.feed.GetScrollRange(wx.VERTICAL))
            else:
                self.feed.Scroll(*previous)
        finally:
            self.feed.Thaw()

    def page_messages(self, start):
        self.window_start = start
        self.populate(force=True)

    def resize_cards(self, event):
        event.Skip()
        if self.closed:
            return
        if self.resize_call:
            self.resize_call.Stop()
        self.resize_call = wx.CallLater(80, self.wrap_cards)

    def wrap_cards(self):
        if self.closed:
            return
        width = self.feed.GetClientSize().width
        for card in self.cards:
            card.wrap(width - 30)
            card.SetMinSize((-1, card.GetSizer().CalcMin().height))
        self.feed.GetSizer().Layout()
        for card in self.cards:
            card.Layout()
        self.feed.FitInside()

    def begin_reply(self, row):
        self.reply_to = row['id']
        self.reply_label.SetLabel('Replying to ' + row['author'] + ' · ' + MARKER.sub('', row['body']).strip().replace('\n', ' ')[:65])
        self.reply_label.SetToolTip(MARKER.sub('', row['body']).strip())
        self.reply_banner.Show()
        self.composer.update_state()
        self.compose.SetFocus()
        self.Layout()

    def cancel_reply(self):
        self.reply_to = None
        self.reply_banner.Hide()
        self.composer.update_state()
        self.Layout()

    def row(self):
        return next((r for r in self.session.rows if r['id'] == self.reply_to), None) if self.session else None

    def open_provider(self, event=None):
        if self.session:
            provider = self.session.provider
            url = provider.web_url
            if provider.kind == 'discussion' and self.session.status != 'synced' and not self.session.rows:
                url = 'https://github.com/' + provider.repository + '/discussions'
            webbrowser.open(url)
        else:
            try:
                target = scope(self.values)
                if self.tabs.GetSelection() == 1 and target.get('provider', 'github') == 'github':
                    webbrowser.open('https://github.com/' + target['repository'] + '/discussions')
                else:
                    from .providers import Provider
                    webbrowser.open(Provider(self.values).web_url)
            except (ValueError, KeyError):
                self.status.SetLabel('Choose the repository and conversation in Settings first.')

    def refresh_failed(self, error):
        if self.session and self.session.provider.kind == 'discussion' and not self.session.rows:
            self.show_empty('Choose a GitHub Discussion', error + '\n\nOpen the provider to choose or create an engineering topic, then enter its Discussion number in Settings.')

    def open_row(self, row):
        if not self.session:
            return
        # Links are regenerated by the provider after a fresh remote read, never
        # launched from editable local cache text.
        identifier = row['id']
        def operation():
            self.session.refresh()
            current = next((r for r in self.session.rows if r['id'] == identifier), None)
            if not current:
                raise ValueError('This message was removed. Refresh the conversation.')
            return current['url']
        self.task(operation, lambda url: webbrowser.open(url), 'Opening provider message…')

    def locate_row(self, row):
        if self.session:
            self.task(lambda: self.session.locate(row['id']), lambda result: self.status.SetLabel('Selected in PCB Editor · focus ' + result.get('focus', 'unknown')), 'Locating design item…')

    def context_menu(self, event):
        with wx.Menu() as menu:
            for title, handler in [('Selected PCB object', self.capture), ('Region in mm…', self.region), ('Clear design context', self.clear_target)]:
                item = menu.Append(wx.ID_ANY, title)
                self.Bind(wx.EVT_MENU, handler, item)
            self.PopupMenu(menu)

    def clear_target(self, event=None):
        self.target = None
        self.target_label.Hide()
        self.Layout()

    def set_target(self, target):
        self.target = target
        if target.get('uuid') or target.get('area'):
            value = target.get('reference') or target.get('netName') or ('Region · ' + str(target['area']) if target.get('area') else 'Selected PCB object')
            self.target_label.SetLabel('⌖ ' + value)
            self.target_label.Wrap(max(330, self.GetClientSize().width - 32))
            self.target_label.Show()
            self.Layout()

    def choose_image(self, event=None):
        if not self.session or self.busy:
            self.status.SetLabel('Connect a conversation before attaching images.')
            return
        with wx.FileDialog(self, 'Attach review images', wildcard='PNG and JPEG images|*.png;*.jpg;*.jpeg',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.attach_files(dialog.GetPaths())

    def attach_files(self, paths):
        if not self.session or self.busy:
            self.status.SetLabel('Connect a conversation and finish the current operation before adding images.')
            return
        if not paths or len(paths) + len(self.pending_attachments) > 4:
            self.status.SetLabel('A message supports at most four images. Choose fewer files or remove an attachment.')
            return
        self._image_queue = list(paths)
        self._image_session = self.session
        self.next_image()

    def next_image(self):
        if self.closed or not getattr(self, '_image_queue', None):
            return
        if self.session is not self._image_session:
            self._image_queue = []
            self.status.SetLabel('Conversation changed; remaining images were not uploaded.')
            return
        path = Path(self._image_queue.pop(0))
        try:
            from .image_input import image_size, MAX_BYTES
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            width, height = image_size(data)
            with wx.LogNull():
                image = wx.Image(io.BytesIO(data))
            if not image.IsOk() or image.GetWidth() != width or image.GetHeight() != height:
                raise ValueError('The image could not be decoded safely.')
            self.attach_bitmap(wx.Bitmap(image), queued=True)
        except (ValueError, OSError) as error:
            self._image_queue = []
            self.status.SetLabel(str(error))

    def image(self, event=None):
        self.composer.paste(None)

    def attach_bitmap(self, bitmap, *, queued=False):
        if not self.session or self.busy:
            self.status.SetLabel('Connect a conversation and finish the current operation before adding images.')
            return
        if not queued:
            self._image_queue = []
        if self.session.provider.provider == 'github':
            self._image_queue = []
            wx.MessageBox('GitHub has no supported public image-upload API. Paste or drop your image in the GitHub browser editor, then Refresh here. Your local text draft is retained.',
                          'Complete image attachment in GitHub', wx.OK | wx.ICON_INFORMATION, self)
            self.open_provider()
            return
        if len(self.pending_attachments) >= 4:
            self.status.SetLabel('A message supports at most four images.')
            return
        if not bitmap.IsOk() or bitmap.GetWidth()*bitmap.GetHeight() > 16*1024*1024:
            self.status.SetLabel('The image is invalid or exceeds 16 megapixels.')
            return
        image = bitmap.ConvertToImage()
        scale = min(1024/image.GetWidth(), 1024/image.GetHeight(), 1)
        if scale < 1:
            image.Rescale(max(1, int(image.GetWidth()*scale)), max(1, int(image.GetHeight()*scale)))
        stream = io.BytesIO()
        if not image.SaveFile(stream, wx.BITMAP_TYPE_PNG):
            self.status.SetLabel('The image could not be encoded as PNG.')
            return
        with wx.Dialog(self, title='Review image before GitLab upload', size=(640, 520),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) as dialog:
            dialog.SetBackgroundColour('#ffffff')
            layout = wx.BoxSizer(wx.VERTICAL)
            display = image.Copy()
            factor = min(580/display.GetWidth(), 350/display.GetHeight(), 1)
            display.Rescale(max(1, int(display.GetWidth()*factor)), max(1, int(display.GetHeight()*factor)))
            layout.Add(wx.StaticBitmap(dialog, bitmap=wx.Bitmap(display)), 1, wx.ALL | wx.ALIGN_CENTER, 12)
            label = wx.StaticText(dialog, label='This sends the image to the configured GitLab project.\nCheck it for private paths, credentials or unrelated content first.')
            layout.Add(label, 0, wx.ALL, 12)
            layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 12)
            dialog.SetSizer(layout)
            if dialog.ShowModal() != wx.ID_OK:
                self._image_queue = []
                return
        def attached(receipt):
            thumb = image.Copy()
            factor = min(96/thumb.GetWidth(), 60/thumb.GetHeight(), 1)
            thumb.Rescale(max(1, int(thumb.GetWidth()*factor)), max(1, int(thumb.GetHeight()*factor)))
            self._thumbnails[receipt['attachment']['url']] = wx.Bitmap(thumb)
            self.attachment_received(receipt)
            wx.CallAfter(self.next_image)
        def failed(error):
            self._image_queue = []
        self.task(lambda: self.session.provider.upload_png(stream.getvalue()), attached,
                  'Uploading approved image to GitLab…', on_error=failed)

    def compose_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and event.ControlDown():
            self.post()
        elif event.ControlDown() and event.GetKeyCode() in (ord('B'), ord('I'), ord('K')):
            self.composer.format({ord('B'): 'bold', ord('I'): 'italic', ord('K'): 'link'}[event.GetKeyCode()])
        else:
            event.Skip()

    def images_for(self, text):
        return list(self.pending_attachments)

    def attachment_received(self, receipt):
        self.pending_attachments.append(receipt['attachment'])
        self.update_attachments()
        self.status.SetLabel('Screenshot uploaded. Send message publishes its reference with your text.')

    def update_attachments(self):
        count = len(self.pending_attachments)
        self.attachments_label.GetSizer().Clear(delete_windows=True)
        for index, value in enumerate(self.pending_attachments):
            thumbnail = self._thumbnails.get(value['url'])
            if thumbnail:
                self.attachments_label.GetSizer().Add(wx.StaticBitmap(self.attachments_label, bitmap=thumbnail), 0, wx.RIGHT, 6)
            button = ActionButton(self.attachments_label, 'Image ' + str(index + 1) + ' ×', compact=True)
            button.SetToolTip('Remove this screenshot from the pending message. The uploaded provider file is retained.')
            button.Bind(wx.EVT_BUTTON, lambda event, i=index: self.remove_attachment(i))
            self.attachments_label.GetSizer().Add(button, 0, wx.RIGHT, 5)
        self.attachments_label.Show(bool(count))
        self.attachments_label.Layout()
        self.composer.update_state()
        self.composer.Layout()
        if count and not getattr(self, '_attachment_count', 0) and self.splitter.GetClientSize().height > 680:
            self.splitter.SetSashPosition(-420)
        self._attachment_count = count
        self.Layout()

    def remove_attachment(self, index):
        if self.busy:
            return
        if 0 <= index < len(self.pending_attachments):
            removed = self.pending_attachments.pop(index)
            self._thumbnails.pop(removed['url'], None)
            self.update_attachments()

    def post(self, event=None):
        if not self.session or self.busy:
            return
        if self.session.status != 'synced':
            self.status.SetLabel('Refresh the provider before sending. Cached comments are unverified; your draft remains local.')
            return
        if getattr(self, '_image_queue', []):
            self.status.SetLabel('Finish reviewing the queued images before sending this message.')
            return
        draft = self.compose.GetValue()
        images = list(self.pending_attachments)
        text = draft
        if images:
            text += '\n\n' + '\n'.join('![Screenshot](' + image['url'] + ')' for image in images)
        row = self.row()
        if self.reply_to and not row:
            self.status.SetLabel('The reply target is no longer available. Refresh first.')
            return
        target = self.target or (row['anchors'][0] if row and len(row.get('anchors', [])) == 1 else self.session.scope)
        if row and self.session.provider.kind != 'discussion':
            text = '> Reply to ' + row['author'] + ' (' + row['url'] + ')\n\n' + text
        try:
            from .model import note
            note(text, target, reply_to=row['id'] if row else None, attachments=images)
            self.session.draft(draft, target, images)
        except (ValueError, OSError) as error:
            self.status.SetLabel('Could not preserve draft: ' + str(error))
            return
        def complete(identifier):
            if self.compose.GetValue() == draft:
                self.compose.Clear()
                self.pending_attachments = []
                self.update_attachments()
                self.cancel_reply()
            try:
                self.session.draft(self.compose.GetValue(), self.target or self.session.scope, self.pending_attachments)
            except (ValueError, OSError):
                self.status.SetLabel('Message was sent, but the local draft cache could not be updated. Check the provider before reposting.')
                return
            self.status.SetLabel('Message sent. Updating conversation…')
            self.refresh()
        self.task(lambda: self.session.publish(text, target, reply_to=row['id'] if row else None, attachments=images), complete, 'Sending message…')
