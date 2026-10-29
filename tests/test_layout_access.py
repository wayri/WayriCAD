"""Native table reading, scroll expansion and destroyed-control lifecycle checks."""
import unittest

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Native wxPython required')
class LayoutAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = wx.Frame(None, size=(800, 550))

    def tearDown(self):
        self.frame.Destroy(); wx.YieldIfNeeded()

    def table(self):
        table = wx.ListCtrl(self.frame, style=wx.LC_REPORT)
        table.InsertColumn(0, 'Reference', width=60)
        table.InsertColumn(1, 'Full property', width=80)
        table.InsertItem(0, 'U1'); table.SetItem(0, 1, 'long value ' + 'x'*1800)
        table.InsertItem(1, 'R1'); table.SetItem(1, 1, 'second value')
        table.Select(0)
        return table

    def test_shared_form_install_adds_action_icons_without_changing_commands(self):
        from wayricad_runtime.layout import install_accessibility
        button = wx.Button(self.frame, label='Preview selected nets')
        button.SetToolTip('Preview only the exact selected nets')
        invoked = []
        button.Bind(wx.EVT_BUTTON, lambda event: invoked.append('preview'))
        install_accessibility(self.frame)
        self.app.Yield()
        self.assertTrue(button.GetBitmap().IsOk())
        self.assertEqual(button.GetLabel(), 'Preview selected nets')
        self.assertEqual(button.GetToolTipText(), 'Preview only the exact selected nets')
        button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId()))
        self.assertEqual(invoked, ['preview'])

    def test_table_snapshot_retains_unclipped_values_and_selection(self):
        from wayricad_runtime.layout import table_data
        table = self.table()
        headers, rows, selected = table_data(table)
        self.assertEqual(selected, [0]); self.assertEqual(headers, ['Reference', 'Full property'])
        self.assertGreater(len(rows[0][1]), 1800)
        self.assertEqual(rows[0][1], 'long value '+'x'*1800)
        self.assertEqual(table.GetSelectedItemCount(), 1)

    def test_later_panel_controls_get_icons_without_duplicate_readers(self):
        from wayricad_runtime.layout import install_accessibility
        table=self.table()
        install_accessibility(self.frame);self.app.Yield()
        toggle=wx.ToggleButton(self.frame,label='Setup')
        install_accessibility(self.frame);self.app.Yield()
        self.assertTrue(toggle.GetBitmap().IsOk())
        self.assertEqual(toggle.GetLabel(),'Setup')
        self.assertEqual(table.GetToolTipText().count('Ctrl+Shift+Enter'),1)

    def test_nested_toolbar_reflows_after_late_icons_without_manual_resize(self):
        from wayricad_runtime.layout import install_accessibility
        header=wx.Panel(self.frame)
        row=wx.WrapSizer(wx.HORIZONTAL)
        buttons=[wx.Button(header,label=label,style=wx.BU_EXACTFIT) for label in ('Setup','Files','Help')]
        for button in buttons:row.Add(button,0,wx.RIGHT,4)
        header.SetSizer(row)
        outer=wx.BoxSizer(wx.VERTICAL);outer.Add(header,0,wx.EXPAND);outer.Add(wx.Panel(self.frame),1,wx.EXPAND)
        self.frame.SetSizer(outer);self.frame.Show();self.frame.Layout();self.app.Yield()
        install_accessibility(self.frame);self.app.Yield()
        for button in buttons:
            image=button.GetBitmap()
            picture=image.GetLogicalSize() if hasattr(image,'GetLogicalSize') else image.GetSize()
            text=button.GetTextExtent(button.GetLabelText())
            self.assertGreaterEqual(button.GetSize().width,text[0]+picture[0]+button.FromDIP(16))

    def test_reader_filters_complete_values_and_details_are_resizable(self):
        from wayricad_runtime.layout import table_data, TableReader
        dialog = TableReader(self.frame, *table_data(self.table()))
        try:
            dialog.Show(); wx.YieldIfNeeded()
            self.assertTrue(dialog.HasFlag(wx.RESIZE_BORDER))
            self.assertIn('x'*1800, dialog.text.GetValue())
            dialog.search.SetValue('second value'); dialog.filter()
            self.assertEqual(dialog.indices, [1]); self.assertIn('R1', dialog.text.GetValue())
            dialog.SetSize((700, 500)); dialog.Layout(); wx.YieldIfNeeded()
            self.assertGreater(dialog.text.GetSize().width, 250)
            dialog.search.SetValue('not present'); dialog.filter()
            self.assertEqual(dialog.indices, [])
        finally:
            dialog.Destroy()

    def test_table_reader_retains_supplementary_unicode_characters(self):
        from wayricad_runtime.layout import full_item_text
        table = self.table()
        value = '\U0001f9ea'*600
        table.SetItem(0, 1, value)
        self.assertEqual(full_item_text(table, 0, 1), value)

    def test_collapsible_parent_scrolls_to_new_content(self):
        from wayricad_runtime.layout import relayout
        scroll = wx.ScrolledWindow(self.frame, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 12)
        outer = wx.BoxSizer(wx.VERTICAL)
        pane = wx.CollapsiblePane(scroll, label='More options', style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        inner = wx.BoxSizer(wx.VERTICAL)
        inner.Add(wx.TextCtrl(pane.GetPane(), style=wx.TE_MULTILINE, size=(240, 800)), 0, wx.EXPAND)
        pane.GetPane().SetSizer(inner); outer.Add(pane, 0, wx.EXPAND); scroll.SetSizer(outer)
        root = wx.BoxSizer(wx.VERTICAL); root.Add(scroll, 1, wx.EXPAND); self.frame.SetSizer(root)
        self.frame.Show(); wx.YieldIfNeeded(); pane.Collapse(False); relayout(pane)
        self.assertGreater(scroll.GetVirtualSize().height, scroll.GetClientSize().height)
        scroll.Scroll(0, 100); self.assertGreater(scroll.GetViewStart()[1], 0)

    def test_install_is_idempotent_and_safe_before_destruction(self):
        from wayricad_runtime.layout import install_accessibility
        table = self.table()
        install_accessibility(self.frame); install_accessibility(self.frame)
        wx.YieldIfNeeded()
        self.assertTrue(table._wayricad_reader)
        self.assertEqual(table.GetToolTipText().count('Ctrl+Shift+Enter'), 1)
        ephemeral = wx.Frame(None); install_accessibility(ephemeral); ephemeral.Destroy(); wx.YieldIfNeeded()

    def test_readable_choice_queued_resize_after_destroy_is_harmless(self):
        from wayricad_runtime.readable_choice import ReadableChoice
        control = ReadableChoice(self.frame, choices=['long net '*30])
        control.Destroy(); wx.YieldIfNeeded()
        control._popup_dirty = True
        control._update_popup()
        control._refresh_tip()

    def test_grid_snapshot_uses_column_names_and_full_values(self):
        import wx.grid as grid
        from wayricad_runtime.layout import table_data
        table = grid.Grid(self.frame); table.CreateGrid(2, 2)
        table.SetColLabelValue(0, 'Rule'); table.SetCellValue(0, 1, 'scope '*200)
        table.SetGridCursor(0, 0)
        headers, rows, selected = table_data(table)
        self.assertEqual(headers[0], 'Rule'); self.assertEqual(rows[0][1], 'scope '*200)
        self.assertEqual(selected, [0])


if __name__ == '__main__':
    unittest.main()
