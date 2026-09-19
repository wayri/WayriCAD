"""Compact local routing forms: primary choices first, detailed controls on demand."""
import wx
from .preview import GeometryPreview
from .routing import FanoutPlanner, StitchingPlanner, netclass_names, copper_layer_names
from .fanout_profiles import FANOUT_PATTERNS, SIGNAL_PROFILES, ANGLE_MODES, PAIR_MODES, profile_defaults


def _combo(parent, choices, value):
    control=wx.ComboBox(parent,choices=choices,style=wx.CB_READONLY)
    control.SetValue(value);return control


def _row(parent,sizer,label,control):
    text=wx.StaticText(parent,label=label)
    sizer.Add(text,0,wx.TOP|wx.BOTTOM,5)
    sizer.Add(control,0,wx.EXPAND|wx.BOTTOM,7)
    return text


def _base(frame,title):
    panel=wx.Panel(frame);root=wx.BoxSizer(wx.VERTICAL);workspace=wx.BoxSizer(wx.HORIZONTAL)
    left=wx.ScrolledWindow(panel,style=wx.VSCROLL);left.SetScrollRate(0,12);left.SetMinSize((280,-1))
    settings=wx.BoxSizer(wx.VERTICAL)
    heading=wx.StaticText(left,label=title);heading.SetFont(heading.GetFont().Bold())
    settings.Add(heading,0,wx.BOTTOM,12)
    right=wx.Panel(panel);preview=wx.BoxSizer(wx.VERTICAL)
    bar=wx.BoxSizer(wx.HORIZONTAL);label=wx.StaticText(right,label='Board preview')
    label.SetFont(label.GetFont().Bold());bar.Add(label,1,wx.ALIGN_CENTER_VERTICAL)
    grid=wx.CheckBox(right,label='Grid');bar.Add(grid,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
    fit=wx.Button(right,label='Fit',size=(58,-1));bar.Add(fit,0)
    preview.Add(bar,0,wx.EXPAND|wx.BOTTOM,8)
    frame.geometry_preview=GeometryPreview(right,'Choose pads or a net, then click Preview.')
    frame.geometry_preview.set_board(frame.board,frame._routing_api)
    grid.Bind(wx.EVT_CHECKBOX,lambda event:(setattr(frame.geometry_preview,'show_grid',grid.GetValue()),frame.geometry_preview.Refresh()))
    fit.Bind(wx.EVT_BUTTON,frame.geometry_preview.fit)
    preview.Add(frame.geometry_preview,1,wx.EXPAND)
    details=wx.CollapsiblePane(right,label='Candidate details and rejected items')
    detail_sizer=wx.BoxSizer(wx.VERTICAL)
    frame.preview_list=wx.ListCtrl(details.GetPane(),style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
    frame.preview_list.SetMinSize((-1,150));detail_sizer.Add(frame.preview_list,1,wx.EXPAND)
    details.GetPane().SetSizer(detail_sizer);details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:frame.Layout())
    frame.preview_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,frame.on_preview_row_activated)
    preview.Add(details,0,wx.EXPAND|wx.TOP,8)
    right.SetSizer(preview);workspace.Add(left,0,wx.EXPAND|wx.RIGHT,18);workspace.Add(right,1,wx.EXPAND)
    root.Add(workspace,1,wx.EXPAND|wx.ALL,16)
    frame.status=wx.StaticText(panel,label='Preview changes before applying them to the board.')
    root.Add(frame.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
    left.SetSizer(settings);panel.SetSizer(root)
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
    row.Add(more,0,wx.LEFT,8);row.AddStretchSpacer()
    preview=wx.Button(panel,label='Preview',size=(100,-1));preview.Bind(wx.EVT_BUTTON,frame.preview);row.Add(preview,0,wx.RIGHT,8)
    frame.commit_button=wx.Button(panel,label='Apply to board',size=(128,-1));frame.commit_button.Disable()
    frame.commit_button.Bind(wx.EVT_BUTTON,frame.generate);frame.commit_button.SetDefault();row.Add(frame.commit_button,0)
    root.Add(row,0,wx.EXPAND|wx.ALL,16)


def build_fanout(frame,api,help_callback):
    frame._routing_api=api
    panel,root,left,settings=_base(frame,'Fanout')
    frame.scope=_combo(left,['Selected pads','Selected footprints','Reference wildcard','All SMD pads'],'Selected footprints')
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
    _row(left,settings,'Signal family',profile_row)
    for label,control in (('Pads to fan out',frame.scope),('Netclass',frame.netclass_filter),('Output',frame.output_mode),('Fanout style',frame.pattern),('Routing',frame.routing_mode),('Angle (degrees)',frame.escape_angle),('Trace layer',frame.escape_layer)):
        text=_row(left,settings,label,control)
        if control is frame.escape_angle:frame.angle_label=text
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
    parent,advanced=_advanced(frame,left,settings)
    frame.angle_mode=_combo(parent,list(ANGLE_MODES),'Pattern')
    frame.pair_mode=_combo(parent,list(PAIR_MODES),'Independent')
    _row(parent,advanced,'Direction reference',frame.angle_mode)
    _row(parent,advanced,'Pair handling',frame.pair_mode)
    for name,label,value in (('net_filter','Net names (wildcards)','*'),('ref','Reference wildcard','*'),('launch_length','Straight launch (mm)','0.50'),('stagger_pitch','Row stagger (mm)','0.50'),('spread_pitch','Outer pitch (mm; 0 = auto)','0'),('adaptive_radius','Adaptive radius (mm)','3.0'),('adaptive_step','Adaptive search step (mm)','0.25'),('pair_gap','Pair edge gap (mm)','0.20'),('max_pair_skew','Maximum escape pair skew (mm)','0.10'),('width','Track width (mm)','0.20'),('length','Escape length (mm)','1.50'),('via_diameter','Via diameter (mm)','0.60'),('via_drill','Via drill (mm)','0.30'),('clearance','Copper clearance (mm)','0.20'),('angle_offset','Additional rotation (degrees)','0'),('offset_x','Endpoint X offset (mm)','0'),('offset_y','Endpoint Y offset (mm)','0')):
        control=wx.TextCtrl(parent,value=value);setattr(frame,name,control);_row(parent,advanced,label,control)
    frame.escape_angle.SetToolTip('Custom-angle spread and straight + angled styles use this angle. Board and footprint direction modes use it as the absolute or relative direction.')
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
    frame.auto_refresh=wx.CheckBox(parent,label='Refresh when PCB selection changes');frame.auto_refresh.SetValue(False);advanced.Add(frame.auto_refresh,0,wx.BOTTOM,8)
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
    _footer(frame,panel,root,help_callback);frame._update_controls();left.FitInside()


def build_stitching(frame,api,help_callback):
    frame._routing_api=api
    panel,root,left,settings=_base(frame,'Via stitching')
    frame.net_choice=_combo(left,[],'');frame.pattern=_combo(left,['Square grid','Staggered grid'],'Square grid')
    frame.spacing=wx.TextCtrl(left,value='2.50')
    for label,control in (('Net',frame.net_choice),('Pattern',frame.pattern),('Spacing (mm)',frame.spacing)):_row(left,settings,label,control)
    frame.require_target_zone=wx.CheckBox(left,label='Stay inside filled target copper');frame.require_target_zone.SetValue(True)
    settings.Add(frame.require_target_zone,0,wx.TOP|wx.BOTTOM,8)
    frame.selection_status=wx.StaticText(left,label='Choose a net, then preview the grid.');frame.selection_status.Wrap(250);settings.Add(frame.selection_status,0,wx.TOP|wx.BOTTOM,8)
    parent,advanced=_advanced(frame,left,settings)
    for name,label,value in (('diameter','Via diameter (mm)','0.60'),('drill','Via drill (mm)','0.30'),('clearance','Copper clearance (mm)','0.20'),('edge','Edge inset (mm)','1.00')):
        control=wx.TextCtrl(parent,value=value);setattr(frame,name,control);_row(parent,advanced,label,control)
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
    if frame.net_choice.FindString('GND')!=wx.NOT_FOUND:frame.net_choice.SetValue('GND')
    for name in frame._settings_names:
        control=getattr(frame,name);event=wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_CHECKBOX if isinstance(control,wx.CheckBox) else wx.EVT_TEXT
        control.Bind(event,frame.on_config_changed)
    _footer(frame,panel,root,help_callback);left.FitInside()
