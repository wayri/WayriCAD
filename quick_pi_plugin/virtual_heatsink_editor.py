"""Native, local editor for explicit QuickTherm virtual heatsinks."""
from __future__ import annotations

import math


SHAPES = {
    'straight_fin': ('Straight fins', (40., 40., 15.)),
    'pin_fin': ('Pin fins', (25., 25., 10.)),
    'radial_fin': ('Radial fins', (30., 30., 20.)),
    'plate': ('Flat plate', (40., 40., 3.)),
    'resistance_only': ('Resistance only · no envelope', None),
}


def parse_heatsink_inputs(reference, shape, width, depth, height, contact, air, vacuum):
    """Validate UI values without deriving thermal resistance from geometry."""
    if not reference or shape not in SHAPES:
        raise ValueError('Choose one component and a supported heatsink shape.')
    def number(value, label, *, positive=True):
        try:result=float(value)
        except (TypeError, ValueError) as exc:raise ValueError(label+' must be a number.') from exc
        if not math.isfinite(result) or (result<=0 if positive else result<0):
            raise ValueError(label+' must be finite and '+('positive.' if positive else 'nonnegative.'))
        return result
    sink={'shape':shape,'contact_k_per_w':number(contact,'Contact resistance')}
    if shape!='resistance_only':
        sink.update(width_mm=number(width,'Width mm'),depth_mm=number(depth,'Depth mm'),
                    height_mm=number(height,'Height mm'))
    if air.strip():sink['theta_sa_air_k_per_w']=number(air,'Air sink-to-ambient K/W')
    if vacuum.strip():sink['theta_sa_vacuum_k_per_w']=number(vacuum,'Vacuum sink-to-environment K/W')
    if 'theta_sa_air_k_per_w' not in sink and 'theta_sa_vacuum_k_per_w' not in sink:
        raise ValueError('Enter at least one measured or estimated sink-to-environment K/W value.')
    return sink


class VirtualHeatsinkDialog:
    def __init__(self, parent, references, existing):
        import wx
        from matplotlib.figure import Figure
        from .plot_canvas import FigureCanvasWxAgg
        self.wx=wx;self.data={key:dict(value) for key,value in existing.items()};self.references=sorted(references)
        self.dialog=wx.Dialog(parent,title='QuickTherm · Virtual heatsinks',
                              size=parent.FromDIP((920,680)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self.dialog,label='Assign a virtual heatsink to a component. Envelope presets are editable illustrations, not product ratings. Enter actual thermal resistance for the intended air or vacuum path.')
        note.Wrap(parent.FromDIP(860));root.Add(note,0,wx.EXPAND|wx.ALL,12)
        body=wx.BoxSizer(wx.HORIZONTAL);left=wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(self.dialog,label='Assigned components'),0,wx.BOTTOM,6)
        self.list=wx.ListBox(self.dialog,size=parent.FromDIP((230,-1)));self.list.Bind(wx.EVT_LISTBOX,self._load_selected)
        left.Add(self.list,1,wx.EXPAND);remove=wx.Button(self.dialog,label='Remove assignment')
        remove.Bind(wx.EVT_BUTTON,self._remove);left.Add(remove,0,wx.TOP,8);body.Add(left,0,wx.EXPAND|wx.RIGHT,16)
        right=wx.BoxSizer(wx.VERTICAL);grid=wx.FlexGridSizer(0,2,8,9);grid.AddGrowableCol(1,1)
        self.reference=wx.Choice(self.dialog,choices=self.references)
        if self.references:self.reference.SetSelection(0)
        self.shape=wx.Choice(self.dialog,choices=[label for label,_ in SHAPES.values()]);self.shape.SetSelection(0)
        self.width=wx.TextCtrl(self.dialog,value='40');self.depth=wx.TextCtrl(self.dialog,value='40')
        self.height=wx.TextCtrl(self.dialog,value='15');self.contact=wx.TextCtrl(self.dialog)
        self.air=wx.TextCtrl(self.dialog);self.vacuum=wx.TextCtrl(self.dialog)
        for label,ctrl in [('Component',self.reference),('Shape',self.shape),('Width mm',self.width),
            ('Depth mm',self.depth),('Height mm',self.height),('Contact Rθ K/W',self.contact),
            ('Air sink-to-ambient Rθ K/W',self.air),('Vacuum sink-to-environment Rθ K/W',self.vacuum)]:
            grid.Add(wx.StaticText(self.dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(ctrl,1,wx.EXPAND)
        right.Add(grid,0,wx.EXPAND|wx.BOTTOM,8)
        self.figure=Figure(figsize=(5,2.3),dpi=100);self.canvas=FigureCanvasWxAgg(self.dialog,wx.ID_ANY,self.figure)
        right.Add(self.canvas,1,wx.EXPAND)
        hint=wx.StaticText(self.dialog,label='The sketch changes with shape and dimensions. Only entered Rθ values affect temperatures.')
        right.Add(hint,0,wx.TOP|wx.BOTTOM,6)
        assign=wx.Button(self.dialog,label='Assign / update heatsink');assign.Bind(wx.EVT_BUTTON,self._assign)
        right.Add(assign,0,wx.ALIGN_RIGHT);body.Add(right,1,wx.EXPAND)
        root.Add(body,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        footer=self.dialog.CreateButtonSizer(wx.OK|wx.CANCEL);root.Add(footer,0,wx.ALIGN_RIGHT|wx.ALL,12)
        self.dialog.SetSizer(root)
        self.shape.Bind(wx.EVT_CHOICE,self._shape_changed)
        for control in (self.width,self.depth,self.height):control.Bind(wx.EVT_TEXT,self._draw)
        self._refresh();self._draw()

    def _shape_key(self):
        return list(SHAPES)[max(0,self.shape.GetSelection())]

    def _shape_changed(self,event):
        default=SHAPES[self._shape_key()][1]
        if default:
            for ctrl,value in zip((self.width,self.depth,self.height),default):ctrl.ChangeValue(f'{value:g}')
        self._update_dimension_state()
        self._draw()

    def _update_dimension_state(self):
        enabled=self._shape_key()!='resistance_only'
        for ctrl in (self.width,self.depth,self.height):ctrl.Enable(enabled)

    def _draw(self,event=None):
        from matplotlib.patches import Rectangle, Circle
        self.figure.clear();ax=self.figure.add_subplot(111);shape=self._shape_key()
        try:w=max(1.,float(self.width.GetValue()));d=max(1.,float(self.depth.GetValue()))
        except ValueError:w,d=40.,40.
        ax.add_patch(Rectangle((0,0),w,d,facecolor='#cbdde0',edgecolor='#347185',linewidth=2))
        if shape=='straight_fin':
            for i in range(1,7):ax.plot([w*i/7]*2,[d*.08,d*.92],color='#147b90',linewidth=5)
        elif shape=='pin_fin':
            for i in range(1,6):
                for j in range(1,5):ax.add_patch(Circle((w*i/6,d*j/5),min(w,d)/27,color='#147b90'))
        elif shape=='radial_fin':
            import math
            for i in range(12):
                angle=i*math.tau/12
                ax.plot([w/2,w/2+math.cos(angle)*w*.43],[d/2,d/2+math.sin(angle)*d*.43],
                        color='#147b90',linewidth=3)
        elif shape=='resistance_only':
            ax.text(w/2,d/2,'Rθ only',ha='center',va='center',color='#225667',fontsize=15)
        ax.set_xlim(-w*.08,w*1.08);ax.set_ylim(-d*.08,d*1.08);ax.set_aspect('equal');ax.axis('off')
        ax.set_title('Top view · '+SHAPES[shape][0]+(' · editable envelope' if shape!='resistance_only' else ''))
        self.figure.tight_layout();self.canvas.draw_idle()
        if event:event.Skip()

    def _refresh(self):
        self.list.Set([ref+' · '+SHAPES.get(row.get('shape'),('Unknown',))[0] for ref,row in sorted(self.data.items())])

    def _load_selected(self,event):
        index=self.list.GetSelection()
        if index<0:return
        reference=sorted(self.data)[index];sink=self.data[reference]
        self.reference.SetStringSelection(reference);self.shape.SetSelection(list(SHAPES).index(sink['shape']))
        for ctrl,key in ((self.width,'width_mm'),(self.depth,'depth_mm'),(self.height,'height_mm'),
                         (self.contact,'contact_k_per_w'),(self.air,'theta_sa_air_k_per_w'),
                         (self.vacuum,'theta_sa_vacuum_k_per_w')):
            ctrl.ChangeValue(str(sink.get(key,'')))
        self._update_dimension_state();self._draw()

    def _assign(self,event):
        try:
            reference=self.reference.GetStringSelection()
            sink=parse_heatsink_inputs(reference,self._shape_key(),self.width.GetValue(),self.depth.GetValue(),
                self.height.GetValue(),self.contact.GetValue(),self.air.GetValue(),self.vacuum.GetValue())
            self.data[reference]=sink;self._refresh()
        except ValueError as exc:self.wx.MessageBox(str(exc),'Virtual heatsink',self.wx.OK|self.wx.ICON_WARNING)

    def _remove(self,event):
        index=self.list.GetSelection()
        if index>=0:self.data.pop(sorted(self.data)[index],None);self._refresh()

    def show(self):
        try:return self.data if self.dialog.ShowModal()==self.wx.ID_OK else None
        finally:self.dialog.Destroy()
