"""Small native results view for actual KiCad-ngspice simulations."""
import math
import threading
import wx
from .simulation import run_simulation


class SimulationPlot(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent);self.result=None;self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear();fg=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT);dc.SetTextForeground(fg)
        if not self.result:dc.DrawText('Run KiCad SPICE to inspect actual circuit results.',self.FromDIP(16),self.FromDIP(20));return
        result=self.result;w,h=self.GetClientSize();pad=self.FromDIP(65)
        if 'samples' not in result:
            lines=['DC operating point',f"Speed {result['speed']:.7g} {result['speed_unit']}",f"Current {result['current_A']:.7g} A",f"Effort {result['effort']:.7g} {result['effort_unit']}",f"Electrical input {result['electrical_input_W']:.7g} W",f"Mechanical conversion {result['converted_mechanical_W']:.7g} W"]
            for i,line in enumerate(lines):dc.DrawText(line,pad,pad+i*self.FromDIP(35))
            return
        rows=result['samples'];x=[math.log10(row['frequency_Hz']) for row in rows]
        metrics=[('input_impedance_magnitude_ohm','|Zin| (ohm, log) · frequency (log Hz)',True)]
        metrics+=[('voltage_gain_magnitude','|Vout/Vin| (linear) · frequency (log Hz)',False)] if 'voltage_gain_magnitude' in rows[0] else [('input_impedance_phase_deg','Phase (degrees, linear) · frequency (log Hz)',False)]
        for index,(key,label,logscale) in enumerate(metrics):
            left,right=pad,w-self.FromDIP(25);top=self.FromDIP(35)+index*h//2;bottom=(index+1)*h//2-self.FromDIP(40)
            if right<=left or bottom<=top:return
            values=[math.log10(max(row[key],1e-30)) if logscale else row[key] for row in rows];lo,hi=min(values),max(values)
            if hi-lo<1e-8:lo-=1;hi+=1
            dc.SetPen(wx.Pen(fg));dc.DrawLine(left,top,left,bottom);dc.DrawLine(left,bottom,right,bottom)
            dc.DrawText(label,left,top-self.FromDIP(24));dc.DrawText(f"{10**hi if logscale else hi:.3g}",4,top);dc.DrawText(f"{10**lo if logscale else lo:.3g}",4,bottom-self.FromDIP(10))
            dc.DrawText(f"{rows[0]['frequency_Hz']:g} Hz",left,bottom+self.FromDIP(6));dc.DrawText(f"{rows[-1]['frequency_Hz']:g} Hz",right-self.FromDIP(75),bottom+self.FromDIP(6))
            points=[wx.Point(round(left+(value-x[0])/max(x[-1]-x[0],1e-30)*(right-left)),round(bottom-(y-lo)/(hi-lo)*(bottom-top))) for value,y in zip(x,values)]
            dc.SetPen(wx.Pen(wx.Colour('#208bb5'),2))
            if len(points)>1:dc.DrawLines(points)
            elif points:dc.DrawCircle(points[0],3)


class SimulationPanel(wx.Panel):
    def __init__(self,parent,owner):
        super().__init__(parent);self.owner=owner;self.busy=False;root=wx.BoxSizer(wx.VERTICAL);row=wx.FlexGridSizer(cols=4,vgap=6,hgap=8);self.fields={}
        for key,label,value in [('voltage_v','Drive V','1'),('load_ohm','Load Ω','10'),('start_hz','Start Hz','10'),('stop_hz','Stop Hz','1000000')]:
            row.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4);control=wx.TextCtrl(self,value=value,size=self.FromDIP((70,-1)));self.fields[key]=control;row.Add(control,0,wx.RIGHT,8);control.Bind(wx.EVT_TEXT,self.invalidate)
        self.run=wx.Button(self,label='Run KiCad SPICE');self.run.Bind(wx.EVT_BUTTON,self.simulate);root.Add(row,0,wx.ALL,8);root.Add(self.run,0,wx.ALL,8)
        self.plot=SimulationPlot(self);root.Add(self.plot,1,wx.EXPAND|wx.ALL,8)
        self.status=wx.StaticText(self,label='AC sweep for inductors/transformers; mechanical equivalents use DC operating point. Uses KiCad’s bundled engine.');self.status.Wrap(self.FromDIP(600));root.Add(self.status,0,wx.EXPAND|wx.ALL,8);self.SetSizer(root)
    def invalidate(self,event=None):
        self.owner.simulation=None;self.plot.result=None;self.plot.Refresh()
        if event:event.Skip()
    def configure(self):
        model=self.owner.model or {};mechanical=bool(model.get('actuator'))
        self.fields['load_ohm'].Enable(not self.busy and 'secondary_L_H' in model)
        for key in ('start_hz','stop_hz'):self.fields[key].Enable(not self.busy and not mechanical)
    def simulate(self,event):
        if self.busy:return
        if not self.owner.model:self.status.SetLabel('Review valid model inputs before running SPICE.');return
        keys=['voltage_v']+(['load_ohm'] if 'secondary_L_H' in self.owner.model else [])+(['start_hz','stop_hz'] if not self.owner.model.get('actuator') else [])
        try:values={key:float(self.fields[key].GetValue()) for key in keys}
        except ValueError:self.status.SetLabel('Simulation inputs must be finite numbers.');return
        model=self.owner.model;self.busy=True;self.run.Disable();self.invalidate()
        for control in self.fields.values():control.Disable()
        self.status.SetLabel('Running the isolated KiCad ngspice engine…')
        def worker():
            try:result,error=run_simulation(model,**values),None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.complete,model,result,error)
        threading.Thread(target=worker,daemon=True).start()
    def complete(self,model,result,error):
        if not self or self.IsBeingDeleted():return
        self.busy=False;self.run.Enable()
        for control in self.fields.values():control.Enable()
        self.configure()
        if self.owner.model is not model:self.status.SetLabel('Model changed while SPICE ran; results discarded. Run again.');return
        if error:self.status.SetLabel(error);self.status.Wrap(max(200,self.GetClientSize().width-24));self.Layout();return
        self.owner.simulation=result;self.plot.result=result;self.plot.Refresh();self.status.SetLabel(result['analysis']+' · '+str(result['engine'].get('engine','KiCad ngspice'))+'\n'+result['limits']);self.status.SetToolTip(str(result['engine'].get('path',''))+'\n'+'\n'.join(result['engine'].get('log',[])[:6]));self.status.Wrap(max(200,self.GetClientSize().width-24));self.Layout()

