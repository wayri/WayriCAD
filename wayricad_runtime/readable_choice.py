"""Native choices with readable Windows popups and complete selected-value tips.

The control remains a wx Choice/ComboBox: item text, indices and client data are
unchanged. Windows permits a popup wider than the collapsed sidebar control;
other wx ports keep their native popup sizing and still get full-value tips.
"""
from __future__ import annotations

import sys
import wx


def popup_width(text_widths, control_width, available_width, padding=36):
    """Return a measured popup width bounded by the current display work area."""
    return max(control_width, min(max(text_widths, default=0) + padding,
                                  max(control_width, available_width)))


class _ReadableItems:
    def _readable_init(self):
        self._choice_help = ''
        self._popup_dirty = True
        for event in (wx.EVT_CHOICE, wx.EVT_COMBOBOX, wx.EVT_ENTER_WINDOW,
                      wx.EVT_SET_FOCUS, wx.EVT_TEXT):
            self.Bind(event, self._readable_event)
        self.Bind(wx.EVT_SIZE, self._readable_size)
        self._refresh_tip()

    def SetToolTip(self, tip):
        """Retain caller help alongside the complete selected item."""
        self._choice_help = tip.GetTip() if isinstance(tip, wx.ToolTip) else str(tip or '')
        self._refresh_tip()

    def _refresh_tip(self):
        if not hasattr(self, '_choice_help'):
            return
        selected = self.GetValue() if isinstance(self, wx.ComboBox) else self.GetStringSelection()
        text = selected
        if self._choice_help and self._choice_help != selected:
            text = '\n\n'.join(value for value in (selected, self._choice_help) if value)
        super().SetToolTip(text)

    def _readable_event(self, event):
        self._refresh_tip()
        self._update_popup()
        event.Skip()

    def _readable_size(self, event):
        self._popup_dirty = True
        self._update_popup()
        event.Skip()

    def _items_changed(self):
        self._popup_dirty = True
        self._refresh_tip()
        self._update_popup()

    def _update_popup(self):
        if not getattr(self, '_popup_dirty', False) or not self.GetHandle():
            return
        if sys.platform != 'win32':
            return
        import ctypes
        from ctypes import wintypes
        display = wx.Display.GetFromWindow(self)
        available = wx.Display(display if display != wx.NOT_FOUND else 0).GetClientArea().width
        width = popup_width((self.GetTextExtent(item).width for item in self.GetStrings()),
                            self.GetSize().width, available - self.FromDIP(24), self.FromDIP(36))
        send = ctypes.windll.user32.SendMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = ctypes.c_ssize_t
        send(self.GetHandle(), 0x0160, width, 0)  # CB_SETDROPPEDWIDTH
        self._popup_dirty = False

    def Set(self, items, *args, **kwargs):
        result = super().Set(items, *args, **kwargs)
        self._items_changed()
        return result

    def SetItems(self, items, *args, **kwargs):
        result = super().SetItems(items, *args, **kwargs)
        self._items_changed()
        return result

    def Append(self, *args, **kwargs):
        result = super().Append(*args, **kwargs)
        self._items_changed()
        return result

    def Clear(self):
        result = super().Clear()
        self._items_changed()
        return result

    def SetString(self, *args, **kwargs):
        result = super().SetString(*args, **kwargs)
        self._items_changed()
        return result

    def SetSelection(self, index):
        result = super().SetSelection(index)
        self._refresh_tip()
        return result

    def SetStringSelection(self, value):
        result = super().SetStringSelection(value)
        self._refresh_tip()
        return result

    def SetValue(self, value):
        result = super().SetValue(value)
        self._refresh_tip()
        return result


class ReadableChoice(_ReadableItems, wx.Choice):
    """Choice with measured popup width and full selected-item tooltip."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._readable_init()


class ReadableComboBox(_ReadableItems, wx.ComboBox):
    """ComboBox preserving native events and item identity without label elision."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._readable_init()
