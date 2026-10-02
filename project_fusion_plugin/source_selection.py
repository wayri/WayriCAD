"""Inline selection of exact schematic sheet occurrences for Fusion sources.

The panel only captures a request. Native extraction and validation run later in
the caller's worker thread through :func:`materialize_selection`.
"""
from __future__ import annotations

from pathlib import Path

from .model import MergeError
from .schematic import discover, new_uuid
from .sections import (list_sections, suggest_region, preview_section, apply_section,
                       preview_schematic_sections, apply_schematic_sections)

try:
    import wx
except ImportError:  # Keep the extraction API usable in headless tests.
    wx = None


def _normalize_request(request):
    if not isinstance(request, dict):
        raise MergeError('Choose a Fusion source selection.')
    whole = request.get('whole_project')
    if not isinstance(whole, bool):
        raise MergeError('Choose either the whole project or exact sheet occurrences.')
    paths = request.get('sheet_paths', [])
    if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
        raise MergeError('Sheet occurrences must be exact UUID paths.')
    depth = request.get('max_depth')
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int) or depth < 0 or depth > 31):
        raise MergeError('Selection depth must be 0–31 or unlimited.')
    layout = request.get('include_layout', False)
    if not isinstance(layout, bool):
        raise MergeError('Layout selection must be yes or no.')
    if whole:
        if paths or depth is not None or request.get('region_mm') is not None:
            raise MergeError('Whole-project selection cannot also choose sheets, depth or a PCB rectangle.')
    elif not paths:
        raise MergeError('Check at least one sheet occurrence.')
    if layout and not whole and len(paths) != 1:
        raise MergeError('Routed layout extraction needs exactly one selected sheet subtree.')
    return whole, paths, depth, layout


def materialize_selection(spec, request, destination, cli_path=''):
    """Return mergeable source copies after preview, stale-hash and native checks.

    ``destination`` is a new folder outside the original source.  A whole
    project needs no extraction and returns its original SourceSpec unchanged.
    """
    whole, paths, depth, layout = _normalize_request(request)
    if whole:
        if layout:
            return [spec]
        root = discover(spec, new_uuid(), require_board=False).sheets[0].old_path
        plan = preview_schematic_sections(spec, [root], cli_path, allow_root=True)
        return apply_schematic_sections(plan, Path(destination))
    destination = Path(destination)
    if layout:
        region = request.get('region_mm')
        if region is None:
            region = suggest_region(spec, paths[0], cli_path, max_depth=depth)
        plan = preview_section(spec, paths[0], region, cli_path, max_depth=depth)
        return [apply_section(plan, destination)]
    if request.get('region_mm') is not None:
        raise MergeError('A PCB rectangle only applies when copying routed layout.')
    plan = preview_schematic_sections(spec, paths, cli_path, max_depth=depth)
    return apply_schematic_sections(plan, destination)


def prepare_sources(spec, parent_folder, request, cli_path=''):
    """Compatibility name for callers already using a captured request."""
    return materialize_selection(spec, request, parent_folder, cli_path)


class SourceSelectionPanel(wx.Panel if wx is not None else object):
    """Embedded source controls; selection depth means included descendants."""

    def __init__(self, parent, on_change):
        if wx is None:
            raise RuntimeError('The inline source selector requires KiCad wxPython.')
        super().__init__(parent)
        self.on_change = on_change
        self.spec = None
        self.cli_path = ''
        self.instances = []
        self._forced_layout = None
        self._loading = False
        column = wx.BoxSizer(wx.VERTICAL)
        self.whole = wx.RadioButton(self, label='Whole project', style=wx.RB_GROUP)
        self.selected = wx.RadioButton(self, label='Selected pages / subtrees')
        column.Add(self.whole, 0, wx.BOTTOM, 5)
        column.Add(self.selected, 0, wx.BOTTOM, 5)
        self.pages = wx.TreeCtrl(self, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT |
                                  wx.TR_MULTIPLE | wx.TR_HIDE_ROOT, size=(-1, 150))
        column.Add(self.pages, 1, wx.EXPAND | wx.BOTTOM, 5)
        self.hint = wx.StaticText(self, label='Ctrl-click to select multiple pages. A page includes its descendants.')
        self.hint.Wrap(360)
        column.Add(self.hint, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.depth_check = wx.CheckBox(self, label='Limit included depth')
        self.depth = wx.SpinCtrl(self, min=0, max=31, initial=0, size=(75, -1))
        depth_row = wx.BoxSizer(wx.HORIZONTAL)
        depth_row.Add(self.depth_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        depth_row.Add(self.depth, 0)
        column.Add(depth_row, 0, wx.BOTTOM, 5)
        self.layout = wx.CheckBox(self, label='Include routed layout')
        column.Add(self.layout, 0, wx.BOTTOM, 5)
        column.Add(wx.StaticText(self, label='PCB rectangle (mm; blank = suggest):'), 0, wx.BOTTOM, 3)
        region_row = wx.FlexGridSizer(rows=2, cols=4, vgap=3, hgap=5)
        self.region = []
        for label in ('X1', 'Y1', 'X2', 'Y2'):
            region_row.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = wx.TextCtrl(self, size=(65, -1))
            self.region.append(control)
            region_row.Add(control, 0)
            control.Bind(wx.EVT_TEXT, self._changed)
        column.Add(region_row, 0, wx.BOTTOM, 5)
        self.status = wx.StaticText(self, label='Choose a saved KiCad project.')
        column.Add(self.status, 0, wx.EXPAND)
        self.SetSizer(column)
        for button in (self.whole, self.selected):
            button.Bind(wx.EVT_RADIOBUTTON, self._changed)
        self.pages.Bind(wx.EVT_TREE_SEL_CHANGED, self._checked)
        self.depth_check.Bind(wx.EVT_CHECKBOX, self._changed)
        self.depth.Bind(wx.EVT_SPINCTRL, self._changed)
        self.layout.Bind(wx.EVT_CHECKBOX, self._changed)
        self.SetMinSize((1, -1))
        self._sync()

    def load_spec(self, spec, cli_path=''):
        """Read saved sheet occurrences for the selected project and variant."""
        self._loading = True
        self.spec, self.cli_path = spec, cli_path
        self.instances = []
        self.pages.DeleteAllItems()
        self.status.SetLabel('Reading saved sheet occurrences…')
        try:
            self.instances = list_sections(spec)
        except Exception:
            self._loading = False
            self.status.SetLabel('Could not read this project’s sheet hierarchy.')
            raise
        self.pages.DeleteAllItems()
        root = self.pages.AddRoot(Path(spec.project).stem)
        nodes = {}
        for item in self.instances:
            parts = [part for part in item['display_path'].split('/') if part]
            name = parts[-1] if parts else Path(item['file']).stem
            path = item['sheet_path']
            parent = nodes.get(path.rsplit('/', 1)[0], root)
            node = self.pages.AppendItem(parent, name + f"  ({item['descendant_symbols']})")
            self.pages.SetItemData(node, path)
            nodes[path] = node
        for node in nodes.values():
            self.pages.Expand(node)
        saved = getattr(spec, 'selection', {}) or {}
        paths = set(saved.get('sheet_paths', []))
        selected = not saved.get('whole_project', True)
        self.whole.SetValue(not selected)
        self.selected.SetValue(selected)
        for path in paths:
            if path in nodes:
                self.pages.SelectItem(nodes[path])
        depth = saved.get('max_depth')
        self.depth_check.SetValue(depth is not None)
        if isinstance(depth, int) and not isinstance(depth, bool) and 0 <= depth <= 31:
            self.depth.SetValue(depth)
        self.layout.SetValue(bool(saved.get('include_layout', False)))
        for control in self.region:
            control.ChangeValue('')
        region = saved.get('region_mm')
        if isinstance(region, (list, tuple)) and len(region) == 4:
            for control, value in zip(self.region, region):
                control.ChangeValue(str(value))
        self.status.SetLabel(f'{len(self.instances)} saved subsheet occurrence(s). Check pages to import.')
        self._sync()
        self._loading = False
        self.on_change()

    def set_include_layout(self, include_layout):
        """Use the parent window's global layout choice; hide the local control."""
        self._forced_layout = bool(include_layout)
        self.layout.Hide()
        self._sync()
        self.Layout()

    def _layout_value(self):
        return self._forced_layout if self._forced_layout is not None else self.layout.GetValue()

    def _checked(self, event):
        if self._loading:
            return
        if self.pages.GetSelections():
            self.selected.SetValue(True)
            self.whole.SetValue(False)
        self._changed(event)

    def _sync(self):
        selected = self.selected.GetValue()
        self.pages.Enable(selected)
        self.depth_check.Enable(selected)
        self.depth.Enable(selected and self.depth_check.GetValue())
        self.layout.Enable(selected and self._forced_layout is None)
        for control in self.region:
            control.Enable(selected and self._layout_value())

    def _changed(self, event):
        self._sync()
        self.on_change()

    def selected_request(self):
        if self.spec is None:
            raise MergeError('Choose a saved KiCad project first.')
        if self.whole.GetValue():
            return {'whole_project': True, 'sheet_paths': [], 'max_depth': None,
                    'include_layout': self._layout_value(), 'region_mm': None}
        paths = [self.pages.GetItemData(item) for item in self.pages.GetSelections()]
        region = None
        if self._layout_value():
            values = [control.GetValue().strip() for control in self.region]
            if any(values):
                if not all(values):
                    raise MergeError('Supply all four PCB rectangle coordinates, or leave all blank for a suggested rectangle.')
                try:
                    region = [float(value) for value in values]
                except ValueError as error:
                    raise MergeError('PCB rectangle coordinates must be numbers in mm.') from error
        request = {'whole_project': False, 'sheet_paths': paths,
                   'max_depth': self.depth.GetValue() if self.depth_check.GetValue() else None,
                   'include_layout': self._layout_value(), 'region_mm': region}
        _normalize_request(request)
        return request
