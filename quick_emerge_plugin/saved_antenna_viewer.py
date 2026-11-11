"""Native 3D extension to immutable archives; no solver/editor reattachment."""
import wx

from . import plots
from .field_display import field_for_display
from .inspection import FieldInspection
from .radiation_pattern import radiation_status, sample_row
from .polarization_view import available as polarization_available, plot as polarization_plot
from .saved_solver_result import load_solver_json


class SavedAntennaPanel(wx.Panel):
    def __init__(self, parent, result):
        super().__init__(parent)
        self.result=result
        self.samples,_=radiation_status(result)
        modes=[]
        if self.samples is not None: modes.append('3D radiation')
        if result.get('field'): modes.extend(('3D fields','3D phase vectors'))
        if polarization_available(result): modes.append('3D polarization')
        if result.get('scene_geometry'): modes.append('3D saved geometry')
        self.modes=modes
        layout=wx.BoxSizer(wx.VERTICAL); bar=wx.WrapSizer(wx.HORIZONTAL)
        self.choice=wx.Choice(self,choices=modes or ['No saved 3D samples'])
        self.choice.SetSelection(0); self.choice.Bind(wx.EVT_CHOICE,self.draw)
        bar.Add(self.choice,0,wx.ALL,4)
        self.quantity=wx.Choice(self,choices=['E magnitude','H magnitude']); self.quantity.SetSelection(0)
        self.quantity.Bind(wx.EVT_CHOICE,self.draw); bar.Add(self.quantity,0,wx.ALL,4)
        layers=result.get('field',{}).get('volume',{}).get('z_mm',[])
        self.slice=wx.Choice(self,choices=['Original sampling plane']+[f'Z = {z:g} mm' for z in layers])
        self.slice.SetSelection(0); self.slice.Bind(wx.EVT_CHOICE,self.draw)
        bar.Add(self.slice,0,wx.ALL,4)
        self.phase=wx.Slider(self,value=0,minValue=0,maxValue=360,size=(150,-1))
        self.phase.SetToolTip('Saved phasor phase, degrees; not a new simulation')
        self.phase.Bind(wx.EVT_SLIDER,self.draw); bar.Add(self.phase,0,wx.ALL,4)
        self.readout=wx.StaticText(self,label=''); self.readout.SetMinSize((1,-1))
        layout.Add(bar,0,wx.EXPAND)
        try:
            from .scene_viewport import SceneViewport
            self.view=SceneViewport(self,'3D radiation',self.probe)
        except ImportError:
            from .viewport import PlotViewport
            self.view=PlotViewport(self,'3D radiation',self.probe)
        self.view.show_controls(True); layout.Add(self.view,1,wx.EXPAND)
        layout.Add(self.readout,0,wx.EXPAND|wx.ALL,6); self.SetSizer(layout)
        wx.CallAfter(self.draw)

    def draw(self, event=None):
        if not self or not self.modes: return
        name=self.choice.GetStringSelection()
        self.quantity.Show(name in ('3D fields','3D phase vectors'))
        self.slice.Show(name in ('3D fields','3D phase vectors') and self.slice.GetCount()>1)
        self.phase.Show(name=='3D phase vectors')
        self.view.name='3D fields' if name=='3D phase vectors' else '3D setup' if name=='3D saved geometry' else name
        data=dict(self.result); options={'field':True,'archive_only':True,'show_context':True,'copper':True,'ports':True}
        rows=[]
        try:
            if name=='3D radiation':
                renderer=plots.radiation
                rows=[sample_row(self.samples,i,j) for i in range(len(self.samples.theta)) for j in range(len(self.samples.phi))]
                rows=[row for row in rows if row is not None]
            elif name=='3D polarization': renderer=polarization_plot
            elif name=='3D saved geometry': renderer=plots.geometry
            else:
                index=self.slice.GetSelection()-1
                z_index=index if index>=0 else None
                field=field_for_display(self.result,self.quantity.GetStringSelection(),z_index)
                inspection=FieldInspection(field); data['field']=field
                renderer=plots.near_field3d
                if name=='3D phase vectors':
                    from .field_vectors import sample_vectors
                    vectors=sample_vectors(self.result['field'],self.quantity.GetStringSelection(),self.phase.GetValue(),z_index)
                    field['display_vectors']=vectors
                    rows=[dict(inspection.probe(p[0],p[1]),kind='field',phase_deg=vectors['phase_deg'],instantaneous_vector=v.tolist())
                          for p,v in zip(vectors['positions'],vectors['vectors'])]
                else: rows=[dict(inspection.probe(x,y),kind='field') for y in inspection.y for x in inspection.x]
            self.view.render(renderer,data,reset=True,options=options); self.view.set_samples(rows)
            self.readout.SetLabel('Read-only saved samples; no solver, source reattachment or PCB changes.')
        except (ValueError,KeyError,TypeError) as exc:
            self.view.clear(); self.readout.SetLabel('Saved 3D data unavailable: '+str(exc))
        self.Layout()

    def probe(self,name,event,row=None,selected=False):
        if row is None: return
        if row.get('kind')=='radiation':
            text=f"theta={row['theta_deg']:.5g} deg; phi={row['phi_deg']:.5g} deg; relative E={row['relative_e']:.7g}"
        else:
            text=f"X={row['x_mm']:g}, Y={row['y_mm']:g}, Z={row['z_mm']:g} mm"
            if 'instantaneous_vector' in row: text+=f"; phase={row['phase_deg']:g} deg; vector={row['instantaneous_vector']}"
            else: text+='; '+str({k:v for k,v in row.items() if k.startswith('value_')})
        self.readout.SetLabel(text)


def create_viewer(parent, loaded):
    from wayricad_runtime.project_results_ui import create_viewer as generic_viewer
    frame=generic_viewer(parent,loaded)
    result=loaded['bundle']
    if isinstance(result.get('config'),dict) and (result.get('radiation') or result.get('field') or result.get('scene_geometry')):
        page=SavedAntennaPanel(frame.book,result)
        frame.book.AddPage(page,'Antenna 3D',select=True)
        frame.antenna_3d=page
    return frame
