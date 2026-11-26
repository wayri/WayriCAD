'''Follow saved KiCad inputs without polling geometry or assuming live edit support.'''

from pathlib import Path


def source_stamp(path, suffixes=('.kicad_pcb', '.kicad_pro', '.kicad_dru')):
    '''Cheap change detection; callers still verify bytes when accepting results.'''
    if not path:
        return None
    board = Path(path)
    records = []
    for suffix in suffixes:
        item = board if suffix == ".kicad_pcb" else board.with_suffix(suffix)
        try:
            stat = item.stat()
        except OSError:
            record = None
        else:
            record = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        records.append((str(item), record))
    return tuple(records)


class RevisionState:
    '''Invalidate immediately, then wait for one stable observation before reload.'''

    def __init__(self, stamp):
        self.reset(stamp)

    def reset(self, stamp):
        self.stamp = stamp
        self.pending = False

    def observe(self, stamp, *, ready, available):
        if stamp != self.stamp:
            self.stamp = stamp
            self.pending = True
            return 'invalidate'
        if self.pending and available and ready:
            self.pending = False
            return 'reload'
        return None


class SavedBoardRefresh:
    '''A GUI-owned watcher for one saved PCB and its adjacent project/rules.

    Callbacks run on the owner's UI thread. Invalidate should hide stale results
    and cancel pending work. Reload should start the regular source-bound load.
    The watcher cannot inspect unsaved edits in the editor.
    '''

    def __init__(self, owner, path, invalidate, reload, ready, *, interval_ms=450):
        import wx

        self.owner = owner
        self.path = path if callable(path) else lambda: path
        self.invalidate = invalidate
        self.reload = reload
        self.ready = ready
        self.state = RevisionState(source_stamp(self.path()))
        self.closed = False
        self.timer = wx.Timer(owner)
        owner.Bind(wx.EVT_TIMER, self.poll, self.timer)
        owner.Bind(wx.EVT_WINDOW_DESTROY, self.destroy)
        self.timer.Start(interval_ms)

    def reset(self):
        '''Rebind a deliberate source switch before starting its initial load.'''
        self.state.reset(source_stamp(self.path()))

    def destroy(self, event):
        if event.GetEventObject() is self.owner:
            self.stop()
        event.Skip()

    def stop(self):
        if not self.closed:
            self.closed = True
            self.timer.Stop()

    def poll(self, event=None):
        if self.closed:
            return
        stamp = source_stamp(self.path())
        action = self.state.observe(stamp, ready=self.ready(), available=bool(stamp and stamp[0][1]))
        if action == 'invalidate':
            self.invalidate()
        elif action == 'reload':
            self.reload()
