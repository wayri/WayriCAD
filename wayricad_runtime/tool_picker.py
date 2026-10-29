"""Readable tool selection and discovery of installed saved-board launchers."""
import json
from pathlib import Path


DESKTOP_TOOLS = {'bom-studio', 'quick-pi', 'quick-therm', 'quick-emerge', 'assistant', 'review-comments'}


def installed_desktop_tools(root):
    """Read immediate installed peers, including KiCad's user and PCM roots."""
    root = Path(root).resolve()
    parent = root.parent
    parents = [parent]
    if parent.name == 'plugins':
        if parent.parent.name == '3rdparty':
            parents.append(parent.parent.parent / 'plugins')
        else:
            parents.append(parent.parent / '3rdparty' / 'plugins')
    tools = {}
    for directory in parents:
        if not directory.is_dir() or directory.is_symlink():
            continue
        for plugin in sorted(directory.iterdir()):
            if not plugin.is_dir() or plugin.is_symlink():
                continue
            manifest = plugin / 'plugin.json'
            try:
                if not manifest.is_file() or manifest.stat().st_size > 65536:
                    continue
                data = json.loads(manifest.read_text(encoding='utf-8'))
                identifier = data.get('identifier', '')
                if not identifier.startswith('com.github.wayri.wayricad.'):
                    continue
                if plugin.name not in (identifier, identifier.replace('.', '_')):
                    continue
                short = identifier.removeprefix('com.github.wayri.wayricad.')
                script = plugin / 'desktop_entrypoint.py'
                if (short not in DESKTOP_TOOLS or not script.is_file() or
                        script.is_symlink() or manifest.is_symlink()):
                    continue
                action = next(a for a in data['actions'] if 'pcb' in a.get('scopes', []))
                if action.get('entrypoint') not in {'ipc_entrypoint.py', 'desktop_entrypoint.py'}:
                    continue
                name = action['name']
                if not isinstance(name, str) or not name.strip():
                    continue
                # Prefer the caller's install root when both install types exist.
                tools.setdefault(name, (plugin, short))
            except (OSError, ValueError, TypeError, AttributeError, KeyError, StopIteration):
                continue
    return tools


def text_colours(selected, dark):
    """Use explicit contrasting foreground/background pairs in both themes."""
    if selected:
        return '#ffffff', '#1559a6'
    return ('#f1f3f4', '#202124') if dark else ('#202124', '#ffffff')


def create_tool_list(parent):
    """Create a native keyboard-selectable list with readable selected rows."""
    import wx

    class ToolList(wx.VListBox):
        def __init__(self):
            super().__init__(parent, style=wx.BORDER_SIMPLE)
            self.names = []
            self.dark = sum(parent.GetBackgroundColour()[:3]) < 384
            foreground, background = text_colours(False, self.dark)
            self.SetForegroundColour(foreground)
            self.SetBackgroundColour(background)
            self.Bind(wx.EVT_LISTBOX, self.selection_changed)

        def Set(self, names):
            self.names = list(names)
            self.SetItemCount(len(self.names))
            self.SetSelection(wx.NOT_FOUND)
            self.SetToolTip('')
            self.Refresh()

        def GetStringSelection(self):
            index = self.GetSelection()
            return self.names[index] if 0 <= index < len(self.names) else ''

        def SetSelection(self, index):
            super().SetSelection(index)
            self.SetToolTip(self.GetStringSelection())

        def selection_changed(self, event):
            self.SetToolTip(self.GetStringSelection())
            event.Skip()

        def OnMeasureItem(self, index):
            return self.GetCharHeight() + self.FromDIP(12)

        def OnDrawBackground(self, dc, rect, index):
            _, background = text_colours(self.IsSelected(index), self.dark)
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(background))
            dc.DrawRectangle(rect)

        def OnDrawItem(self, dc, rect, index):
            foreground, _ = text_colours(self.IsSelected(index), self.dark)
            dc.SetFont(self.GetFont())
            dc.SetTextForeground(foreground)
            dc.SetBackgroundMode(wx.TRANSPARENT)
            text = self.names[index]
            width = max(0, rect.width - self.FromDIP(16))
            if dc.GetTextExtent(text).width > width:
                while text and dc.GetTextExtent(text + '…').width > width:
                    text = text[:-1]
                text += '…'
            dc.DrawText(text, rect.x + self.FromDIP(8),
                        rect.y + (rect.height - dc.GetCharHeight()) // 2)

    return ToolList()
