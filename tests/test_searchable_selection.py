"""Literal search, hidden checked identities and native event compatibility."""
import unittest
from unittest.mock import patch

from wayricad_runtime.searchable_selection import CheckedSelection, SearchIndex, matching_indices

try:
    import wx
except ImportError:
    wx = None


class SelectionModelTests(unittest.TestCase):
    def test_literal_unicode_search_retains_original_duplicate_indices(self):
        items = ['GND', '/Clock/USB[3]_P', 'Straße', 'GND']
        self.assertEqual(matching_indices(items, ' [3] '), [1])
        self.assertEqual(matching_indices(items, 'STRASSE'), [2])
        self.assertEqual(matching_indices(items, 'gnd'), [0, 3])
        self.assertEqual(matching_indices(items, 'missing'), [])

    def test_visible_actions_preserve_hidden_checks(self):
        state = CheckedSelection(['GND', 'CAN_P', 'CAN_N', 'VCC'], [0, 3])
        state.check_visible('can')
        self.assertEqual(state.checked, {0, 1, 2, 3})
        state.check_visible('can', False)
        self.assertEqual(state.checked, {0, 3})
        state.check_visible('unmatched', False)
        self.assertEqual(state.checked, {0, 3})

    def test_index_converts_labels_only_once_across_repeated_queries(self):
        calls = []
        class Label:
            def __str__(self):
                calls.append('converted')
                return '/Board/Long/Clock_P'
        index = SearchIndex([Label()])
        self.assertEqual(index.match('CLOCK'), [0])
        self.assertEqual(index.match('missing'), [])
        self.assertEqual(index.match(''), [0])
        self.assertEqual(calls, ['converted'])


@unittest.skipIf(wx is None, 'Requires native wxPython')
class NativeSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        self.frame = wx.Frame(None)

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()

    def test_scalar_selection_keeps_items_clientdata_and_native_event(self):
        from wayricad_runtime.readable_choice import ReadableChoice, ReadableComboBox
        for cls, event in ((ReadableChoice, wx.EVT_CHOICE),
                           (ReadableComboBox, wx.EVT_COMBOBOX)):
            control = cls(self.frame, choices=['same', '/very/long/net_P', 'same'])
            control.SetSelection(0)
            payload = {'terminal': 'original-uuid'}
            control.SetClientData(1, payload)
            events = []
            control.Bind(event, lambda e: events.append((e.GetInt(), e.GetString(), e.GetEventObject())))
            with patch('wayricad_runtime.searchable_selection.choose_items', return_value=[1]):
                self.assertTrue(control.ShowSearch())
            self.assertEqual(control.GetStrings(), ['same', '/very/long/net_P', 'same'])
            self.assertIs(control.GetClientData(1), payload)
            self.assertEqual(events, [(1, '/very/long/net_P', control)])
            with patch('wayricad_runtime.searchable_selection.choose_items', return_value=None):
                self.assertFalse(control.ShowSearch())
            self.assertEqual(control.GetSelection(), 1)

    def test_multi_events_observe_final_checks_not_partial_update(self):
        from wayricad_runtime.readable_choice import SearchableCheckListBox
        control = SearchableCheckListBox(self.frame, choices=['A', 'B', 'C'])
        control.Check(0)
        seen = []
        control.Bind(wx.EVT_CHECKLISTBOX,
                     lambda e: seen.append((e.GetInt(), control.GetCheckedItems())))
        with patch('wayricad_runtime.searchable_selection.choose_items', return_value=[1, 2]):
            self.assertTrue(control.ShowSearch())
        self.assertEqual(control.GetStrings(), ['A', 'B', 'C'])
        self.assertEqual(control.GetCheckedItems(), (1, 2))
        self.assertEqual(seen, [(0, (1, 2)), (1, (1, 2)), (2, (1, 2))])

    def test_changed_source_during_modal_is_rejected(self):
        from wayricad_runtime.readable_choice import ReadableChoice
        control = ReadableChoice(self.frame, choices=['old-A', 'old-B'])
        def replaced(*args):
            control.Set(['new-A', 'new-B'])
            return [1]
        with patch('wayricad_runtime.searchable_selection.choose_items', side_effect=replaced):
            self.assertFalse(control.ShowSearch())
        self.assertEqual(control.GetSelection(), wx.NOT_FOUND)

    def test_same_labels_repopulated_for_new_source_are_rejected(self):
        from wayricad_runtime.readable_choice import ReadableChoice, SearchableCheckListBox
        for cls in (ReadableChoice, SearchableCheckListBox):
            control = cls(self.frame, choices=['same-A', 'same-B'])
            def replaced(*args):
                control.Set(['same-A', 'same-B'])
                return [1]
            with patch('wayricad_runtime.searchable_selection.choose_items', side_effect=replaced):
                self.assertFalse(control.ShowSearch())

    def test_event_handler_cannot_reenter_or_dispatch_stale_indices(self):
        from wayricad_runtime.readable_choice import SearchableCheckListBox
        control = SearchableCheckListBox(self.frame, choices=['A', 'B', 'C'])
        seen = []
        def changed(event):
            seen.append(event.GetInt())
            self.assertFalse(control.ShowSearch())
            control.Set(['replacement'])
        control.Bind(wx.EVT_CHECKLISTBOX, changed)
        with patch('wayricad_runtime.searchable_selection.choose_items', return_value=[0, 1, 2]) as picker:
            self.assertTrue(control.ShowSearch())
        self.assertEqual(seen, [0])
        self.assertEqual(picker.call_count, 1)
        self.assertEqual(control.GetStrings(), ['replacement'])

    def test_real_filter_dialog_preserves_hidden_checked_items(self):
        from wayricad_runtime.searchable_selection import choose_items
        errors = []
        def interact():
            dialog = next(w for w in wx.GetTopLevelWindows()
                          if isinstance(w, wx.Dialog) and w.GetTitle() == 'Search and choose items')
            try:
                search = next(c for c in dialog.GetChildren() if isinstance(c, wx.SearchCtrl))
                listing = next(c for c in dialog.GetChildren() if isinstance(c, wx.CheckListBox))
                search.SetValue('CAN')
                self.assertEqual(listing.GetStrings(), ['CAN_P', 'CAN_N'])
                listing.Check(1)
                event = wx.CommandEvent(wx.wxEVT_CHECKLISTBOX, listing.GetId())
                event.SetInt(1)
                listing.GetEventHandler().ProcessEvent(event)
                search.SetValue('no match')
                self.assertEqual(listing.GetCount(), 0)
                search.SetValue('')
                self.assertEqual(listing.GetCheckedItems(), (0, 2))
            except Exception as exc:
                errors.append(exc)
            finally:
                dialog.EndModal(wx.ID_OK)
        checks = []
        native_check = wx.CheckListBox.Check
        def check(control, index, checked=True):
            checks.append(checked)
            return native_check(control, index, checked)
        wx.CallLater(50, interact)
        with patch.object(wx.CheckListBox, 'Check', check):
            result = choose_items(self.frame, ['GND', 'CAN_P', 'CAN_N'], checked=[0])
        if errors:
            raise errors[0]
        self.assertEqual(result, [0, 2])
        self.assertTrue(checks)
        self.assertTrue(all(checks), 'New native rows are unchecked without per-row Check(False) calls')


if __name__ == '__main__':
    unittest.main()
