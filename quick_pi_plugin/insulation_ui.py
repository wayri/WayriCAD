"""Native, explicit post-batch insulation screening inputs and warning markers."""
from __future__ import annotations
import json
import wx
from wayricad_runtime.readable_choice import ReadableChoice
from wayricad_runtime.layout import fit_to_display
from .insulation_screen import SCHEMA, screen


class InsulationScreenDialog(wx.Dialog):
    def __init__(self, parent, bundle, board_path):
        super().__init__(parent,title='Quick PI · Insulation engineering screen',size=(1120,820),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.bundle=bundle;self.board_path=board_path;self.result=None
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Review rule applicability, material and environment. This screen compares solved-net planar copper spacing with your entered limits. '
            'Physical creepage remains UNKNOWN unless you supply a reviewed surface measurement accounting for slots and obstacles. No certification is granted.')
        note.Wrap(1050);root.Add(note,0,wx.EXPAND|wx.ALL,10)
        grid=wx.FlexGridSizer(0,4,7,10);grid.AddGrowableCol(1);grid.AddGrowableCol(3);self.fields={}
        specifications=[('rule_citation','Rule / clause citation',''),('material','Material / surface assumptions',''),
            ('environment','Environment / pollution / altitude',''),('voltage_limit_V','Rule applicable up to V',''),
            ('minimum_clearance_mm','Minimum planar clearance mm',''),('minimum_creepage_mm','Minimum creepage mm',''),
            ('envelope_V','Reviewed maximum inter-net V',''),('envelope_citation','Voltage-envelope evidence',''),
            ('domain','Common voltage-domain description',''),('offsets','Common-domain offsets JSON V','')]
        for key,label,value in specifications:
            grid.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(self,value=value);self.fields[key]=control;grid.Add(control,1,wx.EXPAND)
        root.Add(grid,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.mode=ReadableChoice(self,choices=['Reviewed conservative voltage envelope','Reviewed common voltage domain + net offsets'])
        self.mode.SetSelection(0);root.Add(self.mode,0,wx.EXPAND|wx.ALL,10)
        self.review=wx.CheckBox(self,label='I reviewed the voltage reference/envelope and applicability of these entered thresholds.')
        root.Add(self.review,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        root.Add(wx.StaticText(self,label='Optional reviewed creepage measurements JSON: net_a, net_b, length_mm, evidence, reviewed=true. Evidence must account for surface paths, slots and obstacles.'),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,10)
        self.creepage=wx.TextCtrl(self,value='[]',style=wx.TE_MULTILINE,size=(-1,60));root.Add(self.creepage,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        actions=wx.BoxSizer(wx.HORIZONTAL);run=wx.Button(self,label='Screen solved nets');self.locate=wx.Button(self,label='Locate selected net pair on PCB')
        self.locate.Disable();run.Bind(wx.EVT_BUTTON,self.run);self.locate.Bind(wx.EVT_BUTTON,self.locate_pair)
        actions.Add(run,0,wx.RIGHT,8);actions.Add(self.locate,0);root.Add(actions,0,wx.ALL,10)
        body=wx.BoxSizer(wx.HORIZONTAL)
        self.table=wx.ListCtrl(self,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(label,width) in enumerate([('Net pair',220),('ΔV max V',95),('Clearance lower mm',135),('Clearance',165),('Creepage',165)]):self.table.InsertColumn(i,label,width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED,self.selected)
        body.Add(self.table,3,wx.EXPAND|wx.RIGHT,10)
        self.marker=wx.Panel(self,size=(240,160));self.marker.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.marker.Bind(wx.EVT_PAINT,self.paint_marker)
        body.Add(self.marker,1,wx.EXPAND);root.Add(body,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,95));root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        root.Add(self.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.Bind(wx.EVT_BUTTON,lambda event:self.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        self.SetSizer(root);fit_to_display(self)
        for control in [*self.fields.values(),self.creepage]:control.Bind(wx.EVT_TEXT,self.invalidate)
        self.mode.Bind(wx.EVT_CHOICE,self.invalidate);self.review.Bind(wx.EVT_CHECKBOX,self.invalidate)

    def invalidate(self,event=None):
        self.result=None;self.table.DeleteAllItems();self.locate.Disable();self.marker.Refresh()
        self.status.SetValue('Inputs changed. Screen again before reviewing or locating a pair.')
        if event:event.Skip()

    def policy(self):
        def text(key):return self.fields[key].GetValue().strip()
        if self.mode.GetSelection()==0:
            reference={'mode':'conservative-envelope','reviewed':self.review.GetValue(),
                'maximum_voltage_difference_V':float(text('envelope_V')),'citation':text('envelope_citation')}
        else:
            reference={'mode':'common-domain','reviewed':self.review.GetValue(),
                'domain':text('domain'),'net_offsets_V':json.loads(text('offsets'))}
        return {'schema':SCHEMA,'rule_citation':text('rule_citation'),'material':text('material'),
            'environment':text('environment'),'voltage_limit_V':float(text('voltage_limit_V')),
            'minimum_clearance_mm':float(text('minimum_clearance_mm')),
            'minimum_creepage_mm':float(text('minimum_creepage_mm')),
            'voltage_reference':reference,'reviewed_creepage':json.loads(self.creepage.GetValue())}

    def run(self,event=None):
        self.invalidate()
        try:self.result=screen(self.bundle,self.policy())
        except (ValueError,TypeError,ImportError) as error:
            self.status.SetValue('Screen unavailable: '+str(error));return
        for pair in self.result['pairs']:
            i=self.table.InsertItem(self.table.GetItemCount(),pair['net_a']+' / '+pair['net_b'])
            for column,value in enumerate((pair['maximum_voltage_difference_V'],pair['clearance_lower_bound_mm'],pair['clearance_status'],pair['creepage_status']),1):
                self.table.SetItem(i,column,'UNKNOWN' if value is None else str(value))
            if pair['status']!='SCREENED':self.table.SetItemTextColour(i,wx.Colour('#a34b00'))
        self.status.SetValue(self.result['status']+' · '+self.result['notice'])
        if self.result['pairs']:self.table.Select(0);self.selected()

    def selected_pair(self):
        index=self.table.GetFirstSelected()
        return self.result['pairs'][index] if self.result and 0<=index<len(self.result['pairs']) else None

    def selected(self,event=None):
        pair=self.selected_pair();self.locate.Enable(pair is not None);self.marker.Refresh()
        if pair:self.status.SetValue(pair['status']+' · '+('; '.join(pair['issues']) or 'Within the entered limits; applicability remains your responsibility.')+'\n'+self.result['notice'])
        if event:event.Skip()

    def locate_pair(self,event=None):
        pair=self.selected_pair()
        if not pair:return
        try:
            from wayricad_runtime.analysis_selection import select_origin
            select_origin(self.board_path,nets=[pair['net_a'],pair['net_b']],expected_sha256=self.result['source_sha256'],focus=True)
        except Exception as error:self.status.SetValue('PCB locate unavailable: '+str(error))

    def paint_marker(self,event):
        dc=wx.AutoBufferedPaintDC(self.marker);dc.SetBackground(wx.Brush(self.marker.GetBackgroundColour()));dc.Clear()
        pair=self.selected_pair()
        if not pair or not pair['closest_points_mm']:
            dc.DrawText('No planar marker available',8,12);return
        a,b=pair['closest_points_mm'];width,height=self.marker.GetClientSize();margin=25
        span=max(abs(a[0]-b[0]),abs(a[1]-b[1]),.001);scale=max(1,min(width-2*margin,height-75))/span
        cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
        points=[(round(width/2+(p[0]-cx)*scale),round(height/2+(p[1]-cy)*scale)) for p in (a,b)]
        dc.SetPen(wx.Pen(wx.Colour('#c45a00'),3));dc.DrawLine(*points[0],*points[1])
        dc.SetBrush(wx.Brush(wx.Colour('#c45a00')))
        for x,y in points:dc.DrawCircle(x,y,5)
        dc.DrawText('Layer '+str(pair['layer_id'])+' · extracted closest points',5,5)
        dc.DrawText('A '+str([round(v,5) for v in a])+' mm',5,max(25,height-45))
        dc.DrawText('B '+str([round(v,5) for v in b])+' mm',5,max(40,height-25))


def show_insulation(parent, bundle, board_path):
    dialog=InsulationScreenDialog(parent,bundle,board_path)
    try:dialog.ShowModal();return dialog.result
    finally:dialog.Destroy()
