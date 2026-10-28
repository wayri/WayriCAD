"""Typed scalar-network operations; original EM geometry and fields stay intact."""
import math
import wx
from .network import from_result

class NetworkToolsDialog(wx.Dialog):
    def __init__(self,parent,result):
        super().__init__(parent,title='Network analysis',size=(490,590),style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.network=from_result(result);self.rows={};layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Each operation starts from the original solved network. Fields retain their recorded excitation. Components are ideal sampled elements.')
        note.Wrap(430);layout.Add(note,0,wx.EXPAND | wx.ALL,14)
        self.operation=wx.Choice(self,choices=['Renormalize','Mixed mode','Terminate ports','Embed R / L / C','Rational fit'])
        self.operation.SetSelection(0);layout.Add(self.operation,0,wx.EXPAND | wx.LEFT | wx.RIGHT,14)
        self.operation.Bind(wx.EVT_CHOICE,self.update_fields)
        self.fields={}
        def add(key,label,control,operations):
            panel=wx.Panel(self);row=wx.BoxSizer(wx.VERTICAL);row.Add(wx.StaticText(panel,label=label),0,wx.BOTTOM,3)
            control.Reparent(panel);row.Add(control,0,wx.EXPAND);panel.SetSizer(row)
            self.fields[key]=control;self.rows[key]=(panel,operations);layout.Add(panel,0,wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,14)
        def text(key,label,value,operations):add(key,label,wx.TextCtrl(self,value=str(value)),operations)
        def choice(key,label,values,operations):
            control=wx.Choice(self,choices=values);control.SetSelection(0);add(key,label,control,operations)
        text('reference','New common reference [ohm]',50,[0])
        names=list(self.network.port_names)
        choice('positive','Positive port',names,[1,3]);choice('negative','Negative port / component reference',['Reference']+names,[1,3])
        self.fields['negative'].SetSelection(min(2,len(names)))
        keep=wx.CheckListBox(self,choices=names);keep.Check(0);add('keep','Keep these ports (all other ports receive the selected load)',keep,[2])
        choice('load','Terminated-port load',['Matched','Resistance','Open','Short'],[2]);text('resistance','Load resistance [ohm]',50,[2])
        choice('connection','Connection',['shunt','series'],[3]);choice('element','Element',['R','L','C'],[3]);text('value','Value [R: ohm, L: nH, C: pF]',50,[3])
        choice('method','Fit method',['aaa','vf'],[4]);text('tolerance','Fit tolerance (complex absolute)',.0005,[4]);text('points','Evaluation frequencies within the solved band',201,[4]);text('poles','Pole budget for vector fitting',6,[4])
        layout.AddStretchSpacer();buttons=self.CreateButtonSizer(wx.OK | wx.CANCEL);layout.Add(buttons,0,wx.EXPAND | wx.ALL,14)
        self.SetSizer(layout);self.update_fields()
    def update_fields(self,event=None):
        operation=self.operation.GetSelection()
        for panel,operations in self.rows.values():panel.Show(operation in operations)
        self.Layout()
    def normalized_operation(self):
        f=self.fields;operation=self.operation.GetSelection()
        def number(key):
            value=float(f[key].GetValue())
            if not math.isfinite(value):raise ValueError('Enter finite numeric settings.')
            return value
        if operation==0:return {'kind':'renormalize','reference_ohm':number('reference')}
        if operation==1:
            positive=f['positive'].GetStringSelection();negative=f['negative'].GetStringSelection()
            if negative=='Reference':raise ValueError('Choose a distinct negative port for mixed mode.')
            return {'kind':'mixed_mode','pairs':[[positive,negative]]}
        if operation==2:
            keep=[self.network.port_names[i] for i in range(self.network.port_count) if f['keep'].IsChecked(i)]
            kind=f['load'].GetStringSelection();loads={}
            for i,name in enumerate(self.network.port_names):
                if name in keep:continue
                loads[name]=float(self.network.z0_ohm[i]) if kind=='Matched' else number('resistance') if kind=='Resistance' else kind.lower()
            return {'kind':'terminate','keep':keep,'loads_ohm':loads}
        if operation==3:
            element=f['element'].GetStringSelection();scale={'R':1,'L':1e-9,'C':1e-12}[element]
            ports=[f['positive'].GetStringSelection()];negative=f['negative'].GetStringSelection()
            if negative!='Reference':ports.append(negative)
            return {'kind':'components','components':[{'connection':f['connection'].GetStringSelection(),'element':element,'value_si':number('value')*scale,'unit':{'R':'ohm','L':'H','C':'F'}[element],'ports':ports}]}
        return {'kind':'fit','method':f['method'].GetStringSelection(),'tolerance':number('tolerance'),'points':int(f['points'].GetValue()),'poles':int(f['poles'].GetValue())}
