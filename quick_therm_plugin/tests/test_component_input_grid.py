"""Native wx input-table behavior in a bounded, isolated process."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


NATIVE_GRID = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import wx
from quick_therm_plugin.component_input_grid import ComponentInputPanel
from quick_therm_plugin.component_inputs import ComponentInputsModel
from quick_therm_plugin.tests.test_component_inputs import INVENTORY, MAPPING, LIMITS
app = wx.App(False)
frame = wx.Frame(None, size=(1250, 500))
notifications, selections = [], []
panel = ComponentInputPanel(frame, ComponentInputsModel(
    INVENTORY, MAPPING, selected_references=['U1', 'R1'], limit_field_map=LIMITS),
    on_change=notifications.append, on_select=selections.append)
sizer = wx.BoxSizer(wx.VERTICAL); sizer.Add(panel, 1, wx.EXPAND)
frame.SetSizer(sizer); frame.Show(); wx.Yield()
assert panel.select_all_button.IsShown()
assert panel.select_all_button.GetLabel() == 'Select all'
row = panel.table.references.index('U1')
assert panel.grid.GetCellValue(row, 4) == '250 mW'
assert not panel.grid.IsReadOnly(row, 6), 'RthetaJB always editable'
panel.grid.SetGridCursor(row, 6); panel.grid.EnableCellEditControl(); wx.Yield()
editor = panel.grid.GetCellEditor(row, 6)
editor.GetControl().SetValue('8 K/W'); editor.DecRef()
panel.commit_pending_edits()
assert panel.effective_values()['U1']['theta_jb_k_per_w'] == 8
assert notifications[-1]['manual_values']['U1']['theta_jb_k_per_w'] == 8
assert panel.model.cell('U1', 'theta_jb_k_per_w').source_raw == '5 °C/W'
panel.grid.SetFocus(); wx.Yield(); panel.grid.EnableCellEditControl()
editor = panel.grid.GetCellEditor(row, 6)
editor.GetControl().SetValue('0'); editor.DecRef()
try:
    panel.commit_pending_edits()
    raise AssertionError('Invalid editor must block commit')
except ValueError:
    pass
assert panel.model.cell('U1', 'theta_jb_k_per_w').value == 8
editor = panel.grid.GetCellEditor(row, 6)
editor.GetControl().SetValue(''); editor.DecRef()
panel.commit_pending_edits()
assert 'theta_jb_k_per_w' not in panel.effective_values()['U1']
panel.search.ChangeValue('controller'); panel._filter(); wx.Yield()
assert panel.table.references == ['U1']
assert panel.selected_references() == ['R1', 'U1'], 'hidden checked scope retained'
panel._select_all(False); assert panel.selected_references() == []
panel._select_visible(); assert panel.selected_references() == ['U1']
panel._select_all(True); assert panel.selected_references() == ['R1', 'U1', 'U2']
assert 'including hidden rows' in panel.scope.GetLabel()
panel.search.ChangeValue(''); panel._filter(); wx.Yield()
row = panel.table.references.index('U1')
panel.grid.SetGridCursor(row, 4); wx.Yield()
assert selections[-1] == 'U1', 'cross-selection callback'
panel.grid.SelectRow(row); panel._restore_saved()
assert panel.effective_values()['U1']['theta_jb_k_per_w'] == 5
panel.search.ChangeValue('no matches'); panel._filter(); wx.Yield()
assert panel.grid.GetNumberRows() == 0
assert panel.export_state()['references'] == ['R1', 'U1', 'U2']
panel.load(INVENTORY, MAPPING, {'R1': {'power_w': 0}}, ['R1'], LIMITS)
panel.search.ChangeValue(''); panel._filter(); wx.Yield()
assert panel.effective_values()['R1']['power_w'] == 0
frame.Destroy(); wx.Yield(); app.Destroy()
print('Native component grid passed: prefill, JB edit, invalid commit, blank, scope, search, provenance, callbacks.')
'''


class NativeInputGridTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("wx"), "Native wx bindings unavailable")
    def test_native_input_review(self):
        root = Path(__file__).resolve().parents[2]
        run = subprocess.run([sys.executable, "-B", "-I", "-c", NATIVE_GRID, str(root)],
                             stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Native component grid passed", run.stdout)


if __name__ == "__main__":
    unittest.main()
