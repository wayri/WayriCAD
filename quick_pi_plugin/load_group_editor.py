"""Native Quick PI editor for independent physical load pad groups."""
import wx
from wayricad_runtime.readable_choice import ReadableChoice


def edit_load_groups(frame, unit_ids, load_values):
    """Edit a primary pad group and independent additional current or power loads."""
    if frame._busy or frame._series_request:return
    from .pin_units import peers,unit,validate_units
    from .terminals import pad_names
    from .sink_groups import choose_pads, group_caption, ordered_pads, reserved_pads
    dialog=wx.Dialog(frame,title='Quick PI · Load pad groups',size=(820,490),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    rows=[dict(row) for row in frame._extra_sinks];labels={row['id']:row.get('label',row['id']) for row in frame._terminals}
    layout=wx.BoxSizer(wx.VERTICAL)
    source_ids=unit_ids(frame,'source')
    primary_before=unit_ids(frame,'sink')
    primary=list(primary_before)
    terminals=list(frame._terminals)
    supported=(hasattr(frame,'model_dimension') and frame.model_dimension.GetSelection()==0
               and frame.load_mode.GetSelection() in (0,2) and not getattr(frame,'_package_conduction',[]))
    heading=wx.WrapSizer(wx.HORIZONTAL)
    primary_button=wx.Button(dialog,label='Primary sink pads…')
    primary_button.Enable(supported and bool(primary))
    primary_summary=wx.StaticText(dialog,label=group_caption(primary,labels))
    primary_summary.SetToolTip(', '.join(labels.get(i,i) for i in primary))
    heading.Add(primary_button,0,wx.RIGHT,8)
    heading.Add(primary_summary,0,wx.ALIGN_CENTER_VERTICAL)
    layout.Add(heading,0,wx.EXPAND|wx.ALL,10)
    layout.Add(wx.StaticText(dialog,label='Each load draws the entered total across its own pads.'),0,wx.LEFT|wx.BOTTOM,10)
    table=wx.ListCtrl(dialog,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
    for index,(name,width) in enumerate([('Pad',210),('Demand A / W',130),('Min V',110),('Max V',110)]):table.InsertColumn(index,name,width=width)
    layout.Add(table,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
    grid=wx.FlexGridSizer(2,5,6,10)
    for name in ('Sink pad','Load kind','Demand A / W','Minimum V (blank = 0)','Maximum V (blank = none)'):grid.Add(wx.StaticText(dialog,label=name))
    pad=ReadableChoice(dialog,choices=[labels[row['id']] for row in frame._terminals]);current=wx.TextCtrl(dialog,value='1')
    kind=ReadableChoice(dialog,choices=['Current · A','Constant power · W']);kind.SetSelection(0)
    minimum=wx.TextCtrl(dialog);minimum.SetHint('0 V');maximum=wx.TextCtrl(dialog);maximum.SetHint('Unbounded')
    for control in (pad,kind,current,minimum,maximum):grid.Add(control,1,wx.EXPAND)
    for column in range(5):grid.AddGrowableCol(column)
    layout.Add(grid,0,wx.EXPAND|wx.ALL,10)
    include=wx.CheckBox(dialog,label='Include other same-net pins');include.Hide()
    layout.Add(include,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
    peer_ids=[]
    custom=None
    group_row=wx.WrapSizer(wx.HORIZONTAL)
    choose=wx.Button(dialog,label='Choose pads…')
    group_row.Add(choose,0,wx.RIGHT,8)
    picked=wx.StaticText(dialog)
    group_row.Add(picked,0,wx.ALIGN_CENTER_VERTICAL)
    layout.Add(group_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
    def recommend():
        index=table.GetFirstSelected();choice=pad.GetSelection()
        blocked=reserved_pads(source_ids,primary,rows,editing=index)
        available=peers(terminals,terminals[choice]['id'],blocked) if choice>=0 and supported else []
        choose.Enable(supported)
        picked.SetLabel(group_caption(custom or [],labels))
        picked.SetToolTip(', '.join(labels.get(i,i) for i in custom or []))
        peer_ids[:]=[row['id'] for row in available]
        include.SetLabel(f'Include {len(available)} other same-net pin'+('s' if len(available)!=1 else ''))
        include.Show(bool(available))
        if not available:include.SetValue(False)
        include.SetToolTip('Also include '+', '.join(row.get('label',row['id']) for row in available)+
                           '. The entered current is the TOTAL across these ideal equipotential pins.')
        dialog.Layout()
    def pad_changed(event):
        nonlocal custom
        custom=None
        include.SetValue(False);recommend()
    def all_changed(event):
        nonlocal custom
        custom=None
        recommend()
    include.Bind(wx.EVT_CHECKBOX,all_changed)
    pad.Bind(wx.EVT_CHOICE,pad_changed)
    message=wx.StaticText(dialog,label='Select a row to edit it, or choose a pad and add a new sink.');layout.Add(message,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
    buttons=wx.BoxSizer(wx.HORIZONTAL)
    add=wx.Button(dialog,label='Add sink');update=wx.Button(dialog,label='Update selected');remove=wx.Button(dialog,label='Remove selected')
    for button in (add,update,remove):buttons.Add(button,0,wx.RIGHT,8)
    layout.Add(buttons,0,wx.ALL,10);layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
    def pick_group(event, primary_group=False):
        nonlocal custom,primary
        try:
            if primary_group:
                blocked=reserved_pads(source_ids,(),rows)
                new=choose_pads(dialog,terminals,primary,blocked,primary[0] if primary else None)
                if new is not None:
                    primary=new
                    primary_summary.SetLabel(group_caption(primary,labels))
                    primary_summary.SetToolTip(', '.join(labels.get(i,i) for i in primary))
            else:
                choice=pad.GetSelection()
                identifier=terminals[choice]['id'] if choice>=0 else None
                checked=custom if custom is not None else ([identifier] if identifier else [])+(peer_ids if include.GetValue() else [])
                blocked=reserved_pads(source_ids,primary,rows,editing=table.GetFirstSelected())
                new=choose_pads(dialog,terminals,checked,blocked,identifier)
                if new is not None:
                    custom=new
                    pad.SetSelection(next(i for i,t in enumerate(terminals) if t['id']==new[0]))
                    include.SetValue(False)
                    message.SetLabel('Pads selected. Choose Add sink or Update selected to store this group.')
            recommend()
        except ValueError as exc:
            message.SetLabel(str(exc));dialog.Layout()
    primary_button.Bind(wx.EVT_BUTTON,lambda event:pick_group(event,True))
    choose.Bind(wx.EVT_BUTTON,pick_group)
    def refresh():
        table.DeleteAllItems()
        for row in rows:
            label=', '.join(labels.get(i,i) for i in pad_names(row))
            index=table.InsertItem(table.GetItemCount(),label)
            demand='power_W' if 'power_W' in row else 'current_A'
            table.SetItem(index,1,str(row[demand])+(' W' if demand=='power_W' else ' A'))
            for column,key in enumerate(('min_voltage_V','max_voltage_V'),2):
                table.SetItem(index,column,str(row.get(key,0 if key=='min_voltage_V' else 'Unbounded')))
    def selected(event):
        nonlocal custom
        if not 0<=event.GetIndex()<len(rows):return
        row=rows[event.GetIndex()]
        custom=pad_names(row)
        index=next((i for i,item in enumerate(terminals) if item['id']==custom[0]),-1)
        pad.SetSelection(index);kind.SetSelection(1 if 'power_W' in row else 0);current.ChangeValue(str(row.get('power_W',row.get('current_A'))));minimum.ChangeValue(str(row.get('min_voltage_V','')));maximum.ChangeValue(str(row.get('max_voltage_V','')))
        recommend();include.SetValue(False)
    def save(edit=False):
        nonlocal custom
        try:
            choice=pad.GetSelection();index=table.GetFirstSelected() if edit else -1
            if choice<0:raise ValueError('Choose a sink pad.')
            if edit and index<0:raise ValueError('Select a row to update.')
            identifier=terminals[choice]['id']
            wanted=custom if custom is not None else [identifier]+(peer_ids if include.GetValue() else [])
            ids=ordered_pads(wanted,identifier,terminals,reserved_pads(source_ids,primary,rows,editing=index))
            row=unit(load_values(ids[0],current.GetValue(),minimum.GetValue(),maximum.GetValue(),power=kind.GetSelection()==1),ids[1:])
            if edit:
                for key in ('id','label'):
                    if key in rows[index]:row[key]=rows[index][key]
                rows[index]=row
            else:rows.append(row)
            custom=None
            refresh();include.SetValue(False);recommend();message.SetLabel('Sink demand updated. Apply with OK.');dialog.Layout()
        except ValueError as exc:message.SetLabel(str(exc));dialog.Layout()
    def delete(event):
        nonlocal custom
        index=table.GetFirstSelected()
        if index>=0:
            rows.pop(index);custom=None
            refresh();include.SetValue(False);recommend()
    add.Bind(wx.EVT_BUTTON,lambda event:save());update.Bind(wx.EVT_BUTTON,lambda event:save(True));remove.Bind(wx.EVT_BUTTON,delete)
    table.Bind(wx.EVT_LIST_ITEM_SELECTED,selected);refresh();recommend()
    try:
        if dialog.ShowModal()==wx.ID_OK:
            if (unit_ids(frame,'source')!=source_ids or unit_ids(frame,'sink')!=primary_before
                    or {t['id'] for t in frame._terminals}!={t['id'] for t in terminals}):
                frame.status.SetLabel('The active endpoints changed. Reopen load pad groups to review the current setup.')
                return
            try:
                validate_units(source_ids,([{'terminals':primary}] if primary else [])+rows)
            except ValueError as exc:
                frame.status.SetLabel('Load groups were not applied. '+str(exc))
                return
            frame._extra_sinks=rows
            if primary!=primary_before:frame._set_primary_sink_pads(primary)
            frame.loads_button.SetLabel(f'Additional sinks ({len(rows)})…');frame._invalidate()
    finally:
        dialog.Destroy()
