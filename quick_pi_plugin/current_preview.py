"""Small, constant-cost before/after values for live current interaction."""
import math


FIELDS = {
    'voltage': ('Voltage', 'V'), 'drop': ('Voltage drop', 'mV'),
    'resistance': ('Drop / total demand', 'mΩ'), 'density': ('Current density', 'A/mm²'),
    'flow': ('Sheet current', 'A/mm'), 'loss': ('Local loss density', 'W/mm²'),
    'risk': ('Pulse / temperature limit', 'ratio'), 'melt': ('Pulse / melting action', 'ratio')}


def values(bundle, identity=None, sink=None):
    """Read one actual cell/barrel/electrode; missing support remains unknown."""
    result=bundle.get('result',{});mesh=bundle.get('mesh',{})
    out={key:None for key in FIELDS}
    out['current']=result.get('sink_current_A')
    out['total_loss']=result.get('total_power_W')
    if sink is not None and sink<len(result.get('sinks',[])):
        row=result['sinks'][sink];out['current']=row['current_A']
        out['voltage']=row['voltage_V'];out['drop']=row['voltage_drop_V']*1000
        total=result.get('sink_current_A',0)
        out['resistance']=out['drop']/total if total else None
    if identity is None:return out
    kind,index=identity;thermal={};density=None
    if kind=='sheet':
        triangle=mesh['triangles'][index];vector=result['cell_J_A_mm2'][index]
        if vector is None:return out
        density=math.hypot(*vector);out['density']=density
        out['flow']=math.hypot(*result['cell_sheet_current_A_mm'][index])
        a,b,c=[mesh['points_mm'][i] for i in triangle]
        area=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
        out['loss']=result['cell_power_W'][index]/area if area else None
        thermal=result['cell_thermal'][index]
        potential=[result['potential_V'][i] for i in triangle]
        if sink is None and all(v is not None for v in potential):
            out['voltage']=sum(potential)/3
            out['drop']=(result['source_voltage_V']-out['voltage'])*1000
            total=result.get('sink_current_A',0)
            out['resistance']=out['drop']/total if total else None
    elif kind=='via':
        row=next((v for v in result.get('vias',[]) if str(v['id'])==str(index)),None)
        if row is None:return out
        density=row.get('current_density_A_mm2');out['density']=density
        thermal=row.get('thermal',{})
    out['risk']=thermal.get('energy_ratio')
    model=result.get('fusing',{})
    if density is not None and model.get('status')=='available' and model.get('pulse_duration_s') is not None:
        out['melt']=density**2*model['pulse_duration_s']/model['melt_action_A2s_mm4']
    return out


def comparison(before,after,metric,identity=None,sink=None,all_fields=False,pending_current=None):
    """Return label/unit/old/new rows; pending physics never becomes a number."""
    old=values(before,identity,sink)
    new=values(after,identity,sink) if after is not None else {}
    if pending_current is not None:new['current']=pending_current
    keys=['current',*(FIELDS if all_fields else [metric])]
    if all_fields:keys.append('total_loss')
    labels={**FIELDS,'current':('Sink current' if sink is not None else 'Total current','A'),
            'total_loss':('Whole-model loss','W')}
    return [dict(key=key,label=labels[key][0],unit=labels[key][1],before=old.get(key),after=new.get(key)) for key in keys]


def text(value):
    return 'Unknown' if value is None or not math.isfinite(value) else f'{value:.6g}'


def popup(parent):
    """Create the native non-activating readout lazily; no wx import in maths."""
    import wx
    class Preview(wx.PopupWindow):
        def __init__(self):
            super().__init__(parent,flags=wx.BORDER_SIMPLE)
            self.SetBackgroundColour('#f5f9fb');self.rows=[]
            self.root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(self.root)
            self.timer=wx.Timer(self);self.Bind(wx.EVT_TIMER,lambda e:self.Hide(),self.timer)
            self.Bind(wx.EVT_LEFT_DOWN,lambda e:self.Hide())
        def present(self,position,rows,pending=False):
            self.rows=rows;self.root.Clear(True)
            title=wx.StaticText(self,label='Current preview · '+('computing fields…' if pending else 'before → after'))
            title.SetFont(title.GetFont().Bold());self.root.Add(title,0,wx.ALL,6)
            grid=wx.FlexGridSizer(cols=4,hgap=10,vgap=3)
            for label in ('Parameter','Before','After','Change'):
                item=wx.StaticText(self,label=label);item.SetFont(item.GetFont().Bold());grid.Add(item)
            for row in rows:
                a,b=row['before'],row['after'];delta=None if a is None or b is None else b-a
                labels=(row['label']+' · '+row['unit'],text(a),('…' if pending and b is None else text(b)),
                        '—' if delta is None else f'{delta:+.4g}')
                for col,label in enumerate(labels):
                    item=wx.StaticText(self,label=label)
                    if col>=2 and delta is not None and delta!=0:item.SetForegroundColour('#974800' if delta>0 else '#146a95')
                    grid.Add(item,0)
            self.root.Add(grid,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,6);self.Fit()
            x,y=position;size=self.GetSize();area=wx.Display(wx.Display.GetFromPoint(wx.Point(x,y))).GetClientArea() if wx.Display.GetFromPoint(wx.Point(x,y))!=wx.NOT_FOUND else wx.GetClientDisplayRect()
            self.Position(wx.Point(min(x+18,area.GetRight()-size.width),min(y+18,area.GetBottom()-size.height)),(0,0))
            self.Show(True);self.timer.StartOnce(3500)
    return Preview()
