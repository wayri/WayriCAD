"""Read-only connector mating, editable label batches and physical pin tables."""
from __future__ import annotations

import csv
import hashlib
from io import StringIO
from pathlib import Path
import threading
import re

import wx
import wx.grid as gridlib
from wayricad_runtime.readable_choice import ReadableComboBox
try:
    from .core import connector_labels as labels
    from .core import connector_mating as mating
except ImportError:
    from core import connector_labels as labels
    from core import connector_mating as mating


def copy_text(text):
    """Copy reviewed native objects or text without editing a design."""
    if not wx.TheClipboard.Open():
        raise ValueError('Clipboard is busy. Try Copy again.')
    try:
        if not wx.TheClipboard.SetData(wx.TextDataObject(text)):
            raise ValueError('Could not write the clipboard.')
        wx.TheClipboard.Flush()
    finally:
        wx.TheClipboard.Close()


class ContactPreview(wx.Panel):
    """Two posed contact arrays; matching contacts share a highlight colour."""
    def __init__(self, parent):
        super().__init__(parent)
        self.contacts=([],[]);self.selected=('', '');self.on_contact=None;self._hits=[]
        self.SetMinSize((240,140));self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
        self.Bind(wx.EVT_LEFT_DOWN,self.pick)

    def pick(self,event):
        hits=[(abs(x-event.GetX())**2+abs(y-event.GetY())**2,side,pin) for x,y,side,pin in self._hits]
        if hits:
            distance,side,pin=min(hits)
            if distance<=144 and self.on_contact:self.on_contact(side,pin)

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour('#152530')));dc.Clear()
        width,height=self.GetClientSize()
        all_pins=self.contacts[0]+self.contacts[1]
        extent=max([abs(float(p[k])) for p in all_pins for k in ('x_mm','y_mm')]+[1.])
        scale=max(1,min(width/4-35,height/2-40)/extent)
        self._hits=[]
        for side,pins in enumerate(self.contacts):
            cx=width*(.25 if side==0 else .75);cy=height/2+10
            dc.SetPen(wx.Pen('#455966',1));dc.DrawLine(int(cx-12),int(cy),int(cx+12),int(cy));dc.DrawLine(int(cx),int(cy-12),int(cx),int(cy+12))
            dc.SetTextForeground(wx.Colour('#e8f2f6'))
            dc.DrawText('A — assembly XY' if side==0 else 'B — assembly XY',int(cx-65),8)
            for p in pins:
                x=int(cx+float(p['x_mm'])*scale);y=int(cy+float(p['y_mm'])*scale)
                selected=str(p['pin'])==self.selected[side]
                colour='#ffe178' if selected else '#ffad66' if str(p['pin'])=='1' else ('#63d9c9' if side==0 else '#80baff')
                dc.SetPen(wx.Pen(colour,2));dc.SetBrush(wx.Brush(colour))
                dc.DrawCircle(x,y,7 if selected else 4)
                self._hits.append((x,y,side,str(p['pin'])))
                if len(pins)<=100 or selected or str(p['pin'])=='1':
                    dc.SetTextForeground(wx.Colour(colour));dc.DrawText(str(p['pin']),x+7,y-7)


class ConnectorToolsPanel(wx.Panel):
    """Explicit Preview then Copy workflow; no board or schematic writes."""
    def __init__(self,parent,board,initial_refs=()):
        super().__init__(parent)
        self.board=board;self.external={};self.external_errors={};self.external_path=None;self.external_stamp=None;self.external_hash=None
        self._alive=True;self._loading=False;self._mate_snapshot=None
        self._paste_snapshot=None;self._physical_snapshot=None
        self._mate_result=None;self._physical_text=''
        refs=sorted(str(fp.GetReference()) for fp in board.GetFootprints())
        self.refs=refs
        preferred=next((r for r in initial_refs if r in refs),next((r for r in refs if r.startswith(('J','P'))),refs[0] if refs else ''))
        root=wx.BoxSizer(wx.VERTICAL)
        tabs=wx.Notebook(self);self.tabs=tabs
        self.mate_page=self.make_mate(tabs,preferred)
        self.paste_page=self.make_paste(tabs)
        self.physical_page=self.make_physical(tabs,preferred)
        for page,title in ((self.mate_page,'Mating pair'),(self.paste_page,'Paste labels'),(self.physical_page,'Physical pinout')):
            tabs.AddPage(page,title)
        root.Add(tabs,1,wx.EXPAND)
        self.status=wx.StaticText(self,label='Choose inputs, preview, edit label rows, then copy. Designs stay unchanged.',style=wx.ST_ELLIPSIZE_END)
        self.status.Wrap(900);root.Add(self.status,0,wx.EXPAND|wx.ALL,8)
        self.SetSizer(root)
        self.Bind(wx.EVT_WINDOW_DESTROY,self.destroyed)
        groups=(('mate',('a_ref','b_ref','a_side','b_side','a_angle','b_angle','a_x','b_x','a_y','b_y','a_prefix','b_prefix','a_suffix','b_suffix','template','tolerance','mate_case','a_mirror','b_mirror')),
                ('paste',('paste_text','csv_mode','sequence','start','step','grid_columns','header','paste_prefix','paste_suffix','paste_template','paste_case')),
                ('physical',('phys_ref','phys_side','phys_angle','phys_order','phys_tolerance','phys_mirror')))
        for name,controls in groups:
            for control in controls:
                for event_type in (wx.EVT_TEXT,wx.EVT_COMBOBOX,wx.EVT_CHECKBOX):
                    getattr(self,control).Bind(event_type,lambda event,name=name:self.invalidate(name,event))

    def invalidate(self,name,event):
        setattr(self,'_'+name+'_snapshot',None)
        table=getattr(self,{'mate':'mate_table','paste':'paste_table','physical':'physical_table'}[name])
        table.Enable(False)
        if name=='mate':self.contact_preview.contacts=([],[]);self.contact_preview.Refresh()
        self.status.SetLabel('Inputs changed. Preview again to rebuild the proposed rows; earlier row edits will be replaced.')
        event.Skip()

    def destroyed(self,event):
        if event.GetEventObject() is self:self._alive=False
        event.Skip()

    def field(self,parent,sizer,title,value='',choices=None,editable=False):
        sizer.Add(wx.StaticText(parent,label=title),0,wx.ALIGN_CENTER_VERTICAL)
        if choices is None:control=wx.TextCtrl(parent,value=str(value))
        else:
            control=ReadableComboBox(parent,choices=list(choices),style=wx.CB_DROPDOWN if editable else wx.CB_READONLY)
            control.SetStringSelection(str(value))
        control.SetToolTip(title);sizer.Add(control,1,wx.EXPAND)
        return control

    def button(self,parent,sizer,title,handler):
        button=wx.Button(parent,label=title);button.Bind(wx.EVT_BUTTON,lambda event:self.run(handler))
        sizer.Add(button,0,wx.RIGHT|wx.BOTTOM,6);return button

    def run(self,handler):
        try:handler()
        except (ValueError,KeyError,OSError,RuntimeError,TypeError) as exc:
            self.status.SetLabel(str(exc));self.status.SetToolTip(str(exc))

    def table(self,parent,headings):
        table=gridlib.Grid(parent);table.CreateGrid(0,len(headings))
        for i,title in enumerate(headings):table.SetColLabelValue(i,title);table.SetColSize(i,160)
        table.SetSelectionMode(gridlib.Grid.SelectRows);table.SetRowLabelSize(42)
        def tip(event):
            point=table.CalcUnscrolledPosition(event.GetPosition());cell=table.XYToCell(point.x,point.y)
            text=table.GetCellValue(cell.GetRow(),cell.GetCol()) if 0<=cell.GetRow()<table.GetNumberRows() and 0<=cell.GetCol()<table.GetNumberCols() else ''
            window=table.GetGridWindow()
            if window.GetToolTipText()!=text:window.SetToolTip(text)
            event.Skip()
        table.GetGridWindow().Bind(wx.EVT_MOTION,tip)
        return table

    def fill(self,table,rows):
        table.BeginBatch()
        try:
            if table.GetNumberRows():table.DeleteRows(0,table.GetNumberRows())
            if rows:table.AppendRows(len(rows))
            for i,row in enumerate(rows):
                for j,value in enumerate(row):table.SetCellValue(i,j,str(value))
        finally:table.EndBatch()

    def selected_rows(self,table,selected=False):
        table.SaveEditControlValue();table.HideCellEditControl()
        if not selected:return list(range(table.GetNumberRows()))
        rows=set(table.GetSelectedRows())
        for lo,hi in zip(table.GetSelectionBlockTopLeft(),table.GetSelectionBlockBottomRight()):
            rows.update(range(lo.GetRow(),hi.GetRow()+1))
        rows.update(cell.GetRow() for cell in table.GetSelectedCells())
        if not rows and table.GetNumberRows():rows.add(table.GetGridCursorRow())
        return sorted(i for i in rows if 0<=i<table.GetNumberRows())

    def footprint_rows(self,ref,external=False):
        if external:
            if self.external_path and (self.external_path.stat().st_mtime_ns!=self.external_stamp or
                                       hashlib.sha256(self.external_path.read_bytes()).hexdigest()!=self.external_hash):
                raise ValueError('The external board changed. Load it again before copying.')
            if ref in self.external_errors:raise ValueError(ref+': '+self.external_errors[ref])
            return [dict(p) for p in self.external[ref]]
        found=[fp for fp in self.board.GetFootprints() if str(fp.GetReference())==ref]
        if len(found)!=1:raise ValueError('Choose one uniquely referenced footprint.')
        return mating.footprint_pins(found[0])

    def make_mate(self,tabs,preferred):
        page=wx.Panel(tabs);root=wx.BoxSizer(wx.VERTICAL)
        convention='Board-top XY input: a bottom view reflects X; the extra reflection is independent. Review contact 1 in both views.'
        hint=wx.StaticText(page,label=convention,style=wx.ST_ELLIPSIZE_END);hint.SetToolTip(convention)
        root.Add(hint,0,wx.EXPAND|wx.ALL,6)
        settings=wx.ScrolledWindow(page,size=(-1,220),style=wx.VSCROLL);settings.SetScrollRate(0,15)
        controls=wx.FlexGridSizer(cols=4,vgap=5,hgap=10);controls.AddGrowableCol(1);controls.AddGrowableCol(3)
        self.a_ref=self.field(settings,controls,'A connector',preferred,self.refs)
        self.b_ref=self.field(settings,controls,'B connector','Proposed mate of A',['Proposed mate of A']+self.refs)
        self.a_side=self.field(settings,controls,'A view side','top',['top','bottom'])
        self.b_side=self.field(settings,controls,'B view side','top',['top','bottom'])
        self.a_angle=self.field(settings,controls,'A added rotation °','0')
        self.b_angle=self.field(settings,controls,'B added rotation °','0')
        self.a_x=self.field(settings,controls,'A assembly X mm','0');self.b_x=self.field(settings,controls,'B assembly X mm','0')
        self.a_y=self.field(settings,controls,'A assembly Y mm','0');self.b_y=self.field(settings,controls,'B assembly Y mm','0')
        self.a_prefix=self.field(settings,controls,'A label prefix','');self.b_prefix=self.field(settings,controls,'B label prefix','')
        self.a_suffix=self.field(settings,controls,'A label suffix','');self.b_suffix=self.field(settings,controls,'B label suffix','')
        self.template=self.field(settings,controls,'Label template','{label}',['{label}','{ref}_{label}','{pin}_{label}'],editable=True)
        self.tolerance=self.field(settings,controls,'Contact tolerance mm','0.1')
        self.mate_case=self.field(settings,controls,'Label case','unchanged',['unchanged','upper','lower'])
        self.mate_pitch=self.field(settings,controls,'Schematic pitch mm','2.54')
        self.a_label_angle=self.field(settings,controls,'A label angle °','0',['0','90','180','270'])
        self.b_label_angle=self.field(settings,controls,'B label angle °','0',['0','90','180','270'])
        self.mate_size=self.field(settings,controls,'Label text size mm','1.27')
        controls.Add((1,1));controls.Add((1,1))
        box=wx.BoxSizer(wx.VERTICAL);box.Add(controls,0,wx.EXPAND|wx.ALL,8)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.a_mirror=wx.CheckBox(settings,label='Reflect A left/right')
        self.b_mirror=wx.CheckBox(settings,label='Reflect B left/right (opposite face)');self.b_mirror.SetValue(True)
        row.Add(self.a_mirror,0,wx.RIGHT,12);row.Add(self.b_mirror,0)
        box.Add(row,0,wx.ALL,8);settings.SetSizer(box);settings.FitInside()
        root.Add(settings,0,wx.EXPAND)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        self.button(page,actions,'Load B board…',self.load_external)
        self.button(page,actions,'Use current board for B',self.clear_external)
        self.button(page,actions,'Preview pair',self.preview_pair)
        self.button(page,actions,'Assign pasted names to pair',self.assign_pasted_names)
        self.button(page,actions,'Copy A labels',lambda:self.copy_pair('a'))
        self.button(page,actions,'Copy B labels',lambda:self.copy_pair('b'))
        self.button(page,actions,'Copy selected pair',lambda:self.copy_pair('pair',True))
        self.button(page,actions,'Copy pair table',self.copy_pair_table)
        root.Add(actions,0,wx.EXPAND|wx.ALL,6)
        self.kind=wx.Choice(page,choices=['global','local','hierarchical']);self.kind.SetSelection(0)
        self.kind.SetToolTip('Schematic label scope. Global labels connect equal names throughout one project.')
        root.Add(self.kind,0,wx.LEFT|wx.BOTTOM,8)
        split=wx.SplitterWindow(page,style=wx.SP_LIVE_UPDATE);split.SetMinimumPaneSize(100)
        self.contact_preview=ContactPreview(split)
        self.contact_preview.on_contact=self.select_contact
        self.mate_table=self.table(split,['A pin','A label','B pin','B proposed label','Distance mm','B current net'])
        split.SplitHorizontally(self.contact_preview,self.mate_table,180);split.SetSashGravity(.35)
        self.mate_table.Bind(gridlib.EVT_GRID_SELECT_CELL,self.highlight_pair)
        root.Add(split,1,wx.EXPAND|wx.ALL,6);page.SetSizer(root);return page

    def pose(self,side):
        return dict(side=getattr(self,side+'_side').GetValue(),rotation_deg=float(getattr(self,side+'_angle').GetValue()),
                    mirror=getattr(self,side+'_mirror').GetValue(),x_mm=float(getattr(self,side+'_x').GetValue()),y_mm=float(getattr(self,side+'_y').GetValue()))

    def mate_inputs(self):
        if self._loading:raise ValueError('Wait for the external connector inventory to finish loading.')
        a=self.footprint_rows(self.a_ref.GetValue())
        proposed=self.b_ref.GetValue()=='Proposed mate of A'
        b=[dict(p,label='') for p in a] if proposed else self.footprint_rows(self.b_ref.GetValue(),bool(self.external_path))
        signature=(a,b,self.pose('a'),self.pose('b'),self.a_ref.GetValue(),self.b_ref.GetValue(),
                   self.a_prefix.GetValue(),self.b_prefix.GetValue(),self.a_suffix.GetValue(),self.b_suffix.GetValue(),self.template.GetValue(),float(self.tolerance.GetValue()),self.mate_case.GetValue())
        return signature

    def preview_pair(self):
        self._mate_snapshot=None;self._mate_result=None;self.fill(self.mate_table,[])
        values=self.mate_inputs();a,b,pa,pb=values[:4]
        result=mating.match_mating(a,b,tolerance_mm=values[11],pose_a=pa,pose_b=pb)
        rows=[]
        ordered=sorted(result['pairs'],key=lambda pair:[int(t) if t.isdigit() else t.casefold() for t in re.split(r'(\d+)',pair['a']['pin'])])
        for pair in ordered:
            base=[dict(pin=pair['a']['pin'],label=pair['a']['label'])]
            al=labels.format_labels(base,prefix=values[6],suffix=values[8],template=values[10],ref=values[4],case=values[12])[0]['label'] if pair['a']['label'] else ''
            bl=labels.format_labels([dict(pin=pair['b']['pin'],label=pair['a']['label'])],prefix=values[7],suffix=values[9],template=values[10],ref='MATE' if values[5]=='Proposed mate of A' else values[5],case=values[12])[0]['label'] if pair['a']['label'] else ''
            rows.append([pair['a']['pin'],al,pair['b']['pin'],bl,f"{pair['distance_mm']:.5g}",pair['b']['label']])
        self.fill(self.mate_table,rows)
        for i in range(len(rows)):
            for col in (0,2,4,5):self.mate_table.SetReadOnly(i,col)
        self.contact_preview.contacts=(mating.transform_pins(a,**pa),mating.transform_pins(b,**pb));self.contact_preview.Refresh()
        self._mate_snapshot=values;self._mate_result=result
        self.mate_table.Enable(True)
        missing=len(result['unmatched_a'])+len(result['unmatched_b'])
        issues='; '.join(result['issues'])
        if result['unmatched_a']:issues+=' A unresolved: '+', '.join(p['pin'] for p in result['unmatched_a'])+'.'
        if result['unmatched_b']:issues+=' B unresolved: '+', '.join(p['pin'] for p in result['unmatched_b'])+'.'
        conflicts=sum(bool(r[5]) and r[3]!=r[5] for r in rows)
        if conflicts:issues+=f' {conflicts} B proposed labels differ from current nets; copying does not rename existing nets.'
        self.status.SetLabel(f'{len(rows)} unique contact pairs; {missing} unmatched. '+issues+
                             ' Review pin 1 and the manufacturer mating view. Proposed geometry does not establish connector compatibility.')
        self.status.SetToolTip(self.status.GetLabel())

    def assign_pasted_names(self):
        if self._mate_snapshot is None or self.mate_inputs()!=self._mate_snapshot:
            raise ValueError('Preview the connector pair before assigning pasted names.')
        names=labels.format_labels(self.paste_rows())
        indices={self.mate_table.GetCellValue(i,0):i for i in range(self.mate_table.GetNumberRows())}
        missing={r['pin'] for r in names}-set(indices)
        if missing:raise ValueError('Pasted pin IDs are not in the matched A contacts: '+', '.join(sorted(missing)))
        prepared=[]
        for row in names:
            i=indices[row['pin']];bpin=self.mate_table.GetCellValue(i,2)
            a=labels.format_labels([row],prefix=self.a_prefix.GetValue(),suffix=self.a_suffix.GetValue(),template=self.template.GetValue(),case=self.mate_case.GetValue(),ref=self.a_ref.GetValue())[0]['label']
            b=labels.format_labels([dict(pin=bpin,label=row['label'])],prefix=self.b_prefix.GetValue(),suffix=self.b_suffix.GetValue(),template=self.template.GetValue(),case=self.mate_case.GetValue(),ref='MATE' if self.b_ref.GetValue()=='Proposed mate of A' else self.b_ref.GetValue())[0]['label']
            prepared.append((i,a,b))
        for i,a,b in prepared:self.mate_table.SetCellValue(i,1,a);self.mate_table.SetCellValue(i,3,b)
        self.status.SetLabel(f'Assigned {len(prepared)} pasted names by exact A pin ID to the preview only. Existing PCB and schematic nets are unchanged.')

    def checked_pair(self,selected=False):
        if self._mate_snapshot is None or self.mate_inputs()!=self._mate_snapshot:
            raise ValueError('Inputs or board contacts changed. Preview the pair again.')
        result=self._mate_result
        if not selected and (result['unmatched_a'] or result['unmatched_b'] or result['issues']):
            raise ValueError('Some contacts are unresolved. Correct the poses, or explicitly select reviewed matched pairs to copy.')
        return self.selected_rows(self.mate_table,selected)

    def copy_pair(self,side,selected=False):
        indices=self.checked_pair(selected)
        if not indices:raise ValueError('No matched pair selected.')
        kind=self.kind.GetStringSelection();text=[]
        for key,x in ([('a',0),('b',60)] if side=='pair' else [(side,0)]):
            col=0 if key=='a' else 2
            rows=[dict(pin=self.mate_table.GetCellValue(i,col),label=self.mate_table.GetCellValue(i,col+1)) for i in indices]
            text.append(labels.schematic_labels(rows,kind=kind,origin=(x,0),orientation=int(getattr(self,key+'_label_angle').GetValue()),pitch_mm=float(self.mate_pitch.GetValue()),text_size_mm=float(self.mate_size.GetValue())))
        copy_text('\n'.join(text));self.status.SetLabel('Copied native schematic labels. Paste in Schematic Editor, then attach to the intended pins.')

    def copy_pair_table(self):
        indices=self.checked_pair(False);out=StringIO();writer=csv.writer(out)
        writer.writerow(['A pin','A label','B pin','B proposed label','Distance mm','B current net'])
        writer.writerows([[self.mate_table.GetCellValue(i,j) for j in range(6)] for i in indices]);copy_text(out.getvalue())

    def select_contact(self,side,pin):
        column=0 if side==0 else 2
        for i in range(self.mate_table.GetNumberRows()):
            if self.mate_table.GetCellValue(i,column)==pin:
                self.mate_table.SelectRow(i);self.mate_table.MakeCellVisible(i,column)
                self.contact_preview.selected=(self.mate_table.GetCellValue(i,0),self.mate_table.GetCellValue(i,2));self.contact_preview.Refresh();return
        self.status.SetLabel('Contact '+pin+' is unmatched. Adjust the poses and preview again.')

    def highlight_pair(self,event):
        i=event.GetRow()
        if i<self.mate_table.GetNumberRows():
            self.contact_preview.selected=(self.mate_table.GetCellValue(i,0),self.mate_table.GetCellValue(i,2));self.contact_preview.Refresh()
        event.Skip()

    def clear_external(self):
        if self._loading:raise ValueError('Wait for the current B board load before switching sources.')
        self.external={};self.external_errors={};self.external_path=None;self.external_stamp=None;self.external_hash=None
        self.b_ref.SetItems(['Proposed mate of A']+self.refs);self.b_ref.SetSelection(0);self._mate_snapshot=None

    def load_external(self):
        if self._loading:return
        with wx.FileDialog(self,'Choose the read-only B board',wildcard='KiCad PCB (*.kicad_pcb)|*.kicad_pcb',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        self._loading=True;self._mate_snapshot=None;self.status.SetLabel('Loading B board contacts… You can continue using the other tabs.')
        def worker():
            try:
                import pcbnew
                before=path.stat().st_mtime_ns;digest=hashlib.sha256(path.read_bytes()).hexdigest()
                board=pcbnew.LoadBoard(str(path));inventory={};errors={}
                for fp in board.GetFootprints():
                    ref=str(fp.GetReference())
                    if not ref:continue
                    if ref in inventory or ref in errors:raise ValueError('External board has duplicate footprint references.')
                    try:inventory[ref]=mating.footprint_pins(fp)
                    except ValueError as exc:errors[ref]=str(exc)
                if before!=path.stat().st_mtime_ns or digest!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('External board changed while loading. Try again.')
                outcome=(inventory,errors,before,digest,None)
            except Exception as exc:outcome=({},{},None,None,str(exc))
            wx.CallAfter(self.external_done,path,outcome)
        threading.Thread(target=worker,daemon=True).start()

    def external_done(self,path,outcome):
        if not self._alive:return
        self._loading=False;inventory,errors,stamp,digest,error=outcome
        if error:self.status.SetLabel('B board was not loaded: '+error);return
        self.external=inventory;self.external_errors=errors;self.external_path=path;self.external_stamp=stamp;self.external_hash=digest
        refs=sorted(set(inventory)|set(errors));self.b_ref.SetItems(refs)
        if refs:self.b_ref.SetSelection(next((i for i,r in enumerate(refs) if r.startswith(('J','P'))),0))
        self.status.SetLabel(f'Loaded {len(inventory)} B footprints read-only; {len(errors)} require padstack review. Choose the mate and preview.')

    def make_paste(self,tabs):
        page=wx.Panel(tabs);root=wx.BoxSizer(wx.VERTICAL)
        self.paste_text=wx.TextCtrl(page,style=wx.TE_MULTILINE,size=(-1,120))
        self.paste_text.SetHint('One label per line, or pin,label CSV / tab-separated columns')
        root.Add(self.paste_text,0,wx.EXPAND|wx.ALL,6)
        settings=wx.FlexGridSizer(cols=6,vgap=5,hgap=6)
        for col in (1,3,5):settings.AddGrowableCol(col)
        self.csv_mode=self.field(page,settings,'Columns','auto',['auto','labels','pin-label'])
        self.sequence=self.field(page,settings,'Number order','sequential',['sequential','row-major','column-major','odd-even','serpentine'])
        self.start=self.field(page,settings,'Start','1');self.step=self.field(page,settings,'Step','1')
        self.grid_columns=self.field(page,settings,'Grid columns','2')
        self.paste_kind=self.field(page,settings,'Label type','global',['global','local','hierarchical'])
        self.paste_prefix=self.field(page,settings,'Prefix','');self.paste_suffix=self.field(page,settings,'Suffix','')
        self.paste_angle=self.field(page,settings,'Text angle','0',['0','90','180','270'])
        self.paste_template=self.field(page,settings,'Template','{label}',['{label}','{pin}_{label}'],editable=True)
        self.paste_case=self.field(page,settings,'Case','unchanged',['unchanged','upper','lower'])
        self.paste_pitch=self.field(page,settings,'Pitch mm','2.54')
        self.paste_size=self.field(page,settings,'Text size mm','1.27')
        settings.Add((1,1));settings.Add((1,1));settings.Add((1,1));settings.Add((1,1))
        root.Add(settings,0,wx.EXPAND|wx.ALL,6)
        self.header=wx.CheckBox(page,label='First record is a header');root.Add(self.header,0,wx.ALL,6)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        self.button(page,actions,'Preview / assign numbers',self.preview_paste)
        self.button(page,actions,'Copy all labels',lambda:self.copy_paste(False))
        self.button(page,actions,'Copy selected lines',lambda:self.copy_paste(True))
        self.button(page,actions,'Copy edited CSV',self.copy_paste_csv)
        root.Add(actions,0,wx.EXPAND|wx.ALL,6)
        self.paste_table=self.table(page,['Pin','Label (editable)']);root.Add(self.paste_table,1,wx.EXPAND|wx.ALL,6)
        page.SetSizer(root);return page

    def paste_inputs(self):
        return (self.paste_text.GetValue(),self.csv_mode.GetValue(),self.sequence.GetValue(),self.start.GetValue(),self.step.GetValue(),self.grid_columns.GetValue(),self.header.GetValue(),self.paste_prefix.GetValue(),self.paste_suffix.GetValue(),self.paste_template.GetValue(),self.paste_case.GetValue())

    def preview_paste(self):
        self._paste_snapshot=None;self.fill(self.paste_table,[])
        values=self.paste_inputs()
        rows=labels.parse_pin_text(values[0],columns=values[1],sequence=values[2],start=int(values[3]),step=int(values[4]),grid_columns=int(values[5]),header=values[6])
        rows=labels.format_labels(rows,prefix=values[7],suffix=values[8],template=values[9],case=values[10])
        self.fill(self.paste_table,[[r['pin'],r['label']] for r in rows]);self._paste_snapshot=values
        self.paste_table.Enable(True)
        warnings=labels.label_warnings(rows)
        self.status.SetLabel(f'{len(rows)} editable lines. Select rows for individual labels; Copy all includes every row. '+(' '.join(warnings) if warnings else 'Equal label names connect electrically within their scope.'))
        self.status.SetToolTip(self.status.GetLabel())

    def paste_rows(self,selected=False):
        if self._paste_snapshot is None or self.paste_inputs()!=self._paste_snapshot:
            raise ValueError('Paste or numbering inputs changed. Preview again before copying.')
        indices=self.selected_rows(self.paste_table,selected)
        return [dict(pin=self.paste_table.GetCellValue(i,0),label=self.paste_table.GetCellValue(i,1)) for i in indices]

    def copy_paste(self,selected):
        copy_text(labels.schematic_labels(self.paste_rows(selected),kind=self.paste_kind.GetValue(),orientation=int(self.paste_angle.GetValue()),pitch_mm=float(self.paste_pitch.GetValue()),text_size_mm=float(self.paste_size.GetValue())))
        self.status.SetLabel('Copied native labels. Paste in Schematic Editor; labels do not attach themselves to connector pins.')

    def copy_paste_csv(self):
        out=StringIO();writer=csv.writer(out);writer.writerow(['pin','label'])
        writer.writerows((r['pin'],r['label']) for r in self.paste_rows());copy_text(out.getvalue())

    def make_physical(self,tabs,preferred):
        page=wx.Panel(tabs);root=wx.BoxSizer(wx.VERTICAL)
        settings=wx.FlexGridSizer(cols=4,vgap=6,hgap=10);settings.AddGrowableCol(1);settings.AddGrowableCol(3)
        self.phys_ref=self.field(page,settings,'Connector',preferred,self.refs)
        self.phys_side=self.field(page,settings,'View side','top',['top','bottom'])
        self.phys_angle=self.field(page,settings,'Rotation °','0',['0','90','180','270'])
        self.phys_order=self.field(page,settings,'Export layout','rows',['rows','columns'])
        self.phys_tolerance=self.field(page,settings,'Grid tolerance mm','0.02')
        self.phys_mirror=self.field(page,settings,'Additional X reflection','no',['no','yes'])
        root.Add(settings,0,wx.EXPAND|wx.ALL,8)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        self.button(page,actions,'Preview physical pinout',self.preview_physical)
        self.button(page,actions,'Copy physical CSV',self.copy_physical)
        root.Add(actions,0,wx.ALL,8)
        self.physical_table=self.table(page,['Preview']);root.Add(self.physical_table,1,wx.EXPAND|wx.ALL,6)
        page.SetSizer(root);return page

    def physical_inputs(self):
        return (self.footprint_rows(self.phys_ref.GetValue()),self.phys_ref.GetValue(),self.phys_side.GetValue(),self.phys_angle.GetValue(),self.phys_order.GetValue(),float(self.phys_tolerance.GetValue()),self.phys_mirror.GetValue()=='yes')

    def preview_physical(self):
        self._physical_snapshot=None;values=self.physical_inputs()
        rows=mating.physical_grid(values[0],side=values[2],rotation_deg=float(values[3]),tolerance_mm=values[5],mirror=values[6])
        if not rows:raise ValueError('This footprint has no numbered contacts to export.')
        if values[4]=='columns':rows=[list(r) for r in zip(*rows)]
        text_rows=[[f"{p['pin']} · {p['label']}" if p else '' for p in row] for row in rows]
        table=self.physical_table
        if table.GetNumberRows():table.DeleteRows(0,table.GetNumberRows())
        if table.GetNumberCols():table.DeleteCols(0,table.GetNumberCols())
        table.AppendCols(len(text_rows[0]) if text_rows else 1)
        self.fill(table,text_rows);table.EnableEditing(False)
        for col in range(table.GetNumberCols()):table.SetColSize(col,160)
        out=StringIO();csv.writer(out).writerows(text_rows);self._physical_text=out.getvalue();self._physical_snapshot=values
        self.physical_table.Enable(True)
        self.status.SetLabel('Physical contact rows/columns from saved pad coordinates. Empty grid locations are retained; pin numbers are not renumbered.')

    def copy_physical(self):
        if self._physical_snapshot is None or self.physical_inputs()!=self._physical_snapshot:
            raise ValueError('Board or view changed. Preview the physical pinout again.')
        copy_text(self._physical_text)
