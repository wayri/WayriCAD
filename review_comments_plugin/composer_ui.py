"""Native Markdown composer with safe local preview and explicit attachment inputs."""
from __future__ import annotations

import wx
import wx.html

from .widgets import ActionButton, INK, ACCENT


class ReviewDropTarget(wx.DropTarget):
    """Accept image files, bitmap data or text without opening links or executing HTML."""
    def __init__(self, composer):
        super().__init__()
        self.composer = composer
        self.files = wx.FileDataObject()
        self.bitmap = wx.BitmapDataObject()
        self.html = wx.HTMLDataObject()
        self.text = wx.TextDataObject()
        self.data = wx.DataObjectComposite()
        self.data.Add(self.files, True)
        self.data.Add(self.bitmap)
        self.data.Add(self.html)
        self.data.Add(self.text)
        self.SetDataObject(self.data)

    def OnDragOver(self, x, y, result):
        return wx.DragCopy if self.composer.editor.IsEnabled() else wx.DragNone

    def OnData(self, x, y, result):
        if not self.composer.editor.IsEnabled() or not self.GetData():
            return wx.DragNone
        received = self.data.GetReceivedFormat()
        kind = received.GetType()
        if kind == wx.DF_FILENAME:
            self.composer.owner.attach_files(self.files.GetFilenames())
        elif kind in (wx.DF_BITMAP, wx.DF_DIB):
            bitmap = self.bitmap.GetBitmap()
            if bitmap.IsOk():
                self.composer.owner.attach_bitmap(bitmap)
        elif received == self.html.GetFormat():
            from .composer_format import html_to_markdown
            try:
                self.composer.insert_text(html_to_markdown(self.html.GetHTML()))
            except ValueError as error:
                self.composer.owner.status.SetLabel(str(error))
                return wx.DragNone
        else:
            self.composer.insert_text(self.text.GetText())
        return wx.DragCopy


class Composer(wx.Panel):
    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner
        self.SetBackgroundColour('#ffffff')
        self.preview_call = None
        layout = wx.BoxSizer(wx.VERTICAL)
        mode = wx.BoxSizer(wx.HORIZONTAL)
        self.mode_label = wx.StaticText(self, label='New message', style=wx.ST_ELLIPSIZE_END)
        self.mode_label.SetMinSize((0, -1))
        self.mode_label.SetForegroundColour(INK)
        mode.Add(self.mode_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.write_button = ActionButton(self, 'Write', lambda event: self.show_editor(), compact=True)
        self.preview_button = ActionButton(self, 'Preview', self.toggle_preview, compact=True)
        self.write_button.set_active(True)
        self.preview_button.SetToolTip('Local Markdown preview · Ctrl+Shift+P · no remote resources')
        mode.Add(self.write_button, 0, wx.RIGHT, 4)
        mode.Add(self.preview_button, 0)
        layout.Add(mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        toolbar = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.extra_formats = wx.Panel(self)
        self.extra_formats.SetBackgroundColour('#ffffff')
        extras = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.format_buttons = {}
        for label, action, tip in [('B', 'bold', 'Bold'), ('I', 'italic', 'Italic'),
                ('</>', 'inlinecode', 'Inline code'), ('H', 'heading', 'Heading'),
                ('• List', 'bullets', 'Bulleted list'), ('1. List', 'numbered', 'Numbered list'), ('☑', 'tasks', 'Task list'),
                ('❝', 'quote', 'Quote'), ('Link', 'link', 'HTTPS link'),
                ('Table', 'table', 'Engineering table'), ('Code', 'codeblock', 'Code block')]:
            primary = action in ('bold', 'italic', 'inlinecode', 'link')
            button = ActionButton(self if primary else self.extra_formats, label, lambda event, action=action: self.format(action), compact=True)
            button.SetToolTip(tip)
            if action in ('bold', 'italic'):
                face = button.GetFont()
                if action == 'bold':
                    face.SetWeight(wx.FONTWEIGHT_BOLD)
                else:
                    face.SetStyle(wx.FONTSTYLE_ITALIC)
                button.SetFont(face)
            (toolbar if primary else extras).Add(button, 0, wx.RIGHT | wx.BOTTOM, 4)
            self.format_buttons[action] = button
        self.more_button = ActionButton(self, 'More formats', self.toggle_formats, compact=True)
        self.more_button.SetToolTip('Headings, lists, tasks, quotes, tables and code blocks')
        toolbar.Add(self.more_button, 0, wx.BOTTOM, 4)
        layout.Add(toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.extra_formats.SetSizer(extras)
        self.extra_formats.Hide()
        layout.Add(self.extra_formats, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.book = wx.Simplebook(self)
        self.editor = wx.TextCtrl(self.book, style=wx.TE_MULTILINE | wx.TE_RICH2 | wx.BORDER_NONE)
        self.editor.SetBackgroundColour('#ffffff')
        self.editor.SetForegroundColour(INK)
        self.editor.SetHint('Write a review… Paste screenshots or drop PNG / JPEG images here.')
        self.editor.SetMinSize((-1, 110))
        self.editor.SetMaxLength(16000)
        self.editor.SetDropTarget(ReviewDropTarget(self))
        self.editor.Bind(wx.EVT_TEXT_PASTE, self.paste)
        self.editor.Bind(wx.EVT_TEXT, self.changed)
        self.editor.Bind(wx.EVT_KEY_DOWN, owner.compose_key)
        self.preview = wx.html.HtmlWindow(self.book, style=wx.html.HW_SCROLLBAR_AUTO | wx.BORDER_NONE)
        self.preview.SetDropTarget(ReviewDropTarget(self))
        self.preview.Bind(wx.html.EVT_HTML_LINK_CLICKED, lambda event: None)
        self.book.AddPage(self.editor, 'Write')
        self.book.AddPage(self.preview, 'Preview')
        layout.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.attachments = wx.Panel(self)
        self.attachments.SetBackgroundColour('#ffffff')
        self.attachments.SetSizer(wx.WrapSizer(wx.HORIZONTAL))
        self.attachments.Hide()
        layout.Add(self.attachments, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        footer = wx.WrapSizer(wx.HORIZONTAL)
        self.context_button = ActionButton(self, '+ Context', owner.context_menu, compact=True)
        self.image_button = ActionButton(self, 'Image', owner.choose_image, compact=True)
        self.paste_button = ActionButton(self, 'Paste', lambda event: self.paste(None), compact=True)
        for button in (self.context_button, self.image_button, self.paste_button):
            footer.Add(button, 0, wx.RIGHT | wx.BOTTOM, 5)
        self.send = ActionButton(self, 'Send message', owner.post, primary=True, compact=True)
        self.send.SetToolTip('Publish to this conversation · Ctrl+Enter · drafts stay local until sent')
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(footer, 1, wx.EXPAND | wx.RIGHT, 8)
        actions.Add(self.send, 0, wx.ALIGN_BOTTOM | wx.BOTTOM, 5)
        layout.Add(actions, 0, wx.EXPAND | wx.ALL, 10)
        self.hint = wx.StaticText(self, label='Markdown · Ctrl+Enter sends · 4000 published / 16000 draft characters', style=wx.ST_ELLIPSIZE_END)
        self.hint.SetMinSize((0, -1))
        self.hint.SetForegroundColour('#65738b')
        layout.Add(self.hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(layout)
        self.SetDropTarget(ReviewDropTarget(self))
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroyed)

    def toggle_formats(self, event=None):
        expanded = not self.extra_formats.IsShown()
        self.extra_formats.Show(expanded)
        self.more_button.set_active(expanded)
        self.more_button.SetLabel('Fewer formats' if expanded else 'More formats')
        self.Layout()
        self.GetParent().Layout()

    def show_editor(self):
        self.book.SetSelection(0)
        self.write_button.set_active(True)
        self.preview_button.set_active(False)
        self.editor.SetFocus()

    def update_state(self):
        count = len(self.editor.GetValue())
        images = getattr(self.owner, 'pending_attachments', [])
        published = count + (2 + sum(len('![Screenshot](' + image['url'] + ')') for image in images) + max(0, len(images)-1) if images else 0)
        row = self.owner.row() if hasattr(self.owner, 'row') else None
        session = self.owner.session
        if row and session and session.provider.kind != 'discussion':
            published += len('> Reply to ' + row['author'] + ' (' + row.get('url', session.provider.web_url) + ')\n\n')
        replying = bool(getattr(self.owner, 'reply_to', None))
        self.send.SetLabel('Send reply' if replying else 'Send message')
        destination = ('Discussion' if session.provider.kind == 'discussion' else 'Conversation') + ' #' + str(session.provider.number) if session else 'Connect a review'
        self.mode_label.SetLabel(('Reply · ' if replying else 'New message · ') + destination)
        self.hint.SetLabel(str(published) + ' / 4000 published · ' + str(count) + ' / 16000 draft' +
                           (' · shorten before sending' if published > 4000 else ' · Ctrl+Enter sends'))
        self.hint.SetForegroundColour('#aa4b21' if published > 4000 else '#65738b')
        self.hint.SetToolTip(self.hint.GetLabel())
        self.Layout()

    def destroyed(self, event):
        if event.GetEventObject() is self and self.preview_call:
            self.preview_call.Stop()
        event.Skip()

    def insert_text(self, text):
        self.show_editor()
        try:
            start, end = self.editor.GetSelection()
            if len(self.editor.GetValue()) - (end-start) + len(text) > 16000:
                raise ValueError('The message is limited to 16000 characters; split the review into replies.')
            self.editor.WriteText(text)
        except ValueError as error:
            self.owner.status.SetLabel(str(error))

    def format(self, action):
        if not self.editor.IsEnabled():
            return
        from .composer_format import apply_format
        url = None
        if action == 'link':
            with wx.TextEntryDialog(self, 'HTTPS URL', 'Insert link', 'https://') as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                url = dialog.GetValue()
        try:
            # wx offsets count native CRLF/UTF-16 positions on Windows. Convert
            # through GetRange, then use WriteText for a single undoable edit.
            start, end = self.editor.GetSelection()
            prefix = self.editor.GetRange(0, start)
            selected = self.editor.GetStringSelection()
            text = self.editor.GetValue()
            result, first, last = apply_format(text, len(prefix), len(prefix)+len(selected), action, url=url)
            self.editor.SelectAll()
            self.editor.WriteText(result)
            native_first = self.native_offset(first)
            self.editor.SetSelection(native_first, self.native_offset(last))
            self.show_editor()
        except ValueError as error:
            self.owner.status.SetLabel(str(error))

    def native_offset(self, python_offset):
        # RichEdit offsets count UTF-16 code units, with one position per LF.
        # XYToPosition counts wrapped visual lines, so cannot map logical text.
        prefix = self.editor.GetValue()[:python_offset]
        return len(prefix.encode('utf-16-le'))//2 if wx.Platform == '__WXMSW__' else len(prefix)

    def changed(self, event):
        event.Skip()
        self.update_state()
        if self.book.GetSelection() == 1:
            if self.preview_call:
                self.preview_call.Stop()
            self.preview_call = wx.CallLater(100, self.render_preview)

    def render_preview(self):
        if self.owner.closed:
            return
        from .composer_format import preview_html
        try:
            self.preview.SetPage(preview_html(self.editor.GetValue()))
        except ValueError as error:
            self.owner.status.SetLabel(str(error))

    def toggle_preview(self, event=None):
        preview = self.book.GetSelection() == 0
        if preview:
            self.render_preview()
        self.book.SetSelection(1 if preview else 0)
        self.preview_button.set_active(preview)
        self.write_button.set_active(not preview)
        if not preview:self.editor.SetFocus()

    def paste(self, event=None):
        if not self.editor.IsEnabled() or not wx.TheClipboard.Open():
            return
        bitmap = wx.BitmapDataObject()
        html = wx.HTMLDataObject()
        text = wx.TextDataObject()
        files = wx.FileDataObject()
        try:
            if wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_BITMAP)) and wx.TheClipboard.GetData(bitmap):
                kind, value = 'bitmap', bitmap.GetBitmap()
            elif wx.TheClipboard.IsSupported(html.GetFormat()) and wx.TheClipboard.GetData(html):
                kind, value = 'html', html.GetHTML()
            elif wx.TheClipboard.GetData(files) and files.GetFilenames():
                kind, value = 'files', files.GetFilenames()
            elif wx.TheClipboard.GetData(text):
                kind, value = 'text', text.GetText()
            else:
                kind, value = None, None
        finally:
            wx.TheClipboard.Close()
        if kind == 'bitmap':
            self.owner.attach_bitmap(value)
        elif kind == 'files':
            self.owner.attach_files(value)
        elif kind == 'html':
            from .composer_format import html_to_markdown
            try:
                self.insert_text(html_to_markdown(value))
            except ValueError as error:
                self.owner.status.SetLabel(str(error))
        elif kind == 'text':
            self.insert_text(value)
