"""Narrow, capability-checked SWIG selection bridge. No rule/board writes.
Testable with adapter objects; executing these tests does not test KiCad itself.
"""
from pathlib import Path


def uuid_text(item):
    uid=getattr(item,'m_Uuid',None)
    return str(uid.AsString()) if uid is not None and hasattr(uid,'AsString') else ''


def native_items(board):
    """Enumerate public collections and deduplicate nested objects by UUID."""
    result={}
    def add(seq):
        for item in seq:
            key=uuid_text(item)
            if key:result[key]=item
    for name in ('GetFootprints','GetTracks','GetDrawings','Groups'):
        fn=getattr(board,name,None)
        if callable(fn):add(fn())
    fn=getattr(board,'GetZoneList',None)
    if callable(fn):add(fn(True))
    footprints=getattr(board,'GetFootprints',lambda:[])()
    for fp in footprints:
        for name in ('Pads','GraphicalItems','Zones'):
            fn=getattr(fp,name,None)
            if callable(fn):add(fn())
        for name in ('Reference','Value'):
            fn=getattr(fp,name,None)
            if callable(fn):add([fn()])
    return result


class SelectionBridge:
    def __init__(self,get_board,refresh,get_selection=None,focus=None):
        board=get_board()
        self.get_board=get_board;self.refresh=refresh;self.get_selection=get_selection;self.focus=focus
        self.path=Path(str(board.GetFileName())).resolve()
        self.stamp=board.GetTimeStamp() if hasattr(board,'GetTimeStamp') else None
    def active(self):
        board=self.get_board()
        if not board or Path(str(board.GetFileName())).resolve()!=self.path:
            raise RuntimeError('Active board changed. Close and relaunch Constraint Studio.')
        if self.stamp is not None and board.GetTimeStamp()!=self.stamp:
            raise RuntimeError('The active board changed after launch. Save it and reopen Constraint Studio before cross-probing.')
        return board
    def selection(self):
        self.active()
        if self.get_selection is not None:return [uuid_text(item) for item in self.get_selection() if uuid_text(item)]
        return [key for key,item in native_items(self.active()).items() if item.IsSelected()]
    def probe(self,ids):
        ids=list(dict.fromkeys(ids))
        if not ids:return
        if len(ids)>2000:raise ValueError('Select at most 2,000 objects for one cross-probe')
        board=self.active();items=native_items(board)
        missing=[key for key in ids if key not in items]
        if missing:raise ValueError('Some report/preview objects are not on the active board. No selection was changed. Reload or regenerate evidence.')
        if any(not hasattr(x,'ClearSelected') or not hasattr(x,'SetSelected') for x in items.values()):
            raise RuntimeError('This host lacks the required selection adapter; no board geometry was changed')
        previous=[key for key,item in items.items() if item.IsSelected()]
        try:
            for item in items.values():item.ClearSelected()
            for key in ids:items[key].SetSelected()
            self.refresh()
            if self.focus is not None and len(ids)==1:self.focus(items[ids[0]])
        except Exception:
            for item in items.values():item.ClearSelected()
            for key in previous:items[key].SetSelected()
            self.refresh()
            raise
    def reference(self,reference):
        matches=[fp for fp in self.active().GetFootprints() if fp.GetReference()==reference]
        if len(matches)!=1:raise ValueError('Component reference is missing or ambiguous')
        self.probe([uuid_text(matches[0])])


def open_resolution(pair=True):
    """Dispatch an existing native menu action; never simulate the DRC engine.
    Selection MUST belong to the native selection tool, not just item flags.
    Labels are localized through wx; no undocumented action IDs are invented.
    """
    import wx
    import pcbnew
    get=getattr(pcbnew,'GetCurrentSelection',None)
    if not callable(get):raise RuntimeError('Native selection API missing. Use Inspect → Clearance/Constraints Resolution in PCB Editor.')
    selection=list(get());needed=2 if pair else 1
    if len(selection)!=needed:raise ValueError(f'Select {needed} item(s) directly in PCB Editor first. Highlight flags are not the native tool selection.')
    def normalize(s):return s.split('\t')[0].replace('&','').replace('…','').replace('...','').strip().casefold()
    labels=['Clearance Resolution'] if pair else ['Constraints Resolution','Constraint Resolution']
    labels={normalize(x) for label in labels for x in (label,wx.GetTranslation(label))}
    def entries(menu):
        for item in menu.GetMenuItems():
            if item.GetSubMenu():yield from entries(item.GetSubMenu())
            else:yield item
    candidates=[]
    for window in wx.GetTopLevelWindows():
        bar=window.GetMenuBar() if hasattr(window,'GetMenuBar') else None
        if not bar:continue
        for i in range(bar.GetMenuCount()):
            for item in entries(bar.GetMenu(i)):
                if normalize(item.GetItemLabel()) in labels and item.IsEnabled():candidates.append((window,item.GetId()))
    if len(candidates)!=1:raise RuntimeError('Native resolution action was not uniquely available. Use PCB Editor → Inspect → '+('Clearance Resolution' if pair else 'Constraints Resolution')+'. No rule values were guessed.')
    window,identifier=candidates[0];window.Raise()
    wx.PostEvent(window,wx.CommandEvent(wx.EVT_MENU.typeId,identifier))
