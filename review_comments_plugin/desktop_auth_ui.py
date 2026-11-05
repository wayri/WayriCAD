"""Small native device-code sign-in dialog for process-memory Review auth."""
from __future__ import annotations

from datetime import datetime
import threading
import weakref
import webbrowser

import wx
from wx.lib.checkbox import GenCheckBox
from .widgets import ActionButton

from . import desktop_auth


class SignInDialog(wx.Dialog):
    """Explicit browser sign-in; no token or terminal input is displayed."""

    def __init__(self, parent, provider='github', origin='https://github.com', theme=None):
        super().__init__(parent, title='Sign in to Review', size=(470, 320),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.provider, self.origin = provider, origin
        self._cancelled = threading.Event()
        self._epoch = None
        self._closed = False
        self._working = False
        layout = wx.BoxSizer(wx.VERTICAL)
        service = 'GitHub' if provider == 'github' else 'GitLab'
        heading = wx.StaticText(self, label=f'Sign in to {service} for Review')
        heading.SetFont(heading.GetFont().Bold().Larger())
        layout.Add(heading, 0, wx.EXPAND | wx.ALL, 16)
        self.instructions = wx.StaticText(self, label='Choose Sign in browser to request a one-time code. Approve Review there, then return here.')
        self.instructions.Wrap(420)
        layout.Add(self.instructions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.private = GenCheckBox(self, label='Include private GitHub repositories (broad repo write scope)')
        self.private.Show(provider == 'github')
        layout.Add(self.private, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        layout.Add(wx.StaticText(self, label='One-time code'), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        code_row = wx.BoxSizer(wx.HORIZONTAL)
        self.code = wx.TextCtrl(self, style=wx.TE_READONLY)
        code_row.Add(self.code, 1, wx.RIGHT, 8)
        self.copy = ActionButton(self, 'Copy code')
        self.copy.Disable()
        code_row.Add(self.copy, 0)
        layout.Add(code_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        layout.Add(wx.StaticText(self, label='Verification address'), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.verification = wx.TextCtrl(self, style=wx.TE_READONLY)
        layout.Add(self.verification, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.message = wx.StaticText(self, label='No sign-in has started.')
        self.message.Wrap(420)
        layout.Add(self.message, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.AddStretchSpacer()
        self.cancel_button = ActionButton(self, 'Cancel', id=wx.ID_CANCEL)
        actions.Add(self.cancel_button, 0, wx.RIGHT, 8)
        self.primary = ActionButton(self, 'Sign in browser', primary=True)
        actions.Add(self.primary, 0)
        layout.Add(actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.SetSizerAndFit(layout)
        self.SetMinSize((430, 290))
        self.primary.Bind(wx.EVT_BUTTON, self.start)
        self.copy.Bind(wx.EVT_BUTTON, self.copy_code)
        self.cancel_button.Bind(wx.EVT_BUTTON, self.cancel)
        self.Bind(wx.EVT_CLOSE, self.cancel)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)
        from .theme import apply_theme, theme_of
        apply_theme(self, theme or theme_of(parent))
        self._show_existing()

    def _show_existing(self):
        state = desktop_auth.AUTH.status(self.provider, self.origin)
        if state['authenticated']:
            until = datetime.fromtimestamp(state['expiresAt']).strftime('%Y-%m-%d %H:%M')
            self.message.SetLabel(f"Signed in as {state['account']} until {until}. Review will require a new sign-in after expiry.")
            self.primary.SetLabel('Done')

    def _alive(self):
        return not self._closed and not self.IsBeingDeleted()

    def start(self, event=None):
        if not self._alive() or self._working:
            return
        if desktop_auth.AUTH.status(self.provider, self.origin)['authenticated']:
            self._finish()
            return
        self._working = True
        self._cancelled.clear()
        self.code.SetValue('')
        self.verification.SetValue('')
        self.copy.Disable()
        self.private.Disable()
        self.primary.Disable()
        self.message.SetLabel('Requesting a one-time code…')
        reference = weakref.ref(self)
        provider, origin, private = self.provider, self.origin, self.private.GetValue()
        cancelled = self._cancelled

        def progress(value):
            epoch = value.get('epoch')
            if cancelled.is_set():
                if isinstance(epoch, int):
                    desktop_auth.AUTH.cancel(provider, origin, epoch)
                return
            dialog = reference()
            if dialog is not None:
                wx.CallAfter(dialog._progress, value)

        def work():
            try:
                receipt = desktop_auth.sign_in(provider, origin, progress=progress,
                                               cancelled=cancelled.is_set, private=private)
                outcome = (receipt, None)
            except (ValueError, RuntimeError, OSError) as error:
                outcome = (None, str(error))
            dialog = reference()
            if dialog is not None:
                wx.CallAfter(dialog._completed, *outcome)

        threading.Thread(target=work, name='Review device sign-in', daemon=True).start()

    def _progress(self, value):
        epoch = value.get('epoch')
        if not self._alive() or self._cancelled.is_set():
            if isinstance(epoch, int):
                desktop_auth.AUTH.cancel(self.provider, self.origin, epoch)
            return
        base = desktop_auth._key(self.provider, self.origin)[1]
        expected = base + ('/login/device' if self.provider == 'github' else '/oauth/device')
        if value.get('verification_uri') != expected:
            if isinstance(epoch, int):
                desktop_auth.AUTH.cancel(self.provider, self.origin, epoch)
            self.message.SetLabel('Provider returned an unsafe verification address. Start sign-in again.')
            self.primary.Enable()
            self.private.Enable()
            self._working = False
            return
        self._epoch = epoch
        self.code.SetValue(value['user_code'])
        self.verification.SetValue(value['verification_uri'])
        self.copy.Enable()
        self.message.SetLabel('Enter the code in your browser, approve Review, then return here. This window waits for approval.')
        if not webbrowser.open(value['verification_uri']):
            self.message.SetLabel('Open the verification address shown above in your browser and enter the code.')

    def _completed(self, receipt, error):
        if not self._alive() or self._cancelled.is_set():
            if self._epoch is not None:
                desktop_auth.AUTH.cancel(self.provider, self.origin, self._epoch)
            return
        self._working = False
        if error:
            self.message.SetLabel(error)
            self.primary.Enable()
            self.private.Enable()
            return
        try:
            desktop_auth.AUTH.assert_ticket(self.provider, self.origin, self._epoch)
            if not desktop_auth.AUTH.status(self.provider, self.origin)['authenticated']:
                raise desktop_auth.SignInRequired('Review sign-in expired. Sign in again.')
        except desktop_auth.SignInRequired as failure:
            self.message.SetLabel(str(failure))
            self.primary.Enable()
            self.private.Enable()
            return
        self._finish()

    def _finish(self):
        if self._alive():
            self._epoch = None  # Closing a successful dialog must not revoke its receipt.
            self._closed = True
            self.EndModal(wx.ID_OK) if self.IsModal() else self.Hide()

    def copy_code(self, event=None):
        value = self.code.GetValue()
        if not value or not wx.TheClipboard.Open():
            self.message.SetLabel('The code is unavailable or the clipboard is busy.')
            return
        try:
            if not wx.TheClipboard.SetData(wx.TextDataObject(value)):
                self.message.SetLabel('Could not copy the code. Select it and copy manually.')
        finally:
            wx.TheClipboard.Close()

    def cancel(self, event=None):
        if self._closed:
            return
        self._closed = True
        self._cancelled.set()
        if self._epoch is not None:
            desktop_auth.AUTH.cancel(self.provider, self.origin, self._epoch)
        self.EndModal(wx.ID_CANCEL) if self.IsModal() else self.Hide()

    def _destroyed(self, event):
        if event.GetEventObject() is self:
            self._closed = True
            self._cancelled.set()
            if self._epoch is not None:
                desktop_auth.AUTH.cancel(self.provider, self.origin, self._epoch)
        event.Skip()
