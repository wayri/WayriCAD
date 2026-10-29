"""Guided provider/design/conversation setup using the existing validation rules."""
from pathlib import Path

import wx

from .ui import Settings, initial_settings
from .widgets import ActionButton, INK, BACKGROUND


class ReviewSetup(Settings):
    def __init__(self, parent, values):
        wx.Dialog.__init__(self, parent, title='Connect a design review', size=(710, 660),
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((540, 570))
        self.SetBackgroundColour(BACKGROUND)
        self.values = dict(values)
        self.fields = {}
        main = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label='Connect your review workspace')
        title.SetForegroundColour(INK)
        title.SetFont(title.GetFont().Bold().Larger())
        main.Add(title, 0, wx.ALL, 18)
        self.steps = wx.BoxSizer(wx.HORIZONTAL)
        self.step_buttons = []
        for index, name in enumerate(('1  Provider', '2  Saved design', '3  Conversation')):
            button = ActionButton(self, name, lambda event, index=index: self.go(index))
            self.step_buttons.append(button)
            self.steps.Add(button, 1, wx.RIGHT, 6)
        main.Add(self.steps, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 18)
        self.book = wx.Simplebook(self)
        groups = [
            ('Connect uses the existing CLI session. If GitLab explicitly rejects a stored CLI credential, Connect replaces only that host’s rejected CLI connection. Phone and browser sessions stay separate.',
             [('provider', 'Provider', 'github'), ('host', 'GitLab HTTPS origin', 'https://gitlab.com')]),
            ('Choose a saved design matching an immutable Git commit. Unsaved editor changes stay outside this review.',
             [('root', 'Local Git worktree', ''), ('file', 'Design path inside repository', ''),
              ('ref', 'Full saved commit ID', '')]),
            ('Choose the remote conversation. Comments and Discussions remain separate provider threads.',
             [('repository', 'Repository / GitLab project', ''), ('kind', 'Comments conversation type', 'issue'),
              ('number', 'Issue / PR / MR number', '1'), ('discussionNumber', 'GitHub Discussion number', '1')])]
        for index, (explanation, fields) in enumerate(groups):
            page = wx.ScrolledWindow(self.book)
            page.SetScrollRate(0, 10)
            page.SetBackgroundColour('#ffffff')
            layout = wx.BoxSizer(wx.VERTICAL)
            help_text = wx.StaticText(page, label=explanation)
            help_text.Wrap(580)
            layout.Add(help_text, 0, wx.EXPAND | wx.ALL, 16)
            for key, label, default in fields:
                layout.Add(wx.StaticText(page, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
                if key in ('provider', 'kind'):
                    choices = ['github', 'gitlab'] if key == 'provider' else ['issue', 'pull', 'merge_request']
                    control = wx.ComboBox(page, value=str(values.get(key, default)), choices=choices, style=wx.CB_READONLY)
                else:
                    control = wx.TextCtrl(page, value=str(values.get(key, default)))
                control.SetToolTip(label)
                self.fields[key] = control
                layout.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
            if index == 0:
                layout.Add(ActionButton(page, 'Check existing login', self.check_existing), 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
                layout.Add(ActionButton(page, 'Connect with browser', self.login), 0, wx.ALL, 16)
                layout.Add(ActionButton(page, 'Cancel sign-in', lambda event: self.cancel_login(), compact=True), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
                layout.Add(ActionButton(page, 'Copy terminal sign-in command', self.copy_login, compact=True), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
            elif index == 1:
                layout.Add(ActionButton(page, 'Choose saved PCB or schematic…', self.choose_design), 0, wx.ALL, 16)
            else:
                layout.Add(ActionButton(page, 'Open provider work board', self.board), 0, wx.ALL, 16)
            page.SetSizer(layout)
            self.book.AddPage(page, str(index))
        main.Add(self.book, 1, wx.EXPAND | wx.ALL, 18)
        self.login_status = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 65))
        main.Add(self.login_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 18)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        footer.Add(ActionButton(self, 'Help', self.help), 0, wx.RIGHT, 6)
        self.back = ActionButton(self, 'Back', lambda event: self.go(self.book.GetSelection()-1))
        footer.Add(self.back, 0)
        footer.AddStretchSpacer()
        footer.Add(ActionButton(self, 'Cancel', lambda event: self.EndModal(wx.ID_CANCEL)), 0, wx.RIGHT, 6)
        self.next = ActionButton(self, 'Next', self.advance, primary=True)
        self.next.SetMinSize((165, 36))
        footer.Add(self.next, 0)
        main.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 18)
        self.SetSizer(main)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroyed)
        self.go(0)

    def destroyed(self, event):
        if event.GetEventObject() is self:
            self.cancel_login()
        event.Skip()

    def check_existing(self, event):
        import threading
        from .providers import verify_login
        provider = self.fields['provider'].GetValue()
        origin = self.fields['host'].GetValue().strip()
        button = event.GetEventObject()
        button.Disable()
        self.login_status.SetValue('Checking the existing CLI session. No sign-in or credential transfer is performed.')
        def finished(message):
            if self and not self.IsBeingDeleted():
                self.login_status.SetValue(message)
                button.Enable()
        def work():
            try:
                verify_login(provider, origin)
                message = 'Connected: this process can use the existing CLI login.'
            except (ValueError, RuntimeError, OSError) as error:
                message = str(error)
            wx.CallAfter(finished, message)
        threading.Thread(target=work, daemon=True).start()

    def copy_login(self, event=None):
        """Copy a quoted PowerShell command only on the user's explicit action."""
        from .providers import login_command
        try:
            provider = self.fields['provider'].GetValue()
            if provider not in ('github', 'gitlab'):
                raise ValueError('Choose GitHub or GitLab first.')
            command = login_command(provider, self.fields['host'].GetValue().strip())
            quoted = '& ' + ' '.join("'" + part.replace("'", "''") + "'" for part in command)
            if not wx.TheClipboard.Open():
                raise ValueError('The clipboard is busy; try again.')
            try:
                if not wx.TheClipboard.SetData(wx.TextDataObject(quoted)):
                    raise ValueError('The command could not be copied; try again.')
            finally:
                wx.TheClipboard.Close()
            self.login_status.SetValue('Copied the nonsecret PowerShell command. Cancel unfinished sign-in here first, then paste it into your normal terminal and approve the official provider CLI in this computer browser. Return here and connect after terminal sign-in succeeds.')
        except ValueError as error:
            self.login_status.SetValue(str(error))

    def go(self, index):
        index = max(0, min(2, index))
        self.book.SetSelection(index)
        self.back.Enable(index > 0)
        self.next.SetLabel('Connect review' if index == 2 else 'Next')
        for i, button in enumerate(self.step_buttons):
            button.set_active(i == index)
        self.Layout()

    def advance(self, event):
        if self.book.GetSelection() < 2:
            self.go(self.book.GetSelection()+1)
        else:
            self.accept(event)

    def choose_design(self, event):
        with wx.FileDialog(self, 'Choose saved review design', wildcard='KiCad designs|*.kicad_pcb;*.kicad_sch',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            values = initial_settings(Path(dialog.GetPath()))
            if not values.get('root'):
                self.login_status.SetValue('Choose a saved design inside a Git worktree.')
                return
            for key, value in values.items():
                if key in self.fields:
                    self.fields[key].SetValue(str(value))
            self.login_status.SetValue('Loaded the repository, saved revision and design path. Review the conversation next.')
