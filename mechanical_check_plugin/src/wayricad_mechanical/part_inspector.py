"""Small, read-only part dimension card in the saved CAD coordinate frame."""
import math
import wx
from .inspection_state import height_annotation


def dimension_rows(body):
    bounds=body.get('bounds',[])
    if len(bounds)!=6 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in bounds):
        return [('Dimensions','Unavailable')]
    inspection=body.get('inspection',{})
    dimensions=inspection.get('dimensions_mm') or [bounds[i+3]-bounds[i] for i in range(3)]
    rows=[(f'{axis} extent',f'{value:.4g} mm') for axis,value in zip('XYZ',dimensions)]
    rows.extend((f'{axis} range',f'{bounds[i]:.4g} → {bounds[i+3]:.4g} mm') for i,axis in enumerate('XYZ'))
    center=inspection.get('center_mm')
    rows.append(('Volume centroid',', '.join(f'{v:.4g}' for v in center)+' mm' if center else 'Unavailable'))
    volume=inspection.get('volume_mm3')
    rows.append(('Solid volume',f'{volume:.5g} mm³' if volume is not None else 'Unavailable'))
    if 'edge_count' in inspection:rows.append(('CAD edges',str(inspection['edge_count'])))
    return rows


class PartInspector(wx.PopupTransientWindow):
    def __init__(self,parent,body,palette,findings=()):
        super().__init__(parent,wx.BORDER_SIMPLE)
        ink,muted,background,_=palette
        panel=wx.Panel(self);panel.SetBackgroundColour(background)
        layout=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(panel,label=body['ref'])
        font=title.GetFont();font.SetPointSize(12);font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(font);title.SetForegroundColour(ink)
        header=wx.BoxSizer(wx.HORIZONTAL);header.Add(title,1,wx.ALIGN_CENTER_VERTICAL)
        close=wx.Button(panel,label='Close');close.Bind(wx.EVT_BUTTON,lambda e:self.Dismiss())
        header.Add(close);layout.Add(header,0,wx.EXPAND|wx.BOTTOM,8)
        table=wx.FlexGridSizer(cols=2,vgap=5,hgap=14);table.AddGrowableCol(1)
        rows=dimension_rows(body)
        for issue in findings:
            if height_annotation(issue):
                rows.append((issue.get('side','Component').title()+' height',f"{issue['measured']:.6g} mm / max {issue['limit']:.6g} mm"))
                rows.append(('Over limit',f"+{issue['measured']-issue['limit']:.6g} mm"))
        for name,value in rows:
            for text in (name,value):
                cell=wx.StaticText(panel,label=text);cell.SetForegroundColour(ink);table.Add(cell)
        layout.Add(table,0,wx.EXPAND)
        note_text=('Axis-aligned CAD XYZ extents.\nGeometric volume centroid; density is not used.'
                   if body.get('inspection',{}).get('center_mm') else
                   '2D envelope extents. Physical part height is unavailable.' if body.get('bounds',[0]*6)[5]==body.get('bounds',[0]*6)[2] else
                   'Axis-aligned CAD XYZ extents.\nCentroid and volume unavailable for this body.')
        note=wx.StaticText(panel,label=note_text)
        note.SetForegroundColour(muted);layout.Add(note,0,wx.TOP,10)
        wrapper=wx.BoxSizer(wx.VERTICAL);wrapper.Add(layout,1,wx.ALL,12);panel.SetSizer(wrapper)
        outer=wx.BoxSizer(wx.VERTICAL);outer.Add(panel,1,wx.EXPAND);self.SetSizerAndFit(outer)
