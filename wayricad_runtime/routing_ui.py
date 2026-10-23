"""Compact local routing forms: primary choices first, detailed controls on demand."""
import wx
from .readable_choice import ReadableComboBox
from .preview import GeometryPreview
from .routing import FanoutPlanner, StitchingPlanner, netclass_names, copper_layer_names
from .fanout_profiles import FANOUT_PATTERNS, SIGNAL_PROFILES, ANGLE_MODES, PAIR_MODES, profile_defaults


def _combo(parent, choices, value):
    control=ReadableComboBox(parent,choices=choices,style=wx.CB_READONLY)
    control.SetValue(value);return control


def _row(parent,sizer,label,control):
    text=wx.StaticText(parent,label=label)
    sizer.Add(text,0,wx.TOP|wx.BOTTOM,5)
    sizer.Add(control,0,wx.EXPAND|wx.BOTTOM,7)
    return text


def _base(frame,title):
    panel=wx.Panel(frame);root=wx.BoxSizer(wx.VERTICAL)
    workspace=wx.SplitterWindow(panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D);workspace.SetMinimumPaneSize(210);workspace.SetSashGravity(0)
    frame.workspace_splitter=workspace
    left=wx.ScrolledWindow(workspace,style=wx.VSCROLL);left.SetScrollRate(0,12);left.SetMinSize((210,1))
    settings=wx.BoxSizer(wx.VERTICAL)
    frame.settings_pane=left
    heading=wx.StaticText(left,label=title);heading.SetFont(heading.GetFont().Bold())
    settings.Add(heading,0,wx.BOTTOM,12)
    right=wx.Panel(workspace);preview=wx.BoxSizer(wx.VERTICAL)
    results=wx.SplitterWindow(right,style=wx.SP_LIVE_UPDATE|wx.SP_3D);results.SetMinimumPaneSize(80);results.SetSashGravity(.7)
    frame.results_splitter=results
    drawing=wx.Panel(results);drawing_sizer=wx.BoxSizer(wx.VERTICAL)
    bar=wx.BoxSizer(wx.HORIZONTAL);label=wx.StaticText(drawing,label='Board preview')
    label.SetFont(label.GetFont().Bold());bar.Add(label,1,wx.ALIGN_CENTER_VERTICAL)
    grid=wx.CheckBox(drawing,label='Grid');bar.Add(grid,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
    fit=wx.Button(drawing,label='Fit',size=(58,-1));bar.Add(fit,0)
    drawing_sizer.Add(bar,0,wx.EXPAND|wx.BOTTOM,8)
    frame.geometry_preview=GeometryPreview(drawing,'Choose pads or a net, then click Preview.')
    frame.geometry_preview.SetMinSize((160,100))
    if not hasattr(frame,'on_live_preview_changed'):
        frame.geometry_preview.set_board(frame.board,frame._routing_api)
    grid.Bind(wx.EVT_CHECKBOX,lambda event:(setattr(frame.geometry_preview,'show_grid',grid.GetValue()),frame.geometry_preview.Refresh()))
    fit.Bind(wx.EVT_BUTTON,frame.geometry_preview.fit)
    drawing_sizer.Add(frame.geometry_preview,1,wx.EXPAND);drawing.SetSizer(drawing_sizer)
    details=wx.Panel(results)
    detail_sizer=wx.BoxSizer(wx.VERTICAL)
    frame.preview_list=wx.ListCtrl(details,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
    frame.preview_list.SetMinSize((1,80));detail_sizer.Add(frame.preview_list,1,wx.EXPAND)
    details.SetSizer(detail_sizer)
    frame.preview_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,frame.on_preview_row_activated)
    results.Initialize(drawing);details.Hide()
    preview.Add(results,1,wx.EXPAND)
    toggle=wx.ToggleButton(right,label='Candidate details and rejected items');frame.details_toggle=toggle
    def show_details(event):
        if toggle.GetValue():
            details.Show();results.SplitHorizontally(drawing,details,max(100,round(results.GetClientSize().height*.65)))
        elif results.IsSplit():results.Unsplit(details);details.Hide()
        right.Layout()
    toggle.Bind(wx.EVT_TOGGLEBUTTON,show_details);preview.Add(toggle,0,wx.EXPAND|wx.TOP,8)
    right.SetSizer(preview);workspace.SplitVertically(left,right,320)
    root.Add(workspace,1,wx.EXPAND|wx.ALL,16)
    frame.status=wx.StaticText(panel,label='Preview changes before applying them to the board.')
    root.Add(frame.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
    left.SetSizer(settings);panel.SetSizer(root)
    frame.SetMinSize((680,480))
    return panel,root,left,settings


def _advanced(frame,parent,sizer):
    pane=wx.CollapsiblePane(parent,label='Dimensions and advanced settings')
    inner=wx.BoxSizer(wx.VERTICAL);pane.GetPane().SetSizer(inner)
    sizer.Add(pane,0,wx.EXPAND|wx.TOP,8)
    pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(parent.FitInside(),frame.Layout()))
    frame.advanced=pane
    return pane.GetPane(),inner


def _footer(frame,panel,root,help_callback):
    row=wx.BoxSizer(wx.HORIZONTAL)
    frame.undo_button=wx.Button(panel,label='Undo');frame.undo_button.Disable()
    frame.undo_button.Bind(wx.EVT_BUTTON,frame.undo);row.Add(frame.undo_button,0)
    menu=wx.Menu();frame._more_menu=menu
    frame.redo_button=menu.Append(wx.ID_ANY,'Redo last change');frame.redo_button.Enable(False)
    frame.show_button=menu.Append(wx.ID_ANY,'Review placement again');frame.show_button.Enable(False)
    clear=menu.Append(wx.ID_ANY,'Clear preview');menu.AppendSeparator();help_item=menu.Append(wx.ID_ANY,'Help')
    for item,handler in ((frame.redo_button,frame.redo),(frame.show_button,frame.show_on_pcb),(clear,frame.clear_preview)):
        frame.Bind(wx.EVT_MENU,handler,id=item.GetId())
    frame.Bind(wx.EVT_MENU,lambda event:help_callback(),id=help_item.GetId())
    more=wx.Button(panel,label='More',size=(64,-1));more.Bind(wx.EVT_BUTTON,lambda event:more.PopupMenu(menu))
    row.Add(more,0,wx.LEFT,8)
    help_button=wx.Button(panel,label='Help');help_button.Bind(wx.EVT_BUTTON,lambda event:help_callback());row.Add(help_button,0,wx.LEFT,8)
    if hasattr(frame, 'export_connector_review'):
        export=wx.Button(panel,label='Export local-rule review…');frame.export_button=export;export.Disable()
        export.Bind(wx.EVT_BUTTON,frame.export_connector_review)
        row.Add(export,0,wx.LEFT,8)
    row.AddStretchSpacer()
    preview=wx.Button(panel,label='Refresh preview' if hasattr(frame,'on_live_preview_changed') else 'Preview',size=(128,-1))
    frame.preview_button=preview;preview.Bind(wx.EVT_BUTTON,frame.preview);row.Add(preview,0,wx.RIGHT,8)
    preview.SetToolTip('Recompute all candidates for the chosen scope. Preview does not change board copper.')
    frame.commit_button=wx.Button(panel,label='Apply to board',size=(128,-1));frame.commit_button.Disable()
    frame.commit_button.Bind(wx.EVT_BUTTON,frame.generate);frame.commit_button.SetDefault();row.Add(frame.commit_button,0)
    root.Add(row,0,wx.EXPAND|wx.ALL,16)
    from .layout import install_accessibility
    install_accessibility(frame)
    def help_key(event):
        if event.GetKeyCode()==wx.WXK_F1:help_callback()
        else:event.Skip()
    frame.Bind(wx.EVT_CHAR_HOOK,help_key)


def build_fanout(frame,api,help_callback):
    from .visual_feedback import decorate_button
    frame._routing_api=api
    panel,root,left,settings=_base(frame,'Fanout')
    frame.scope=_combo(left,['Selected pads','Selected footprints','Reference wildcard','All SMD pads','All connector pads'],'Selected footprints')
    frame.netclass_filter=_combo(left,['All netclasses']+netclass_names(frame.board),'All netclasses')
    frame.output_mode=_combo(left,['Escape traces','Via-in-pad'],'Escape traces')
    frame.pattern=_combo(left,list(FANOUT_PATTERNS),'Perimeter pitch expansion')
    frame.routing_mode=_combo(left,['Fixed','Adaptive'],'Fixed')
    frame.signal_profile=_combo(left,list(SIGNAL_PROFILES),'Generic')
    frame.escape_angle=wx.TextCtrl(left,value='45')
    frame.escape_layer=_combo(left,['Pad layer']+copper_layer_names(frame.board),'Pad layer')
    profile_row=wx.BoxSizer(wx.HORIZONTAL)
    profile_row.Add(frame.signal_profile,1,wx.RIGHT,6)
    load_profile=wx.Button(left,label='Load defaults',size=(100,-1))
    load_profile.SetToolTip('Explicitly load suggested geometry, net-name filters and pairing. Selecting a family alone preserves all your settings.')
    frame.signal_profile.SetToolTip('A family label does not select nets. Load defaults for suggested net filters, then review them in advanced settings.')
    profile_row.Add(load_profile,0)
    intro=wx.StaticText(left,label='1. Select parts or pins in PCB Editor\n2. Choose a style and inspect the preview\n3. Apply when the candidates look right')
    intro.Wrap(270);settings.Add(intro,0,wx.EXPAND|wx.BOTTOM,10)
    frame.ref=wx.TextCtrl(left,value='*')
    for label,control in (('1 · Pads to fan out',frame.scope),('Reference / wildcard',frame.ref),('Output',frame.output_mode),('2 · Fanout style',frame.pattern)):
        text=_row(left,settings,label,control)
        if control is frame.escape_angle:frame.angle_label=text
        if control is frame.ref:frame.ref_label=text
        if control is frame.pattern:
            style_box=wx.StaticBoxSizer(wx.VERTICAL,left,'Selected style on component')
            style_parent=style_box.GetStaticBox()
            frame.style_component=_combo(style_parent,[],'')
            frame.style_component.SetToolTip('Choose which selected component to inspect. The main canvas keeps every candidate.')
            style_box.Add(frame.style_component,0,wx.EXPAND|wx.ALL,4)
            frame.style_preview=GeometryPreview(style_parent,'Select a footprint to see its fanout.',compact=True)
            frame.style_preview.SetMinSize((180,160))
            style_box.Add(frame.style_preview,0,wx.EXPAND|wx.LEFT|wx.RIGHT,4)
            frame.style_summary=wx.StaticText(style_parent,label='Live preview follows the selected component.')
            frame.style_summary.Wrap(250);style_box.Add(frame.style_summary,0,wx.EXPAND|wx.ALL,4)
            settings.Add(style_box,0,wx.EXPAND|wx.BOTTOM,8)
            frame.style_component.Bind(wx.EVT_COMBOBOX,frame._update_style_preview)
    frame.connector_exit=_combo(left,['Nearest edge','Top','Bottom','Left','Right'],'Nearest edge')
    frame.connector_exit_label=_row(left,settings,'Connector exit (footprint coordinates)',frame.connector_exit)
    frame.connector_exit.SetToolTip('Connector edge style: choose the nearest body edge or a specific side in footprint-local coordinates. Includes plated through-hole pins.')
    frame.auto_refresh=wx.CheckBox(left,label='Live preview');frame.auto_refresh.SetValue(True)
    frame.auto_refresh.SetToolTip('Update selected components after a short pause. Whole-board scopes use Refresh preview. Apply is always separate.')
    frame.auto_refresh.Bind(wx.EVT_CHECKBOX,frame.on_live_preview_changed)
    settings.Add(frame.auto_refresh,0,wx.BOTTOM,8)
    filename=frame.board.GetFileName()
    frame.snapshot_mode=_combo(left,['Saved board · fast','Live snapshot · slower'],
        'Saved board · fast' if filename else 'Live snapshot · slower')
    _row(left,settings,'Preview source',frame.snapshot_mode)
    frame.snapshot_mode.SetToolTip('Fast mode uses a private copy of the saved board; save PCB and project changes first. Live capture preserves unsaved native geometry but can pause while KiCad serializes it. Live native captures require explicit Refresh preview.')
    frame.snapshot_mode.Bind(wx.EVT_COMBOBOX,frame.on_config_changed)
    frame.selection_status=wx.StaticText(left,label='Select pads or footprints in PCB Editor.')
    frame.selection_status.Wrap(255);settings.Add(frame.selection_status,0,wx.TOP|wx.BOTTOM,8)
    frame.fanout_groups=[];frame.group_unmatched='defaults'
    group_pane=wx.CollapsiblePane(left,label='Per-pin / net groups')
    group_sizer=wx.BoxSizer(wx.VERTICAL)
    frame.group_summary=wx.StaticText(group_pane.GetPane(),label='0 groups; unmatched: defaults')
    group_sizer.Add(frame.group_summary,0,wx.ALL,5)
    edit_groups=wx.Button(group_pane.GetPane(),label='Manage groups…')
    from .fanout_groups_ui import manage_groups
    edit_groups.Bind(wx.EVT_BUTTON,lambda event:manage_groups(frame))
    group_sizer.Add(edit_groups,0,wx.ALL,5);group_pane.GetPane().SetSizer(group_sizer)
    group_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(left.FitInside(),frame.Layout()))
    settings.Add(group_pane,0,wx.EXPAND|wx.BOTTOM,8)
    filters=wx.CollapsiblePane(left,label='Limit pins or nets (optional)')
    target_parent=filters.GetPane();target_sizer=wx.BoxSizer(wx.VERTICAL);target_parent.SetSizer(target_sizer)
    frame.pad_filter=wx.TextCtrl(target_parent,value='*')
    frame.net_filter=wx.TextCtrl(target_parent,value='*')
    _row(target_parent,target_sizer,'Pin numbers · e.g. 1,2,5,1?',frame.pad_filter)
    _row(target_parent,target_sizer,'Net names · e.g. USB*,+3V3',frame.net_filter)
    frame.target_filters=filters
    filters.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(left.FitInside(),frame.Layout()))
    settings.Add(filters,0,wx.EXPAND|wx.BOTTOM,8)
    parent,advanced=_advanced(frame,left,settings)
    frame.signal_profile.Reparent(parent);load_profile.Reparent(parent)
    _row(parent,advanced,'Signal family',profile_row)
    frame.netclass_filter.Reparent(parent)
    _row(parent,advanced,'Netclass',frame.netclass_filter)
    for name,label in (('routing_mode','Routing search'),('escape_layer','Trace layer'),('escape_angle','Spread angle (degrees)')):
        control=getattr(frame,name);control.Reparent(parent);text=_row(parent,advanced,label,control)
        if name=='escape_angle':frame.angle_label=text
    frame.angle_mode=_combo(parent,list(ANGLE_MODES),'Pattern')
    frame.pair_mode=_combo(parent,list(PAIR_MODES),'Independent')
    _row(parent,advanced,'Direction reference',frame.angle_mode)
    _row(parent,advanced,'Pair handling',frame.pair_mode)
    for name,label,value in (('pad_filter','Pin numbers (wildcards)','*'),('connector_edge_margin','Beyond connector body (mm)','0.50'),('connector_clearance','Local connector clearance (mm; blank = unchanged)',''),('net_filter','Net names (wildcards)','*'),('launch_length','Straight launch (mm)','0.50'),('stagger_pitch','Row stagger (mm)','0.50'),('spread_pitch','Outer pitch (mm; 0 = auto)','0'),('adaptive_radius','Adaptive radius (mm)','3.0'),('adaptive_step','Adaptive search step (mm)','0.25'),('pair_gap','Pair edge gap (mm)','0.20'),('max_pair_skew','Maximum escape pair skew (mm)','0.10'),('width','Track width (mm)','0.20'),('length','Escape length (mm)','1.50'),('via_diameter','Via diameter (mm)','0.60'),('via_drill','Via drill (mm)','0.30'),('clearance','Copper clearance (mm)','0.20'),('angle_offset','Additional rotation (degrees)','0'),('offset_x','Endpoint X offset (mm)','0'),('offset_y','Endpoint Y offset (mm)','0')):
        if name in ('pad_filter','net_filter'):continue
        control=wx.TextCtrl(parent,value=value);setattr(frame,name,control);_row(parent,advanced,label,control)
    frame.escape_angle.SetToolTip('Custom-angle spread and straight + angled styles use this angle. Board and footprint direction modes use it as the absolute or relative direction.')
    frame.connector_clearance.SetToolTip('Optional scoped clearance in a separate exported review project. Live board Apply is disabled; source rules are preserved. Must respect fabrication minimums.')
    frame.pad_filter.SetToolTip('Comma-separated pin numbers or wildcards, combined with selected pads/footprints and net filters. Example: 1,2,5,1?.')
    frame.net_filter.SetToolTip('Comma-separated net-name wildcards; this combines with the selected scope and netclass.')
    frame.pair_gap.SetToolTip('Requested edge spacing on the parallel escape run. Terminal vias may flare for clearance.')
    frame.routing_mode.SetToolTip('Adaptive preserves existing copper and searches nearby short 45-degree escapes. Preview reports blocked or ambiguous existing routes. Fixed uses only the selected pattern.')
    frame.spread_pitch.SetToolTip('Perimeter pitch expansion: target center-to-center spacing. Zero fits existing pitch and track/via clearance; outer traces bend first. Not a BGA style.')
    frame.max_pair_skew.SetToolTip('Maximum difference between the two generated escape lengths; excludes existing routing.')
    frame.use_netclass_rules=wx.CheckBox(parent,label='Use netclass track / via dimensions')
    advanced.Add(frame.use_netclass_rules,0,wx.TOP|wx.BOTTOM,8)
    frame.add_vias=wx.CheckBox(parent,label='Add endpoint vias');frame.add_vias.SetValue(True);frame.add_vias.Disable()
    frame.add_vias.SetToolTip('Required by dogbone and via-in-pad. A source via connects traces placed on another layer.')
    advanced.Add(frame.add_vias,0,wx.TOP|wx.BOTTOM,8)
    note=wx.StaticText(parent,label='Families provide escape geometry aids, not protocol signoff. Check stackup, impedance and whole-route timing separately. Changing trace layer adds a source via; through vias span all copper layers.')
    note.Wrap(235);advanced.Add(note,0,wx.BOTTOM,8)
    for i,(label,width) in enumerate((('Footprint',80),('Pad',45),('Net',120),('Layer',70),('Result',220),('Length (mm)',95),('Pair',120),('Group',110))):frame.preview_list.InsertColumn(i,label,width=width)
    frame._settings_names=tuple(k for k in FanoutPlanner.defaults if k not in ('groups','unmatched'))
    for name in frame._settings_names:
        control=getattr(frame,name);event=wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_CHECKBOX if isinstance(control,wx.CheckBox) else wx.EVT_TEXT
        control.Bind(event,frame.on_config_changed)
    def load_defaults(_event):
        values=profile_defaults(frame.signal_profile.GetValue())
        for name,value in values.items():
            if name not in frame._settings_names:continue
            control=getattr(frame,name)
            if isinstance(control,wx.TextCtrl):control.ChangeValue(str(value))
            elif isinstance(control,wx.CheckBox):control.SetValue(bool(value))
            else:control.SetValue(str(value))
        frame.on_config_changed(None)
        frame.advanced.Expand();left.FitInside();frame.Layout()
        frame.status.SetLabel('Loaded suggestions. Review net filters, dimensions and pair handling, then preview.')
    load_profile.Bind(wx.EVT_BUTTON,load_defaults)
    frame.load_profile_button=load_profile
    drawing=frame.geometry_preview.GetParent();drawing_sizer=drawing.GetSizer()
    review_row=wx.BoxSizer(wx.HORIZONTAL)
    frame.review_mode=wx.Choice(drawing,choices=['Before · existing copper','After · proposed + existing'])
    frame.review_mode.SetSelection(1);frame.review_mode.Bind(wx.EVT_CHOICE,frame.on_review_mode)
    review_row.Add(frame.review_mode,0,wx.RIGHT,10)
    for color,label in (('#758d86','Existing'),('#087f98','Proposed')):
        swatch=wx.Panel(drawing,size=(12,12));swatch.SetBackgroundColour(color)
        review_row.Add(swatch,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
        review_row.Add(wx.StaticText(drawing,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
    drawing_sizer.Insert(1,review_row,0,wx.EXPAND|wx.BOTTOM,8)
    feedback=wx.BoxSizer(wx.HORIZONTAL)
    frame.preview_badge=wx.StaticText(panel,label='1 · SELECT TARGETS');frame.preview_badge.SetFont(frame.preview_badge.GetFont().Bold())
    frame.preview_counts=wx.StaticText(panel,label='No current candidates · choose scope and style')
    frame.preview_progress=wx.Gauge(panel,range=100,size=(100,12))
    frame.preview_cancel=wx.Button(panel,label='Cancel preview');frame.preview_cancel.Disable()
    frame.preview_cancel.Bind(wx.EVT_BUTTON,frame.cancel_preview)
    feedback.Add(frame.preview_badge,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
    feedback.Add(frame.preview_counts,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
    feedback.Add(frame.preview_progress,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
    feedback.Add(frame.preview_cancel)
    root.Add(feedback,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,16)
    _footer(frame,panel,root,help_callback)
    frame.preview_button.SetDefault()
    for button in (frame.preview_button,frame.commit_button,frame.preview_cancel,load_profile):decorate_button(button)
    frame._update_controls();left.FitInside()
    # Bind the full panel to the frame after adding feedback and footer controls.
    # A bare single-child auto-layout can retain the panel's earlier client size.
    frame_sizer=wx.BoxSizer(wx.VERTICAL);frame_sizer.Add(panel,1,wx.EXPAND)
    frame.SetSizer(frame_sizer);frame.Layout();panel.Layout()
    export_menu=frame._more_menu.Append(wx.ID_ANY,'Export local-rule review…')
    frame.Bind(wx.EVT_MENU,frame.export_connector_review,id=export_menu.GetId())
    def fit_actions(event):
        # The same export command remains in More on small displays.
        frame.export_button.Show(panel.GetClientSize().width>=1000)
        panel.Layout();event.Skip()
    panel.Bind(wx.EVT_SIZE,fit_actions)


def build_stitching(frame,api,help_callback):
    from .readable_choice import SearchableCheckListBox
    frame._routing_api=api
    panel,root,left,settings=_base(frame,'Via stitching')
    frame.mode=_combo(left,['Grid','Guard selected routes'],'Grid')
    _row(left,settings,'Placement mode',frame.mode)
    frame.net_choice=_combo(left,[],'');frame.pattern=_combo(left,['Square grid','Staggered grid'],'Square grid')
    frame.spacing=wx.TextCtrl(left,value='2.50')
    for label,control in (('Via net (ground / guard)',frame.net_choice),('Grid pattern',frame.pattern),('Via pitch (mm)',frame.spacing)):_row(left,settings,label,control)
    frame.net_choice.SetToolTip('All generated vias use this net. In guard mode it must differ from every selected signal net.')
    frame.guard_panel=wx.Panel(left);guard=wx.BoxSizer(wx.VERTICAL)
    frame.guard_panel.SetSizer(guard);settings.Add(frame.guard_panel,0,wx.EXPAND)
    class GuardNets(SearchableCheckListBox):
        def GetValue(self):return list(self.GetCheckedStrings())
    frame.guard_nets=GuardNets(frame.guard_panel,size=(-1,125))
    frame.guard_nets.SetToolTip('Choose exact signal nets. Ctrl+F opens wildcard/fuzzy search and multiple selection; hidden checked names remain selected.')
    _row(frame.guard_panel,guard,'Signal nets to guard (Ctrl+F to search)',frame.guard_nets)
    selected=wx.Button(frame.guard_panel,label='Use selected PCB tracks')
    selected.Bind(wx.EVT_BUTTON,frame.capture_guard_tracks);guard.Add(selected,0,wx.EXPAND|wx.BOTTOM,7)
    frame.guard_selection=wx.StaticText(frame.guard_panel,label='No captured tracks. Check signal nets above, or capture selected tracks.')
    frame.guard_selection.Wrap(260);guard.Add(frame.guard_selection,0,wx.EXPAND|wx.BOTTOM,7)
    frame.guard_side=_combo(frame.guard_panel,['Both','Left','Right'],'Both')
    frame.guard_offset=wx.TextCtrl(frame.guard_panel,value='1.00')
    _row(frame.guard_panel,guard,'Guard side',frame.guard_side)
    _row(frame.guard_panel,guard,'Track centre → via centre offset (mm)',frame.guard_offset)
    class CapturedTracks:
        def GetValue(self):return list(getattr(frame,'_guard_track_ids',()))
    frame.guard_tracks=CapturedTracks()
    frame.require_target_zone=wx.CheckBox(left,label='Stay inside filled target copper');frame.require_target_zone.SetValue(True)
    settings.Add(frame.require_target_zone,0,wx.TOP|wx.BOTTOM,8)
    frame.selection_status=wx.StaticText(left,label='Grid: choose a via net. Guard: choose signal routes and a separate ground net.');frame.selection_status.Wrap(260);settings.Add(frame.selection_status,0,wx.TOP|wx.BOTTOM,8)
    parent,advanced=_advanced(frame,left,settings)
    for name,label,value in (('diameter','Via diameter (mm)','0.60'),('drill','Via drill (mm)','0.30'),('clearance','Copper clearance (mm)','0.20'),('edge','Edge inset (mm)','1.00')):
        control=wx.TextCtrl(parent,value=value);setattr(frame,name,control);_row(parent,advanced,label,control)
    frame.guard_budget=wx.TextCtrl(parent,value='50000');_row(parent,advanced,'Guard candidate budget (max 50,000)',frame.guard_budget)
    frame.guard_timeout=wx.TextCtrl(parent,value='15');_row(parent,advanced,'Guard planning time budget (seconds)',frame.guard_timeout)
    frame.live_snapshot=wx.CheckBox(parent,label='Include unsaved PCB edits (slower snapshot)')
    frame.live_snapshot.SetToolTip('Default previews use the saved board in an isolated process. Enable this explicitly to serialize unsaved editor geometry; Apply always rejects stale or mismatched geometry.')
    advanced.Add(frame.live_snapshot,0,wx.EXPAND|wx.BOTTOM,8)
    frame.live_snapshot.Bind(wx.EVT_CHECKBOX,frame.on_config_changed)
    frame.density=_combo(parent,['Uniform','Dense perimeter / sparse interior','Dense selected area'],'Uniform');_row(parent,advanced,'Density',frame.density)
    frame.universal=wx.CheckBox(parent,label='Use full board bounds');frame.universal.SetValue(True);advanced.Add(frame.universal,0,wx.TOP|wx.BOTTOM,8)
    for name,label,value in (('x_min','X min (mm)','0'),('y_min','Y min (mm)','0'),('x_max','X max (mm)','100'),('y_max','Y max (mm)','100'),('skip_refs','Exclude footprint references','')):
        control=wx.TextCtrl(parent,value=value);setattr(frame,name,control);_row(parent,advanced,label,control)
    selection=wx.Button(parent,label='Use selected area');selection.Bind(wx.EVT_BUTTON,frame.use_selection_bounds);advanced.Add(selection,0,wx.EXPAND|wx.BOTTOM,8)
    for name,label in (('skip_parts','Avoid footprint bodies'),('skip_tracks','Avoid same-net tracks'),('skip_zones','Other-net zones (required)'),('skip_keepouts','Via keepouts (required)')):
        control=wx.CheckBox(parent,label=label);control.SetValue(True);setattr(frame,name,control);advanced.Add(control,0,wx.BOTTOM,8)
    frame.skip_zones.Disable();frame.skip_keepouts.Disable()
    frame.auto_refresh=wx.CheckBox(parent,label='Refresh when PCB selection changes');frame.auto_refresh.SetValue(False);advanced.Add(frame.auto_refresh,0,wx.BOTTOM,8)
    for i,(label,width) in enumerate((('#',55),('Net',130),('X (mm)',95),('Y (mm)',95),('Result',300))):frame.preview_list.InsertColumn(i,label,width=width)
    frame._settings_names=tuple(StitchingPlanner.defaults)
    frame._load_nets()
    frame.guard_nets.Set([name for name in frame.net_choice.GetStrings() if name!='<No net>'])
    if frame.net_choice.FindString('GND')!=wx.NOT_FOUND:frame.net_choice.SetValue('GND')
    for name in frame._settings_names:
        control=getattr(frame,name)
        if not isinstance(control,wx.Window):continue
        event=wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_CHECKLISTBOX if isinstance(control,wx.CheckListBox) else wx.EVT_CHECKBOX if isinstance(control,wx.CheckBox) else wx.EVT_TEXT
        control.Bind(event,frame.on_config_changed)
    _footer(frame,panel,root,help_callback)
    frame.cancel_button=wx.Button(panel,label='Cancel planning');frame.cancel_button.Disable()
    frame.cancel_button.Bind(wx.EVT_BUTTON,frame.cancel_planning)
    row=root.GetItem(root.GetItemCount()-1).GetSizer()
    row.Insert(row.GetItemCount()-2,frame.cancel_button,0,wx.RIGHT,8)
    frame._update_guard_controls();left.FitInside()


def choose_review_destination(frame):
    """Pick a new project basename; the fanout editor remains modeless."""
    from pathlib import Path
    with wx.FileDialog(frame, 'Export a new review project', wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb', style=wx.FD_SAVE) as dialog:
        return Path(dialog.GetPath()) if dialog.ShowModal()==wx.ID_OK else None
