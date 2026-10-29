"""Viewport-first Quick SI controls without changing analysis state."""
import wx


class Workspace:
    """Keep setup, results and file actions reachable beside the full-size route."""
    def __init__(self, panel, inputs, form, view_host, layout):
        self.panel, self.inputs, self.view_host = panel, inputs, view_host
        inputs.SetMinSize((1,1));inputs.SetScrollRate(10,12)
        self.input_width = panel.FromDIP(330)
        self.result_height = panel.FromDIP(200)
        self.focused = False
        self.saved_visibility = (False, False)
        header = wx.Panel(panel)
        row = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.setup = self._button(header, row, 'Setup', self.toggle_setup, toggle=True,
                                  tip='Show editable inputs, returns, IBIS models and multi-net studies')
        for control, label in ((panel.setup_button, 'Set up path…'),
                               (panel.run_button, 'Run SI'), (panel.cancel_button, 'Cancel')):
            form.Detach(control); control.Reparent(header); control.SetLabel(label)
            control.SetMinSize((-1, header.FromDIP(28)))
            row.Add(control, 0, wx.RIGHT | wx.BOTTOM, 5)
        panel.run_button.SetBitmap(wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, wx.ART_BUTTON, (16,16)))
        self.details = self._button(header, row, 'Details', self.toggle_details, toggle=True,
                                    tip='Show or hide the complete results and evidence table')
        self.fit = self._button(header, row, 'Fit', self.fit_view, tip='Fit the route to its original extents')
        self.focus = self._button(header, row, 'Focus view', self.focus_view, toggle=True,
                                  tip='Temporarily hide panels; restore their previous sizes and visibility')
        self.pcb = self._button(header,row,'PCB',self.show_pcb,
                               tip='Read the originating editor selection or select this route and return nets')
        self.files = self._button(header, row, 'Files', self.show_files,
                                  tip='Save/load setup or results; export reports, Blender or a KiCad circuit')
        self._button(header, row, 'Help', self.show_help)
        header.SetSizer(row)
        layout.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.summary = wx.StaticText(panel, style=wx.ST_ELLIPSIZE_MIDDLE)
        self.summary.SetMinSize((1,-1))
        layout.Add(self.summary,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        # These existing controllers own enable/disable and error handling.
        # Their commands stay visible in Files instead of consuming the sidebar.
        for control in (panel.export, panel.blender, panel.export_circuit_button, panel.copy_circuit_button,
                        panel.select_route_button,panel.select_returns_button,panel.read_selection_button):
            form.Detach(control); control.Hide()
        for controller in (panel.project_setup,panel.project_results):
            controller.save.Hide();controller.load.Hide()
        panel.results_splitter.Initialize(view_host);panel.results.Hide()
        panel.workspace_splitter.Initialize(panel.results_splitter);inputs.Hide()
        panel.workspace_splitter.SetMinimumPaneSize(panel.FromDIP(220))
        panel.workspace_splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGING,self.limit_setup)
        panel.workspace_splitter.Bind(wx.EVT_SIZE,self.resized)
        self.refresh_summary()

    @staticmethod
    def _button(parent, row, label, callback, *, toggle=False, tip=''):
        control=(wx.ToggleButton if toggle else wx.Button)(parent,label=label,style=wx.BU_EXACTFIT)
        control.SetMinSize((-1,parent.FromDIP(28)))
        if tip:control.SetToolTip(tip)
        control.Bind(wx.EVT_TOGGLEBUTTON if toggle else wx.EVT_BUTTON,callback)
        row.Add(control,0,wx.RIGHT|wx.BOTTOM,5)
        return control

    def refresh_summary(self):
        values={key:self.panel.fields[key].GetValue() for key in ('net','start','end')}
        message=(values['net']+' · '+(values['start'] or 'Source?')+' → '+(values['end'] or 'Receiver?')
                 if values['net'] else '1 Set up a path · 2 Run SI · 3 Inspect the route and Details')
        if self.panel.saved_board:message+=' · Saved PCB snapshot'
        self.summary.SetLabel(message);self.summary.SetToolTip(message)

    def setup_limit(self):
        width=self.panel.workspace_splitter.GetClientSize().width
        return max(self.panel.FromDIP(220),round(width*.3))

    def toggle_setup(self,event=None,*,show=None):
        split=self.panel.workspace_splitter;current=split.IsSplit()
        show=not current if show is None else bool(show)
        if show and not current:
            self.inputs.Show()
            split.SplitVertically(self.inputs,self.panel.results_splitter,min(self.input_width,self.setup_limit()))
            self.inputs.Layout();self.inputs.FitInside()
        elif current and not show:
            self.input_width=split.GetSashPosition();split.Unsplit(self.inputs)
        self.setup.SetValue(show);self.panel.Layout()
        self.panel.preview.Refresh()

    def toggle_details(self,event=None,*,show=None):
        split=self.panel.results_splitter;current=split.IsSplit()
        show=not current if show is None else bool(show)
        if show and not current:
            self.panel.results.Show()
            height=split.GetClientSize().height
            wanted=min(self.result_height,round(height*.3))
            split.SplitHorizontally(self.view_host,self.panel.results,max(self.panel.FromDIP(260),height-wanted))
            split.SetSashGravity(1.)
        elif current and not show:
            self.result_height=split.GetClientSize().height-split.GetSashPosition()
            split.Unsplit(self.panel.results)
        self.details.SetValue(show);self.panel.Layout()
        self.panel.preview.Refresh()

    def focus_view(self,event=None):
        if not self.focused:
            self.saved_visibility=(self.panel.workspace_splitter.IsSplit(),self.panel.results_splitter.IsSplit())
            self.toggle_setup(show=False);self.toggle_details(show=False)
            self.focused=True;self.focus.SetLabel('Restore panels')
        else:
            self.toggle_setup(show=self.saved_visibility[0]);self.toggle_details(show=self.saved_visibility[1])
            self.focused=False;self.focus.SetLabel('Focus view')
        from wayricad_runtime.visual_feedback import decorate_button
        decorate_button(self.focus,role='focus')
        self.focus.SetValue(self.focused);self.panel.Layout()

    def fit_view(self,event=None):
        if self.panel.views.GetSelection()==0:self.panel.preview.fit()
        else:self.panel.eye_preview.Refresh()  # Eye/step already fits the available panel.

    def limit_setup(self,event):
        event.SetSashPosition(min(event.GetSashPosition(),self.setup_limit()));event.Skip()

    def resized(self,event):
        if not getattr(self,'_resize_pending',False):
            self._resize_pending=True
            wx.CallAfter(self._limit_after_layout)
        event.Skip()

    def _limit_after_layout(self):
        self._resize_pending=False
        if not self.panel or self.panel.IsBeingDeleted():return
        split=self.panel.workspace_splitter
        if split.IsSplit() and split.GetSashPosition()>self.setup_limit():
            split.SetSashPosition(self.setup_limit())

    def show_help(self,event=None):
        from .help_utils import open_help
        open_help(self.panel)

    def show_files(self,event=None):
        panel=self.panel
        choices=[('Save setup…',panel.project_setup.on_save,None),('Load setup…',panel.project_setup.on_load,None),
                 ('Save results…',panel.project_results.on_save,None),('Load results…',panel.project_results.on_load,None),
                 ('Export HTML / PDF report…',panel.export_report,panel.export),
                 ('Export to Blender…',panel.export_blender,panel.blender),
                 ('Export KiCad circuit…',lambda event:panel._start_circuit_export(False),panel.export_circuit_button),
                 ('Copy KiCad circuit…',lambda event:panel._start_circuit_export(True),panel.copy_circuit_button)]
        with wx.Menu() as menu:
            for label,callback,control in choices:
                item=menu.Append(wx.ID_ANY,label)
                if control is not None:item.Enable(control.IsEnabled())
                menu.Bind(wx.EVT_MENU,callback,id=item.GetId())
            self.files.PopupMenu(menu)

    def show_pcb(self,event=None):
        panel=self.panel
        with wx.Menu() as menu:
            choices=[('Use PCB selection',panel.use_pcb_selection,panel.read_selection_button),
                     ('Choose net on board…',panel.select_board_net,None),
                     ('Select route in PCB',panel.select_route_in_pcb,panel.select_route_button),
                     ('Select return nets in PCB',panel.select_returns_in_pcb,panel.select_returns_button)]
            for label,callback,control in choices:
                item=menu.Append(wx.ID_ANY,label)
                if control is not None:item.Enable(control.IsEnabled())
                menu.Bind(wx.EVT_MENU,callback,id=item.GetId())
            self.pcb.PopupMenu(menu)
