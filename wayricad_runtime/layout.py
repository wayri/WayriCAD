"""Opt-in native reading, scrolling and display-fit helpers; no editor writes."""
from pathlib import Path
import sys

import wx


def relayout(window):
    """Recompute expanded content and every enclosing scrollable viewport."""
    while window is not None:
        window.Layout()
        if isinstance(window, wx.ScrolledWindow):
            window.FitInside()
        if isinstance(window, wx.TopLevelWindow):
            break
        window = window.GetParent()


def fit_to_display(frame):
    """Keep initial native windows and their minimum sizes inside the work area."""
    index = wx.Display.GetFromWindow(frame)
    area = wx.Display(max(0, index)).GetClientArea()
    margin = frame.FromDIP(16)
    available = max(300, area.width-2*margin), max(240, area.height-2*margin)
    minimum = frame.GetMinSize()
    frame.SetMinSize((min(max(-1, minimum.width), available[0]),
                      min(max(-1, minimum.height), available[1])))
    size = frame.GetSize()
    if size.width > available[0] or size.height > available[1]:
        frame.SetSize((min(size.width, available[0]), min(size.height, available[1])))
    point = frame.GetPosition(); size = frame.GetSize()
    frame.Move((max(area.x, min(point.x, area.GetRight()-size.width+1)),
                max(area.y, min(point.y, area.GetBottom()-size.height+1))))


def full_item_text(control, row, column):
    """Avoid wxMSW's fixed 512-character ListCtrl retrieval buffer."""
    text = control.GetItemText(row, column)
    # Windows limits UTF-16 units, so a clipped supplementary character
    # can leave a lone surrogate even when Python's character count is short.
    if sys.platform != 'win32' or len(text.encode('utf-16-le', errors='surrogatepass'))//2 < 511:
        return text
    import ctypes
    from ctypes import wintypes
    class Item(ctypes.Structure):
        _fields_ = [('mask',wintypes.UINT),('iItem',ctypes.c_int),('iSubItem',ctypes.c_int),
                    ('state',wintypes.UINT),('stateMask',wintypes.UINT),('pszText',wintypes.LPWSTR),
                    ('cchTextMax',ctypes.c_int),('iImage',ctypes.c_int),('lParam',ctypes.c_ssize_t),
                    ('iIndent',ctypes.c_int),('iGroupId',ctypes.c_int),('cColumns',wintypes.UINT),
                    ('puColumns',ctypes.POINTER(wintypes.UINT)),('piColFmt',ctypes.POINTER(ctypes.c_int)),
                    ('iGroup',ctypes.c_int)]
    send = ctypes.windll.user32.SendMessageW
    send.argtypes = (wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
    send.restype = ctypes.c_ssize_t
    for capacity in (1024,4096,16384,65536,262144):
        buffer = ctypes.create_unicode_buffer(capacity)
        item = Item(); item.iSubItem = column
        item.pszText = ctypes.cast(buffer,wintypes.LPWSTR); item.cchTextMax = capacity
        count = send(control.GetHandle(),0x1000+115,row,ctypes.addressof(item))
        if count < capacity-1:
            return buffer.value
    raise ValueError('This cell exceeds the 262,143-character reader limit; use the exported report.')


def table_data(control):
    """Snapshot complete displayed values without changing selection or a model."""
    if isinstance(control, wx.ListCtrl):
        count = control.GetColumnCount()
        headers = [control.GetColumn(i).GetText() for i in range(count)]
        rows = [[full_item_text(control, row, col) for col in range(count)]
                for row in range(control.GetItemCount())]
        selected = []
        row = control.GetFirstSelected()
        while row != -1:
            selected.append(row); row = control.GetNextSelected(row)
        return headers, rows, selected
    from wx import grid
    if isinstance(control, grid.Grid):
        headers = [control.GetColLabelValue(i) for i in range(control.GetNumberCols())]
        rows = [[control.GetCellValue(r, c) for c in range(control.GetNumberCols())]
                for r in range(control.GetNumberRows())]
        selected = list(control.GetSelectedRows())
        if not selected and control.GetGridCursorRow() >= 0:
            selected = [control.GetGridCursorRow()]
        return headers, rows, selected
    from wx import dataview as dv
    if isinstance(control, dv.DataViewCtrl):
        model = control.GetModel()
        if not hasattr(model, 'GetCount') or not hasattr(model, 'GetValueByRow'):
            raise ValueError('This hierarchical view supplies its own item inspector.')
        columns = list(control.GetColumns())
        headers = [column.GetTitle() for column in columns]
        rows = [[str(model.GetValueByRow(row, column.GetModelColumn())) for column in columns]
                for row in range(model.GetCount())]
        selected = [model.GetRow(item) for item in control.GetSelections()]
        return headers, rows, selected
    raise ValueError('This control is not a supported table.')


def row_text(headers, row):
    return '\n\n'.join((header or f'Column {i+1}') + ':\n' + str(value)
                       for i, (header, value) in enumerate(zip(headers, row)))


class TableReader(wx.Dialog):
    """Resizable searchable full-text view of an immutable table snapshot."""
    def __init__(self, parent, headers, rows, selected=()):
        super().__init__(parent, title='WayriCAD — Read table details', size=(920, 650),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.headers, self.rows = headers, rows
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label='Search any cell. Select a row to read its complete values; Ctrl+C copies text.'), 0, wx.ALL, 10)
        self.search = wx.SearchCtrl(self); self.search.SetDescriptiveText('Search table values')
        root.Add(self.search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        split.SetMinimumPaneSize(self.FromDIP(140)); split.SetSashGravity(.25)
        self.list = wx.ListBox(split)
        self.text = wx.TextCtrl(split, style=wx.TE_MULTILINE | wx.TE_READONLY)
        split.SplitVertically(self.list, self.text, self.FromDIP(250))
        root.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        close = wx.Button(self, wx.ID_CLOSE, 'Close')
        root.Add(close, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(root); self.SetMinSize(self.FromDIP((480, 320)))
        self.Layout()
        split.SetSashPosition(min(self.FromDIP(250), max(self.FromDIP(140), split.GetClientSize().width//3)))
        close.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        self.search.Bind(wx.EVT_TEXT, self.filter)
        self.list.Bind(wx.EVT_LISTBOX, self.choose)
        self.filter()
        if selected and selected[0] in self.indices:
            self.list.SetSelection(self.indices.index(selected[0])); self.choose()
        fit_to_display(self)

    def filter(self, event=None):
        needle = self.search.GetValue().casefold()
        self.indices = [i for i, row in enumerate(self.rows) if needle in '\n'.join(map(str, row)).casefold()]
        self.list.Set([f'{i+1} · ' + (' · '.join(map(str, self.rows[i]))[:100]) for i in self.indices])
        if self.indices:
            self.list.SetSelection(0); self.choose()
        else:
            self.text.SetValue('No matching rows.')

    def choose(self, event=None):
        i = self.list.GetSelection()
        if i != wx.NOT_FOUND:
            self.text.SetValue(row_text(self.headers, self.rows[self.indices[i]]))


def read_table(control):
    try:
        headers, rows, selected = table_data(control)
    except ValueError as exc:
        wx.MessageBox(str(exc), 'Read table', wx.OK | wx.ICON_INFORMATION, control)
        return
    dialog = TableReader(wx.GetTopLevelParent(control), headers, rows, selected)
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()


def _attach_table(control):
    if getattr(control, '_wayricad_reader', False):
        return
    control._wayricad_reader = True
    hint = 'Ctrl+Shift+Enter: read full table values. Ctrl+C: copy selected rows.'
    old = control.GetToolTipText()
    control.SetToolTip((old+'\n' if old else '')+hint)
    def key(event):
        if event.ControlDown() and event.ShiftDown() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            read_table(control); return
        if event.ControlDown() and event.GetKeyCode() == ord('C'):
            headers, rows, selected = table_data(control)
            if selected and wx.TheClipboard.Open():
                try:
                    text = '\t'.join(headers)+'\n'+'\n'.join('\t'.join(map(str, rows[i])) for i in selected)
                    wx.TheClipboard.SetData(wx.TextDataObject(text))
                finally:
                    wx.TheClipboard.Close()
                return
        event.Skip()
    control.Bind(wx.EVT_KEY_DOWN, key)


def install_accessibility(frame, help_path=None):
    """Install reading shortcuts and scrolling fixes after a form is constructed."""
    frame = wx.GetTopLevelParent(frame)
    if help_path and not getattr(frame, '_wayricad_help_shortcut', False):
        frame._wayricad_help_shortcut = True
        path = Path(help_path)
        def help_key(event):
            if event.GetKeyCode() == wx.WXK_F1:
                from .help import open_help
                open_help(frame, path); return
            event.Skip()
        frame.Bind(wx.EVT_CHAR_HOOK, help_key)
    if getattr(frame, '_wayricad_accessibility', False):
        return
    frame._wayricad_accessibility = True
    def configure():
        try:
            if not frame or frame.IsBeingDeleted(): return
        except RuntimeError:
            return
        from wx import grid
        from wx import dataview as dv
        def walk(window):
            if isinstance(window, (wx.ListCtrl, grid.Grid)):
                _attach_table(window)
            elif isinstance(window, dv.DataViewCtrl):
                model = window.GetModel()
                if hasattr(model, 'GetCount') and hasattr(model, 'GetValueByRow'):
                    _attach_table(window)
            if isinstance(window, wx.CollapsiblePane):
                def changed(event):
                    relayout(event.GetEventObject()); event.Skip()
                window.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, changed)
            for child in window.GetChildren(): walk(child)
        walk(frame); relayout(frame); fit_to_display(frame)
    wx.CallAfter(configure)
