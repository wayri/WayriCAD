"""PCB-first PI inputs with explicit endpoint roles and origin-bound IPC."""
import wx
from .board_selection import selection_plan
from .workspace_controls import icon_button


class BoardWorkflow:
    def __init__(self, frame, panel, toolbar):
        self.frame = frame
        self.buttons=[]
        self.follow = wx.CheckBox(panel, label='Follow PCB')
        from wayricad_runtime.context import LaunchContext
        origin=LaunchContext.capture()
        self.follow.SetValue(bool(origin.socket and origin.token))
        self.follow.SetToolTip('Follow one selected net in the originating editor; never infer source/load direction.')
        toolbar.Add(self.follow, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.BOTTOM, 8)
        control=icon_button(panel,'PCB',wx.ART_FIND,'Use selected PCB net or explicitly assign Source pad / Load pad')
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
                control.PopupMenu(popup)
        control.Bind(wx.EVT_BUTTON,menu)
        toolbar.Add(control,0,wx.RIGHT|wx.BOTTOM,4);self.buttons.append(control)
        path=icon_button(panel,'Path',wx.ART_LIST_VIEW,'Power path: extract and review sequential stages and parallel banks')
        path.Bind(wx.EVT_BUTTON,frame.on_series_editor)
        toolbar.Add(path,0,wx.RIGHT|wx.BOTTOM,4)
        self.buttons.append(path)
        from wayricad_runtime.selection_follow import SelectionFollower
        self.follower = SelectionFollower(frame, self.follow, self.read,
            lambda ids: self.apply(ids, 'net'), self.ready,
            lambda error: frame.status.SetLabel('PCB follow paused: ' + str(error)))

    def ready(self):
        f = self.frame
        return bool(not f._closed and not f._closing and not f._busy
                    and not getattr(f, '_live_running', False)
                    and f.inventory and f._saved_source_current)

    def refresh(self):
        for control in self.buttons:control.Enable(self.ready())

    def read(self):
        from .origin_selection import selected_origin_ids
        return selected_origin_ids(self.frame.board_path, expected_sha256=self.frame._origin_sha())

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
            getattr(f, role + '_pins').SetValue(False)
            f._invalidate()
        f._buttons()
        f.status.SetLabel('PCB net: ' + plan['net'] +
                         ('. Select a pad and assign Source or Load.' if role == 'net'
                          else '. Assigned ' + role + ' pad; review voltage and load before Run.'))

    def stop(self):
        self.follower.stop()
