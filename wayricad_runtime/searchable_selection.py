"""Filtered native pickers that preserve original item indices and hidden checks."""
from __future__ import annotations


def matching_indices(items, query):
    """Return original indices matching a case-insensitive literal substring."""
    return SearchIndex(items).match(query)


class SearchIndex:
    """Cache immutable labels once rather than recase long names per keypress."""
    def __init__(self, items):
        self.labels = tuple(str(item) for item in items)
        self.folded = tuple(item.casefold() for item in self.labels)

    def match(self, query):
        query = str(query).strip().casefold()
        return [index for index, label in enumerate(self.folded) if query in label]


class CheckedSelection:
    """Keep checked identities independent of the currently visible filter."""
    def __init__(self, items, checked=()):
        self.items = tuple(items)
        self.search = SearchIndex(self.items)
        self.checked = {index for index in checked if 0 <= index < len(self.items)}

    def check(self, index, checked=True):
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        if checked:
            self.checked.add(index)
        else:
            self.checked.discard(index)

    def check_visible(self, query, checked=True):
        for index in self.search.match(query):
            self.check(index, checked)


def choose_items(parent, items, selection=-1, checked=None):
    """Open a literal-search picker; return original indices, or None on cancel.

    ``checked=None`` selects one item. A checked-index iterable enables multiple
    checked items, retained when a search hides them. No source control changes
    until the caller accepts this result.
    """
    import wx
    items = tuple(items)
    multiple = checked is not None
    state = CheckedSelection(items, checked or ())
    dialog = wx.Dialog(parent, title='Search and choose items' if multiple else 'Search and choose',
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(740, 490))
    dialog.SetMinSize((460, 330))
    root = wx.BoxSizer(wx.VERTICAL)
    search = wx.SearchCtrl(dialog)
    search.SetDescriptiveText('Search any part of the name; clear to show all')
    search.ShowCancelButton(True)
    root.Add(search, 0, wx.EXPAND | wx.ALL, 12)
    status = wx.StaticText(dialog)
    root.Add(status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    style = wx.LB_SINGLE | wx.LB_HSCROLL
    listing = (wx.CheckListBox(dialog, style=style) if multiple
               else wx.ListBox(dialog, style=style))
    root.Add(listing, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
    detail = wx.TextCtrl(dialog, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 48))
    root.Add(detail, 0, wx.EXPAND | wx.ALL, 12)
    visible = []
    selected = selection
    rebuilding = False

    def update_status():
        status.SetLabel(f'{len(visible)} of {len(items)} shown' +
                        (f' · {len(state.checked)} checked, including hidden items' if multiple else ''))

    def rebuild(event=None):
        nonlocal rebuilding
        rebuilding = True
        listing.Freeze()
        try:
            visible[:] = state.search.match(search.GetValue())
            listing.Set([state.search.labels[index] for index in visible])
            if multiple and state.checked:
                # Set creates unchecked rows. Cross the wx boundary only for
                # checked rows, rather than once for every unchecked net.
                for row, index in enumerate(visible):
                    if index in state.checked:
                        listing.Check(row, True)
            try:
                selected_row = visible.index(selected)
            except ValueError:
                selected_row = -1
            if selected_row >= 0:
                listing.SetSelection(selected_row)
            detail.ChangeValue(state.search.labels[selected] if selected_row >= 0 else '')
            ok.Enable(multiple or selected_row >= 0)
            update_status()
        finally:
            listing.Thaw()
            rebuilding = False

    def on_select(event):
        nonlocal selected
        if rebuilding:
            return
        row = event.GetInt()
        if 0 <= row < len(visible):
            selected = visible[row]
            detail.ChangeValue(str(items[selected]))
            ok.Enable(True)

    def on_check(event):
        if rebuilding:
            return
        row = event.GetInt()
        if 0 <= row < len(visible):
            state.check(visible[row], listing.IsChecked(row))
            update_status()

    if multiple:
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, value in (('Check visible', True), ('Uncheck visible', False)):
            button = wx.Button(dialog, label=label)
            def toggle(event, value=value):
                state.check_visible(search.GetValue(), value)
                rebuild()
            button.Bind(wx.EVT_BUTTON, toggle)
            actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        listing.Bind(wx.EVT_CHECKLISTBOX, on_check)
    listing.Bind(wx.EVT_LISTBOX, on_select)
    buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
    root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
    dialog.SetSizer(root)
    ok = dialog.FindWindow(wx.ID_OK)
    search.Bind(wx.EVT_TEXT, rebuild)
    search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda event: search.SetValue(''))
    rebuild()
    search.SetFocus()
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        return sorted(state.checked) if multiple else [selected]
    finally:
        dialog.Destroy()


def searchable_row(control, label='Find…'):
    """Place a visible search button beside an unchanged native item control."""
    import wx
    row = wx.BoxSizer(wx.HORIZONTAL)
    minimum = control.GetMinSize()
    control.SetMinSize((control.FromDIP(80), minimum.height))
    row.Add(control, 1, wx.EXPAND)
    button = wx.Button(control.GetParent(), label=label, style=wx.BU_EXACTFIT)
    button.SetToolTip('Search full item names. Checks remain selected when hidden by a filter.')
    button.Bind(wx.EVT_BUTTON, lambda event: control.ShowSearch())
    row.Add(button, 0, wx.LEFT | wx.ALIGN_TOP, 5)
    # Follow the real control's enabled state when project/runtime inputs change.
    def update(event):
        button.Enable(control.IsEnabled())
    button.Bind(wx.EVT_UPDATE_UI, update)
    return row
