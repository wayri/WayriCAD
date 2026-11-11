"""Two native, sample-aware radiation views of the same stored result."""
import wx

from . import plots
from .radiation_pattern import radiation_status, available_cuts, radiation_cut, sample_row
from .viewport import PlotViewport


class RadiationOverview(wx.Panel):
    def __init__(self, parent, callback, scene_class=None):
        super().__init__(parent)
        self.callback = callback
        self.result = self.samples = None
        self.caption = wx.StaticText(self, style=wx.ST_ELLIPSIZE_END)
        self.caption.SetMinSize((1,-1))
        self.cut_choice = wx.Choice(self)
        self.cut_choice.SetToolTip('Principal-plane cut from original stored angular samples')
        self.cut_choice.Bind(wx.EVT_CHOICE, self.change_cut)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.Add(self.caption,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        bar.Add(self.cut_choice,0)
        self.splitter = wx.SplitterWindow(self,style=wx.SP_LIVE_UPDATE|wx.SP_NOBORDER)
        self.splitter.SetMinimumPaneSize(160)
        self.splitter.SetSashGravity(.55)
        self.scene_view = (scene_class or PlotViewport)(self.splitter,'3D radiation',self._probe)
        self.cut_view = PlotViewport(self.splitter,'Radiation pattern',self._probe)
        self.scene_view.show_controls(True);self.cut_view.show_controls(True)
        self.splitter.SplitVertically(self.scene_view,self.cut_view)
        self.readout = wx.StaticText(self,label='Orbit the 3D pattern; hover or Probe original samples in either view.',style=wx.ST_ELLIPSIZE_END)
        self.readout.SetMinSize((1,-1))
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(bar,0,wx.EXPAND|wx.ALL,8)
        layout.Add(self.splitter,1,wx.EXPAND)
        layout.Add(self.readout,0,wx.EXPAND|wx.ALL,6)
        self.SetSizer(layout)
        self.Bind(wx.EVT_SIZE,self._resize)
        self.clear()

    def _resize(self, event):
        vertical = self.GetClientSize().width >= self.FromDIP(850)
        if self.splitter.IsSplit() and (self.splitter.GetSplitMode()==wx.SPLIT_VERTICAL) != vertical:
            self.splitter.Unsplit()
            self.scene_view.Show();self.cut_view.Show()
            if vertical:self.splitter.SplitVertically(self.scene_view,self.cut_view)
            else:self.splitter.SplitHorizontally(self.scene_view,self.cut_view)
        self.Layout()
        wx.CallAfter(self.scene_view.refresh_canvas)
        wx.CallAfter(self.cut_view.refresh_canvas)
        event.Skip()

    def clear(self):
        self.result = self.samples = None
        self.caption.SetLabel('No stored radiation samples. Run or load a completed antenna study.')
        self.cut_choice.Clear();self.cut_choice.Disable()
        self.scene_view.clear();self.cut_view.clear()
        self.readout.SetLabel('No current radiation result. Run or load a completed antenna study.')

    def render_result(self,result):
        samples,reason = radiation_status(result)
        if samples is None:
            self.clear()
            raise ValueError(reason or 'No stored radiation samples are available')
        cuts=available_cuts(samples)
        if not cuts:
            self.clear()
            raise ValueError('No stored principal-plane cut is available; use the standalone 3D view')
        self.result,self.samples=result,samples
        mode=('Ideal array factor; no FEM coupling' if result.get('array_factor') else
              'Coupled FEM array; mesh not convergence-qualified' if result.get('array') else
              'Stored antenna result; inspect its model scope')
        self.caption.SetLabel(f'{mode} | {samples.frequency/1e9:g} GHz | relative |E|, not dBi')
        self.caption.SetToolTip(self.caption.GetLabel())
        previous=self.cut_choice.GetStringSelection()
        self.cut_choice.Set(cuts);self.cut_choice.SetStringSelection(previous if previous in cuts else cuts[0]);self.cut_choice.Enable()
        self.scene_view.render(plots.radiation,result,reset=True)
        self.scene_view.set_samples([row for i in range(len(samples.theta)) for j in range(len(samples.phi))
                                     if (row:=sample_row(samples,i,j)) is not None])
        self.change_cut()

    def change_cut(self,event=None):
        if self.result is None:return
        cut=radiation_cut(self.samples,self.cut_choice.GetStringSelection())
        self.cut_view.set_samples([row for row in cut['samples'] if row is not None])
        self.cut_view.render(plots.radiation_polar,self.result,reset=True,options={'radiation_cut':cut['name']})
        self.readout.SetLabel(cut['caption']+' | same global normalization as the 3D pattern')

    def _probe(self,name,event,sample=None,selected=False):
        self.callback(name,event,sample,selected)
        if sample and sample.get('kind')=='radiation':
            self.readout.SetLabel(f'Theta {sample["theta_deg"]:.5g} deg | phi {sample["phi_deg"]:.5g} deg | relative |E| {sample["relative_e"]:.7g} | {self.samples.frequency/1e9:g} GHz')
            if selected:
                self.scene_view.set_selection(sample)
                self.cut_view.set_selection(sample)
