"""Small native controls for progressive disclosure in WayriCAD dialogs."""
import wx


def form_page(notebook, title):
    page = wx.ScrolledWindow(notebook, style=wx.VSCROLL)
    page.SetScrollRate(0, 12)
    layout = wx.BoxSizer(wx.VERTICAL)
    grid = wx.FlexGridSizer(0, 2, 10, 10)
    grid.AddGrowableCol(1, 1)
    layout.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
    page.SetSizer(layout)
    notebook.AddPage(page, title)
    return page, layout, grid


def field(parent, grid, label, value):
    control = wx.TextCtrl(parent, value=str(value))
    control.SetMinSize((84, -1))
    grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(control, 1, wx.EXPAND)
    return control


def choice(parent, grid, label, values):
    control = wx.ComboBox(parent, choices=list(values), style=wx.CB_READONLY)
    if values:
        control.SetSelection(0)
    grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(control, 1, wx.EXPAND)
    return control


def more_button(parent, actions, label="More…"):
    button = wx.Button(parent, label=label)
    def show(_event):
        menu = wx.Menu()
        for text, handler in actions:
            entry = menu.Append(wx.ID_ANY, text)
            menu.Bind(wx.EVT_MENU, handler, entry)
        try:
            button.PopupMenu(menu)
        finally:
            menu.Destroy()
    button.Bind(wx.EVT_BUTTON, show)
    return button


def details(parent, layout, title):
    pane = wx.CollapsiblePane(parent, label=title, style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
    content = pane.GetPane()
    inner = wx.BoxSizer(wx.VERTICAL)
    content.SetSizer(inner)
    layout.Add(pane, 0, wx.EXPAND | wx.TOP, 8)
    pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda event: parent.Layout())
    return content, inner
