"""Native, keyboard-accessible wxWidgets workflow shared with KiCad."""
import json
import tempfile
import threading
from copy import deepcopy
from pathlib import Path

import wx
import wx.grid as grid
import wx.html

from .config import load, mount_defaults, save, validate
from .findings import finish
from .report import export
from .runner import run
from .runtime import Cancelled, discover
from .viewer import Scene
from .measurement_service import MeasurementSession
from .inspection_state import measurement_text
from .part_inspector import PartInspector
from .extract import is_mounting

INK, MUTED, BG, TEAL = '#243444', '#5c7180', '#f7fafc', '#267269'


def theme_palette(dark):
    """Keep wx-owned surfaces and custom labels in one OS appearance."""
    return ('#eef5f8', '#bacbd4', '#1d252d', '#68d0c0') if dark else (
        '#243444', '#5c7180', '#f7fafc', '#267269')


def label(parent, text, size=11, bold=False, color=None):
    widget = wx.StaticText(parent, label=text)
    font = widget.GetFont()
    font.SetPointSize(size)
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    widget.SetFont(font)
    widget.SetForegroundColour(INK if color is None else color)
    return widget


def button(parent, text, action):
    widget = wx.Button(parent, label=text)
    widget.Bind(wx.EVT_BUTTON, action)
    return widget


class NozzleProfilePreview(wx.Panel):
    """Live, dimensioned side view of the conservative PnP nozzle envelope."""
    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize((-1, 154))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.values = (1.5, 1.5, 0.0, 15.0)
        self.Bind(wx.EVT_PAINT, self.paint)

    def set_profile(self, tip, head, setback, travel):
        self.values = tuple(float(value) for value in (tip, head, setback, travel))
        self.Refresh()

    def paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        self.draw(dc, *self.GetClientSize())

    def draw(self, dc, width, height):
        dc.SetBackground(wx.Brush(BG));dc.Clear()
        if width < 200 or height < 100:return
        tip, head, setback, travel = self.values
        dark = wx.SystemSettings.GetAppearance().IsDark()
        copper = '#d59a53' if dark else '#9a682e'
        nozzle = '#68d0c0' if dark else '#177f83'
        outline = '#a9c1ce' if dark else '#426073'
        centre = min(width * .38, 230)
        pickup_y = height - 32
        top_y = 25
        span = max(1.0, travel)
        setback_y = pickup_y - (pickup_y-top_y)*min(1.0,setback/span)
        radius_scale = min(16.0, (width*.24)/max(1.0,head,tip))
        tip_px = max(3,tip*radius_scale)
        head_px = max(tip_px,head*radius_scale)
        dc.SetPen(wx.Pen(outline,1,wx.PENSTYLE_DOT))
        dc.DrawLine(round(centre),top_y-7,round(centre),pickup_y+8)
        dc.SetPen(wx.Pen(copper,2));dc.DrawLine(20,pickup_y,width-18,pickup_y)
        dc.SetTextForeground(copper);dc.DrawText('Component pickup plane',20,pickup_y+4)
        dc.SetPen(wx.Pen(nozzle,2));dc.SetBrush(wx.Brush(nozzle))
        if setback_y>top_y:
            dc.DrawRectangle(round(centre-head_px),top_y,round(2*head_px),round(setback_y-top_y))
        dc.DrawRectangle(round(centre-tip_px),round(setback_y),round(2*tip_px),round(pickup_y-setback_y))
        dc.SetTextForeground(INK)
        x = round(width*.63)
        for offset, line in enumerate((f'Tip Ø {2*tip:g} mm', f'Head Ø {2*head:g} mm',
                                       f'Head setback {setback:g} mm', f'Access travel {travel:g} mm')):
            dc.DrawText(line,x,20+offset*26)
        dc.SetPen(wx.Pen(outline,1))
        dc.DrawLine(round(centre-head_px),top_y-3,round(centre+head_px),top_y-3)
        dc.DrawLine(round(centre-tip_px),pickup_y-8,round(centre+tip_px),pickup_y-8)


class SectionProfile(wx.Panel):
    """Draw exact FreeCAD section-edge polylines for one selected finding."""
    def __init__(self,parent,section):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.section=section
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((420,320))
        self.Bind(wx.EVT_PAINT,self.paint)

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        dark=wx.SystemSettings.GetAppearance().IsDark()
        dc.SetBackground(wx.Brush('#1d252d' if dark else '#ffffff'));dc.Clear()
        curves=self.section.get('curves',[])
        if not curves:
            dc.SetTextForeground('#bacbd4' if dark else '#243444')
            dc.DrawText(self.section.get('error') or 'No solid intersects this exact plane.',16,16)
            return
        points=[point for curve in curves for point in curve['points']]
        width,height=self.GetClientSize()
        lo=[min(point[i] for point in points) for i in range(2)]
        hi=[max(point[i] for point in points) for i in range(2)]
        scale=min((width-64)/max(hi[0]-lo[0],0.1),(height-64)/max(hi[1]-lo[1],0.1))
        def project(point):
            return (round(32+(point[0]-lo[0])*scale),round(height-32-(point[1]-lo[1])*scale))
        for curve in curves:
            dc.SetPen(wx.Pen('#2d9e95' if curve['ref']=='A' else '#d28b42',2))
            coords=[project(point) for point in curve['points']]
            if len(coords)>1:dc.DrawLines(coords)
        dc.SetTextForeground('#bacbd4' if dark else '#243444')
        dc.DrawText('Current board',16,8)
        dc.DrawText('Comparison board',130,8)
        dc.DrawText('Scale: %.2f px/mm' % scale,16,height-22)


class Window(wx.Frame):
    def __init__(self, board_path=None, rules_path=None, live_board=None, snapshot_of=None):
        global INK, MUTED, BG, TEAL
        INK, MUTED, BG, TEAL = theme_palette(wx.SystemSettings.GetAppearance().IsDark())
        super().__init__(None, title='WayriCAD Mechanical Check — Board validation', size=(1160, 820))
        self.SetMinSize((980, 680))
        self.SetBackgroundColour(BG)
        icon=Path(__file__).resolve().parents[2]/'resources/icon-24.png'
        if icon.exists():self.SetIcon(wx.Icon(str(icon),wx.BITMAP_TYPE_PNG))
        self.config = load(rules_path)
        self.rules_path = rules_path
        self.live_board = live_board
        self.snapshot_of = snapshot_of
        self.board_path = str(board_path or (live_board.GetFileName() if live_board else ''))
        self.result = None
        self.running = False
        self._closing=False;self.live_temp=None
        self.measurement_session=None;self.measuring=False
        self.part_inspector=None
        self.measure_cancel=threading.Event();self.measure_generation=0
        self.cancel = threading.Event()
        self.mount_rows = []
        self.filtered = []
        self.step = 0
        root = wx.Panel(self);root.SetBackgroundColour(BG)
        layout = wx.BoxSizer(wx.VERTICAL)
        navigation = wx.BoxSizer(wx.HORIZONTAL)
        navigation.Add(label(root, 'Mechanical Check', 12, True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 18)
        self.nav_buttons=[]
        for i, title in enumerate(['Board', 'Rules', 'Run', 'Review', 'Report']):
            control=button(root,title,lambda e,n=i:self.show_step(n))
            navigation.Add(control,0,wx.RIGHT,5)
            self.nav_buttons.append(control)
        navigation.AddStretchSpacer()
        navigation.Add(button(root,'Help',self.help))
        layout.Add(navigation,0,wx.EXPAND|wx.ALL,12)
        content=wx.Panel(root);content.SetBackgroundColour(BG)
        vertical=wx.BoxSizer(wx.VERTICAL)
        header=wx.BoxSizer(wx.HORIZONTAL)
        self.heading=label(content,'Board',14,True)
        header.Add(self.heading,1,wx.ALIGN_CENTER_VERTICAL)
        header.Add(label(content,'Saved board · millimetres',10,False,MUTED),0,wx.ALIGN_CENTER_VERTICAL)
        vertical.Add(header,0,wx.EXPAND|wx.ALL,12)
        self.book=wx.Simplebook(content)
        self.pages=[]
        for _ in range(5):
            page=wx.Panel(self.book)
            page.SetBackgroundColour(BG)
            self.book.AddPage(page,'')
            self.pages.append(page)
        self.board_page()
        self.rules_page()
        self.run_page()
        self.review_page()
        self.report_page()
        vertical.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.status=label(content,'Checks the saved file. Save PCB edits before running.',10,False,MUTED)
        footer.Add(self.status,1,wx.ALIGN_CENTER_VERTICAL)
        self.back=button(content,'Back',lambda e:self.show_step(max(0,self.step-1)))
        self.next=button(content,'Continue',lambda e:self.show_step(min(4,self.step+1)))
        footer.Add(self.back,0,wx.RIGHT,10)
        footer.Add(self.next)
        vertical.Add(footer,0,wx.EXPAND|wx.ALL,12)
        content.SetSizer(vertical)
        layout.Add(content,1,wx.EXPAND)
        root.SetSizer(layout)
        self.Bind(wx.EVT_CLOSE,self.close)
        self.load_board()
        if snapshot_of:
            self.file.Disable()
            self.status.SetLabel('IPC snapshot captured at launch — reopen WayriCAD Mechanical Check after editing the PCB')
        self.show_step(0)
        self.Centre()

    def board_page(self):
        p=self.pages[0]; s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Choose the saved board to check.',12,True),0,wx.BOTTOM,12)
        s.Add(label(p,'Inspect solid interference, fasteners, height allowances and assembly access.\nThe report records exactly what was checked and what needs more information.',11,False,MUTED),0,wx.BOTTOM,28)
        s.Add(label(p,'BOARD FILE',9,True,MUTED),0,wx.BOTTOM,8)
        self.file=wx.FilePickerCtrl(p,path=self.board_path,message='Choose a KiCad board',wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',style=wx.FLP_OPEN|wx.FLP_FILE_MUST_EXIST|wx.FLP_USE_TEXTCTRL)
        self.file.Enable(self.live_board is None)
        self.file.Bind(wx.EVT_FILEPICKER_CHANGED,lambda e:self.load_board())
        s.Add(self.file,0,wx.EXPAND|wx.BOTTOM,14)
        s.Add(label(p,'COMPARISON BOARD — OPTIONAL',9,True,MUTED),0,wx.BOTTOM,5)
        self.comparison_file=wx.FilePickerCtrl(p,path=(self.config['comparison_board'] or {}).get('path',''),
            message='Choose another KiCad board',wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',
            style=wx.FLP_OPEN|wx.FLP_FILE_MUST_EXIST|wx.FLP_USE_TEXTCTRL)
        self.comparison_file.Bind(wx.EVT_FILEPICKER_CHANGED,lambda e:self.load_board())
        s.Add(self.comparison_file,0,wx.EXPAND|wx.BOTTOM,6)
        placement=wx.BoxSizer(wx.HORIZONTAL)
        self.comparison_position={}
        saved=(self.config['comparison_board'] or {}).get('translation_mm',[0,0,0])
        for index,axis in enumerate('XYZ'):
            placement.Add(label(p,axis+' (mm)'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
            control=wx.SpinCtrlDouble(p,min=-100000,max=100000,inc=1,initial=saved[index]);control.SetDigits(3)
            placement.Add(control,1,wx.RIGHT,10)
            self.comparison_position[axis]=control
        placement.Add(label(p,'Z rotation (°)'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
        self.comparison_rotation=wx.SpinCtrlDouble(p,min=-360,max=360,inc=5,
            initial=(self.config['comparison_board'] or {}).get('rotation_deg',0));self.comparison_rotation.SetDigits(2)
        placement.Add(self.comparison_rotation,1)
        s.Add(placement,0,wx.EXPAND|wx.BOTTOM,8)
        s.Add(label(p,'Position relative to the current board’s KiCad STEP export origin. Save both boards before checking.',10,False,MUTED),0,wx.BOTTOM,14)
        form=wx.FlexGridSizer(cols=2,hgap=18,vgap=14);form.AddGrowableCol(1)
        self.project=wx.TextCtrl(p,value=self.config['project_name'])
        self.revision=wx.TextCtrl(p,value=self.config['project_revision'])
        self.reviewer=wx.TextCtrl(p,value=self.config['reviewer'])
        for title,control in [('Project name',self.project),('Revision / build',self.revision),('Reviewer',self.reviewer)]:
            form.Add(label(p,title),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        s.Add(form,0,wx.EXPAND|wx.BOTTOM,25)
        self.board_stats=label(p,'Choose a board to inspect its model inventory.',12,True)
        s.Add(self.board_stats,0,wx.BOTTOM,18)
        runtime=discover()
        self.mode=wx.Choice(p,choices=['Quick 2D footprint screen (no FreeCAD)', 'Exact 3D solids (FreeCAD)'])
        self.mode.SetSelection(0 if self.config['mode']=='quick2d' else 1)
        s.Add(self.mode,0,wx.EXPAND|wx.BOTTOM,12)
        s.Add(label(p,'GEOMETRY ENGINE',9,True,MUTED),0,wx.BOTTOM,8)
        s.Add(label(p,'KiCad STEP exporter + FreeCAD / Open CASCADE\n'+('Executables found — Run checks runtime compatibility' if all(runtime.values()) else 'Setup needed — open Help'),11,False,MUTED),0,wx.BOTTOM,15)
        s.AddStretchSpacer()
        s.Add(label(p,'Missing STEP models are reported as coverage gaps. They never count as a pass.',10,False,TEAL),0,wx.BOTTOM,20)
        p.SetSizer(s)

    def rules_page(self):
        p=self.pages[1]; s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Set the physical limits for this assembly.',14,True),0,wx.BOTTOM,14)
        s.Add(label(p,'Global board limits',12,True),0,wx.BOTTOM,8)
        fields=wx.FlexGridSizer(cols=4,vgap=10,hgap=14);fields.AddGrowableCol(1);fields.AddGrowableCol(3)
        self.numbers={}
        for title,key in [('Max top height','top_height_mm'),('Max bottom height','bottom_height_mm'),
                          ('3D clearance','clearance_mm'),('Proximity warning','proximity_warning_mm')]:
            control=wx.SpinCtrlDouble(p,min=0,max=10000,inc=.1,initial=self.config.get(key,0));control.SetDigits(3)
            fields.Add(label(p,title+' (mm)'),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND)
            self.numbers[key]=control
        s.Add(fields,0,wx.EXPAND|wx.BOTTOM,8)
        s.Add(label(p,'Height is measured outward from each PCB face, including opposite-side protrusions.\nProximity warning: 0 = off. Quick 2D checks footprint gaps; heights require 3D models.',10,False,MUTED),0,wx.BOTTOM,14)
        fields=wx.FlexGridSizer(cols=4,vgap=10,hgap=14);fields.AddGrowableCol(1);fields.AddGrowableCol(3)
        for title,key in [('Horizontal allowance','xy_clearance_mm'),('Vertical allowance','z_clearance_mm'),('PnP tip radius','nozzle_radius_mm'),('Hardware clearance','screw_clearance_mm'),('PnP head radius','nozzle_head_radius_mm'),('PnP head setback','nozzle_head_setback_mm'),('Nozzle travel','nozzle_travel_mm')]:
            control=wx.SpinCtrlDouble(p,min=0,max=10000,inc=.1,initial=self.config[key]);control.SetDigits(3)
            fields.Add(label(p,title+' (mm)'),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND)
            self.numbers[key]=control
        s.Add(fields,0,wx.EXPAND|wx.BOTTOM,14)
        section_row=wx.BoxSizer(wx.HORIZONTAL)
        section_row.Add(label(p,'Custom section normal',10,True),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
        self.section_normal_inputs={}
        for axis,value in zip('XYZ',self.config['section_normal']):
            section_row.Add(label(p,axis),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
            control=wx.SpinCtrlDouble(p,min=-1000,max=1000,inc=.1,initial=value);control.SetDigits(3)
            section_row.Add(control,1,wx.RIGHT,9)
            self.section_normal_inputs[axis]=control
        s.Add(section_row,0,wx.EXPAND|wx.BOTTOM,5)
        s.Add(label(p,'The custom plane cuts through each selected contact or close approach; X/Y/Z sections are always generated too.',10,False,MUTED),0,wx.BOTTOM,12)
        self.nozzle_preview=NozzleProfilePreview(p)
        s.Add(self.nozzle_preview,0,wx.EXPAND|wx.BOTTOM,8)
        s.Add(label(p,'PnP nozzle: vertical circular tip and wider head. The diagram is a screening envelope; confirm actual tooling and pickup offset with the assembler.',10,False,MUTED),0,wx.BOTTOM,12)
        for key in ('nozzle_radius_mm','nozzle_head_radius_mm','nozzle_head_setback_mm','nozzle_travel_mm'):
            self.numbers[key].Bind(wx.EVT_SPINCTRLDOUBLE,self.refresh_nozzle)
            self.numbers[key].Bind(wx.EVT_TEXT,self.refresh_nozzle)
        self.refresh_nozzle()
        self.dnp=wx.CheckBox(p,label='Include components marked Do Not Populate')
        self.dnp.SetValue(self.config['include_dnp']);s.Add(self.dnp,0,wx.BOTTOM,16)
        s.Add(label(p,'Mounting intent',13,True),0,wx.BOTTOM,5)
        s.Add(label(p,'Confirm each hole. Dimensions below describe your actual hardware, not a certified screw standard.',10,False,MUTED),0,wx.BOTTOM,10)
        self.mount_grid=grid.Grid(p)
        self.mount_grid.CreateGrid(0,9)
        for i,title in enumerate(['Ref','Actual','Required','Side','Head Ø','Washer Ø','Height','Shaft Ø','Tool R']):
            self.mount_grid.SetColLabelValue(i,title)
            self.mount_grid.SetColSize(i,90 if i!=2 else 112)
        self.mount_grid.SetRowLabelSize(0)
        if wx.SystemSettings.GetAppearance().IsDark():
            self.mount_grid.SetDefaultCellBackgroundColour('#202a32')
            self.mount_grid.SetDefaultCellTextColour(INK)
            self.mount_grid.SetLabelBackgroundColour('#28343d')
            self.mount_grid.SetLabelTextColour(INK)
            self.mount_grid.SetGridLineColour('#465865')
        s.Add(self.mount_grid,1,wx.EXPAND|wx.BOTTOM,12)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        for title,fn in [('Load rules…',self.import_rules),('Save rules…',self.save_rules),('Zones / enclosure / advanced…',self.advanced)]:
            actions.Add(button(p,title,fn),0,wx.RIGHT,8)
        s.Add(actions,0,wx.BOTTOM,10)
        p.SetSizer(s)

    def run_page(self):
        p=self.pages[2];s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'A complete mechanical review, with traceable evidence.',15,True),0,wx.TOP|wx.BOTTOM,18)
        for title,desc in [('01   Model coverage','Resolve STEP files and preserve KiCad placement, rotations and board side.'),('02   Physical fit','Measure solid interference, clearances, height limits and PCB penetration.'),('03   Hardware & assembly','Review plating intent, screw envelopes, nearby pads and nozzle access.')]:
            s.Add(label(p,title,13,True),0,wx.TOP,22);s.Add(label(p,desc,11,False,MUTED),0,wx.TOP,7)
        self.progress=wx.Gauge(p,range=100)
        s.Add(self.progress,0,wx.EXPAND|wx.TOP,30)
        self.progress_text=label(p,'Ready when you are.',11,False,TEAL);s.Add(self.progress_text,0,wx.TOP,12)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.run_button=button(p,'Run selected check',self.start)
        self.run_button.SetMinSize((200,44))
        self.cancel_button=button(p,'Cancel',lambda e:self.cancel.set());self.cancel_button.Disable()
        row.Add(self.run_button,0,wx.RIGHT,12);row.Add(self.cancel_button,0,wx.ALIGN_CENTER_VERTICAL)
        s.Add(row,0,wx.TOP,24);s.AddStretchSpacer()
        p.SetSizer(s)

    def review_page(self):
        p=self.pages[3];s=wx.BoxSizer(wx.VERTICAL)
        toolbar=wx.BoxSizer(wx.HORIZONTAL)
        self.geometry_mode=label(p,'No geometry loaded',10,True)
        toolbar.Add(self.geometry_mode,1,wx.ALIGN_CENTER_VERTICAL)
        self.view_3d=button(p,'Load 3D models',self.show_3d)
        self.view_3d.SetToolTip('Run exact STEP analysis using KiCad and FreeCAD, then orbit the solid assembly.')
        toolbar.Add(self.view_3d,0,wx.RIGHT,5)
        for name,title in [('top','Top'),('bottom','Bottom'),('side','Side')]:
            toolbar.Add(button(p,title,lambda e,n=name:self.view(n)),0,wx.RIGHT,5)
        toolbar.Add(button(p,'Fit',lambda e:self.scene.fit()),0)
        s.Add(toolbar,0,wx.EXPAND|wx.BOTTOM,6)
        self.review_split=split=wx.SplitterWindow(p,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        left=wx.Panel(split);left.SetBackgroundColour(BG);ls=wx.BoxSizer(wx.VERTICAL)
        self.scene=Scene(left);ls.Add(self.scene,1,wx.EXPAND)
        left.SetSizer(ls)
        right=wx.Panel(split);right.SetBackgroundColour(BG);rs=wx.BoxSizer(wx.VERTICAL)
        self.summary=label(right,'Run validation to see findings.',10,True)
        rs.Add(self.summary,0,wx.EXPAND|wx.BOTTOM,6)
        tools=wx.BoxSizer(wx.HORIZONTAL)
        self.measure_mode=wx.Choice(right,choices=['Select / orbit','Minimum part gap','Point → point',
                                                  'Edge → edge','Point → edge','Body center → center'])
        self.measure_mode.SetSelection(0);self.measure_mode.Bind(wx.EVT_CHOICE,self.change_measure_mode)
        tools.Add(self.measure_mode,1,wx.RIGHT,5)
        tools.Add(button(right,'Clear',self.clear_rulers))
        rs.Add(tools,0,wx.EXPAND|wx.BOTTOM,6)
        self.part_panel=wx.Panel(right);pairs=wx.BoxSizer(wx.HORIZONTAL)
        self.part_a=wx.ComboBox(self.part_panel);self.part_b=wx.ComboBox(self.part_panel)
        self.part_a.SetHint('First part');self.part_b.SetHint('Second part')
        pairs.Add(self.part_a,1,wx.RIGHT,4);pairs.Add(self.part_b,1,wx.RIGHT,4)
        self.measure_button=button(self.part_panel,'Measure',self.measure_selected_parts)
        pairs.Add(self.measure_button)
        self.edge_panel=wx.Panel(self.part_panel);edges=wx.BoxSizer(wx.HORIZONTAL)
        self.edge_a=wx.SpinCtrl(self.edge_panel,min=1,max=100000,initial=1,size=(70,-1))
        self.edge_b=wx.SpinCtrl(self.edge_panel,min=1,max=100000,initial=1,size=(70,-1))
        for title,control in [('Edge A',self.edge_a),('Edge B',self.edge_b)]:
            edges.Add(label(self.edge_panel,title,9),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
            edges.Add(control,1,wx.RIGHT,5)
        self.edge_panel.SetSizer(edges)
        pair_layout=wx.BoxSizer(wx.VERTICAL);pair_layout.Add(pairs,0,wx.EXPAND)
        pair_layout.Add(self.edge_panel,0,wx.EXPAND|wx.TOP,5);self.edge_panel.Hide()
        self.part_panel.SetSizer(pair_layout)
        rs.Add(self.part_panel,0,wx.EXPAND|wx.BOTTOM,6);self.part_panel.Hide()
        self.measure_readout=wx.TextCtrl(right,value='Hover a part for closest approach. Select a ruler tool to measure.',
                                       style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_SIMPLE,size=(-1,100))
        rs.Add(self.measure_readout,0,wx.EXPAND|wx.BOTTOM,6)
        self.scene.on_measure=self.measure_pair
        self.scene.on_pick=self.scene_picked
        self.scene.on_hover=self.scene_hovered
        self.scene.on_ruler=self.point_ruler
        self.scene.on_features=self.measure_features
        tabs=wx.Notebook(right)
        findings=wx.Panel(tabs);findings.SetBackgroundColour(BG);fs=wx.BoxSizer(wx.VERTICAL)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.search=wx.SearchCtrl(findings,style=wx.TE_PROCESS_ENTER);self.search.SetDescriptiveText('Search findings')
        self.search.Bind(wx.EVT_TEXT,self.filter_findings)
        self.severity=wx.Choice(findings,choices=['All','Errors','Warnings','Waived']);self.severity.SetSelection(0);self.severity.Bind(wx.EVT_CHOICE,self.filter_findings)
        row.Add(self.search,1,wx.RIGHT,5);row.Add(self.severity)
        fs.Add(row,0,wx.EXPAND|wx.BOTTOM,6)
        self.list=wx.ListCtrl(findings,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.list.SetBackgroundColour(BG);self.list.SetForegroundColour(INK)
        for i,(title,width) in enumerate([('Level',65),('Parts',75),('Finding',280)]):self.list.InsertColumn(i,title,width=width)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_finding)
        fs.Add(self.list,1,wx.EXPAND)
        self.detail=wx.TextCtrl(findings,style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_SIMPLE,size=(-1,130))
        fs.Add(self.detail,0,wx.EXPAND|wx.TOP,6)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        for title,action in [('Locate',self.locate),('Waiver…',self.waive),('Coverage…',self.coverage)]:
            actions.Add(button(findings,title,action),0,wx.RIGHT|wx.TOP,4)
        fs.Add(actions,0,wx.EXPAND|wx.TOP,4);findings.SetSizer(fs)
        tabs.AddPage(findings,'Findings')
        display=wx.ScrolledWindow(tabs);display.SetBackgroundColour(BG);display.SetScrollRate(0,12)
        ds=wx.BoxSizer(wx.VERTICAL)
        controls=wx.WrapSizer(wx.HORIZONTAL)
        controls.Add(button(display,'Focus contact',lambda e:self.scene.focus_contact()),0,wx.RIGHT,5)
        controls.Add(button(display,'Isometric',lambda e:self.view('iso')))
        ds.Add(controls,0,wx.TOP|wx.BOTTOM,8)
        ds.Add(button(display,'Save view…',self.save_view),0,wx.BOTTOM,10)
        for title,key,initial in [('Violation / proximity markers','alert_markers',True),('Isolate selected parts','isolate',False),('Transparent PCB','ghost',False),('Cutaway PCB','section',False),('Grid','grid',False),('Selected / hovered references','labels',True)]:
            control=wx.CheckBox(display,label=title);control.SetValue(initial)
            control.Bind(wx.EVT_CHECKBOX,lambda e,k=key:(setattr(self.scene,k,e.IsChecked()),self.scene.Refresh()))
            ds.Add(control,0,wx.BOTTOM,8)
        self.ortho=wx.CheckBox(display,label='Orthographic')
        self.ortho.Bind(wx.EVT_CHECKBOX,lambda e:(setattr(self.scene,'orthographic',e.IsChecked()),self.scene.Refresh(False)))
        ds.Add(self.ortho,0,wx.BOTTOM,12)
        ds.Add(label(display,'Section plane',10,True),0,wx.BOTTOM,6)
        sections=wx.BoxSizer(wx.HORIZONTAL)
        self.section_axis=wx.Choice(display,choices=['X','Y','Z','Custom'])
        self.section_axis.SetSelection(1)
        self.section_axis.Bind(wx.EVT_CHOICE,self.change_section_axis)
        sections.Add(self.section_axis,0,wx.RIGHT,8)
        self.section_offset=wx.SpinCtrlDouble(display,min=-100000,max=100000,inc=.1,initial=0)
        self.section_offset.SetDigits(2)
        self.section_offset.Bind(wx.EVT_SPINCTRLDOUBLE,self.change_section_offset)
        sections.Add(label(display,'mm',10),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
        sections.Add(self.section_offset,1,wx.RIGHT,8)
        ds.Add(sections,0,wx.EXPAND|wx.BOTTOM,8)
        ds.Add(button(display,'2D section…',self.show_section_profile),0,wx.BOTTOM,12)
        self.scene_legend=label(display,'Rulers show through surfaces.\nCAD XYZ, millimetres.',9,False,MUTED)
        ds.Add(self.scene_legend,0,wx.BOTTOM,8);display.SetSizer(ds)
        tabs.AddPage(display,'Display');rs.Add(tabs,1,wx.EXPAND)
        right.SetSizer(rs);split.SetMinimumPaneSize(300);split.SetSashGravity(1)
        split.SplitVertically(left,right,800)
        s.Add(split,1,wx.EXPAND)
        p.SetSizer(s)

    def report_page(self):
        p=self.pages[4];s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Share the review with your mechanical and assembly teams.',15,True),0,wx.BOTTOM,18)
        s.Add(label(p,'Each export creates a new project + UTC timestamp folder.\nThe interactive HTML report works offline; JSON preserves the complete run and CSV lists findings.',11,False,MUTED),0,wx.BOTTOM,20)
        self.report_info=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,260))
        s.Add(self.report_info,1,wx.EXPAND|wx.BOTTOM,18)
        self.export_button=button(p,'Export HTML + JSON + CSV…',self.export_report)
        self.export_button.SetMinSize((270,45));s.Add(self.export_button,0,wx.BOTTOM,20)
        p.SetSizer(s)

    def load_board(self):
        self.reset_measurement_session()
        path=self.file.GetPath()
        self.board_path=path
        self.result=None
        self.export_button.Disable()
        self.list.DeleteAllItems()
        self.detail.Clear()
        self.report_info.Clear()
        self.summary.SetLabel('Run validation to see findings for this board.')
        self.scene.set_report({'bodies': []})
        self.part_a.Clear();self.part_b.Clear()
        if not path and not self.live_board:return
        try:
            import pcbnew as pcb
            board=self.live_board or pcb.LoadBoard(path)
            footprints=list(board.GetFootprints())
            count=sum(bool(list(f.Models())) for f in footprints)
            self.board_stats.SetLabel(f'{len(footprints):,} footprints    ·    {count:,} with model assignments    ·    {pcb.ToMM(board.GetDesignSettings().GetBoardThickness()):.2f} mm board')
            if not self.project.GetValue():self.project.SetValue(Path(path).stem)
            rows=[]
            for fp in footprints:
                if is_mounting(fp,self.config['mounts']):
                    for pad in fp.Pads():
                        if max(pad.GetDrillSize().x,pad.GetDrillSize().y):
                            rows.append((fp.GetReference(),'NPTH' if pad.GetAttribute()==pcb.PAD_ATTRIB_NPTH else 'PTH'))
                            break
            self.fill_mounts(sorted(rows))
            self.result=None
        except Exception as exc:
            self.board_stats.SetLabel('Could not read board: '+str(exc))

    def fill_mounts(self,rows):
        self.mount_rows=rows
        g=self.mount_grid
        if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
        if not rows:return
        g.AppendRows(len(rows))
        for row,(ref,actual) in enumerate(rows):
            m=self.config['mounts'].get(ref,mount_defaults())
            vals=[ref,actual,m['expected_plating'] if ref in self.config['mounts'] else 'Unconfirmed',m.get('side','top'),m.get('head_diameter_mm',0),m.get('washer_diameter_mm',0),m.get('head_height_mm',0),m.get('shaft_diameter_mm',0),m.get('tool_radius_mm',0)]
            for col,val in enumerate(vals):g.SetCellValue(row,col,str(val))
            g.SetReadOnly(row,0);g.SetReadOnly(row,1)
            g.SetCellEditor(row,2,grid.GridCellChoiceEditor(['Unconfirmed','NPTH','PTH','either']))
            g.SetCellEditor(row,3,grid.GridCellChoiceEditor(['top','bottom','both']))
            for col in range(4,9):g.SetCellEditor(row,col,grid.GridCellFloatEditor(precision=3))

    def refresh_nozzle(self, event=None):
        try:
            self.nozzle_preview.set_profile(*(self.numbers[key].GetValue() for key in (
                'nozzle_radius_mm','nozzle_head_radius_mm','nozzle_head_setback_mm','nozzle_travel_mm')))
        except (TypeError, ValueError):
            pass  # Native spin controls may briefly contain incomplete typed text.
        if event is not None:event.Skip()

    def get_config(self):
        if self.mount_grid.IsCellEditControlEnabled():
            self.mount_grid.SaveEditControlValue();self.mount_grid.DisableCellEditControl()
        c=deepcopy(self.config)
        c.update(project_name=self.project.GetValue().strip(),project_revision=self.revision.GetValue().strip(),reviewer=self.reviewer.GetValue().strip(),include_dnp=self.dnp.GetValue())
        c['mode']='quick2d' if self.mode.GetSelection()==0 else 'exact3d'
        path=self.comparison_file.GetPath().strip()
        c['comparison_board']=(dict(path=path,translation_mm=[self.comparison_position[axis].GetValue() for axis in 'XYZ'],
                                    rotation_deg=self.comparison_rotation.GetValue()) if path else None)
        c.update({key:control.GetValue() for key,control in self.numbers.items()})
        c['section_normal']=[self.section_normal_inputs[axis].GetValue() for axis in 'XYZ']
        c['mounts']={}
        for row,(ref,actual) in enumerate(self.mount_rows):
            expected=self.mount_grid.GetCellValue(row,2)
            if expected=='Unconfirmed':continue
            m=dict(expected_plating=expected,side=self.mount_grid.GetCellValue(row,3))
            for col,key in enumerate(['head_diameter_mm','washer_diameter_mm','head_height_mm','shaft_diameter_mm','tool_radius_mm'],4):m[key]=float(self.mount_grid.GetCellValue(row,col))
            c['mounts'][ref]=m
        return validate(c)

    def show_step(self,n):
        if self.running and n!=2:return
        self.step=n;self.book.SetSelection(n)
        for index, control in enumerate(self.nav_buttons): control.Enable(index != n and not self.running)
        self.heading.SetLabel(['Board and project','Clearance and hardware rules','Run mechanical checks','Review findings','Export local report'][n])
        self.back.Enable(n>0 and not self.running);self.next.Enable(n<4 and not self.running)
        self.export_button.Enable(self.result is not None)
        self.Layout()

    def start(self,event):
        if self.running:return
        try:
            config=self.get_config()
            if not self.board_path and not self.live_board:raise ValueError('Choose a board first.')
            self.config=config
            path=self.board_path
            self.reset_measurement_session()
            self.measurement_session=MeasurementSession()
            session=self.measurement_session
            self.live_temp=None
            if self.live_board:
                import pcbnew
                self.live_temp=tempfile.TemporaryDirectory(prefix='wayricad-mechanical-live-')
                path=str(Path(self.live_temp.name)/'live.kicad_pcb')
                original=self.live_board.GetFileName()
                try:
                    if not pcbnew.SaveBoard(path,self.live_board):raise RuntimeError('Could not capture live board')
                finally:self.live_board.SetFileName(original)
            self.running=True;self.cancel.clear();self.result=None
            self.pages[0].Disable();self.pages[1].Disable();self.export_button.Disable()
            self.scene.set_report({'bodies':[]})
            self.show_step(2);self.run_button.Disable();self.cancel_button.Enable()
            self.status.SetLabel('Validation running — your board remains editable')
            def worker():
                try:
                    result=run(path,config,lambda value,message:self.dispatch(self.update_progress,value,message),self.cancel,Path(self.snapshot_of or self.board_path).resolve().parent if self.board_path else None,measurement_session=session)
                    if self.live_board:
                        result.update(board_name=Path(self.board_path).name or 'Unsaved board',board_path=self.board_path,source_kind='live editor snapshot')
                    elif self.snapshot_of:
                        result.update(board_name=Path(self.snapshot_of).name,board_path=self.snapshot_of,source_kind='IPC snapshot captured at launch')
                    self.dispatch(self.completed,result,None)
                except Exception as exc:self.dispatch(self.completed,None,exc)
            threading.Thread(target=worker,daemon=True).start()
        except Exception as exc:wx.MessageBox(str(exc),'Check setup',wx.OK|wx.ICON_WARNING,self)

    def update_progress(self,value,message):
        self.progress.SetValue(value);self.progress_text.SetLabel(message)

    def completed(self,result,error):
        self.running=False;self.run_button.Enable();self.cancel_button.Disable()
        self.pages[0].Enable();self.pages[1].Enable()
        if error:
            self.reset_measurement_session()
            self.progress_text.SetLabel('Cancelled.' if isinstance(error,Cancelled) else 'Validation could not finish.')
            self.status.SetLabel('No completed report is available')
            if not isinstance(error,Cancelled):wx.MessageBox(str(error),'Validation error',wx.OK|wx.ICON_ERROR,self)
            self.show_step(2);return
        self.result=result;self.scene.set_report(result);self.refresh_result();self.show_step(3)
        self.measure_mode.SetSelection(0);self.change_measure_mode(None)
        self.scene.fit()

    def refresh_result(self):
        r=self.result
        self.scene.inspection.update_findings(r['findings'])
        quick=r['rules'].get('mode')=='quick2d'
        self.geometry_mode.SetLabel('2D footprint envelopes · heights unchecked' if quick else '3D STEP solids · drag to orbit')
        self.view_3d.SetLabel('Load 3D models' if quick else '3D view')
        self.ortho.SetValue(self.scene.orthographic)
        self.scene_legend.SetLabel('2D footprint envelopes; heights unchecked.\nGold: proximity / envelope warnings · CAD XYZ, mm' if r['rules'].get('mode')=='quick2d' else 'Red: collision / height limit · Gold: proximity warning\nHeight labels show excess above the limit · CAD XYZ, mm')
        refs=sorted({body['ref'] for body in r['bodies'] if body['kind'] not in ('hardware envelope','hole allowance')})
        self.part_a.SetItems(refs);self.part_b.SetItems(refs)
        self.part_a.AutoComplete(refs);self.part_b.AutoComplete(refs)
        self.summary.SetLabel(f"{r['status'].replace('_',' ').upper()} · {len(r['findings'])} findings\n{len(r['coverage']['gaps'])} coverage gaps")
        self.status.SetLabel('Completed '+r['local_timestamp'][:19].replace('T',' '))
        self.report_info.SetValue(f"Project: {r['project_name']}\nRevision: {r['project_revision'] or 'Unspecified'}\nBoard: {r['board_name']}\nReviewer: {r['reviewer'] or 'Unspecified'}\n\nStarted (UTC): {r['started_at']}\nCompleted (UTC): {r['completed_at']}\nLocal time: {r['local_timestamp']}\nDuration: {r['duration_seconds']} s\n\nResult: {r['status']}\nBoard SHA-256: {r['board_sha256']}\n\nEvery finding includes rule, affected references, evidence, measurement, corrective action and waiver reason.")
        self.filter_findings();self.export_button.Enable()

    def filter_findings(self,event=None):
        if not self.result:return
        self.list.DeleteAllItems();self.filtered=[]
        query=self.search.GetValue().lower();severity=self.severity.GetSelection()
        for f in self.result['findings']:
            if query and query not in json.dumps(f).lower():continue
            if severity==1 and f['severity']!='error' or severity==2 and f['severity']!='warning' or severity==3 and not f['waiver']:continue
            self.filtered.append(f)
            i=self.list.InsertItem(self.list.GetItemCount(),'Waived' if f['waiver'] else f['severity'].title())
            self.list.SetItem(i,1,', '.join(f['refs']));self.list.SetItem(i,2,f['summary'])
        if self.filtered:self.list.Select(0)
        else:self.detail.SetValue('No findings match this filter. Review model coverage before accepting the run.')

    def selected(self):
        index=self.list.GetFirstSelected()
        return self.filtered[index] if 0<=index<len(self.filtered) else None

    def select_finding(self,event):
        f=self.filtered[event.GetIndex()];self.scene.select(f)
        limit_title='Maximum' if f['rule'].startswith('height.') else 'Warning below' if f['rule'].endswith('proximity_warning') else 'Required'
        measurement='' if f['measured'] is None else f"\nMeasured: {f['measured']:.6g} {f.get('unit','')}" + (f"   {limit_title}: {f['limit']} {f.get('unit','')}" if f['limit'] is not None else '')
        if f.get('excess_mm') is not None:measurement+=f"\nOver limit: +{f['excess_mm']:.6g} mm ({f.get('side','')} side)"
        self.detail.SetValue(f"{f['summary']}\n{f['rule']}  ·  Evidence: {f['evidence']}  ·  {', '.join(f['refs'])}{measurement}\n{f['action']}\n"+('Waiver: '+f['waiver'] if f['waiver'] else ''))

    def change_section_axis(self,event):
        axis=self.section_axis.GetStringSelection()
        self.scene.section_normal=(self.result['rules']['section_normal'] if axis=='Custom' and self.result else
                                   [self.section_normal_inputs[key].GetValue() for key in 'XYZ'] if axis=='Custom' else
                                   [[1,0,0],[0,1,0],[0,0,1]]['XYZ'.index(axis)])
        self.scene.Refresh()

    def change_section_offset(self,event):
        self.scene.section_offset=self.section_offset.GetValue()
        self.scene.Refresh()

    def show_section_profile(self,event):
        finding=self.selected()
        if not finding or not finding.get('sections'):
            wx.MessageBox('Select an interboard collision or close approach first.','2D section',wx.OK,self)
            return
        axis=self.section_axis.GetStringSelection()
        section=finding['sections'][axis]
        dlg=wx.Dialog(self,title=f"{axis} section — {', '.join(finding['refs'])}",size=(760,600),
                      style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        position=(f"{axis} = {section['coordinate']} mm" if axis!='Custom' else f"Normal {section['normal']}")
        layout.Add(label(dlg,f"{position} · axes {', '.join(section.get('axes',[]))} (mm)",11,True),0,wx.ALL,12)
        profile=SectionProfile(dlg,section)
        layout.Add(profile,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        layout.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALL|wx.ALIGN_RIGHT,12)
        dlg.SetSizer(layout);dlg.ShowModal();dlg.Destroy()

    def set_view(self,yaw,pitch):
        self.view('top' if pitch==0 else 'iso')

    def view(self,name):
        self.scene.set_view(name);self.ortho.SetValue(self.scene.orthographic)

    def show_3d(self,event=None):
        if self.running:return
        if self.result and self.result['rules'].get('mode')=='exact3d':
            self.view('iso');self.scene.fit();return
        self.mode.SetSelection(1)
        if not discover()['freecad_python']:
            self.show_step(0)
            self.status.SetLabel('3D setup: FreeCAD Python was not found. Open Help for installation and path overrides.')
            return
        self.start(event)

    def save_view(self,event=None):
        with wx.FileDialog(self,'Save board view',wildcard='PNG image (*.png)|*.png',
                           defaultFile='mechanical-view.png',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:
                self.scene.Refresh(False);self.scene.Update()
                if not self.scene.snapshot().SaveFile(dialog.GetPath(),wx.BITMAP_TYPE_PNG):
                    raise RuntimeError('Could not save the image.')
                self.status.SetLabel('Board view saved as an opaque PNG image.')
            except Exception as exc:wx.MessageBox(str(exc),'Save board view',wx.OK|wx.ICON_ERROR,self)

    def dispatch(self,callback,*args):
        def guarded():
            if not self._closing and self:callback(*args)
        wx.CallAfter(guarded)

    def reset_measurement_session(self):
        if self.part_inspector:self.part_inspector.Destroy();self.part_inspector=None
        self.measure_generation+=1;self.measure_cancel.set();self.measuring=False
        if hasattr(self,'measure_button'):self.measure_button.Enable()
        if self.measurement_session:self.measurement_session.close();self.measurement_session=None
        if self.live_temp:self.live_temp.cleanup();self.live_temp=None

    def change_measure_mode(self,event):
        mode=('select','parts','points','edges','point_edge','centers')[self.measure_mode.GetSelection()]
        if mode in ('edges','point_edge','centers') and (not self.result or self.result['rules'].get('mode')!='exact3d'):
            self.measure_mode.SetSelection(0);self.scene.set_mode('select')
            self.measure_readout.SetValue('Load 3D models first to select CAD edges and body centers.')
            return
        self.scene.set_mode(mode);self.part_panel.Show(mode in ('parts','edges','point_edge','centers'))
        self.edge_panel.Show(mode in ('edges','point_edge'));self.edge_a.Enable(mode=='edges')
        self.part_panel.Layout();self.part_panel.GetParent().Layout()
        self.measure_readout.SetValue({'select':'Hover a part for its measured nearest-part gap.',
                                      'parts':'Click two different parts, or choose their references and Measure.',
                                      'points':'Click two visible surface points. Picked tessellated points; not minimum part clearance.',
                                      'edges':'Click two CAD edges. Hover highlights the selectable edge. Edges on one part are allowed.',
                                      'point_edge':'Click a surface point, then a CAD edge. The shortest distance is measured to the actual curve.',
                                      'centers':'Click two bodies to measure between their geometric volume centroids.'}[mode])

    def scene_picked(self,hit):
        if self.scene.inspection.mode=='select':
            index=hit.get('body_index')
            body=(self.scene.bodies[index] if index is not None else
                  next((b for b in self.scene.bodies if b['ref']==hit['reference']),None))
            if body:
                if self.part_inspector:self.part_inspector.Destroy()
                self.part_inspector=PartInspector(self,body,(INK,MUTED,BG,TEAL),self.scene.inspection.alerts.get(body['ref'],[]))
                origin=hit.get('popup_position')
                if origin is None:
                    size=self.scene.GetClientSize()
                    origin=self.scene.ClientToScreen(wx.Point(size.width//2,size.height//2))
                self.part_inspector.Position(wx.Point(*origin),(12,12));self.part_inspector.Popup()
        elif self.scene.inspection.mode=='parts':
            pair=self.scene.inspection.pair
            if pair:self.part_a.SetValue(pair[0])
            if len(pair)==2:self.part_b.SetValue(pair[1])
            elif pair:self.measure_readout.SetValue(pair[0]+': choose the second part.')
        elif self.scene.inspection.mode=='points' and self.scene.inspection.point_start:
            self.measure_readout.SetValue('First surface point pinned. Click the second point for a ruler.')
        elif len(self.scene.inspection.feature_pair)==1:
            first=self.scene.inspection.feature_pair[0]
            self.part_a.SetValue(first['ref'])
            if first['kind']=='edge':self.edge_a.SetValue(first['edge_index']+1)
            self.measure_readout.SetValue(f"{first['ref']}: {first['kind']} selected. Choose the second feature.")

    def scene_hovered(self,hit,record):
        if self.measuring or self.scene.inspection.mode!='select':return
        from .inspection_state import finding_readout
        message='Nearest part: '+measurement_text(record) if record else (
            hit['reference']+' · XYZ '+', '.join(f'{v:.6g}' for v in hit['position'])+' mm\nNearest-part distance unavailable for this geometry.' if hit else '')
        if hit:
            notes=[finding_readout(f) for f in self.scene.inspection.alerts.get(hit['reference'],[])]
            if notes:message+='\n'+'\n'.join(notes[:6])
        if message:self.measure_readout.SetValue(message)

    def point_ruler(self,record):
        if self.result:self.result.setdefault('point_rulers',[]).append(record)
        self.measure_readout.SetValue(measurement_text(record))

    def clear_rulers(self,event=None):
        self.measure_generation+=1;self.measure_cancel.set();self.measuring=False
        self.measure_button.Enable();self.scene.clear_measurements()
        if self.result:self.result['point_rulers']=[]
        if self.result:self.result['feature_rulers']=[]
        self.measure_readout.SetValue('Visible rulers cleared. Measured part distances remain available in the report.')

    def measure_selected_parts(self,event):
        first,second=self.part_a.GetValue().strip(),self.part_b.GetValue().strip()
        mode=self.scene.inspection.mode
        if mode=='centers':self.measure_features(dict(kind='center',ref=first),dict(kind='center',ref=second))
        elif mode=='edges':
            self.measure_features(dict(kind='edge',ref=first,edge_index=self.edge_a.GetValue()-1),
                                  dict(kind='edge',ref=second,edge_index=self.edge_b.GetValue()-1))
        elif mode=='point_edge':
            pair=self.scene.inspection.feature_pair
            if len(pair)!=1 or pair[0]['kind']!='point':
                self.measure_readout.SetValue('Click the first surface point, then choose Edge B or click a CAD edge.');return
            self.measure_features(pair[0],dict(kind='edge',ref=second,edge_index=self.edge_b.GetValue()-1))
        else:self.measure_pair(first,second)

    def measure_pair(self,first,second):
        if not self.result:return
        available={body['ref'] for body in self.result['bodies']}
        if first==second or first not in available or second not in available:
            self.measure_readout.SetValue('Choose two different references from this report.');return
        if self.measuring:
            self.measure_readout.SetValue('A distance query is running. Clear rulers to cancel it.');return
        report=self.result;session=self.measurement_session or MeasurementSession()
        self.measuring=True;self.measure_generation+=1;generation=self.measure_generation
        self.measure_cancel=threading.Event();cancel=self.measure_cancel
        self.measure_button.Disable();self.scene.refs={first,second};self.scene.Refresh(False)
        self.measure_readout.SetValue(f'{first} ↔ {second}: measuring report geometry…')
        def worker():
            try:record=session.measure(report,first,second,cancel=cancel);error=None
            except Exception as exc:record=None;error=str(exc)
            finally:
                if session is not self.measurement_session:session.close()
            self.dispatch(self.measured,generation,report,record,error)
        threading.Thread(target=worker,daemon=True).start()

    def measured(self,generation,report,record,error):
        if generation!=self.measure_generation or report is not self.result:return
        self.measuring=False;self.measure_button.Enable()
        if error:self.measure_readout.SetValue('Distance unavailable: '+error);return
        feature=record.get('type')=='feature_ruler'
        records=report.setdefault('feature_rulers' if feature else 'measurements',[])
        if not feature:records[:]=[r for r in records if set(r['refs'])!=set(record['refs'])]
        records.append(record);self.scene.set_measurement(record)
        if feature:self.scene.inspection.feature_pair=[]
        self.measure_readout.SetValue(measurement_text(record))

    def measure_features(self,first,second):
        if not self.result:return
        if self.measuring:
            self.measure_readout.SetValue('A measurement is running. Clear to cancel it.');return
        report=self.result;session=self.measurement_session or MeasurementSession()
        self.measuring=True;self.measure_generation+=1;generation=self.measure_generation
        self.measure_cancel=threading.Event();cancel=self.measure_cancel
        self.measure_button.Disable();self.scene.refs={first['ref'],second['ref']};self.scene.Refresh(False)
        self.measure_readout.SetValue('Measuring saved CAD features…')
        def worker():
            try:record=session.measure_features(report,first,second,cancel=cancel);error=None
            except Exception as exc:record=None;error=str(exc)
            finally:
                if session is not self.measurement_session:session.close()
            self.dispatch(self.measured,generation,report,record,error)
        threading.Thread(target=worker,daemon=True).start()

    def locate(self,event):
        f=self.selected()
        if not f:return
        try:
            import pcbnew
            board=pcbnew.GetBoard()
            if not board or (self.board_path and Path(board.GetFileName()).resolve()!=Path(self.board_path).resolve()):
                raise ValueError('Open this board in PCB Editor and launch WayriCAD Mechanical Check from its toolbar to locate parts.')
            for fp in board.GetFootprints():
                if fp.GetReference() in f['refs']:fp.SetSelected()
                else:fp.ClearSelected()
            pcbnew.Refresh()
        except Exception as exc:wx.MessageBox(str(exc),'Locate parts',wx.OK,self)

    def waive(self,event):
        f=self.selected()
        if not f:return
        with wx.TextEntryDialog(self,'Enter a review reason. Clear the text to remove an existing waiver.','Finding waiver',f['waiver']) as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            reason=dlg.GetValue().strip()
            if reason:self.config['waivers'][f['id']]=reason
            else:self.config['waivers'].pop(f['id'],None)
            self.result['rules']['waivers']=deepcopy(self.config['waivers'])
            finish(self.result,self.config);self.refresh_result()

    def coverage(self,event):
        if self.result:
            dlg=wx.Dialog(self,title='Model coverage and limits',size=(760,550))
            s=wx.BoxSizer(wx.VERTICAL);s.Add(wx.TextCtrl(dlg,value=json.dumps(self.result['coverage'],indent=2),style=wx.TE_MULTILINE|wx.TE_READONLY),1,wx.EXPAND|wx.ALL,15)
            s.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALL|wx.ALIGN_RIGHT,15);dlg.SetSizer(s);dlg.ShowModal();dlg.Destroy()

    def import_rules(self,event):
        with wx.FileDialog(self,'Load project rules',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            try:
                self.config=load(dlg.GetPath());self.rules_path=dlg.GetPath()
                for key,control in self.numbers.items():control.SetValue(self.config[key])
                for axis,value in zip('XYZ',self.config['section_normal']):self.section_normal_inputs[axis].SetValue(value)
                self.project.SetValue(self.config['project_name']);self.revision.SetValue(self.config['project_revision']);self.reviewer.SetValue(self.config['reviewer']);self.dnp.SetValue(self.config['include_dnp'])
                self.mode.SetSelection(0 if self.config['mode']=='quick2d' else 1)
                comparison=self.config['comparison_board'] or {}
                self.comparison_file.SetPath(comparison.get('path',''))
                for index,axis in enumerate('XYZ'):
                    self.comparison_position[axis].SetValue(comparison.get('translation_mm',[0,0,0])[index])
                self.comparison_rotation.SetValue(comparison.get('rotation_deg',0))
                self.load_board()
            except Exception as exc:wx.MessageBox(str(exc),'Invalid rules',wx.OK|wx.ICON_ERROR,self)

    def save_rules(self,event):
        try:
            config=self.get_config()
            with wx.FileDialog(self,'Save project rules',defaultFile=Path(self.board_path).stem+'.wayricad-mechanical.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dlg:
                if dlg.ShowModal()==wx.ID_OK:save(dlg.GetPath(),config);self.config=config;self.rules_path=dlg.GetPath()
        except Exception as exc:wx.MessageBox(str(exc),'Invalid rules',wx.OK|wx.ICON_WARNING,self)

    def advanced(self,event):
        keys=['height_zones','keepouts','enclosures','model_variables','volume_tolerance_mm3']
        dlg=wx.Dialog(self,title='Advanced physical rules',size=(760,600),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(dlg,'Height zones use KiCad XY. Keepouts and enclosure STEP use CAD XYZ.\nSee Help for coordinates and examples.',11,False,MUTED),0,wx.ALL,15)
        editor=wx.TextCtrl(dlg,value=json.dumps({k:self.config[k] for k in keys},indent=2),style=wx.TE_MULTILINE)
        s.Add(editor,1,wx.EXPAND|wx.ALL,15);s.Add(dlg.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALL|wx.ALIGN_RIGHT,15);dlg.SetSizer(s)
        if dlg.ShowModal()==wx.ID_OK:
            try:
                changes=json.loads(editor.GetValue())
                if set(changes)-set(keys):raise ValueError('This editor only accepts the displayed advanced fields.')
                c=deepcopy(self.config);c.update(changes);self.config=validate(c)
            except Exception as exc:wx.MessageBox(str(exc),'Invalid advanced rules',wx.OK|wx.ICON_WARNING,self)
        dlg.Destroy()

    def export_report(self,event):
        if not self.result:return
        with wx.DirDialog(self,'Choose a reports folder') as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            try:
                paths=export(self.result,dlg.GetPath());self.status.SetLabel('Report saved: '+str(Path(paths['html']).parent))
                wx.LaunchDefaultBrowser(Path(paths['html']).as_uri())
            except Exception as exc:wx.MessageBox(str(exc),'Export error',wx.OK|wx.ICON_ERROR,self)

    def help(self,event):
        dlg=wx.Dialog(self,title='WayriCAD Mechanical Check — Help',size=(1050,820),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dlg.SetMinSize((540,480))
        path=Path(__file__).resolve().parents[2]/'resources/help.html'
        if path.exists():
            from .help_viewer import HelpViewer
            viewer=HelpViewer(dlg,path)
        else:
            viewer=wx.html.HtmlWindow(dlg)
            viewer.SetPage('<h1>WayriCAD Mechanical Check help</h1><p>Reinstall the plugin ZIP to restore resources/help.html.</p>')
        s=wx.BoxSizer(wx.VERTICAL);s.Add(viewer,1,wx.EXPAND);s.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALL|wx.ALIGN_RIGHT,12);dlg.SetSizer(s);dlg.ShowModal();dlg.Destroy()

    def close(self,event):
        if self.running:
            self.cancel.set();self.status.SetLabel('Cancelling geometry worker — close again after it stops');event.Veto();return
        self._closing=True;self.reset_measurement_session();self.Destroy()


def launch(board_path=None,rules_path=None,snapshot_of=None,review_path=None):
    app=wx.App.Get() or wx.App(False)
    result=None
    if review_path:
        result=json.loads(Path(review_path).read_text(encoding='utf-8'))
        board_path=result['board_path']
    window=Window(board_path,rules_path,snapshot_of=snapshot_of)
    if result:
        window.result=result;window.config=result['rules'];window.scene.set_report(result)
        window.refresh_result();window.show_step(3)
        window.SetTitle('WayriCAD Mechanical Check — Shaded conflict review')
    window.Show()
    app.MainLoop()
