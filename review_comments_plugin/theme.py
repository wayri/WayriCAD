"""One per-window palette for native controls and inert HTML content."""
PALETTES = {
    'light': dict(background='#f4f6fa', surface='#ffffff', text='#253047', muted='#65738b',
                  border='#d7e0e8', hover='#e4eef1', disabled='#dce3e8', tint='#edf6f7', accent='#087f8c'),
    'dark': dict(background='#151a22', surface='#202733', text='#e5ebf3', muted='#a6b4c7',
                 border='#3b485b', hover='#314052', disabled='#303946', tint='#243d47', accent='#168b99'),
}


def theme_of(window):
    while window:
        if hasattr(window, 'review_theme'):
            return window.review_theme
        window = window.GetParent()
    return 'light'


def palette(window):
    return PALETTES[theme_of(window)]


def apply_theme(root, theme):
    import wx
    if theme not in PALETTES:
        raise ValueError('Choose light or dark theme.')
    colors = PALETTES[theme]
    backgrounds = {p[key].lower(): key for p in PALETTES.values()
                   for key in ('background', 'surface', 'hover', 'disabled', 'tint')}
    backgrounds.update({'#e7f2f4':'tint', '#e7edf3':'background', '#f0f0f0':'background'})
    foregrounds = {p[key].lower(): key for p in PALETTES.values() for key in ('text', 'muted', 'accent')}
    foregrounds['#000000'] = 'text'
    pending = [root]
    while pending:
        window = pending.pop()
        text_value = window.GetValue() if isinstance(window, wx.TextCtrl) else None
        selection = window.GetSelection() if isinstance(window, wx.TextCtrl) else None
        window.review_theme = theme
        old = window.GetBackgroundColour().GetAsString(wx.C2S_HTML_SYNTAX).lower()
        role = backgrounds.get(old)
        if role:
            window.SetBackgroundColour(colors[role])
        if isinstance(window, (wx.StaticText, wx.StaticBitmap)) and window.GetParent():
            window.SetBackgroundColour(window.GetParent().GetBackgroundColour())
        old = window.GetForegroundColour().GetAsString(wx.C2S_HTML_SYNTAX).lower()
        role = foregrounds.get(old)
        if role:
            window.SetForegroundColour(colors[role])
        if isinstance(window, wx.TextCtrl):
            window.SetBackgroundColour(colors['surface'])
            window.SetForegroundColour(colors['text'])
            # MSW rich-edit hint emulation can turn its hint into content when
            # recoloured. A theme change must never introduce draft text.
            if window.GetValue() != text_value:
                window.ChangeValue(text_value)
                window.SetSelection(*selection)
        if hasattr(window, 'primary') and hasattr(window, 'set_active'):
            window.set_active(window.active)
        pending.extend(window.GetChildren())
        window.Refresh()
