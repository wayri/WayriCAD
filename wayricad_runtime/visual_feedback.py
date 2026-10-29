"""Native action icons that retain readable labels and follow DPI/theme changes."""
from __future__ import annotations

import re


_ART = {
    'run': ('ART_GO_FORWARD', 'ART_EXECUTABLE_FILE'),
    'preview': ('ART_FIND',),
    'open': ('ART_FILE_OPEN',),
    'save': ('ART_FILE_SAVE',),
    'report': ('ART_REPORT_VIEW', 'ART_NORMAL_FILE'),
    'help': ('ART_HELP', 'ART_QUESTION'),
    'cancel': ('ART_CROSS_MARK', 'ART_DELETE'),
    'search': ('ART_FIND',),
    'refresh': ('ART_REDO',),
    'settings': ('ART_LIST_VIEW',),
    'clear': ('ART_DELETE',),
    'next': ('ART_GO_FORWARD',),
    'back': ('ART_GO_BACK',),
    'success': ('ART_TICK_MARK', 'ART_INFORMATION'),
    'warning': ('ART_WARNING',),
    'error': ('ART_ERROR',),
    'info': ('ART_INFORMATION',),
    'validate': ('ART_TICK_MARK', 'ART_FIND'),
    'import': ('ART_FILE_OPEN',),
    'select': ('ART_TICK_MARK',),
    'reset': ('ART_UNDO',),
    'focus': ('ART_FIND',),
    'fit': ('ART_FULL_SCREEN', 'ART_FIND'),
    'undo': ('ART_UNDO',),
    'redo': ('ART_REDO',),
    'copy': ('ART_COPY', 'ART_NORMAL_FILE'),
    'probe': ('ART_FIND',),
    'zoom': ('ART_FIND',),
}
_HINTS = {
    'run': 'Run the selected action', 'preview': 'Preview before making changes',
    'open': 'Choose or open a saved file', 'save': 'Save the reviewed result',
    'report': 'Open generated results and reports', 'help': 'Open local help',
    'cancel': 'Cancel the current action', 'search': 'Find matching items',
    'refresh': 'Refresh the displayed information', 'settings': 'Show settings',
    'clear': 'Clear the current selection', 'next': 'Continue to the next step',
    'back': 'Return to the previous step',
    'validate': 'Validate the current preview', 'import': 'Choose data to import',
    'select': 'Select matching items', 'reset': 'Reset the current settings',
    'focus': 'Focus the selected item', 'fit': 'Fit the visible geometry',
    'undo': 'Undo the previous change', 'redo': 'Redo the previous change',
    'copy': 'Copy the selected information', 'probe': 'Inspect a point in the view',
    'zoom': 'Change the view magnification',
}
_LABEL_ROLES = (
    ('help', 'help'), ('cancel', 'cancel'), ('stop', 'cancel'),
    ('clear', 'clear'), ('remove', 'clear'), ('delete', 'clear'),
    ('preview', 'preview'), ('inspect', 'preview'), ('plan', 'preview'),
    ('validat', 'validate'),
    ('report', 'report'), ('result', 'report'),
    ('browse', 'open'), ('choose', 'open'), ('open', 'open'), ('load', 'open'),
    ('save', 'save'), ('export', 'save'),
    ('import', 'import'),
    ('refresh', 'refresh'), ('reload', 'refresh'),
    ('search', 'search'), ('find', 'search'),
    ('undo', 'undo'), ('redo', 'redo'), ('reset', 'reset'),
    ('focus', 'focus'), ('fit', 'fit'), ('select', 'select'),
    ('setting', 'settings'), ('option', 'settings'),
    ('setup', 'settings'), ('detail', 'report'), ('file', 'open'),
    ('copy', 'copy'), ('probe', 'probe'), ('zoom', 'zoom'),
    ('back', 'back'), ('next', 'next'),
    ('run', 'run'), ('solve', 'run'), ('analy', 'run'), ('apply', 'run'),
)
_BITMAPS = {}


def _available(window):
    """Queued theme/DPI callbacks may outlive their native window."""
    if window is None:
        return True
    try:
        return bool(window) and not (hasattr(window,'IsBeingDeleted') and window.IsBeingDeleted())
    except RuntimeError:
        return False


def action_role(label):
    """Infer a presentation role; this never changes the action being executed."""
    text = re.sub(r'&', '', str(label)).casefold()
    for token in re.findall(r'[a-z]+', text):
        role = next((role for word, role in _LABEL_ROLES if token.startswith(word)), None)
        if role is not None:
            return role
    return None


def _theme(wx):
    """Use native system colours rather than maintaining a separate theme setting."""
    return tuple(wx.SystemSettings.GetColour(name).GetRGBA() for name in
                 (wx.SYS_COLOUR_WINDOW, wx.SYS_COLOUR_WINDOWTEXT))


def bitmap(role, window=None, size=16):
    """Return a cached stock bitmap at the window's physical DPI size.

    ArtProvider supplies platform-native, theme-compatible artwork. Cache entries
    are bounded and keyed by system colours and DPI size, never generated in paint.
    Labels remain usable when a platform lacks a requested stock icon.
    """
    import wx

    if not _available(window) or callable(getattr(wx,'GetApp',None)) and wx.GetApp() is None:
        return wx.NullBitmap
    role = role if role in _ART else 'info'
    logical = max(12, min(32, int(size)))
    physical = window.FromDIP((logical, logical)) if window is not None else wx.Size(logical, logical)
    dimensions = (physical[0], physical[1])
    key = (role, dimensions, _theme(wx))
    if key not in _BITMAPS:
        image = wx.NullBitmap
        for name in _ART[role]:
            art = getattr(wx, name, None)
            if art is None:
                continue
            image = wx.ArtProvider.GetBitmap(art, wx.ART_BUTTON, dimensions)
            if image.IsOk():
                break
        if len(_BITMAPS) >= 128:
            _BITMAPS.pop(next(iter(_BITMAPS)))
        _BITMAPS[key] = image
    return _BITMAPS[key]


def _fit_button(button, image, minimum_dip=None):
    """Reserve distinct icon/text space, including wxMSW's exact-fit buttons."""
    if not all(callable(getattr(button,name,None)) for name in
               ('InvalidateBestSize','GetBestSize','GetMinSize','SetMinSize')):
        return
    button.InvalidateBestSize()
    minimum=button.FromDIP(minimum_dip) if minimum_dip is not None else button.GetMinSize()
    best=button.GetBestSize()
    width,height=best.width,best.height
    if callable(getattr(button,'GetTextExtent',None)):
        # wxMSW 4.2.2 can retain the text-only best size for BU_EXACTFIT even
        # after SetBitmap and InvalidateBestSize. Measure both visible elements.
        label=button.GetLabelText() if hasattr(button,'GetLabelText') else button.GetLabel().replace('&','')
        extents=[button.GetTextExtent(line) for line in label.splitlines() or ['']]
        picture=image.GetLogicalSize() if hasattr(image,'GetLogicalSize') else image.GetSize()
        padding=button.FromDIP((20,8))
        width=max(width,max(extent[0] for extent in extents)+picture[0]+padding[0])
        height=max(height,max(sum(extent[1] for extent in extents),picture[1])+padding[1])
    button.SetMinSize((max(width,minimum.width),max(height,minimum.height)))


def decorate_button(button, role=None):
    """Add a semantic icon while preserving the button's label and tooltip."""
    import wx

    if not _available(button) or callable(getattr(wx,'GetApp',None)) and wx.GetApp() is None:
        return button
    chosen = role if role in _ART else action_role(button.GetLabel())
    if chosen is None:
        return button
    state = getattr(button, '_wayricad_visual_feedback', None)
    if state is None:
        if hasattr(button, 'GetBitmap') and button.GetBitmap().IsOk():
            _fit_button(button,button.GetBitmap())
            return button
        state = {'role': chosen}
        if all(callable(getattr(button,name,None)) for name in ('ToDIP','GetMinSize')):
            state['minimum_dip']=button.ToDIP(button.GetMinSize())
        button._wayricad_visual_feedback = state

        def refresh(event=None):
            if state.get('destroyed') or not _available(button):
                if event is not None:event.Skip()
                return
            image = bitmap(state['role'], button)
            if image.IsOk():
                button.SetBitmap(image)
                if hasattr(button, 'SetBitmapPosition'):
                    button.SetBitmapPosition(wx.LEFT)
                if hasattr(button, 'SetBitmapMargins'):
                    button.SetBitmapMargins(button.FromDIP((4, 0)))
                _fit_button(button,image,state.get('minimum_dip'))
            if event is not None:
                parent = button.GetParent()
                if parent is not None:
                    parent.Layout()
                event.Skip()

        state['refresh'] = refresh
        for name in ('EVT_SYS_COLOUR_CHANGED', 'EVT_DPI_CHANGED'):
            event = getattr(wx, name, None)
            if event is not None:
                button.Bind(event, refresh)
        destroyed=getattr(wx,'EVT_WINDOW_DESTROY',None)
        if destroyed is not None:
            def stop(event):
                if event.GetEventObject() is button:state['destroyed']=True
                event.Skip()
            button.Bind(destroyed,stop)
    state['role'] = chosen
    if not button.GetToolTipText():
        button.SetToolTip(_HINTS.get(chosen, button.GetLabel().replace('&', '')))
    state['refresh']()
    return button
