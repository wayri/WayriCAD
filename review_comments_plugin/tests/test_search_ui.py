"""Hidden native checks for the palette-aware Review search field."""
import unittest

try:
    import wx
    from review_comments_plugin.search_ui import ReviewSearch
    from review_comments_plugin.theme import apply_theme, PALETTES
except ImportError:
    wx = None


@unittest.skipUnless(wx is not None, 'native wxPython is unavailable')
class ReviewSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = wx.Frame(None)
        self.search = ReviewSearch(self.frame)
        self.addCleanup(self._close)

    def _close(self):
        self.frame.Destroy()
        self.app.Yield()

    @staticmethod
    def _hex(colour):
        return colour.GetAsString(wx.C2S_HTML_SYNTAX).lower()

    def test_empty_field_has_no_native_hint_or_value(self):
        self.assertEqual(self.search.GetValue(), '')
        self.assertEqual(self.search.field.GetValue(), '')
        self.assertEqual(self.search.caption.GetLabel(), 'Search')
        self.assertFalse(self.search.field.HasFlag(wx.TE_RICH2))
        self.search.SetDescriptiveText('Search this thread')
        self.assertEqual(self.search.caption.GetLabel(), 'Search thread')
        self.assertEqual(self.search.GetValue(), '')

    def test_text_events_propagate_and_changevalue_is_silent(self):
        observed = []
        self.search.Bind(wx.EVT_TEXT, lambda event: observed.append(event.GetString()))
        self.search.SetValue('resistor')
        self.assertEqual(observed, ['resistor'])
        self.search.ChangeValue('capacitor')
        self.assertEqual(observed, ['resistor'])
        self.search.SelectAll()
        self.assertEqual(self.search.field.GetSelection(), (0, len('capacitor')))

    def test_light_dark_theme_preserves_text_and_selection(self):
        self.search.SetValue('R12')
        self.search.field.SetSelection(1, 2)
        for name in ('dark', 'light'):
            apply_theme(self.search, name)
            colors = PALETTES[name]
            self.assertEqual(self.search.GetValue(), 'R12')
            self.assertEqual(self.search.field.GetSelection(), (1, 2))
            self.assertEqual(self._hex(self.search.field.GetBackgroundColour()), colors['surface'])
            self.assertEqual(self._hex(self.search.field.GetForegroundColour()), colors['text'])
            self.assertEqual(self._hex(self.search.caption.GetForegroundColour()), colors['muted'])


if __name__ == '__main__':
    unittest.main()
