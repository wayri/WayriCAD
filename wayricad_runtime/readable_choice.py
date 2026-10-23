"""Native choices with readable Windows popups and complete selected-value tips.

The control remains a wx Choice/ComboBox: item text, indices and client data are
unchanged. Windows permits a popup wider than the collapsed sidebar control;
other wx ports keep their native popup sizing and still get full-value tips.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
import wx


# Different controls commonly display the same full net inventory. Cache exact
# native-font measurements, rather than rescan the Windows item container on
# every resize. The small bound also releases obsolete project inventories.
_TEXT_WIDTHS = OrderedDict()
_TEXT_WIDTH_CACHE_LIMIT = 16


def _replace_items(control, operation, items, args, kwargs):
    """Populate native items with one repaint, preserving an outer freeze."""
    frozen_here = not control.IsFrozen()
    if frozen_here:
        control.Freeze()
    try:
        return operation(items, *args, **kwargs)
    finally:
        if frozen_here and control and not control.IsBeingDeleted():
            control.Thaw()


def popup_width(text_widths, control_width, available_width, padding=36):
    """Return a measured popup width bounded by the current display work area."""
    return max(control_width, min(max(text_widths, default=0) + padding,
                                  max(control_width, available_width)))


class _ReadableItems:
    def _readable_alive(self):
        try:
            return bool(self) and not self.IsBeingDeleted()
        except RuntimeError:
            return False

    def _readable_init(self):
        self._choice_help = ''
        self._popup_dirty = True
        self._items_revision = 0
        self._popup_items = None
        self._popup_measurement = None
        self._last_tip = None
        for event in (wx.EVT_CHOICE, wx.EVT_COMBOBOX, wx.EVT_ENTER_WINDOW,
                      wx.EVT_SET_FOCUS, wx.EVT_TEXT):
            self.Bind(event, self._readable_event)
        self.Bind(wx.EVT_SIZE, self._readable_size)
        if hasattr(wx, 'EVT_DPI_CHANGED'):
            self.Bind(wx.EVT_DPI_CHANGED, self._readable_metrics_changed)
        self.Bind(wx.EVT_CHAR_HOOK, self._search_key)
        self.Bind(wx.EVT_CONTEXT_MENU, self._search_context)
        self._refresh_tip()

    def _search_key(self, event):
        if event.ControlDown() and event.GetKeyCode() in (ord('F'), ord('f')):
            self.ShowSearch()
        else:
            event.Skip()

    def _search_context(self, event):
        menu = wx.Menu()
        item = menu.Append(wx.ID_ANY, 'Search full item names…\tCtrl+F')
        self.Bind(wx.EVT_MENU, lambda event: self.ShowSearch(), id=item.GetId())
        try:
            self.PopupMenu(menu)
        finally:
            self.Unbind(wx.EVT_MENU, id=item.GetId())
            menu.Destroy()

    def ShowSearch(self):
        """Choose by substring without filtering or replacing native items."""
        if getattr(self, '_search_dispatching', False) or not self.IsEnabled():
            return False
        from .searchable_selection import choose_items
        items = self.GetStrings()
        revision = self._items_revision
        result = choose_items(self, items, self.GetSelection())
        if result is None:
            return False
        # Modal background callbacks may repopulate a project-bound control.
        if revision != self._items_revision or items != self.GetStrings():
            return False
        index = result[0]
        if not 0 <= index < len(items):
            return False
        if index == self.GetSelection():
            return True
        self.SetSelection(index)
        event_type = wx.wxEVT_COMBOBOX if isinstance(self, wx.ComboBox) else wx.wxEVT_CHOICE
        event = wx.CommandEvent(event_type, self.GetId())
        event.SetEventObject(self)
        event.SetInt(index)
        event.SetString(items[index])
        event.SetClientData(self.GetClientData(index))
        self._search_dispatching = True
        try:
            self.GetEventHandler().ProcessEvent(event)
        finally:
            self._search_dispatching = False
        return True

    def SetToolTip(self, tip):
        """Retain caller help alongside the complete selected item."""
        self._choice_help = tip.GetTip() if isinstance(tip, wx.ToolTip) else str(tip or '')
        self._refresh_tip()

    def _refresh_tip(self):
        if not hasattr(self, '_choice_help') or not self._readable_alive():
            return
        selected = self.GetValue() if isinstance(self, wx.ComboBox) else self.GetStringSelection()
        text = selected
        if self._choice_help and self._choice_help != selected:
            text = '\n\n'.join(value for value in (selected, self._choice_help) if value)
        if text != self._last_tip:
            super().SetToolTip(text)
            self._last_tip = text

    def _readable_event(self, event):
        self._refresh_tip()
        # The display work area or native theme may have changed while closed.
        # Reapplying the width is cheap; font measurements remain cached.
        self._popup_dirty = True
        self._update_popup()
        event.Skip()

    def _readable_size(self, event):
        self._popup_dirty = True
        self._update_popup()
        event.Skip()

    def _readable_metrics_changed(self, event):
        self._popup_measurement = None
        self._popup_dirty = True
        # Native DPI handling completes after this event propagates.
        wx.CallAfter(self._refresh_popup_metrics)
        event.Skip()

    def _refresh_popup_metrics(self):
        if self._readable_alive():
            self._popup_measurement = None
            self._popup_dirty = True
            self._update_popup()

    def _items_changed(self, items=None):
        self._items_revision = getattr(self, '_items_revision', 0) + 1
        self._popup_items = tuple(items) if items is not None else None
        self._popup_measurement = None
        self._popup_dirty = True
        self._refresh_tip()
        self._update_popup()

    def _maximum_text_width(self):
        """Measure every full label once per item/font/DPI combination."""
        font = self.GetFont().GetNativeFontInfoDesc()
        dpi = self.GetDPI()
        metrics = (font, dpi.x, dpi.y, self.GetDPIScaleFactor())
        cached = self._popup_measurement
        if cached is not None and cached[0] == metrics:
            return cached[1]
        if self._popup_items is None:
            self._popup_items = tuple(self.GetStrings())
        key = (metrics, self._popup_items)
        if key in _TEXT_WIDTHS:
            width = _TEXT_WIDTHS.pop(key)
        else:
            width = max((self.GetTextExtent(item).width for item in self._popup_items), default=0)
        _TEXT_WIDTHS[key] = width
        while len(_TEXT_WIDTHS) > _TEXT_WIDTH_CACHE_LIMIT:
            _TEXT_WIDTHS.popitem(last=False)
        self._popup_measurement = (metrics, width)
        return width

    def _update_popup(self):
        if not self._readable_alive() or not getattr(self, '_popup_dirty', False) or not self.GetHandle():
            return
        if sys.platform != 'win32':
            return
        import ctypes
        from ctypes import wintypes
        display = wx.Display.GetFromWindow(self)
        available = wx.Display(display if display != wx.NOT_FOUND else 0).GetClientArea().width
        width = popup_width((self._maximum_text_width(),),
                            self.GetSize().width, available - self.FromDIP(24), self.FromDIP(36))
        send = ctypes.windll.user32.SendMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = ctypes.c_ssize_t
        send(self.GetHandle(), 0x0160, width, 0)  # CB_SETDROPPEDWIDTH
        self._popup_dirty = False

    def Set(self, items, *args, **kwargs):
        result = _replace_items(self, super().Set, items, args, kwargs)
        self._items_changed(items)
        return result

    def SetItems(self, items, *args, **kwargs):
        result = _replace_items(self, super().SetItems, items, args, kwargs)
        self._items_changed(items)
        return result

    def Append(self, *args, **kwargs):
        result = super().Append(*args, **kwargs)
        self._items_changed()
        return result

    def Clear(self):
        result = super().Clear()
        self._items_changed(())
        return result

    def SetString(self, *args, **kwargs):
        result = super().SetString(*args, **kwargs)
        self._items_changed()
        return result

    def Delete(self, *args, **kwargs):
        result = super().Delete(*args, **kwargs)
        self._items_changed()
        return result

    def Insert(self, *args, **kwargs):
        result = super().Insert(*args, **kwargs)
        self._items_changed()
        return result

    def SetFont(self, font):
        result = super().SetFont(font)
        if hasattr(self, '_popup_dirty'):
            self._popup_measurement = None
            self._popup_dirty = True
            self._update_popup()
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


class SearchableCheckListBox(wx.CheckListBox):
    """Native checked list with a separate search-and-multiselect dialog."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._items_revision = 0
        self.Bind(wx.EVT_CHAR_HOOK, self._search_key)

    def Set(self, items, *args, **kwargs):
        self._items_revision += 1
        return _replace_items(self, super().Set, items, args, kwargs)

    def SetItems(self, items, *args, **kwargs):
        self._items_revision += 1
        return _replace_items(self, super().SetItems, items, args, kwargs)

    def Append(self, *args, **kwargs):
        self._items_revision += 1
        return super().Append(*args, **kwargs)

    def Clear(self):
        self._items_revision += 1
        return super().Clear()

    def Delete(self, *args, **kwargs):
        self._items_revision += 1
        return super().Delete(*args, **kwargs)

    def SetString(self, *args, **kwargs):
        self._items_revision += 1
        return super().SetString(*args, **kwargs)

    def _search_key(self, event):
        if event.ControlDown() and event.GetKeyCode() in (ord('F'), ord('f')):
            self.ShowSearch()
        else:
            event.Skip()

    def ShowSearch(self):
        if getattr(self, '_search_dispatching', False) or not self.IsEnabled():
            return False
        from .searchable_selection import choose_items
        items = self.GetStrings()
        revision = self._items_revision
        result = choose_items(self, items, self.GetSelection(), self.GetCheckedItems())
        if result is None or revision != self._items_revision or items != self.GetStrings():
            return False
        checked = set(result)
        changed = [index for index in range(len(items))
                   if self.IsChecked(index) != (index in checked)]
        for index in changed:
            self.Check(index, index in checked)
        # Each event sees the final complete checked set, never half an update.
        self._search_dispatching = True
        try:
            for index in changed:
                if not self or self.IsBeingDeleted() or revision != self._items_revision:
                    break
                event = wx.CommandEvent(wx.wxEVT_CHECKLISTBOX, self.GetId())
                event.SetEventObject(self)
                event.SetInt(index)
                event.SetString(items[index])
                self.GetEventHandler().ProcessEvent(event)
        finally:
            self._search_dispatching = False
        return True
