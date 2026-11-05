"""Hidden native dialog checks; browser and OAuth traffic are mocked."""
import unittest
from unittest.mock import patch
from unittest.mock import Mock

try:
    import wx
    from review_comments_plugin import desktop_auth_ui as ui
except ImportError:
    wx = None
    ui = None


@unittest.skipUnless(wx is not None, 'native wxPython is unavailable')
class SignInDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.status = patch.object(ui.desktop_auth.AUTH, 'status', return_value={'authenticated': False})
        self.status.start()
        self.addCleanup(self.status.stop)
        self.dialog = ui.SignInDialog(None)
        self.addCleanup(self._close)

    def _close(self):
        if self.dialog:
            self.dialog.Destroy()
            self.app.Yield()

    def test_initial_dialog_does_not_start_signin_or_open_browser(self):
        with patch.object(ui.desktop_auth, 'sign_in') as sign_in, patch.object(ui.webbrowser, 'open') as browser:
            self.assertFalse(self.dialog._working)
            self.assertEqual(self.dialog.code.GetValue(), '')
            self.assertFalse(self.dialog.copy.IsEnabled())
            sign_in.assert_not_called()
            browser.assert_not_called()

    def test_dark_signin_fields_keep_labels_and_disabled_button_readable(self):
        from review_comments_plugin.theme import apply_theme, PALETTES
        from review_comments_plugin.tests.test_theme_contrast import contrast
        apply_theme(self.dialog, 'dark')
        labels = {child.GetLabel(): child for child in self.dialog.GetChildren()
                  if isinstance(child, wx.StaticText)}
        for name in ('One-time code', 'Verification address'):
            control = labels[name]
            foreground = control.GetForegroundColour().GetAsString(wx.C2S_HTML_SYNTAX)
            background = control.GetBackgroundColour().GetAsString(wx.C2S_HTML_SYNTAX)
            self.assertGreaterEqual(contrast(foreground, background), 4.5)
        self.assertEqual(self.dialog.code.GetValue(), '')
        self.assertEqual(self.dialog.verification.GetValue(), '')
        self.assertFalse(self.dialog.copy.IsEnabled())
        dc = Mock()
        dc.GetTextExtent.return_value = (40, 12)
        self.dialog.copy.DrawLabel(dc, 100, 36)
        dc.SetTextForeground.assert_called_once_with(PALETTES['dark']['disabled_text'])
        self.assertEqual(self.dialog.cancel_button.GetId(), wx.ID_CANCEL)
        self.dialog.private.SetValue(True)
        self.dialog.private.Disable()
        self.assertEqual(self.dialog.private.SYS_COLOUR_GRAYTEXT, wx.Colour(PALETTES['dark']['disabled_text']))
        self.dialog.private.Enable()
        self.assertTrue(self.dialog.private.GetValue())

    def test_signin_text_survives_system_white_foreground_and_theme_switches(self):
        from review_comments_plugin.theme import apply_theme
        from review_comments_plugin.tests.test_theme_contrast import contrast
        labels = [child for child in self.dialog.GetChildren() if isinstance(child, wx.StaticText)]
        for label in labels:
            label.SetForegroundColour('#ffffff')
        for theme in ('light', 'dark', 'light'):
            apply_theme(self.dialog, theme)
            for label in labels:
                foreground = label.GetForegroundColour().GetAsString(wx.C2S_HTML_SYNTAX)
                background = label.GetBackgroundColour().GetAsString(wx.C2S_HTML_SYNTAX)
                self.assertGreaterEqual(contrast(foreground, background), 4.5, label.GetLabel())

    def test_progress_opens_verified_uri_and_copy_is_explicit(self):
        value = {'epoch': 7, 'user_code': 'ABCD-EFGH',
                 'verification_uri': 'https://github.com/login/device'}
        with patch.object(ui.webbrowser, 'open', return_value=True) as browser:
            self.dialog._progress(value)
        self.assertEqual(self.dialog.code.GetValue(), 'ABCD-EFGH')
        self.assertEqual(self.dialog.verification.GetValue(), value['verification_uri'])
        self.assertTrue(self.dialog.copy.IsEnabled())
        browser.assert_called_once_with(value['verification_uri'])

    def test_cancel_rejects_late_progress_without_browser(self):
        with patch.object(ui.desktop_auth.AUTH, 'cancel') as cancel, patch.object(
                ui.webbrowser, 'open') as browser:
            self.dialog.cancel()
            self.dialog._progress({'epoch': 9, 'user_code': 'ABCD-EFGH',
                                   'verification_uri': 'https://github.com/login/device'})
        cancel.assert_called_with('github', 'https://github.com', 9)
        browser.assert_not_called()

    def test_unsafe_progress_link_is_never_opened(self):
        with patch.object(ui.desktop_auth.AUTH, 'cancel') as cancel, patch.object(
                ui.webbrowser, 'open') as browser:
            self.dialog._progress({'epoch': 4, 'user_code': 'ABCD-EFGH',
                                   'verification_uri': 'https://github.com/redirect'})
        cancel.assert_called_once_with('github', 'https://github.com', 4)
        browser.assert_not_called()

    def test_success_requires_current_auth_and_does_not_revoke_on_destroy(self):
        self.dialog._epoch = 3
        with patch.object(ui.desktop_auth.AUTH, 'assert_ticket') as ticket, patch.object(
                ui.desktop_auth.AUTH, 'status', return_value={'authenticated': True, 'account': 'alice', 'expiresAt': 1000}), patch.object(
                ui.desktop_auth.AUTH, 'cancel') as cancel:
            self.dialog._completed({'account': 'alice'}, None)
            ticket.assert_called_once_with('github', 'https://github.com', 3)
            self.assertFalse(self.dialog.IsShown())
            self.assertIsNone(self.dialog._epoch)
            self.dialog.Destroy()
            self.app.Yield()
            self.dialog = None
            cancel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
