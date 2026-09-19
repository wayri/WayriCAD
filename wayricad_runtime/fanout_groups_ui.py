"""Compact ordered rule editor for the shared fanout planner."""
from copy import deepcopy
import wx
from .fanout_groups import GROUP_CONTROL_FIELDS, validate_groups
from .fanout_profiles import FANOUT_PATTERNS, SIGNAL_PROFILES, ANGLE_MODES, PAIR_MODES
from .routing import FanoutPlanner, copper_layer_names, netclass_names


def edit_rule(parent, board, rule):
    dialog=wx.Dialog(parent,title='Fanout group',size=(570,680),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    outer=wx.BoxSizer(wx.VERTICAL)
    scroll=wx.ScrolledWindow(dialog);scroll.SetScrollRate(0,12)
    form=wx.FlexGridSizer(cols=2,hgap=10,vgap=8);form.AddGrowableCol(1)
    controls={}
    def row(key,label,value,choices=None):
        control=wx.ComboBox(scroll,value=value,choices=choices,style=wx.CB_READONLY) if choices is not None else wx.TextCtrl(scroll,value=value)
        form.Add(wx.StaticText(scroll,label=label),0,wx.ALIGN_CENTER_VERTICAL)
        form.Add(control,1,wx.EXPAND);controls[key]=control
    row('name','Group name',rule.get('name',''))
    match=rule.get('match',{})
    for key,label in [('net','Net names'),('ref','References'),('pad','Pad numbers')]:row('match_'+key,label,match.get(key,'*'))
    row('match_netclass','Netclass',match.get('netclass','All netclasses'),['All netclasses']+netclass_names(board))
    note=wx.StaticText(scroll,label='Selectors combine. Use comma-separated wildcards. First matching group wins.\nBlank overrides inherit the main settings. Dimensions are millimetres.')
    note.Wrap(470)
    content=wx.BoxSizer(wx.VERTICAL);content.Add(form,0,wx.EXPAND|wx.ALL,12);content.Add(note,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
    overrides=wx.FlexGridSizer(cols=2,hgap=10,vgap=8);overrides.AddGrowableCol(1)
    # Reuse the row builder with this grid for the complete existing vocabulary.
    form=overrides
    enums={'routing_mode':['Fixed','Adaptive'],'pattern':list(FANOUT_PATTERNS)+['Via-in-pad'],'output_mode':['Escape traces','Via-in-pad'],
           'escape_layer':['Pad layer']+copper_layer_names(board),'signal_profile':list(SIGNAL_PROFILES),
           'angle_mode':list(ANGLE_MODES),'pair_mode':list(PAIR_MODES)}
    keys=['output_mode','pattern','escape_layer','escape_angle','width','length','via_diameter','via_drill','clearance']
    keys += [key for key in FanoutPlanner.defaults if key not in GROUP_CONTROL_FIELDS and key not in keys]
    labels={'pattern':'Fanout style','output_mode':'Output','escape_layer':'Trace layer','escape_angle':'Angle (degrees)'}
    for key in keys:
        value=rule.get('settings',{}).get(key,'')
        choices=['']+enums[key] if key in enums else ['', 'Yes','No'] if isinstance(FanoutPlanner.defaults[key],bool) else None
        if isinstance(value,bool):value='Yes' if value else 'No'
        row(key,labels.get(key,key.replace('_',' ').capitalize()),str(value),choices)
    content.Add(overrides,0,wx.EXPAND|wx.ALL,12);scroll.SetSizer(content);scroll.FitInside()
    outer.Add(scroll,1,wx.EXPAND);outer.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.EXPAND|wx.ALL,10);dialog.SetSizer(outer)
    try:
        while dialog.ShowModal()==wx.ID_OK:
            try:
                result={'name':controls['name'].GetValue().strip(),'match':{},'settings':{}}
                for key in ('net','ref','pad','netclass'):result['match'][key]=controls['match_'+key].GetValue().strip()
                for key in keys:
                    value=controls[key].GetValue().strip()
                    if not value:continue
                    default=FanoutPlanner.defaults[key]
                    result['settings'][key]=(value=='Yes') if isinstance(default,bool) else float(value) if isinstance(default,(float,int)) else value
                validate_groups([result],'defaults',FanoutPlanner.defaults)
                return result
            except ValueError as exc:wx.MessageBox(str(exc),'Invalid fanout group',wx.OK|wx.ICON_ERROR,dialog)
        return None
    finally:dialog.Destroy()


def manage_groups(frame):
    rules=deepcopy(frame.fanout_groups)
    dialog=wx.Dialog(frame,title='Fanout groups — first match wins',size=(790,430),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    root=wx.BoxSizer(wx.VERTICAL)
    note=wx.StaticText(dialog,label='Groups apply inside the main pad scope, net and netclass filters. Reorder to change precedence.')
    root.Add(note,0,wx.ALL,10)
    table=wx.ListCtrl(dialog,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
    for i,(label,width) in enumerate([('Group',130),('Nets / class',170),('Ref / pad',130),('Overrides',290)]):table.InsertColumn(i,label,width=width)
    root.Add(table,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
    def refresh(selected=-1):
        table.DeleteAllItems()
        for i,rule in enumerate(rules):
            table.InsertItem(i,rule['name']);m=rule.get('match',{});s=rule.get('settings',{})
            table.SetItem(i,1,m.get('net','*')+' / '+m.get('netclass','All netclasses'))
            table.SetItem(i,2,m.get('ref','*')+' / '+m.get('pad','*'))
            table.SetItem(i,3,', '.join(k.replace('_',' ')+'='+str(v) for k,v in s.items()) or 'Main settings')
        if 0<=selected<len(rules):table.Select(selected)
    def action(kind):
        index=table.GetFirstSelected()
        if kind=='add':
            result=edit_rule(dialog,frame.board,{'name':'Group '+str(len(rules)+1)})
            if result:rules.append(result);index=len(rules)-1
        elif index>=0:
            if kind=='edit':
                result=edit_rule(dialog,frame.board,rules[index])
                if result:rules[index]=result
            elif kind=='remove':rules.pop(index)
            elif kind in ('up','down'):
                other=index+(-1 if kind=='up' else 1)
                if 0<=other<len(rules):rules[index],rules[other]=rules[other],rules[index];index=other
        refresh(index)
    buttons=wx.BoxSizer(wx.HORIZONTAL)
    for kind,label in [('add','Add'),('edit','Edit'),('remove','Remove'),('up','Move up'),('down','Move down')]:
        button=wx.Button(dialog,label=label);button.Bind(wx.EVT_BUTTON,lambda e,k=kind:action(k));buttons.Add(button,0,wx.RIGHT,5)
    table.Bind(wx.EVT_LIST_ITEM_ACTIVATED,lambda e:action('edit'));root.Add(buttons,0,wx.ALL,10)
    unmatched=wx.ComboBox(dialog,value=frame.group_unmatched,choices=['defaults','skip','error'],style=wx.CB_READONLY)
    row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(dialog,label='Unmatched pads'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10);row.Add(unmatched,1);root.Add(row,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
    root.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.EXPAND|wx.ALL,10);dialog.SetSizer(root);refresh()
    try:
        while dialog.ShowModal()==wx.ID_OK:
            try:validate_groups(rules,unmatched.GetValue(),FanoutPlanner.defaults)
            except ValueError as exc:wx.MessageBox(str(exc),'Invalid groups',wx.OK|wx.ICON_ERROR,dialog);continue
            frame.fanout_groups=rules;frame.group_unmatched=unmatched.GetValue()
            frame.group_summary.SetLabel(f'{len(rules)} groups; unmatched: {frame.group_unmatched}')
            frame.on_config_changed(None);return
    finally:dialog.Destroy()
