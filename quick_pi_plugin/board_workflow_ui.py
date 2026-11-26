"""PCB-first PI inputs with explicit endpoint roles and origin-bound IPC."""
import wx
from .board_selection import selection_plan
from .workspace_controls import icon_button


class BoardWorkflow:
    def __init__(self, frame, panel, toolbar):
        self.frame = frame
        self.buttons=[]
        self.reader=None
        self.follow = wx.CheckBox(panel, label='Follow PCB')
        from wayricad_runtime.context import LaunchContext
        self.origin=LaunchContext.capture()
        self.follow.Enable(bool(self.origin.socket and self.origin.token))
        self.follow.SetToolTip('Opt in to highlight selection from the originating PCB Editor. Use PCB selection to assign simulation endpoints.')
        toolbar.Add(self.follow, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.BOTTOM, 8)
        self.live_edits=wx.CheckBox(panel,label='Use unsaved edits')
        self.live_edits.Hide()
        control=icon_button(panel,'PCB selection',wx.ART_FIND,'Use selected PCB net or explicitly assign Source pad / Load pad')
        def menu(event):
            with wx.Menu() as popup:
                for label,role in (('Use PCB net','net'),('Source pad','source'),('Load pad','sink')):
                    item=popup.Append(wx.ID_ANY,label)
                    popup.Bind(wx.EVT_MENU,lambda event,role=role:self.use(role),id=item.GetId())
                popup.AppendSeparator()
                for label,role in (('Select source in PCB','source'),('Select load in PCB','sink')):
                    item=popup.Append(wx.ID_ANY,label)
                    popup.Bind(wx.EVT_MENU,lambda event,role=role:frame._select_ids(
                        frame._unit_ids(role),additive=False),id=item.GetId())
                net=popup.Append(wx.ID_ANY,'Select current net in PCB')
                popup.Bind(wx.EVT_MENU,frame._select_net_scope,id=net.GetId())
                popup.AppendSeparator()
                if self.origin.socket and self.origin.token:
                    live=popup.AppendCheckItem(wx.ID_ANY,'Use unsaved edits')
                    live.Check(self.live_edits.GetValue())
                    def toggle_live(event):
                        self.live_edits.SetValue(event.IsChecked())
                        if not event.IsChecked() and frame._background_analysis:
                            frame._set_routing_watch(False)
                    popup.Bind(wx.EVT_MENU,toggle_live,id=live.GetId())
                    background=popup.AppendCheckItem(wx.ID_ANY,'Live analysis in background')
                    background.Check(frame._background_analysis)
                    popup.Bind(wx.EVT_MENU,lambda event:frame._set_routing_watch(
                        event.IsChecked(),background=True),id=background.GetId())
                watch=popup.AppendCheckItem(wx.ID_ANY,'Watch routing while active')
                watch.Check(frame.auto_run.GetValue() and not frame._background_analysis)
                popup.Bind(wx.EVT_MENU,lambda event:frame._set_routing_watch(event.IsChecked()),
                           id=watch.GetId())
                control.PopupMenu(popup)
        control.Bind(wx.EVT_BUTTON,menu)
        toolbar.Add(control,0,wx.RIGHT|wx.BOTTOM,4);self.buttons.append(control)
        path=icon_button(panel,'Path',wx.ART_LIST_VIEW,'Power path: extract and review sequential stages and parallel banks')
        path.Bind(wx.EVT_BUTTON,frame.on_series_editor)
        toolbar.Add(path,0,wx.RIGHT|wx.BOTTOM,4)
        self.buttons.append(path)
        from wayricad_runtime.selection_follow import SelectionFollower
        self.follower = SelectionFollower(frame, self.follow, self.read,
            self.highlight, self._follow_ready, self._failed, include_empty=True, interval_ms=2200)
        self.follow.Bind(wx.EVT_CHECKBOX,self._clear_when_disabled)

    def ready(self):
        f = self.frame
        return bool(not f._closed and not f._closing and not f._busy
                    and not getattr(f, '_live_running', False)
                    and f.inventory and f._saved_source_current)

    def _follow_ready(self):
        frame = self.frame
        watch = getattr(frame, '_route_watch', None)
        return (frame.IsShownOnScreen() and not frame.IsIconized() and self.ready()
                and not (watch and watch.running))

    def refresh(self):
        for control in self.buttons:control.Enable(self.ready())

    def invalidate(self):
        self.reader=None
        self.follower.state.reset()

    def _failed(self,error):
        from wayricad_runtime.analysis_selection import SavedSelectionChanged
        if isinstance(error,SavedSelectionChanged):
            self.follow.SetValue(True)
            self.frame.editor_refresh.poll()
            return
        self.highlight(())
        self.frame.status.SetLabel('PCB follow paused: '+str(error))

    def _clear_when_disabled(self,event):
        if not self.follow.GetValue():
            self.highlight(())
        event.Skip()

    def highlight(self, identifiers):
        values=tuple(identifiers)
        if values!=self.frame._pcb_highlight_ids:
            self.frame._pcb_highlight_ids=values
            self.frame._draw(preserve=True)

    def read(self):
        from wayricad_runtime.analysis_selection import SavedSelectionReader
        expected=self.frame._origin_sha()
        if self.reader is None:
            self.reader=SavedSelectionReader(self.frame.board_path,expected_sha256=expected,
                                             launch_context=self.origin)
        return self.reader.read()

    def use(self, role):
        if not self.ready():
            return
        self.frame._task(self.read, lambda ids: self.apply(ids, role), 'Reading selected PCB items...')

    def apply(self, identifiers, role):
        f = self.frame
        plan = selection_plan(identifiers, f.inventory, f._board_scene, role)
        if plan['net'] != f.net.GetValue():
            f.net_search.ChangeValue('')
            f.net.Set(f.inventory.get('nets', []))
            f.net.SetValue(plan['net'])
            f._net_changed()
            for control in (f.source, f.sink):
                control.SetSelection(wx.NOT_FOUND)
        if role != 'net':
            index = next((i for i, item in enumerate(f._terminals)
                          if item['id'] == plan['terminal']), None)
            if index is None:
                raise ValueError('Selected pad no longer resolves. Reload the saved board.')
            getattr(f, role).SetSelection(index)
            if role=='sink':f._set_primary_sink_pads(())
            getattr(f, role + '_pins').SetValue(False)
            f._invalidate()
        f._buttons()
        f.status.SetLabel('PCB net: ' + plan['net'] +
                         ('. Select a pad and assign Source or Load.' if role == 'net'
                          else '. Assigned ' + role + ' pad; review voltage and load before Run.'))

    def stop(self):
        self.follower.stop()
