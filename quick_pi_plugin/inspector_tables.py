"""Small sortable inspector tables; row metadata keeps native/mesh identities."""
from __future__ import annotations
import math

try:
    import wx
except ImportError:
    wx=None


def display(value):
    if value is None:return 'Unknown'
    if isinstance(value,float):return f'{value:.6g}' if math.isfinite(value) else 'Unknown'
    return str(value)


def sorted_rows(rows,column,ascending=True):
    known=[];unknown=[]
    for row in rows:
        value=row['cells'][column]
        (unknown if value is None or isinstance(value,float) and not math.isfinite(value) else known).append(row)
    def key(row):
        value=row['cells'][column]
        if isinstance(value,(int,float)):return 0,value
        return 1,str(value).casefold()
    return sorted(known,key=key,reverse=not ascending)+unknown


class InspectorTable(wx.ListCtrl if wx else object):
    """Native draggable columns, numeric sorting and identity-safe selection."""
    def __init__(self,parent,columns,on_select,*,fit_columns=False):
        if wx is None:raise RuntimeError('Native wxPython is required for inspector tables.')
        super().__init__(parent,style=wx.LC_REPORT|wx.LC_SINGLE_SEL|wx.BORDER_SIMPLE)
        self.SetMinSize((1,85));self.rows=[];self._callback=on_select
        self._updating=False;self.sort_column=None;self.ascending=True;self._titles=[title for title,_ in columns]
        self._fit_columns=fit_columns;self._manual_columns=False
        for index,(title,width) in enumerate(columns):self.InsertColumn(index,title,width=width)
        self.SetToolTip('Click a column heading to sort. Drag column borders to resize; scroll horizontally for additional columns. Select a row to focus its copper result.')
        self.Bind(wx.EVT_LIST_COL_CLICK,self._column_clicked)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED,self._selected)
        self.Bind(wx.EVT_LIST_COL_END_DRAG,self._column_resized)
        self.Bind(wx.EVT_SIZE,self._resized)
        self.Bind(wx.EVT_MOTION,self._hover)

    def _column_resized(self,event):self._manual_columns=True;event.Skip()

    def _resized(self,event):
        if self._fit_columns and not self._manual_columns and self.GetColumnCount()==3:
            # Retain readable numbers and units; native horizontal scrolling
            # exposes overflow when the inspector is narrower than its columns.
            width=max(290,self.GetClientSize().width-5);label=max(120,round(width*.44));unit=60
            for i,size in enumerate((label,width-label-unit,unit)):
                if self.GetColumnWidth(i)!=size:self.SetColumnWidth(i,size)
        event.Skip()

    def _hover(self,event):
        index,_=self.HitTest(event.GetPosition())
        if 0<=index<len(self.rows):self.SetToolTip(' · '.join(display(value) for value in self.rows[index]['cells']))
        event.Skip()

    def set_rows(self,rows):
        top=self.GetTopItem() if self.GetItemCount() else 0
        self.rows=list(rows)
        if self.sort_column is not None:self.rows=sorted_rows(self.rows,self.sort_column,self.ascending)
        self._updating=True;self.Freeze()
        try:
            self.DeleteAllItems()
            for row in self.rows:
                index=self.InsertItem(self.GetItemCount(),display(row['cells'][0]))
                for column,value in enumerate(row['cells'][1:],1):self.SetItem(index,column,display(value))
            if self.rows:self.EnsureVisible(min(top,len(self.rows)-1))
        finally:self.Thaw();self._updating=False

    def _column_clicked(self,event):
        column=event.GetColumn()
        self.ascending=not self.ascending if self.sort_column==column else True
        self.sort_column=column
        for index,title in enumerate(self._titles):
            item=self.GetColumn(index);item.SetText(title+(' ↑' if self.ascending else ' ↓') if index==column else title);self.SetColumn(index,item)
        self.set_rows(self.rows)

    def _selected(self,event):
        index=event.GetIndex()
        if not self._updating and 0<=index<len(self.rows):self._callback(self.rows[index])


def loss_rows(result):
    analysis=result.get('analytics',{});losses=analysis.get('losses',{})
    rows=[]
    for key,label in [('planar_W','All sheets'),('via_W','Via barrels'),('component_W','Components'),('package_W','Package contacts'),('total_W','Total modeled loss'),('accounting_error_W','Accounting error')]:
        if key in losses:rows.append({'cells':(label,losses[key],'','',''),'target':None})
    peaks=analysis.get('hotspots_by_current_density',[])
    for layer in analysis.get('layers',[]):
        target=next((row for row in peaks if row['kind']=='sheet' and str(row['layer'])==str(layer['layer'])),None)
        # A layer peak may not survive the global heap. Defer its containing-cell
        # lookup until clicked instead of rescanning all mesh cells on every
        # live-current refresh. A centroid is evidence, never a native UUID.
        if target is None and layer.get('peak_location_mm') is not None:
            target={'kind':'point','layer':layer['layer'],'location_mm':layer['peak_location_mm']}
        lo=layer['thickness_min_mm']*1000;hi=layer['thickness_max_mm']*1000
        thickness=lo if lo==hi else f'{lo:.5g}–{hi:.5g}'
        rows.append({'cells':(layer['name'],layer['planar_power_W'],layer['area_mm2'],layer['peak_current_density_A_mm2'],thickness),
                     'target':target,'metric':'loss','layer':layer['layer']})
    return rows


def heating_rows(result):
    return [{'cells':(f"{row['rank']}. {row['kind']} {row['id']}",row['layer_name'],row['current_density_A_mm2'],row['power_density_W_mm3']),
             'target':row,'metric':'loss'} for row in result.get('analytics',{}).get('hotspots_by_heating_density',[])]


def probe_rows(bundle,record):
    if not record:return [{'cells':('Selection','Click solved copper or a ranked row',''),'target':None}]
    rows=[]
    def add(label,value,unit='',metric=None):
        rows.append({'cells':(label,value,unit),'target':record,'metric':metric})
    add('Copper',record.get('kind'));add('Cell / barrel ID',record.get('id'));add('Layer',record.get('layer_name'))
    for axis,value in zip('XYZ',record.get('location_mm') or []):add(axis,value,'mm')
    add('Displayed result',record.get('value'),record.get('unit',''),record.get('metric'))
    add('Current density',record.get('current_density_A_mm2'),'A/mm²','density')
    add('Cell / barrel loss',record.get('power_W'),'W','loss')
    if record.get('kind')=='via':
        add('Barrel current',record.get('current_A'),'A','density')
        add('Barrel resistance',None if record.get('resistance_ohm') is None else record['resistance_ohm']*1000,'mΩ')
    if record.get('kind')=='sheet':
        mesh=bundle.get('mesh',{});result=bundle.get('result',{});i=int(record['id'])
        if i<len(mesh.get('triangles',[])):
            potentials=[result['potential_V'][n] for n in mesh['triangles'][i]]
            potential=sum(potentials)/len(potentials) if all(v is not None for v in potentials) else None
            add('Cell potential',potential,'V','voltage')
            drop=None if potential is None else (potential-result['source_voltage_V'] if result.get('physical_return') else result['source_voltage_V']-potential)*1000
            add('Cell voltage drop',drop,'mV','drop')
            add('Copper thickness',mesh['triangle_thickness_mm'][i]*1000,'µm')
    thermal=record.get('thermal',{})
    for key,label,unit in [('time_to_limit_s','Time to temperature limit','s'),('energy_ratio','Pulse / temperature-limit energy','ratio'),('adiabatic_temperature_c','Adiabatic pulse temperature','°C')]:
        if key in thermal:add(label,thermal[key],unit,'risk')
    screen=record.get('fusing',{})
    for key,label,unit in [('time_to_onset_s','Melting onset','s'),('time_to_melt_s','Full melting','s'),('pulse_melt_ratio','Pulse / melting action','ratio'),('cross_section_mm2','Nominal / axial section','mm²'),('i2t_to_melt_A2s','Melting I²t','A²s')]:
        if key in screen:add(label,screen[key],unit,'melt')
    add('Saved PCB identities',', '.join(record.get('source_ids',[])) or 'Unavailable')
    return rows
