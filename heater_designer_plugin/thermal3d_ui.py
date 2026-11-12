"""Construction/material review before sharing a generated heater 3D study."""
import copy
import json
import wx
from .thermal3d import build_study,construction_layers


def open_heater_study(parent,heater):
    heater=copy.deepcopy(heater)
    dialog=wx.Dialog(parent,title='Heater 3D construction',size=(700,650),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    layout=wx.BoxSizer(wx.VERTICAL);form=wx.FlexGridSizer(0,2,7,12);form.AddGrowableCol(1)
    fields={}
    def field(key,label,value,choices=None):
        control=wx.ComboBox(dialog,value=value,choices=choices,style=wx.CB_READONLY) if choices else wx.TextCtrl(dialog,value=value)
        form.Add(wx.StaticText(dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND);fields[key]=control
    field('form','Construction','rigid',['rigid','flex','rigid-flex','free foil'])
    minimum=min(row.width_mm for row in heater.segments)
    aligned=all(abs(row.x2_mm-row.x1_mm)<1e-10 or abs(row.y2_mm-row.y1_mm)<1e-10 for row in heater.segments)
    field('cell','Maximum XY cell (mm)','2' if aligned else str(min(minimum,heater.spec.spacing_mm)/2))
    conductor_k={'copper':385.,'nichrome80':15.,'inconel600':14.9}.get(heater.spec.material.key)
    field('conductor_k','Conductor k (W/m K)',str(conductor_k) if conductor_k else '')
    field('substrate_k','Substrate k (W/m K)','.3')
    field('ambient','Ambient (C)','25');field('h','Exposed-face h (W/m2 K)','10');field('emissivity','Emissivity','0.8')
    field('seebeck','Seebeck relative to ideal leads (V/K)','')
    field('reference','Seebeck reference / lead evidence','')
    layout.Add(form,0,wx.EXPAND|wx.ALL,12)
    constant=wx.CheckBox(dialog,label='Reviewed constant resistivity (only when no temperature data exist)')
    layout.Add(constant,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
    reviewed=wx.CheckBox(dialog,label='Material properties, construction and ideal contact assumptions reviewed')
    layout.Add(reviewed,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
    layout.Add(wx.StaticText(dialog,label='Construction layers: thickness_mm, role, thermal_conductivity_w_mk, optional region_mm'),0,wx.LEFT|wx.RIGHT,12)
    layers=wx.TextCtrl(dialog,style=wx.TE_MULTILINE)
    last_preset=['']
    def preset(event=None):
        try:
            value=json.dumps(construction_layers(fields['form'].GetValue(),heater.spec.width_mm,float(fields['substrate_k'].GetValue()),heater.spec.copper_um),indent=2)
            if layers.GetValue()!=last_preset[0]:
                if wx.MessageBox('Replace custom layers and regions with this construction preset?',
                                 'Replace construction?',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,dialog)!=wx.YES:return
            layers.SetValue(value);last_preset[0]=value
        except ValueError:pass
    fields['form'].Bind(wx.EVT_COMBOBOX,preset)
    fields['substrate_k'].Bind(wx.EVT_KILL_FOCUS,lambda event:(preset(),event.Skip()))
    preset()
    layout.Add(layers,1,wx.EXPAND|wx.ALL,12);layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,12)
    dialog.SetSizer(layout);dialog.CentreOnParent()
    try:
        while dialog.ShowModal()==wx.ID_OK:
            try:
                if not reviewed.GetValue():raise ValueError('Review the physical material and construction assumptions before meshing.')
                config=dict(cell_mm=float(fields['cell'].GetValue()),conductor_k_w_mk=float(fields['conductor_k'].GetValue()),
                    layers=json.loads(layers.GetValue()),constant_resistivity_reviewed=constant.GetValue(),
                    boundary=dict(ambient_c=float(fields['ambient'].GetValue()),h_w_m2k=float(fields['h'].GetValue()),emissivity=float(fields['emissivity'].GetValue())),
                    settings=dict(max_cells=50000,temperature_bounds_c=[-50,200],relaxation=.5))
                if fields['seebeck'].GetValue().strip():
                    config.update(seebeck_v_k=float(fields['seebeck'].GetValue()),seebeck_reference_note=fields['reference'].GetValue())
                request=build_study(heater,config)
                from wayricad_runtime.thermoelectric_ui import open_study
                return open_study(parent,request=request,request_factory=lambda:build_study(heater,config))
            except (ValueError,KeyError,TypeError) as exc:wx.MessageBox(str(exc),'Review 3D inputs',wx.OK|wx.ICON_ERROR,dialog)
    finally:dialog.Destroy()
