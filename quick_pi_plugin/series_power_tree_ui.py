"""Native ordered power-tree preview for reviewed series paths."""
from __future__ import annotations


def tree_export_context(board_path, expected_sha256, *, sources=()):
    """Bind a tree to its saved PCB, sidecars and declared study inputs."""
    import hashlib
    from pathlib import Path
    if not board_path or not expected_sha256:
        raise ValueError('Reload the saved PCB before exporting a power tree.')
    board = Path(board_path).resolve()
    paths = {board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru')}
    paths.update(Path(path).resolve() for path in sources if path)
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    fingerprints = {path: digest(path) for path in paths}
    if fingerprints[board] != expected_sha256:
        raise ValueError('Saved PCB changed. Reload and rerun before exporting the power tree.')
    def guard():
        if any(digest(path) != expected for path, expected in fingerprints.items()):
            raise ValueError('Saved design or input study changed. Reload before exporting the power tree.')
    return tuple(paths), guard


def save_tree_data(path, tree, *, sources, source_guard):
    import json
    from pathlib import Path
    from wayricad_runtime.report_ui import publish_documents
    if Path(path).suffix.lower() != '.json':
        raise ValueError('Use a separate .json power-tree destination.')
    publish_documents({Path(path): json.dumps(tree, ensure_ascii=False, allow_nan=False, indent=2)},
                      sources=sources, source_guard=source_guard)


def save_diagram(path, tree, *, sources, source_guard):
    from pathlib import Path
    from wayricad_runtime.report_ui import publish_documents
    from .series_path_diagram import diagram_svg
    if Path(path).suffix.lower() != '.svg':
        raise ValueError('Use a separate .svg series-diagram destination.')
    publish_documents({Path(path): diagram_svg(tree)}, sources=sources, source_guard=source_guard)


def diagram_canvas(parent, tree):
    """Native vector painting avoids enormous bitmaps for long parallel banks."""
    import wx
    import math
    from .series_path_diagram import diagram_layout
    drawing = diagram_layout(tree)
    class Canvas(wx.ScrolledWindow):
        def __init__(self):
            super().__init__(parent, style=wx.HSCROLL | wx.VSCROLL)
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self.SetScrollRate(12, 12)
            self.scale = 1.
            self.Bind(wx.EVT_PAINT, self.paint)
            self.Bind(wx.EVT_SIZE, self.resize)
            self.fit_width()

        def fit_width(self):
            size = self.FromDIP((drawing['width'], drawing['height']))
            # Normal popup widths show both buses. Very narrow windows retain a
            # readable minimum scale and may scroll horizontally.
            self.scale = max(.75, min(1., max(1, self.GetClientSize().width - 2) / size.width))
            target = wx.Size(math.ceil(size.width * self.scale), math.ceil(size.height * self.scale))
            if self.GetVirtualSize() != target:
                self.SetVirtualSize(target)

        def resize(self, event):
            self.fit_width()
            self.Refresh(False)
            event.Skip()

        def paint(self, event):
            dc = wx.AutoBufferedPaintDC(self)
            dc.SetBackground(wx.Brush('white')); dc.Clear()
            self.PrepareDC(dc)
            dc.SetUserScale(self.scale, self.scale)
            for item in sorted(drawing['commands'], key=lambda c: c['kind'] == 'text'):
                if item['kind'] == 'line':
                    dc.SetPen(wx.Pen('#426878', self.FromDIP(2)))
                    dc.DrawLine(*[self.FromDIP(round(item[k])) for k in ('x1', 'y1', 'x2', 'y2')])
                elif item['kind'] == 'rect':
                    dc.SetPen(wx.Pen('#426878')); dc.SetBrush(wx.Brush('#eef5f4'))
                    dc.DrawRoundedRectangle(*[self.FromDIP(round(item[k])) for k in ('x', 'y', 'width', 'height')], self.FromDIP(5))
                else:
                    font = self.GetFont()
                    font.SetPixelSize(wx.Size(0, self.FromDIP(item['size'])))
                    dc.SetFont(font); dc.SetTextForeground('#172c34')
                    dc.DrawText(item['text'], self.FromDIP(round(item['x'])), self.FromDIP(round(item['y'])))
    return Canvas()


def show_series_power_tree(parent, tree, *, board_path=None, expected_sha256=None, sources=(), source_guard=None):
    import json
    from pathlib import Path
    import wx
    from wx.lib.scrolledpanel import ScrolledPanel
    from .series_power_tree import tree_text

    protected, guard = (), None
    if board_path is not None:
        protected, snapshot_guard = tree_export_context(board_path, expected_sha256, sources=sources)
        def guard():
            snapshot_guard()
            if source_guard is not None: source_guard()
        guard()

    dialog = wx.Dialog(parent, title='Quick PI · Series power tree',
                       size=parent.FromDIP((960, 760)),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    notice = wx.StaticText(dialog, label=tree['notice'])
    notice.Wrap(dialog.FromDIP(900))
    layout.Add(notice, 0, wx.EXPAND | wx.ALL, 10)
    tabs = wx.Notebook(dialog)
    tabs.AddPage(diagram_canvas(tabs, tree), 'Series path diagram')
    panel = ScrolledPanel(tabs)
    flow = wx.BoxSizer(wx.VERTICAL)
    for index, node in enumerate(tree['nodes']):
        if index:
            flow.Add(wx.StaticText(panel, label='↓'), 0, wx.ALIGN_CENTER | wx.ALL, 3)
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, node['label'] + ' · ' + node['kind'].replace('_', ' '))
        text = tree_text(dict(notice='', nodes=[node])).strip()
        # The box title already names this node.
        text = '\n'.join(text.splitlines()[1:])
        details = wx.StaticText(panel, label=text)
        details.Wrap(dialog.FromDIP(850))
        box.Add(details, 0, wx.EXPAND | wx.ALL, 8)
        flow.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    panel.SetSizer(flow)
    panel.SetupScrolling(scroll_x=False)
    tabs.AddPage(panel, 'Power and pin details')
    layout.Add(tabs, 1, wx.EXPAND | wx.ALL, 5)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    save = wx.Button(dialog, label='Save tree data…')
    save.Enable(guard is not None)
    if guard is None:
        save.SetToolTip('Export from the main PI workspace with a verified saved-design context.')
    def save_tree(_event):
        with wx.FileDialog(dialog, 'Save series power tree', defaultFile='series-power-tree.json',
                           wildcard='JSON data (*.json)|*.json',
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as picker:
            if picker.ShowModal() == wx.ID_OK:
                try:
                    save_tree_data(picker.GetPath(), tree, sources=protected, source_guard=guard)
                except (OSError, ValueError) as exc:
                    wx.MessageBox(str(exc), 'Could not save power tree', wx.OK | wx.ICON_ERROR, dialog)
    save.Bind(wx.EVT_BUTTON, save_tree)
    buttons.Add(save, 0, wx.ALL, 5)
    image = wx.Button(dialog, label='Save diagram SVG…')
    image.Enable(guard is not None)
    if guard is None:
        image.SetToolTip('Export from the main PI workspace with a verified saved-design context.')
    def save_image(_event):
        with wx.FileDialog(dialog, 'Save series path diagram', defaultFile='series-path.svg',
                           wildcard='SVG diagram (*.svg)|*.svg',
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as picker:
            if picker.ShowModal() == wx.ID_OK:
                try:
                    save_diagram(picker.GetPath(), tree, sources=protected, source_guard=guard)
                except (OSError, ValueError) as exc:
                    wx.MessageBox(str(exc), 'Could not save series diagram', wx.OK | wx.ICON_ERROR, dialog)
    image.Bind(wx.EVT_BUTTON, save_image)
    buttons.Add(image, 0, wx.ALL, 5)
    buttons.AddStretchSpacer()
    close = wx.Button(dialog, wx.ID_CLOSE, 'Close')
    close.Bind(wx.EVT_BUTTON, lambda _event: dialog.EndModal(wx.ID_CLOSE))
    buttons.Add(close, 0, wx.ALL, 5)
    layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)
    dialog.SetSizer(layout)
    work = wx.Display(max(0, wx.Display.GetFromWindow(parent))).GetClientArea()
    dialog.SetSize(min(dialog.GetSize().width, work.width - 20), min(dialog.GetSize().height, work.height - 40))
    dialog.CentreOnParent()
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
