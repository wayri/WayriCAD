"""Explicit, reviewed exact-filename repairs; no silent library substitutions."""
from pathlib import Path
import threading
import wx
from .paths import exact_name_candidates
from .assets import set_window_icons


class FindMissingDialog(wx.Dialog):
    def __init__(self, parent, groups, roots):
        super().__init__(parent, title='Find missing model files', style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.groups = groups  # (reference, source_dir) -> [(source_key, row_index)]
        self.matches, self.proposals, self.accepted = {}, [], {}
        self.running = self.closing = False
        self.cancel_event = threading.Event()
        set_window_icons(self, wx)
        outer = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Search the installed 3D-model folder. Only exact filenames are proposed.\n'
                                        'Review the paths before applying. Ambiguous matches are never chosen automatically.')
        outer.Add(note, 0, wx.EXPAND | wx.ALL, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder = wx.DirPickerCtrl(self, path=str(roots[0]) if roots else '',
                                       message='Choose the stock or custom 3D model root',
                                       style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        self.search = wx.Button(self, label='Search folder')
        row.Add(self.folder, 1, wx.RIGHT, 8); row.Add(self.search)
        outer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.table.EnableCheckBoxes(True)
        for i, (label, size) in enumerate((('Linked model', 260), ('Result', 130), ('Proposed local file', 470))):
            self.table.InsertColumn(i, label, width=self.FromDIP(size))
        outer.Add(self.table, 1, wx.EXPAND | wx.ALL, 12)
        self.detail = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=self.FromDIP((-1, 85)))
        outer.Add(self.detail, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.status = wx.StaticText(self, label='No replacements have been applied.')
        outer.Add(self.status, 0, wx.EXPAND | wx.ALL, 12)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.choose = wx.Button(self, label='Choose candidate…')
        self.cancel = wx.Button(self, wx.ID_CANCEL, 'Cancel')
        self.use = wx.Button(self, label='Use checked matches'); self.use.Enable(False)
        footer.Add(self.choose); footer.AddStretchSpacer(); footer.Add(self.cancel, 0, wx.RIGHT, 8); footer.Add(self.use)
        outer.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(outer); self.SetSize(self.FromDIP((940, 530))); self.SetMinSize(self.FromDIP((760, 430)))
        self.search.Bind(wx.EVT_BUTTON, self.on_search)
        self.choose.Bind(wx.EVT_BUTTON, self.on_choose)
        self.use.Bind(wx.EVT_BUTTON, self.on_use)
        self.cancel.Bind(wx.EVT_BUTTON, self.on_close); self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.CentreOnParent()
        if roots:
            wx.CallAfter(self.on_search)

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close()
        else:
            event.Skip()

    def on_search(self, event=None):
        if self.running:
            return
        root = Path(self.folder.GetPath())
        if not self.folder.GetPath() or not root.is_dir():
            wx.MessageBox('Choose an existing 3D-model folder.', 'Find models', wx.OK | wx.ICON_WARNING, self)
            return
        self.running = True; self.cancel_event.clear()
        self.search.Enable(False); self.folder.Enable(False); self.use.Enable(False)
        self.choose.Enable(False); self.table.Enable(False)
        self.status.SetLabel('Searching exact filenames… No files or model links are being changed.')
        refs = [key[0] for key in self.groups]
        def worker():
            error = None
            try:
                result = exact_name_candidates(refs, [root], self.cancel_event.is_set)
            except Exception as exc:
                result, error = {}, str(exc)
            wx.CallAfter(self.on_done, result, error)
        threading.Thread(target=worker, name='WayriCAD Embed3D-find-models', daemon=True).start()

    def on_done(self, matches, error):
        self.running = False
        if self.closing:
            self.EndModal(wx.ID_CANCEL); return
        self.matches, self.proposals = matches, []
        self.table.DeleteAllItems()
        for key in self.groups:
            basename = key[0].replace('\\', '/').rsplit('/', 1)[-1]
            candidates = matches.get(basename, [])
            proposed = candidates[0] if len(candidates) == 1 else None
            index = self.table.InsertItem(self.table.GetItemCount(), basename)
            self.table.SetItem(index, 1, 'One exact match' if proposed else ('Choose from %d' % len(candidates) if candidates else 'Not found'))
            self.table.SetItem(index, 2, str(proposed or ''))
            self.table.CheckItem(index, bool(proposed))
            self.proposals.append([key, proposed, candidates])
        self.search.Enable(True); self.folder.Enable(True); self.table.Enable(True); self.choose.Enable(True)
        self.use.Enable(not error and bool(self.proposals))
        self.status.SetLabel(error or 'Review checked paths, then use the matches. Same filename is not a guarantee of identical geometry.')

    def on_select(self, event):
        index = self.table.GetFirstSelected()
        if 0 <= index < len(self.proposals):
            key, _, candidates = self.proposals[index]
            self.detail.SetValue('Original: '+key[0]+'\nFootprint-library context: '+key[1]+
                                 '\nCandidates:\n'+'\n'.join(str(p) for p in candidates))

    def on_choose(self, event):
        index = self.table.GetFirstSelected()
        if not 0 <= index < len(self.proposals):
            return
        key, _, candidates = self.proposals[index]
        if not candidates:
            return
        with wx.SingleChoiceDialog(self, 'Select the exact intended model. Geometry is not automatically compared.',
                                   'Resolve multiple matches', [str(p) for p in candidates]) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                path = candidates[dialog.GetSelection()]
                self.proposals[index][1] = path
                self.table.SetItem(index, 1, 'Chosen by you'); self.table.SetItem(index, 2, str(path))
                self.table.CheckItem(index, True)

    def on_use(self, event):
        if self.running:
            return
        for i, (key, path, _) in enumerate(self.proposals):
            if self.table.IsItemChecked(i) and path is not None:
                for source_key, row_index in self.groups[key]:
                    self.accepted.setdefault(source_key, {})[row_index] = str(path)
        self.EndModal(wx.ID_OK)

    def on_close(self, event=None):
        if self.running:
            self.closing = True; self.cancel_event.set()
            self.status.SetLabel('Stopping search…')
            if hasattr(event, 'Veto'):
                event.Veto()
        else:
            self.EndModal(wx.ID_CANCEL)
