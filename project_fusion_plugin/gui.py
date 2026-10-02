"""Native wxPython UI. All work is file-based; the active editor is never modified."""
from pathlib import Path
import json
import re
import threading
import traceback
import copy
import tempfile
import wx
import wx.grid
import wx.html
from .engine import analyse, merge
from .model import Options, SourceSpec, MergeError, MAX_INSTANCES, MAX_COLUMNS, duplicate_sources
from .variants import detect_variants, DEFAULT
from .version import VERSION
from .preview import PlacementPreview
from .sheet_preview import SheetPreview

CHOOSE_VARIANT = "[Choose variant]"


class FusionDialog(wx.Dialog):
    def __init__(self, parent=None, initial=''):
        super().__init__(parent, title=f'Wayri Project Fusion {VERSION} — Testing release',
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         size=(1060, 900))
        self.SetMinSize((860, 700))
        self.busy = False
        self.output_project = None
        self.initial_target = str(Path(initial).with_suffix('.kicad_pro')) if initial else ''
        self.source_extras = []
        self.row_variants = []
        self.import_plan = None
        self.placement_history=[]
        self.selector_row = None
        self.notebook = wx.Notebook(self)
        self.controls_page = wx.ScrolledWindow(self.notebook)
        self.controls_page.SetScrollRate(0,16)
        self.settings_page = wx.ScrolledWindow(self.notebook)
        self.settings_page.SetScrollRate(0,16)
        self.tools_page = wx.ScrolledWindow(self.notebook)
        self.tools_page.SetScrollRate(0,16)
        self.review_page = wx.Panel(self.notebook)
        self.notebook.AddPage(self.controls_page, '1  Sources')
        self.notebook.AddPage(self.settings_page, '2  Merge settings')
        self.notebook.AddPage(self.tools_page, 'Tools and linked designs')
        self.notebook.AddPage(self.review_page, '3  Review and create')
        self.build_controls(initial)
        self.build_review()
        self.gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL)
        self.status = wx.StaticText(self, label='Saved files only. Originals and the active editor remain unchanged.',style=wx.ST_ELLIPSIZE_END)
        self.status.SetMinSize((1,-1))
        self.analyse_button = wx.Button(self, label='Preview')
        self.merge_button = wx.Button(self, label='Create new project')
        self.open_button = wx.BitmapButton(self,bitmap=wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN,wx.ART_BUTTON,(18,18)),style=wx.BORDER_NONE)
        self.open_button.SetName('Open output folder')
        self.open_button.Disable()
        self.help_button = wx.BitmapButton(self,bitmap=wx.ArtProvider.GetBitmap(wx.ART_HELP,wx.ART_BUTTON,(18,18)),style=wx.BORDER_NONE)
        self.help_button.SetName('Help')
        self.close_button = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.offline_button=wx.Button(self,label='Continue offline')
        self.offline_button.Bind(wx.EVT_BUTTON,self.continue_offline);self.offline_button.Disable()
        self.offline_button.SetToolTip('Keep this workspace and reviewed plan in a separate window, then close target editors before Apply.')
        self.analyse_button.Bind(wx.EVT_BUTTON, lambda e: self.start(False))
        self.merge_button.Bind(wx.EVT_BUTTON, lambda e: self.start(True))
        self.open_button.Bind(wx.EVT_BUTTON, self.open_output)
        self.help_button.Bind(wx.EVT_BUTTON, self.help)
        self.close_button.Bind(wx.EVT_BUTTON, self.close)
        for button,art,tip in ((self.analyse_button,wx.ART_FIND,'Read saved sources and review placement and reference mapping.'),
                               (self.merge_button,wx.ART_NEW_DIR,'Create a new combined project after reviewing settings.'),
                               (self.open_button,wx.ART_FOLDER_OPEN,'Open the last successfully created output folder.'),
                               (self.help_button,wx.ART_HELP,'Read the offline workflow and limitations.')):
            self.decorate(button,art,tip)
        self.Bind(wx.EVT_CLOSE, self.close)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.help_button, self.open_button,self.offline_button):
            buttons.Add(b, 0, wx.RIGHT, 8)
        buttons.AddStretchSpacer()
        for b in (self.analyse_button, self.merge_button, self.close_button):
            buttons.Add(b, 0, wx.LEFT, 8)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 12)
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        self.mode_changed(None)
        self.Bind(wx.EVT_SIZE,self.resize_content)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.gauge.Pulse(), self.timer)
        # Keep the full dialog usable on smaller displays.
        area = wx.GetClientDisplayRect()
        self.SetSize((min(1060, max(860, area.width-40)), min(900, max(700, area.height-60))))
        self.CentreOnScreen()

    @staticmethod
    def decorate(button, art, tip=''):
        bitmap=wx.ArtProvider.GetBitmap(art,wx.ART_BUTTON,(16,16))
        if bitmap.IsOk():button.SetBitmap(bitmap)
        button.SetToolTip(tip or button.GetLabel())

    def action(self,parent,label,handler,art,tip):
        compact=label.startswith(('Duplicate','Remove','Move up','Move down','Refresh','Load setup','Save setup','Fit all','Go to source','Undo placement','Open review project','Live PCB capability'))
        if compact:
            button=wx.BitmapButton(parent,bitmap=wx.ArtProvider.GetBitmap(art,wx.ART_BUTTON,(18,18)),style=wx.BORDER_NONE)
            button.SetName(label);button.SetLabel(label)
        else:button=wx.Button(parent,label=label)
        self.decorate(button,art,tip)
        button.Bind(wx.EVT_BUTTON,handler)
        return button

    def note(self,parent,label):
        control=wx.StaticText(parent,label=label)
        self._wrapped.append((control,label))
        control.Wrap(720)
        return control

    def resize_content(self,event):
        if hasattr(self,'_wrapped'):
            for control,label in self._wrapped:
                width=max(200,control.GetParent().GetClientSize().width-40)
                control.SetLabel(label);control.Wrap(width)
            for page in (self.controls_page,self.settings_page,self.tools_page):
                page.Layout();page.FitInside()
        event.Skip()

    def enable_inputs(self,value):
        for page in (self.controls_page,self.settings_page,self.tools_page):page.Enable(value)

    def build_controls(self, initial):
        self._wrapped=[]
        p=self.controls_page;main=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(p,label='Build your source list')
        font=title.GetFont();font.SetPointSize(font.GetPointSize()+3);font.SetWeight(wx.FONTWEIGHT_BOLD);title.SetFont(font)
        main.Add(title,0,wx.ALL,12)
        modebar=wx.BoxSizer(wx.HORIZONTAL)
        self.import_current=wx.CheckBox(p,label='Import into current / existing project')
        self.import_current.SetToolTip('Unchecked creates a new project; checked imports into a saved target with preview and backup.')
        self.import_current.Bind(wx.EVT_CHECKBOX,self.mode_changed)
        modebar.Add(self.import_current,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
        self.copy_layout=wx.CheckBox(p,label='Copy routed layout');self.copy_layout.SetValue(True)
        self.copy_layout.Bind(wx.EVT_CHECKBOX,self.on_layout_changed)
        modebar.Add(self.copy_layout,0,wx.ALIGN_CENTER_VERTICAL)
        self.copy_libraries=wx.ToggleButton(p,label='Libraries + 3D')
        self.copy_libraries.SetValue(True);self.decorate(self.copy_libraries,wx.ART_FOLDER,'Bundle available source libraries and 3D models. Off retains resolved external references; active symbol snapshots and required normalized footprints are still generated.')
        self.copy_libraries.Bind(wx.EVT_TOGGLEBUTTON,self.on_source_cell_changed)
        modebar.Add(self.copy_libraries,0,wx.LEFT,12)
        main.Add(modebar,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        main.Add(self.note(p,'Add whole projects or selected subsheets with their routed layout. Each row is an independent instance; up to 100 instances are supported.'),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.source_splitter=wx.SplitterWindow(p,style=wx.SP_LIVE_UPDATE);self.source_splitter.SetMinimumPaneSize(240)
        self.grid=wx.grid.Grid(self.source_splitter);self.grid.CreateGrid(0,6)
        from .source_selection import SourceSelectionPanel
        self.source_selector=SourceSelectionPanel(self.source_splitter,self.selection_changed)
        self.source_splitter.SplitVertically(self.grid,self.source_selector,540);self.source_splitter.SetSashGravity(.6)
        for i,label in enumerate(('Design file','Alias','Variant','X (mm)','Y (mm)','Scope')):self.grid.SetColLabelValue(i,label)
        for i,width in enumerate((190,110,130,60,60,75)):self.grid.SetColSize(i,width)
        self.grid.GetGridWindow().Bind(wx.EVT_MOTION,self.source_tooltip)
        self.grid.SetRowLabelSize(36);self.grid.SetMinSize((1,250));self.grid.SetSelectionMode(wx.grid.Grid.SelectRows)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self.on_source_cell_changed)
        self.grid.Bind(wx.grid.EVT_GRID_SELECT_CELL,self.select_source_row)
        main.Add(self.source_splitter,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        bar=wx.WrapSizer(wx.HORIZONTAL,wx.REMOVE_LEADING_SPACES)
        for label,handler,art,tip in [
            ('Add design…',self.add,wx.ART_FILE_OPEN,'Choose a project, schematic or PCB; its type and hierarchy are detected automatically.'),
            ('Duplicate…',self.duplicate_selected,wx.ART_COPY,'Duplicate selected instances with unique aliases and independent placement.'),
            ('Remove',self.remove,wx.ART_DELETE,'Remove selected rows from this setup; source files are retained.'),
            ('Move up',lambda e:self.move(-1),wx.ART_GO_UP,'Move selected instance earlier; row 1 supplies project settings.'),
            ('Move down',lambda e:self.move(1),wx.ART_GO_DOWN,'Move selected instance later.'),
            ('Refresh variants',self.refresh_variants,wx.ART_REDO,'Read variant choices from saved sources.'),
            ('Load setup…',self.load_config,wx.ART_FOLDER_OPEN,'Restore saved source instances and merge settings.'),
            ('Save setup…',self.save_config,wx.ART_FILE_SAVE,'Save source paths, variants, placement and merge settings.')]:
            bar.Add(self.action(p,label,handler,art,tip),0,wx.RIGHT|wx.BOTTOM,6)
        main.Add(bar,0,wx.EXPAND|wx.ALL,12)
        self.instance_count=wx.StaticText(p,label='Instances: 0 / '+str(MAX_INSTANCES));main.Add(self.instance_count,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        main.Add(self.note(p,'Choose a variant for each row. Blank X/Y uses automatic placement; explicit X/Y places the source upper-left corner in millimetres. Long paths can be scrolled horizontally in the source table.'),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        p.SetSizer(main)

        p=self.settings_page;main=wx.BoxSizer(wx.VERTICAL)
        self.name=wx.TextCtrl(p,value='Combined')
        self.target_project=wx.FilePickerCtrl(p,path=self.initial_target,message='Choose the saved target project',wildcard='KiCad project or schematic|*.kicad_pro;*.kicad_sch',style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL)
        self.target_project.SetMinSize((1,-1));self.target_project.Bind(wx.EVT_FILEPICKER_CHANGED,self.on_source_cell_changed)
        self.target_closed=wx.CheckBox(p,label='Target schematic and PCB editors are saved and closed for offline Apply')
        main.Add(wx.StaticText(p,label='Import target (uses the current saved project when launched from KiCad)'),0,wx.LEFT|wx.RIGHT|wx.TOP,12)
        main.Add(self.target_project,0,wx.EXPAND|wx.ALL,12);main.Add(self.target_closed,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.parent_folder=wx.DirPickerCtrl(p,path=str(Path(initial).parent.parent) if initial else str(Path.home()),message='Choose the parent for a NEW output folder')
        self.annotation=wx.Choice(p,choices=['Sequential — R1, R2, R3…','Per-design blocks — R1001, R2001…']);self.annotation.SetSelection(0)
        self.columns=wx.SpinCtrl(p,min=1,max=MAX_COLUMNS,initial=2)
        self.gap=wx.SpinCtrlDouble(p,min=0,max=1000,initial=10,inc=1)
        self.margin=wx.SpinCtrlDouble(p,min=0,max=1000,initial=5,inc=1)
        self.outline=wx.Choice(p,choices=['One rectangular Edge.Cuts outline','Preserve original outlines / separate islands']);self.outline.SetSelection(0)
        self.block=wx.SpinCtrl(p,min=10,max=1000000,initial=1000)
        groups=[('Output project',[('New project name',self.name),('Parent folder',self.parent_folder)]),
                ('References and placement',[('Reference numbering',self.annotation),('Reference block size',self.block),('Automatic columns',self.columns),('Gap (mm)',self.gap),('Board outline',self.outline),('Outline margin (mm)',self.margin)])]
        for heading,rows in groups:
            group=wx.StaticBoxSizer(wx.VERTICAL,p,heading);form=wx.FlexGridSizer(cols=2,vgap=8,hgap=12);form.AddGrowableCol(1)
            for label,control in rows:
                control.Reparent(group.GetStaticBox())
                control.SetMinSize((1,-1));form.Add(wx.StaticText(group.GetStaticBox(),label=label),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
            group.Add(form,0,wx.EXPAND|wx.ALL,12);main.Add(group,0,wx.EXPAND|wx.ALL,10)
        self.saved=wx.CheckBox(p,label='Sources are saved and will remain unchanged during this operation')
        self.cuts=wx.CheckBox(p,label='Move original Edge.Cuts to Dwgs.User in rectangle mode')
        self.settings=wx.CheckBox(p,label='Use row 1 settings when sources differ')
        self.layers=wx.CheckBox(p,label='Allow reviewed mapping of mixed copper-layer stacks')
        self.strict_assets=wx.CheckBox(p,label='Require referenced local libraries, models and assets');self.strict_assets.SetValue(True)
        group=wx.StaticBoxSizer(wx.VERTICAL,p,'Review acknowledgements')
        for control,detail in [(self.saved,'Fusion reads saved files. Save schematic and PCB before analysis and creation.'),
                (self.cuts,'Includes slots and cutouts: review and recreate required cuts before manufacture.'),
                (self.settings,'Custom source rules are archived for manual migration, not activated.'),
                (self.layers,'Top-down mapping may convert vias to blind spans. Review PTH barrels, stackup and impedance.'),
                (self.strict_assets,'Missing dependencies stop creation instead of producing a non-portable project.')]:
            control.Reparent(group.GetStaticBox())
            group.Add(control,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,10)
            group.Add(self.note(group.GetStaticBox(),detail),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        main.Add(group,0,wx.EXPAND|wx.ALL,10)
        self.cli=wx.FilePickerCtrl(p,message='Locate KiCad 10 kicad-cli',wildcard='KiCad CLI|kicad-cli.exe;kicad-cli|All files|*',style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL)
        self.cli.SetMinSize((1,-1));main.Add(wx.StaticText(p,label='KiCad CLI override (leave blank to detect automatically)'),0,wx.LEFT|wx.RIGHT,12);main.Add(self.cli,0,wx.EXPAND|wx.ALL,12)
        main.Add(self.note(p,'The largest source supplies the copper stack; row 1 supplies other project settings. Circuits remain electrically isolated with namespaced nets. Review native DRC and ERC before manufacture.'),0,wx.EXPAND|wx.ALL,12)
        p.SetSizer(main)

        p=self.tools_page;main=wx.BoxSizer(wx.VERTICAL)
        for heading,description,actions in [
            ('Prepare selected sources','Review repairs and field edits before creating separate source copies.',[
                ('Repair source copy…',self.repair_source,wx.ART_EXECUTABLE_FILE,'Repair supported source synchronization issues in a new copy.'),
                ('BOM and field manager…',self.bom_fields,wx.ART_LIST_VIEW,'Review consolidated BOM and preview field changes.'),
                ('Audit dependencies…',self.dependencies,wx.ART_FIND,'Inspect local libraries, models and assets.'),
                ('Paths and extra assets…',self.edit_source_paths,wx.ART_FOLDER,'Configure source-specific path remaps and additional assets.')]),
            ('Insert into an existing design','Import selected source projects or subsheets into a saved target; retain target references and hierarchy.',[
                ('Import mode',lambda e:self.choose_import_mode(),wx.ART_GO_FORWARD,'Switch the main workspace to current/existing project import.')]),
            ('Maintain linked designs','Review source changes, pin-connection changes and local conflicts. Links can be broken without deleting local copies.',[
                ('Linked updates and overview…',self.open_linked_updates,wx.ART_REPORT_VIEW,'Open hierarchy overview, link status, change review, update, undo and unlink tools.')])]:
            group=wx.StaticBoxSizer(wx.VERTICAL,p,heading);group.Add(self.note(group.GetStaticBox(),description),0,wx.EXPAND|wx.ALL,10)
            bar=wx.WrapSizer(wx.HORIZONTAL,wx.REMOVE_LEADING_SPACES)
            for label,handler,art,tip in actions:
                button=self.action(group.GetStaticBox(),label,handler,art,tip);bar.Add(button,0,wx.RIGHT|wx.BOTTOM,8)
                if label=='Import mode':self.import_button=button
                if handler==self.open_linked_updates:self.linked_button=button
            group.Add(bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10);main.Add(group,0,wx.EXPAND|wx.ALL,10)
        p.SetSizer(main)
        for control in (self.name,self.columns,self.gap,self.margin,self.block):control.Bind(wx.EVT_TEXT,self.on_source_cell_changed)
        for control in (self.annotation,self.outline):control.Bind(wx.EVT_CHOICE,self.on_source_cell_changed)
        for control in (self.cuts,self.settings,self.layers,self.strict_assets):control.Bind(wx.EVT_CHECKBOX,self.on_source_cell_changed)
        self.parent_folder.Bind(wx.EVT_DIRPICKER_CHANGED,self.on_source_cell_changed)
        self.cli.Bind(wx.EVT_FILEPICKER_CHANGED,self.on_source_cell_changed)
        for page in (self.controls_page,self.settings_page,self.tools_page):page.FitInside()
        if initial and Path(initial).with_suffix('.kicad_pro').is_file():self.append_source(str(Path(initial).with_suffix('.kicad_pro')))

    def choose_import_mode(self):
        self.import_current.SetValue(True);self.mode_changed(None);self.notebook.SetSelection(0)

    def mode_changed(self,event):
        self.clear_results()
        self.merge_button.SetLabel('Apply reviewed import' if self.import_current.GetValue() else 'Create new project')
        self.target_project.Enable(self.import_current.GetValue());self.target_closed.Enable(self.import_current.GetValue())
        if event:event.Skip()

    def on_layout_changed(self,event):
        self.source_selector.set_include_layout(self.copy_layout.GetValue())
        self.selection_changed()
        self.clear_results();event.Skip()

    def select_source_row(self,event):
        row=event.GetRow();wx.CallAfter(self.load_source_selection,row);event.Skip()

    def source_tooltip(self,event):
        _,y=self.grid.CalcUnscrolledPosition(event.GetPosition())
        row=self.grid.YToRow(y)
        if 0<=row<self.grid.GetNumberRows():self.grid.GetGridWindow().SetToolTip(self.grid.GetCellValue(row,0))
        event.Skip()

    def load_source_selection(self,row):
        if self.busy or not 0<=row<self.grid.GetNumberRows():return
        self.selector_row=row
        try:
            spec=self.options().sources[row]
            self.source_selector.load_spec(spec,self.cli.GetPath())
            self.source_selector.set_include_layout(self.copy_layout.GetValue())
        except Exception as exc:self.status.SetLabel(str(exc))

    def selection_changed(self,*unused):
        row=self.selector_row
        if row is not None and 0<=row<len(self.source_extras):
            try:self.source_extras[row]['selection']=self.source_selector.selected_request()
            except Exception:return
            request=self.source_extras[row]['selection']
            self.grid.SetCellValue(row,5,'Project' if request.get('whole_project') else 'Sheets')
        if hasattr(self,'preview'):self.clear_results()

    def build_review(self):
        p=self.review_page; box=wx.BoxSizer(wx.VERTICAL)
        box.Add(self.note(p,'Drag a block to move it; Shift-drag pans; wheel zooms. Existing target is locked. Preview again after moving.'),0,wx.EXPAND|wx.ALL,6)
        box.Add(self.note(p,'Review saved PCB geometry at the planned placement. Select a source on the board or in the reference table. This preview does not certify connectivity or DRC.'),0,wx.EXPAND|wx.ALL,10)
        bar=wx.WrapSizer(wx.HORIZONTAL,wx.REMOVE_LEADING_SPACES)
        bar.Add(self.action(p,'Fit all',lambda e:self.preview.fit(),wx.ART_NORMAL_FILE,'Fit all planned source instances.'),0,wx.RIGHT|wx.BOTTOM,8)
        self.preview_layer=wx.Choice(p,choices=['All copper layers']);self.preview_layer.SetSelection(0)
        self.preview_layer.Bind(wx.EVT_CHOICE,self.change_preview_layer)
        bar.Add(wx.StaticText(p,label='Copper layer'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6);bar.Add(self.preview_layer,0,wx.RIGHT|wx.BOTTOM,8)
        self.preview_details=wx.CheckBox(p,label='Footprint outlines')
        self.preview_labels=wx.CheckBox(p,label='References')
        self.preview_details.Bind(wx.EVT_CHECKBOX,self.preview_display_changed)
        self.preview_labels.Bind(wx.EVT_CHECKBOX,self.preview_display_changed)
        bar.Add(self.preview_details,0,wx.RIGHT,8);bar.Add(self.preview_labels,0,wx.RIGHT,8)
        bar.Add(self.action(p,'Go to source',self.go_to_source,wx.ART_GO_BACK,'Return to the selected source row.'),0,wx.RIGHT|wx.BOTTOM,8)
        box.Add(bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.review_splitter=wx.SplitterWindow(p,style=wx.SP_LIVE_UPDATE);self.review_splitter.SetMinimumPaneSize(240)
        self.visual_tabs=wx.Notebook(self.review_splitter)
        self.preview=PlacementPreview(self.visual_tabs);self.preview.on_select=self.select_preview_source
        self.preview.on_move=self.move_preview_source
        self.visual_tabs.AddPage(self.preview,'PCB layout blocks')
        self.sheet_preview=SheetPreview(self.visual_tabs)
        self.sheet_preview.on_select=self.select_preview_source
        self.sheet_preview.on_move=self.move_sheet_source
        self.visual_tabs.AddPage(self.sheet_preview,'Schematic sheet placement')
        inspector=wx.Notebook(self.review_splitter)
        mapping_page=wx.Panel(inspector);mapping_box=wx.BoxSizer(wx.VERTICAL)
        self.mapping=wx.ListCtrl(mapping_page,style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        for i,(label,width) in enumerate([('Source',150),('Original reference',200),('Combined reference',200)]):
            self.mapping.InsertColumn(i,label,width=width)
        mapping_box.Add(self.mapping,1,wx.EXPAND);mapping_page.SetSizer(mapping_box)
        inspector.AddPage(mapping_page,'References')
        log_page=wx.Panel(inspector);log_box=wx.BoxSizer(wx.VERTICAL)
        self.log=wx.TextCtrl(log_page,style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        log_box.Add(self.log,1,wx.EXPAND);log_page.SetSizer(log_box);inspector.AddPage(log_page,'Progress')
        self.review_inspector=inspector
        bar.Add(self.action(p,'Undo placement',self.undo_placement,wx.ART_UNDO,'Undo the last visual placement change.'),0,wx.RIGHT,8)
        tree_page=wx.Panel(inspector);tree_box=wx.BoxSizer(wx.VERTICAL)
        self.design_tree=wx.TreeCtrl(tree_page,style=wx.TR_HAS_BUTTONS|wx.TR_LINES_AT_ROOT)
        self.design_tree.Bind(wx.EVT_TREE_SEL_CHANGED,self.tree_selected)
        tree_box.Add(self.design_tree,1,wx.EXPAND);tree_page.SetSizer(tree_box)
        inspector.AddPage(tree_page,'Hierarchy')
        issue_page=wx.Panel(inspector);issue_box=wx.BoxSizer(wx.VERTICAL)
        self.issue_list=wx.ListCtrl(issue_page,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.issue_list.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_issue_source)
        for i,(label,width) in enumerate([('Design',120),('Issue / resolution',370)]):self.issue_list.InsertColumn(i,label,width=width)
        issue_box.Add(self.issue_list,1,wx.EXPAND)
        self.resolve_button=wx.Button(issue_page,label='Repair selected design issues in a copy')
        self.resolve_button.Bind(wx.EVT_BUTTON,self.resolve_issue)
        issue_box.Add(self.resolve_button,0,wx.ALL,6)
        issue_page.SetSizer(issue_box);inspector.AddPage(issue_page,'Issues')
        self.merge_issues=[]
        bar.Add(self.action(p,'Open review project',self.open_review_project,wx.ART_FOLDER_OPEN,'Open the validated review copy while source and target editors stay open.'),0,wx.RIGHT,8)
        bar.Add(self.action(p,'Live PCB capability',self.check_live_capability,wx.ART_INFORMATION,'Check the originating editor API without enabling or restarting it.'),0,wx.RIGHT,8)
        self.mapping.Bind(wx.EVT_LIST_ITEM_SELECTED,lambda e:self.preview.set_selected_alias(self.mapping.GetItemText(e.GetIndex())))
        self.review_splitter.SplitVertically(self.visual_tabs,inspector,580)
        self.review_splitter.SetSashGravity(.65)
        box.Add(self.review_splitter,1,wx.EXPAND|wx.ALL,10)
        p.SetSizer(box)

    def change_preview_layer(self,event):
        index=self.preview_layer.GetSelection()
        self.preview.set_layer(None if index==0 else self._preview_layers[index-1])

    def preview_display_changed(self,event):
        self.preview.show_details=self.preview_details.GetValue()
        self.preview.show_references=self.preview_labels.GetValue();self.preview.Refresh()

    def open_review_project(self,event):
        if self.import_plan:
            path=Path(self.import_plan['candidate_directory'])/Path(self.import_plan['target_project']).name
            wx.LaunchDefaultApplication(str(path))
            self.status.SetLabel('Opened the saved-file review copy. The current target and its unsaved editor state are preserved.')
        else:self.status.SetLabel('Preview the designs first to create a validated review project.')

    def check_live_capability(self,event):
        try:
            from .live_apply import connect_originating_board,capabilities
            board=connect_originating_board(str(Path(self.target_project.GetPath()).with_suffix('.kicad_pcb')))
            result=capabilities(board)
            self.status.SetLabel(result['status']+'. PCB transactions only; live schematic/project insertion is unavailable.')
            self.append_log(json.dumps(result,indent=2))
        except Exception as exc:
            self.status.SetLabel(str(exc));self.append_log(str(exc))

    def select_preview_source(self,alias):
        for row in range(self.mapping.GetItemCount()):
            if self.mapping.GetItemText(row)==alias:
                self.mapping.Select(row);self.mapping.EnsureVisible(row);break

    def go_to_source(self,event):
        alias=self.preview.selected_alias
        for row in range(self.grid.GetNumberRows()):
            if self.grid.GetCellValue(row,1)==alias:
                self.grid.ClearSelection();self.grid.SelectRow(row);self.grid.MakeCellVisible(row,0);break
        self.notebook.SetSelection(self.notebook.FindPage(self.controls_page))

    def flush_grid(self):
        if self.grid.IsCellEditControlEnabled():
            self.grid.SaveEditControlValue(); self.grid.HideCellEditControl(); self.grid.DisableCellEditControl()

    def tree_selected(self,event):
        alias=self.design_tree.GetItemData(event.GetItem())
        if alias:self.preview.set_selected_alias(alias);self.sheet_preview.set_selected_alias(alias);self.select_preview_source(alias)

    def fill_design_tree(self,sources):
        self.design_tree.DeleteAllItems();root=self.design_tree.AddRoot('Design instances')
        for source in sources:
            alias=source.alias
            item=self.design_tree.AppendItem(root,alias);self.design_tree.SetItemData(item,alias)
            sheets=getattr(source,'sheets',[])
            if sheets:
                branches={'':item}
                for sheet in sheets:
                    path=sheet.get('display_path','') if isinstance(sheet,dict) else sheet.display_path
                    parts=[v for v in path.split('/') if v]
                    for depth in range(1,len(parts)+1):
                        key='/'.join(parts[:depth])
                        if key not in branches:
                            branch=self.design_tree.AppendItem(branches['/'.join(parts[:depth-1])],parts[depth-1])
                            self.design_tree.SetItemData(branch,alias);branches[key]=branch
            row=next((r for r in range(self.grid.GetNumberRows()) if self.grid.GetCellValue(r,1)==alias),None)
            if row is not None:
                request=self.source_extras[row].get('selection',{})
                for path in request.get('sheet_paths',[]):
                    child=self.design_tree.AppendItem(item,path);self.design_tree.SetItemData(child,alias)
                if not request.get('sheet_paths') and not sheets:self.design_tree.AppendItem(item,'Whole project hierarchy')
        self.design_tree.ExpandAll()

    def move_preview_source(self,alias,x,y,delta):
        if self.busy:
            self.preview.translate(alias,-delta[0],-delta[1]);return
        row=next((r for r in range(self.grid.GetNumberRows()) if self.grid.GetCellValue(r,1)==alias),None)
        if row is None:
            self.preview.translate(alias,-delta[0],-delta[1]);return
        previous=(self.grid.GetCellValue(row,3),self.grid.GetCellValue(row,4))
        self.placement_history.append((alias,previous,delta))
        self.grid.SetCellValue(row,3,f'{x:.6f}');self.grid.SetCellValue(row,4,f'{y:.6f}')
        self.import_plan=None;self.offline_button.Disable()
        self.status.SetLabel(f'{alias}: X {x:.3f}, Y {y:.3f} mm. Placement changed — Preview again before Apply.')

    def move_sheet_source(self,alias,x,y,delta):
        if self.busy:
            self.sheet_preview.translate(alias,-delta[0],-delta[1]);return
        for row in range(self.grid.GetNumberRows()):
            if self.grid.GetCellValue(row,1)==alias:
                old=list(self.source_extras[row].get('sheet_position_mm',[]))
                self.placement_history.append((alias,old,delta,'sheet'))
                self.source_extras[row]['sheet_position_mm']=[round(x,6),round(y,6)]
                self.import_plan=None;self.offline_button.Disable()
                self.status.SetLabel('Sheet block moved. Preview again before Apply.');return

    def undo_placement(self,event):
        if self.busy or not self.placement_history:return
        change=self.placement_history.pop();alias,previous,delta=change[:3]
        for row in range(self.grid.GetNumberRows()):
            if self.grid.GetCellValue(row,1)==alias:
                if len(change)>3:
                    self.source_extras[row]['sheet_position_mm']=previous;break
                self.grid.SetCellValue(row,3,previous[0]);self.grid.SetCellValue(row,4,previous[1]);break
        canvas=self.sheet_preview if len(change)>3 else self.preview
        canvas.translate(alias,-delta[0],-delta[1]);self.import_plan=None
        self.offline_button.Disable();self.status.SetLabel('Placement undone. Preview again before Apply.')

    def show_merge_issues(self,reports):
        self.merge_issues=[];self.issue_list.DeleteAllItems()
        for spec,report in reports:
            for issue in report['issues']:
                row=self.issue_list.InsertItem(self.issue_list.GetItemCount(),spec.alias)
                self.issue_list.SetItem(row,1,issue['error']+' — '+str(issue.get('action') or 'Manual correction required'))
                self.merge_issues.append((spec,report,issue))
        if self.merge_issues:
            self.review_inspector.SetSelection(3)
            try:
                from types import SimpleNamespace
                records=self.visual_source_records([spec for spec,_ in reports],{'report':{'include_layout':True}})
                self.preview.locked_aliases={r['alias'] for r in records}
                self.preview.show_sources([SimpleNamespace(**r) for r in records])
                self.fill_design_tree([SimpleNamespace(**r) for r in records])
            except Exception as exc:self.append_log('Source preview unavailable: '+str(exc))

    def select_issue_source(self,event):
        index=event.GetIndex()
        if 0<=index<len(self.merge_issues):self.preview.set_selected_alias(self.merge_issues[index][0].alias)

    def show_validation_failure(self,error):
        if not self.merge_issues:
            issue={'id':'merge:validation','source':'Merge validation','reference':'','code':'native_validation',
                'error':str(error),'action':None}
            self.show_merge_issues([(SourceSpec('','Merge validation'),{'issues':[issue]})])
        self.review_inspector.SetSelection(3)

    def scan_worker_issues(self,specs,include_layout=True):
        from .merge_issues import scan_source
        reports=[]
        for spec in specs:
            if not include_layout:continue
            try:report=scan_source(spec)
            except Exception as exc:
                report={'source':spec.alias,'project':spec.project,'issues':[{'id':spec.alias+':source','source':spec.alias,
                    'reference':'','code':'source_preflight','error':str(exc),'action':None}]}
            reports.append((spec,report))
        wx.CallAfter(self.show_merge_issues,reports)
        if any(report['issues'] for _,report in reports):
            raise MergeError('Resolve the source issues in the Merge issues panel, then Preview again.')

    @staticmethod
    def visual_source_records(specs,plan):
        from . import sexpr as sx
        from .board import board_bounds
        from .layers import copper_sequence
        from .assets import sha256
        translations={s['alias']:s.get('translation_mm',[0,0]) for s in plan['report'].get('sources',[])}
        records=[];next_x=20.0
        if not plan['report'].get('include_layout'):return records
        for spec in specs:
            board=Path(spec.project).with_suffix('.kicad_pcb')
            if not board.is_file():continue
            tree=sx.load(board)
            from .schematic import discover,new_uuid
            try:hierarchy=discover(spec,new_uuid(),require_board=False);sheets=hierarchy.sheets
            except MergeError:sheets=[]
            bounds=board_bounds(tree)
            translation=translations.get(spec.alias)
            if translation is None:
                x=spec.x_mm if spec.x_mm is not None else next_x
                y=spec.y_mm if spec.y_mm is not None else 20.0
                translation=[x-bounds[0],y-bounds[1]];next_x=x+bounds[2]-bounds[0]+10
            records.append({'alias':spec.alias,'pcb_file':str(board),'bbox':board_bounds(tree),
                'translation':translation,'hashes':{str(board):sha256(board)},
                'layer_map':{},'copper_layers':copper_sequence(tree),
                'sheets':[{'display_path':s.display_path,'file':str(s.source_path)} for s in sheets]})
        return records

    def resolve_issue(self,event):
        if self.busy:return
        index=self.issue_list.GetFirstSelected()
        if index<0:return
        spec,report,issue=self.merge_issues[index]
        resolutions={i['id']:i['action'] for i in report['issues'] if i.get('action')}
        if any(not i.get('action') for i in report['issues']):
            self.status.SetLabel('This design has issues requiring a source correction. See the issue list.');return
        # Review the concrete proposed edits before making an independent copy.
        description='\n'.join(i['error']+'\n  '+str(i.get('action'))+' '+str(i.get('suggested_reference') or i.get('footprint') or '') for i in report['issues'])
        if wx.MessageBox(description+'\n\nCreate a repaired copy and use it for this instance?', 'Review source-copy repairs',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self)!=wx.YES:return
        self.busy=True;self.enable_inputs(False);self.resolve_button.Disable();self.status.SetLabel('Validating source-copy repairs…')
        cli=self.cli.GetPath()
        # Keep local repair candidates adjacent to the requested output, not in the source tree.
        parent=Path(self.options().destination).parent
        def worker():
            try:
                from .repair import preview_repair,apply_repair
                from .insertion_gui import fresh_directory
                plan=preview_repair(spec,cli_path=cli,resolutions=resolutions)
                destination=fresh_directory(parent,spec.alias+'-ReviewedRepair')
                result=apply_repair(plan,str(destination),cli)
                wx.CallAfter(self.repair_issue_done,spec,result,None)
            except Exception as exc:wx.CallAfter(self.repair_issue_done,spec,None,str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def repair_issue_done(self,spec,result,error):
        self.busy=False;self.enable_inputs(True);self.resolve_button.Enable()
        if error:self.status.SetLabel(error);return
        compiled,report=result;project=compiled.project
        for row in range(self.grid.GetNumberRows()):
            if self.grid.GetCellValue(row,1)==spec.alias:
                self.grid.SetCellValue(row,0,str(project));self.grid.SetCellValue(row,2,DEFAULT)
                self.source_extras[row]=self.spec_extras(compiled)
                self.row_variants[row]=[DEFAULT];self.grid.SetCellEditor(row,2,wx.grid.GridCellChoiceEditor([CHOOSE_VARIANT,DEFAULT],False));break
        self.clear_results();self.issue_list.DeleteAllItems();self.merge_issues=[]
        self.status.SetLabel('Repaired copy selected. Originals preserved. Preview again to inspect the merge.')

    @staticmethod
    def spec_extras(spec):
        return {'path_variables':spec.path_variables,'path_remaps':spec.path_remaps,
                'extra_asset_paths':spec.extra_asset_paths,'section_origin':spec.section_origin,'selection':spec.selection,
                'sheet_position_mm':spec.sheet_position_mm}

    def update_instance_count(self):
        self.instance_count.SetLabel(f'Instances: {self.grid.GetNumberRows()} / {MAX_INSTANCES}')

    def on_source_cell_changed(self,event):
        if hasattr(self,'preview'): self.clear_results()
        event.Skip()

    def append_source(self,path,alias=None,x=None,y=None,variant=None,extras=None,variant_choices=None):
        if self.grid.GetNumberRows()>=MAX_INSTANCES:
            raise MergeError(f'Maximum {MAX_INSTANCES} source instances.')
        if not alias:
            base=re.sub('[^A-Za-z0-9_]','_',Path(path).stem)[:20]
            if not base or not base[0].isalpha(): base='D_'+base
            used={self.grid.GetCellValue(r,1).casefold() for r in range(self.grid.GetNumberRows())}
            alias=base; i=2
            while alias.casefold() in used:
                suffix=f'_{i}'
                alias=base[:24-len(suffix)]+suffix; i+=1
        r=self.grid.GetNumberRows(); self.grid.AppendRows(1)
        metadata=dict(extras or {})
        self.source_extras.append(metadata); self.row_variants.append([])
        for c,value in enumerate((path,alias,variant or CHOOSE_VARIANT,'' if x is None else str(x),'' if y is None else str(y),
                                  'Section' if metadata.get('section_origin') else 'Project')):
            self.grid.SetCellValue(r,c,value)
        self.grid.SetReadOnly(r,0,True); self.grid.SetReadOnly(r,5,True)
        if variant_choices is None:
            self.detect_row(r,show_error=False)
        else:
            self.row_variants[r]=list(variant_choices)
            self.grid.SetCellEditor(r,2,wx.grid.GridCellChoiceEditor([CHOOSE_VARIANT,*variant_choices],False))
        self.update_instance_count()
        if hasattr(self,'preview'): self.clear_results()
        if hasattr(self,'source_selector'):wx.CallAfter(self.load_source_selection,r)

    def add(self,event):
        with wx.FileDialog(self,'Select source projects',wildcard='KiCad projects (*.kicad_pro)|*.kicad_pro|Root schematics (*.kicad_sch)|*.kicad_sch|PCBs (*.kicad_pcb)|*.kicad_pcb',style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal()!=wx.ID_OK: return
            paths=dlg.GetPaths()
        if len(paths)+self.grid.GetNumberRows()>MAX_INSTANCES:
            wx.MessageBox(f'A maximum of {MAX_INSTANCES} source instances is allowed.','Too many instances',wx.OK | wx.ICON_WARNING,self); return
        for path in paths: self.append_source(path)

    def duplicate_selected(self,event):
        if self.busy: return
        self.flush_grid()
        selected=self.selected_rows()
        if not selected: return
        remaining=MAX_INSTANCES-self.grid.GetNumberRows()
        maximum=remaining//len(selected)
        if maximum<1:
            wx.MessageBox(f'At most {MAX_INSTANCES} source instances are allowed.','Too many instances',wx.OK | wx.ICON_WARNING,self)
            return
        copies=wx.GetNumberFromUser('Additional copies of each selected instance:', 'Copies per instance',
                                    'Duplicate selected instances', 1, 1, maximum, self)
        if copies<1: return
        try:
            before=self.options().sources
            duplicated=duplicate_sources(before,selected,copies)
            choices=[]
            for index,names in enumerate(self.row_variants):
                choices.append(list(names))
                if index in selected: choices.extend([list(names) for _ in range(copies)])
            self.replace_sources(duplicated,cached_variants=choices)
            self.status.SetLabel(f'Added {len(selected)*copies} instances. Review aliases and automatic placement before Analyse.')
        except Exception as exc:
            wx.MessageBox(str(exc),'Cannot duplicate instances',wx.OK | wx.ICON_ERROR,self)

    def selected_rows(self):
        rows=set(self.grid.GetSelectedRows())
        for top,bottom in zip(self.grid.GetSelectionBlockTopLeft(),self.grid.GetSelectionBlockBottomRight()):
            rows.update(range(top[0],bottom[0]+1))
        if not rows and self.grid.GetNumberRows(): rows.add(self.grid.GetGridCursorRow())
        return sorted(rows)

    def remove(self,event):
        self.flush_grid()
        for r in reversed(self.selected_rows()):
            if r>=0:
                self.grid.DeleteRows(r,1); self.source_extras.pop(r); self.row_variants.pop(r)
        self.update_instance_count(); self.clear_results()

    def move(self,delta):
        self.flush_grid(); selected=self.selected_rows()
        if len(selected)!=1: return
        a=selected[0]; b=a+delta
        if not 0<=b<self.grid.GetNumberRows(): return
        for c in range(6):
            value=self.grid.GetCellValue(a,c)
            self.grid.SetCellValue(a,c,self.grid.GetCellValue(b,c)); self.grid.SetCellValue(b,c,value)
        self.source_extras[a],self.source_extras[b]=self.source_extras[b],self.source_extras[a]
        self.row_variants[a],self.row_variants[b]=self.row_variants[b],self.row_variants[a]
        for row in (a,b):
            self.grid.SetCellEditor(row,2,wx.grid.GridCellChoiceEditor([CHOOSE_VARIANT,*self.row_variants[row]],False))
        self.grid.SelectRow(b); self.grid.SetGridCursor(b,0)
        self.clear_results()

    def detect_row(self,row,show_error=True):
        self.flush_grid()
        try:
            spec=SourceSpec(self.grid.GetCellValue(row,0),self.grid.GetCellValue(row,1),**self.source_extras[row])
            names=detect_variants(spec)
            old=self.grid.GetCellValue(row,2)
            self.row_variants[row]=names
            self.grid.SetCellEditor(row,2,wx.grid.GridCellChoiceEditor([CHOOSE_VARIANT,*names],False))
            if old not in names:
                self.grid.SetCellValue(row,2,DEFAULT if names==[DEFAULT] else CHOOSE_VARIANT)
            return True
        except Exception as exc:
            self.grid.SetCellValue(row,2,CHOOSE_VARIANT)
            if show_error:
                wx.MessageBox(str(exc),'Variant detection stopped',wx.OK | wx.ICON_WARNING,self)
            return False

    def refresh_variants(self,event):
        rows=self.selected_rows() or list(range(self.grid.GetNumberRows()))
        for row in rows: self.detect_row(row)
        self.clear_results()

    def edit_source_paths(self,event):
        rows=self.selected_rows()
        if len(rows)!=1:
            wx.MessageBox('Select exactly one source row.','Source paths',wx.OK | wx.ICON_INFORMATION,self); return
        row=rows[0]
        path_keys=('path_variables','path_remaps','extra_asset_paths')
        data={'path_variables':{},'path_remaps':{},'extra_asset_paths':[]}
        data.update({key:self.source_extras[row][key] for key in path_keys if key in self.source_extras[row]})
        dlg=wx.Dialog(self,title='Source path recovery and additional assets',size=(850,640),style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL)
        text=wx.StaticText(dlg,label='Automatic resolution reads project variables, KiCad Configure Paths, environment variables and local/global library tables.\nUse these per-source JSON overrides only for missing/moved paths. Use forward slashes in Windows paths.\npath_variables: {"MY_MODELS":"D:/CAD/models"}\npath_remaps: {"C:/old/components":"D:/CAD/components"}\nextra_asset_paths: ["D:/CAD/auxiliary"] copies additional files/folders; unrelated project files are not swept blindly.')
        text.Wrap(800); box.Add(text,0,wx.EXPAND | wx.ALL,12)
        editor=wx.TextCtrl(dlg,value=json.dumps(data,indent=2),style=wx.TE_MULTILINE | wx.TE_DONTWRAP)
        box.Add(editor,1,wx.EXPAND | wx.LEFT | wx.RIGHT,12)
        box.Add(dlg.CreateButtonSizer(wx.OK | wx.CANCEL),0,wx.ALIGN_RIGHT | wx.ALL,12); dlg.SetSizer(box)
        while dlg.ShowModal()==wx.ID_OK:
            try:
                result=json.loads(editor.GetValue())
                if not isinstance(result,dict) or set(result)-set(data):
                    raise MergeError('Use only path_variables, path_remaps and extra_asset_paths.')
                for key in ('path_variables','path_remaps'):
                    if not isinstance(result.get(key,{}),dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in result.get(key,{}).items()):
                        raise MergeError(key+' must map strings to strings.')
                if not isinstance(result.get('extra_asset_paths',[]),list) or any(not isinstance(v,str) for v in result.get('extra_asset_paths',[])):
                    raise MergeError('extra_asset_paths must be a string array.')
                self.source_extras[row]={**self.source_extras[row],**result}
                self.detect_row(row)
                self.clear_results()
                break
            except Exception as exc:
                wx.MessageBox(str(exc),'Invalid source path settings',wx.OK | wx.ICON_ERROR,dlg)
        dlg.Destroy()

    def options(self):
        self.flush_grid()
        sources=[]
        try:
            for r in range(self.grid.GetNumberRows()):
                values=[self.grid.GetCellValue(r,c).strip() for c in range(5)]
                sources.append(SourceSpec(values[0],values[1],float(values[3]) if values[3] else None,float(values[4]) if values[4] else None,
                    variant=None if values[2]==CHOOSE_VARIANT else values[2],**self.source_extras[r]))
        except ValueError as exc:
            raise MergeError('X/Y values must be numeric millimetres, or both blank.') from exc
        name=self.name.GetValue().strip()
        return Options(sources=sources,destination=str(Path(self.parent_folder.GetPath())/name),name=name,
            annotation='sequential' if self.annotation.GetSelection()==0 else 'blocks',block_size=self.block.GetValue(),
            columns=self.columns.GetValue(),gap_mm=self.gap.GetValue(),margin_mm=self.margin.GetValue(),
            outline='rectangle' if self.outline.GetSelection()==0 else 'preserve',
            acknowledge_outline_change=self.cuts.GetValue(),accept_primary_settings=self.settings.GetValue(),
            saved_sources_confirmed=self.saved.GetValue(),cli_path=self.cli.GetPath(),
            acknowledge_layer_remap=self.layers.GetValue(),strict_assets=self.strict_assets.GetValue(),copy_assets=self.copy_libraries.GetValue())

    def load_config(self,event):
        with wx.FileDialog(self,'Load merge setup',wildcard='JSON files|*.json',style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal()!=wx.ID_OK: return
            path=dlg.GetPath()
        try:
            o=Options.from_json(path)
            if len(o.sources)>MAX_INSTANCES: raise MergeError(f'Maximum {MAX_INSTANCES} source instances.')
            if Path(o.destination).name!=o.name: raise MergeError('GUI setups require output folder basename to equal the output project name.')
            self.replace_sources(o.sources)
            self.strict_assets.SetValue(o.strict_assets)
            self.copy_libraries.SetValue(o.copy_assets)
            self.name.SetValue(o.name); self.parent_folder.SetPath(str(Path(o.destination).parent))
            self.annotation.SetSelection(0 if o.annotation=='sequential' else 1); self.block.SetValue(o.block_size)
            self.columns.SetValue(o.columns); self.gap.SetValue(o.gap_mm); self.margin.SetValue(o.margin_mm)
            self.outline.SetSelection(0 if o.outline=='rectangle' else 1); self.cli.SetPath(o.cli_path)
            workspace=json.loads(Path(path).read_text(encoding='utf-8-sig')).get('_workspace',{})
            self.import_current.SetValue(bool(workspace.get('import_into_existing',False)))
            self.copy_layout.SetValue(bool(workspace.get('include_layout',True)))
            self.target_project.SetPath(workspace.get('target_project',self.initial_target))
            self.mode_changed(None);self.target_closed.SetValue(False)
            # Safety acknowledgements are deliberately not restored.
            self.saved.SetValue(False); self.cuts.SetValue(False); self.settings.SetValue(False); self.layers.SetValue(False)
        except Exception as exc: wx.MessageBox(str(exc),'Cannot load setup',wx.OK | wx.ICON_ERROR,self)

    def save_config(self,event):
        try: o=self.options()
        except Exception as exc:
            wx.MessageBox(str(exc),'Invalid setup',wx.OK | wx.ICON_ERROR,self); return
        with wx.FileDialog(self,'Save merge setup',wildcard='JSON files|*.json',defaultFile='fusion-setup.json',style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal()!=wx.ID_OK: return
            try:
                data=o.to_dict();data['_workspace']={'import_into_existing':self.import_current.GetValue(),'include_layout':self.copy_layout.GetValue(),'target_project':self.target_project.GetPath()}
                Path(dlg.GetPath()).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
            except OSError as exc: wx.MessageBox(str(exc),'Cannot save',wx.OK | wx.ICON_ERROR,self)

    def append_log(self,message):
        self.log.AppendText(str(message)+'\n')

    def clear_results(self):
        self.preview.clear(); self.mapping.DeleteAllItems()
        self.sheet_preview.clear()
        self.issue_list.DeleteAllItems();self.merge_issues=[]
        self.placement_history=[]
        self.import_plan=None
        if hasattr(self,'offline_button'):self.offline_button.Disable()
        self.output_project=None; self.open_button.Disable()

    def replace_sources(self,specs,cached_variants=None):
        if len(specs)>MAX_INSTANCES: raise MergeError(f'Maximum {MAX_INSTANCES} source instances.')
        if cached_variants is not None and len(cached_variants)!=len(specs):
            raise MergeError('Cached variant choices do not match source instances.')
        if self.grid.GetNumberRows(): self.grid.DeleteRows(0,self.grid.GetNumberRows())
        self.source_extras=[]; self.row_variants=[]
        for index,s in enumerate(specs):
            self.append_source(s.project,s.alias,s.x_mm,s.y_mm,s.variant,
                               self.spec_extras(s),
                               variant_choices=cached_variants[index] if cached_variants is not None else None)
        self.clear_results()

    def add_section(self,event):
        if self.busy:return
        try:
            if self.grid.GetNumberRows()>=MAX_INSTANCES:raise MergeError(f'Maximum {MAX_INSTANCES} source instances. Remove a row before adding a section.')
            specs=self.options().sources
            selected=self.grid.GetSelectedRows()
            row=selected[0] if len(selected)==1 else self.grid.GetGridCursorRow()
            if not 0<=row<len(specs):raise MergeError('Add and select the source project first, then choose its variant.')
            from .section_gui import SectionDialog
            dialog=SectionDialog(self,specs[row],self.cli.GetPath())
            try:
                if dialog.ShowModal()==wx.ID_OK and dialog.result:
                    spec=dialog.result
                    self.append_source(spec.project,variant=spec.variant,extras=self.spec_extras(spec))
                    self.clear_results()
                    self.status.SetLabel('Extracted section added as a Default source copy. Remove the whole-project row if only its section is needed.')
            finally:dialog.Destroy()
        except Exception as exc:wx.MessageBox(str(exc),'Section extraction stopped',wx.OK | wx.ICON_ERROR,self)

    def open_insertion(self,event):
        if self.busy: return
        try:
            specs=self.options().sources
            selected=self.grid.GetSelectedRows()
            if selected: specs=[specs[i] for i in selected]
            from .insertion_gui import InsertionDialog
            dialog=InsertionDialog(self,target_path=self.initial_target,sources=specs,
                                   cli_path=self.cli.GetPath(),embedded=True)
            try:
                dialog.ShowModal()
                if dialog.applied:
                    self.status.SetLabel('Import applied to saved project with a backup. Reopen the target in KiCad and review ERC/DRC.')
            finally: dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc),'Cannot open project import',wx.OK | wx.ICON_ERROR,self)

    def open_linked_updates(self,event):
        if self.busy: return
        try:
            from .linked_gui import LinkedUpdatesDialog
            dialog=LinkedUpdatesDialog(self,target_path=self.initial_target,
                                       cli_path=self.cli.GetPath(),embedded=True)
            try: dialog.ShowModal()
            finally: dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc),'Cannot open linked updates',wx.OK | wx.ICON_ERROR,self)

    def repair_source(self,event):
        if self.busy:return
        try:
            specs=self.options().sources
            selected=self.grid.GetSelectedRows()
            row=selected[0] if len(selected)==1 else self.grid.GetGridCursorRow()
            if not 0<=row<len(specs):raise MergeError('Select one source row to repair.')
            from .management_gui import RepairDialog
            dialog=RepairDialog(self,specs[row],self.cli.GetPath())
            try:
                if dialog.ShowModal()==wx.ID_OK and dialog.result:
                    specs[row]=dialog.result
                    self.replace_sources(specs)
                    self.status.SetLabel('Source row now uses the repaired Default copy. Review it in KiCad and save before merging.')
            finally:dialog.Destroy()
        except Exception as exc:wx.MessageBox(str(exc),'Source repair stopped',wx.OK | wx.ICON_ERROR,self)

    def bom_fields(self,event):
        if self.busy:return
        try:
            specs=self.options().sources
            if not specs:raise MergeError('Add source projects first.')
        except Exception as exc:
            wx.MessageBox(str(exc),'Cannot read BOM/fields',wx.OK | wx.ICON_ERROR,self);return
        self.busy=True; self.enable_inputs(False); self.analyse_button.Disable(); self.merge_button.Disable(); self.close_button.Disable()
        self.status.SetLabel('Reading selected source variants for BOM and field review…')
        def worker():
            try:
                from .schematic import discover,new_uuid
                sources=[discover(spec,new_uuid()) for spec in specs]
                wx.CallAfter(self.show_bom_fields,sources,None)
            except Exception as exc:wx.CallAfter(self.show_bom_fields,None,str(exc))
        threading.Thread(target=worker,name='FusionBomRead',daemon=True).start()

    def show_bom_fields(self,sources,error):
        self.busy=False; self.enable_inputs(True); self.analyse_button.Enable(); self.merge_button.Enable(); self.close_button.Enable()
        if error:
            self.status.SetLabel(error); wx.MessageBox(error,'Cannot read BOM/fields',wx.OK | wx.ICON_ERROR,self);return
        from .management_gui import BomFieldsDialog
        dialog=BomFieldsDialog(self,sources)
        try:
            if dialog.ShowModal()==wx.ID_OK and dialog.result:
                self.replace_sources(dialog.result)
                self.status.SetLabel('Source rows now use field-edited Default copies. Rerun Analyse and review PCB metadata.')
            else:self.status.SetLabel('BOM/field review closed; original projects remain unchanged.')
        finally:dialog.Destroy()

    def dependencies(self,event):
        if self.busy:return
        try:
            specs=self.options().sources
            if not specs:raise MergeError('Add source projects first.')
            from .management_gui import DependencyDialog
            dialog=DependencyDialog(self,specs)
            try:
                if dialog.ShowModal()==wx.ID_OK and dialog.result:
                    self.replace_sources(dialog.result)
                    self.status.SetLabel('Source rows now use dependency copies. Audit again before merging.')
            finally:dialog.Destroy()
        except Exception as exc:wx.MessageBox(str(exc),'Dependency audit stopped',wx.OK | wx.ICON_ERROR,self)

    def start(self,do_merge):
        if self.busy: return
        if self.import_current.GetValue() or not self.copy_layout.GetValue():
            return self.start_workspace(do_merge)
        try: options=self.options(); options.validate()
        except Exception as exc:
            wx.MessageBox(str(exc),'Check merge settings',wx.OK | wx.ICON_WARNING,self); return
        if do_merge:
            message=f'Create a NEW project at:\n{options.destination}\n\nCircuits will remain isolated. Originals will not be edited. Review DRC, cutouts and rules before fabrication.\n\nContinue?'
            if wx.MessageBox(message,'Create combined project',wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,self)!=wx.YES: return
        self.busy=True; self.enable_inputs(False)
        self.analyse_button.Disable(); self.merge_button.Disable(); self.close_button.Disable(); self.open_button.Disable()
        self.log.Clear(); self.notebook.SetSelection(self.notebook.FindPage(self.review_page));self.review_inspector.SetSelection(1)
        self.status.SetLabel('Creating and validating staged output…' if do_merge else 'Reading saved projects…')
        self.timer.Start(120)
        def worker():
            try:
                from .workspace import materialize_sources
                originals=options.sources
                self.scan_worker_issues(originals)
                options.sources,selection_hashes=materialize_sources(originals,True,Path(options.destination).parent,options.cli_path)
                options._selection_originals=selection_hashes
                log=lambda msg:wx.CallAfter(self.append_log,msg)
                result=merge(options,log) if do_merge else analyse(options,log)
                wx.CallAfter(self.done,do_merge,result,None)
            except Exception as exc:
                wx.CallAfter(self.append_log,traceback.format_exc())
                wx.CallAfter(self.done,do_merge,None,str(exc))
        threading.Thread(target=worker,name='WayriFusion',daemon=True).start()

    def start_workspace(self,apply):
        try:
            options=self.options()
            incoming=options.sources
            target=self.target_project.GetPath()
            if self.import_current.GetValue():
                from .insertion_gui import project_identity
                incoming=[s for s in incoming if project_identity(s.project)!=project_identity(target)]
                if not target:raise MergeError('Choose the saved target project on Merge settings.')
            if not incoming and not (apply and self.import_plan):raise MergeError('Add an incoming design; the current target is automatically excluded from imports.')
            if not self.saved.GetValue():raise MergeError('Save the source files and confirm saved-source operation on Merge settings.')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',options.name):raise MergeError('Use a valid output name beginning with a letter.')
            plan=self.import_plan
            if apply:
                if plan is None:
                    self.status.SetLabel('Preparing a fresh Preview. Review it, then Apply.')
                    return self.start_workspace(False)
                if self.import_current.GetValue() and not self.target_closed.GetValue():raise MergeError('Save and close the target editors before offline Apply. Use Continue offline to keep this workspace open outside KiCad.')
                if self.import_current.GetValue() and self.GetParent() is not None:raise MergeError('Use Continue offline, close the target editors, then Apply in the same workspace.')
                if wx.MessageBox('Apply the reviewed selection? Existing targets are backed up and rechecked; new projects use a new folder.','Apply reviewed design',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self)!=wx.YES:return
        except Exception as exc:wx.MessageBox(str(exc),'Check workflow',wx.OK|wx.ICON_WARNING,self);return
        mode_import=self.import_current.GetValue();include_layout=self.copy_layout.GetValue()
        self.busy=True;self.enable_inputs(False);self.analyse_button.Disable();self.merge_button.Disable();self.close_button.Disable();self.offline_button.Disable()
        self.notebook.SetSelection(self.notebook.FindPage(self.review_page));self.review_inspector.SetSelection(1);self.timer.Start(120)
        self.status.SetLabel('Applying reviewed selection…' if apply else 'Preparing selected sheets and validating a review candidate…')
        def worker():
            try:
                from .workspace import materialize_sources,check_originals,preview_new_schematic,publish_new_schematic
                if apply:
                    check_originals(plan)
                    if mode_import:
                        from .insertion import apply_import
                        result=apply_import(plan)
                    else:result=publish_new_schematic(plan,options.destination,options.name)
                else:
                    self.scan_worker_issues(incoming,include_layout)
                    specs,originals=materialize_sources(incoming,include_layout,Path(options.destination).parent,options.cli_path)
                    from .insertion_gui import fresh_directory
                    candidate=fresh_directory(Path(options.destination).parent,options.name+'-Review')
                    if mode_import:
                        from .insertion import preview_import
                        result=preview_import(target,specs,include_layout,str(candidate),options.cli_path,options.gap_mm,copy_assets=options.copy_assets)
                    else:result=preview_new_schematic(specs,str(candidate),options.name,options.cli_path,options.gap_mm,copy_assets=options.copy_assets)
                    result['selection_originals']=originals
                    result['workspace_mode']='import' if mode_import else 'new'
                    result['output_destination']=options.destination;result['output_name']=options.name;result['cli_path']=options.cli_path
                    result['copy_assets']=options.copy_assets
                    result['visual_sources']=self.visual_source_records(specs,result)
                wx.CallAfter(self.workspace_done,apply,result,None)
            except Exception as exc:wx.CallAfter(self.workspace_done,apply,None,str(exc))
        threading.Thread(target=worker,name='FusionWorkspace',daemon=True).start()

    def workspace_done(self,applied,result,error):
        self.busy=False;self.timer.Stop();self.gauge.SetValue(0);self.enable_inputs(True)
        self.analyse_button.Enable();self.merge_button.Enable();self.close_button.Enable()
        if error:
            self.import_plan=None;self.status.SetLabel(error);self.append_log(error);self.show_validation_failure(error);return
        self.append_log(json.dumps(result.get('report',result),indent=2,default=str))
        if applied:
            self.import_plan=None
            self.output_project=Path(result.get('project',result.get('target_project')));self.open_button.Enable()
            self.status.SetLabel('Applied with verified backup.' if result.get('backup_directory') else 'Created the new schematic project; review ERC before use.')
        else:
            self.import_plan=result;self.offline_button.Enable(result['workspace_mode']=='import')
            self.output_project=Path(result['candidate_directory'])/Path(result['target_project']).name;self.open_button.Enable()
            self.show_candidate_preview(result)
            self.status.SetLabel('Review candidate ready. Inspect the report, then Create / Apply. Import targets must be saved and closed before offline Apply.')

    def show_candidate_preview(self,plan):
        self.preview.clear();self.mapping.DeleteAllItems()
        schematic=Path(plan['candidate_directory'])/Path(plan['target_project']).with_suffix('.kicad_sch').name
        if schematic.is_file():
            self.sheet_preview.show_schematic(schematic,{self.grid.GetCellValue(r,1) for r in range(self.grid.GetNumberRows())})
        for source in plan['report'].get('sources',[]):
            for old,new in source.get('reference_map',{}).items():
                row=self.mapping.InsertItem(self.mapping.GetItemCount(),source['alias'])
                self.mapping.SetItem(row,1,old);self.mapping.SetItem(row,2,new)
        board=Path(plan['candidate_directory'])/Path(plan['target_project']).with_suffix('.kicad_pcb').name
        if plan['report'].get('include_layout') and board.is_file():
            try:
                from types import SimpleNamespace
                from . import sexpr as sx
                from .board import board_bounds
                from .layers import copper_sequence
                from .assets import sha256
                records=plan.get('visual_sources',[])
                sources=[SimpleNamespace(**r) for r in records]
                target=Path(plan['target_project']).with_suffix('.kicad_pcb')
                if sources and target.is_file():
                    geometry=sx.load(target)
                    sources.insert(0,SimpleNamespace(alias='Existing target (locked)',pcb_file=target,
                        hashes={str(target):sha256(target)},bbox=board_bounds(geometry),translation=(0,0),
                        layer_map={},copper_layers=copper_sequence(geometry)))
                if not sources:
                    geometry=sx.load(board)
                    sources=[SimpleNamespace(alias='Review candidate (locked)',pcb_file=board,hashes={str(board.resolve()):sha256(board)},
                        bbox=board_bounds(geometry),translation=(0,0),layer_map={},copper_layers=copper_sequence(geometry))]
                self.preview.locked_aliases={s.alias for s in sources if s.alias.endswith('(locked)')}
                self.preview.show_sources(sources);self.fill_design_tree(sources)
            except Exception as exc:self.append_log('Candidate board preview unavailable: '+str(exc))
        self._preview_layers=list(self.preview.layers)
        self.preview_layer.SetItems(['All copper layers']+[self.preview.layers[key] for key in self._preview_layers]);self.preview_layer.SetSelection(0)

    def continue_offline(self,event):
        if self.busy or not self.import_plan:return
        from .insertion_gui import InsertionDialog
        import subprocess
        path=Path(self.import_plan['candidate_directory']).with_name(Path(self.import_plan['candidate_directory']).name+'-workspace-plan.json')
        path.write_text(json.dumps(self.import_plan,indent=2),encoding='utf-8')
        launcher=InsertionDialog.python_launcher()
        entry=Path(__file__).with_name('desktop_entrypoint.py')
        subprocess.Popen([str(launcher),str(entry),'--native-gui','--review-plan',str(path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.close(None)

    def load_workspace_plan(self,path):
        plan=json.loads(Path(path).read_text(encoding='utf-8'))
        self.import_current.SetValue(plan.get('workspace_mode')=='import');self.target_project.SetPath(plan['target_project'])
        self.copy_layout.SetValue(bool(plan['report'].get('include_layout',False)))
        self.copy_libraries.SetValue(plan.get('copy_assets',True))
        self.name.SetValue(plan.get('output_name','Combined'));self.parent_folder.SetPath(str(Path(plan.get('output_destination',plan['candidate_directory'])).parent))
        self.saved.SetValue(True);self.cli.SetPath(plan.get('cli_path',''))
        self.mode_changed(None);self.import_plan=plan
        self.merge_button.Enable();self.offline_button.Enable(False)
        self.notebook.SetSelection(self.notebook.FindPage(self.review_page));self.review_inspector.SetSelection(1)
        self.append_log(json.dumps(plan['report'],indent=2));self.status.SetLabel('Reviewed plan loaded. Close target editors, confirm on Merge settings, then Apply.')
        self.show_candidate_preview(plan)

    def done(self,do_merge,result,error):
        self.busy=False; self.timer.Stop(); self.gauge.SetValue(0)
        self.enable_inputs(True); self.analyse_button.Enable(); self.merge_button.Enable(); self.close_button.Enable()
        if error:
            self.status.SetLabel(error)
            self.append_log(error)
            self.show_validation_failure(error)
        elif do_merge:
            self.output_project=Path(result['project']); self.open_button.Enable()
            self.status.SetLabel(f'Created {self.output_project} — review reports before manufacturing.')
            self.append_log(json.dumps(result,indent=2,default=str))
            wx.MessageBox('The combined project was created.\n\nOpen the new .kicad_pro, inspect the schematic/PCB link, read READ-ME-FIRST.txt and review reports/drc.json. Do not fabricate without a design review.','Merge complete',wx.OK | wx.ICON_INFORMATION,self)
        else:
            _,sources,report=result
            self.preview.locked_aliases=set();self.preview.show_sources(sources);self.fill_design_tree(sources); self.mapping.DeleteAllItems()
            self._preview_layers=list(self.preview.layers)
            self.preview_layer.SetItems(['All copper layers']+[self.preview.layers[key] for key in self._preview_layers]);self.preview_layer.SetSelection(0)
            self.review_inspector.SetSelection(0)
            for s in sources:
                for old,new in s.ref_map.items():
                    row=self.mapping.InsertItem(self.mapping.GetItemCount(),s.alias)
                    self.mapping.SetItem(row,1,old); self.mapping.SetItem(row,2,new)
            self.append_log(json.dumps(report,indent=2,default=str))
            self.status.SetLabel('Structural preflight passed. Electrical verification runs only during Create combined project.')

    def open_output(self,event):
        if self.output_project: wx.LaunchDefaultApplication(str(self.output_project.parent))

    def help(self,event):
        dlg=wx.Dialog(self,title='Wayri Project Fusion — Help',size=(830,700),style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL); viewer=wx.html.HtmlWindow(dlg)
        path=Path(__file__).with_name('help.html')
        if path.is_file(): viewer.LoadPage(str(path))
        else: viewer.SetPage('<h1>Wayri Project Fusion</h1><p>Read README.md in the source package.</p>')
        box.Add(viewer,1,wx.EXPAND | wx.ALL,10); box.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALIGN_RIGHT | wx.ALL,10)
        dlg.SetSizer(box); dlg.ShowModal(); dlg.Destroy()

    def close(self,event):
        if self.busy:
            if isinstance(event,wx.CloseEvent) and event.CanVeto(): event.Veto()
            return
        if self.IsModal(): self.EndModal(wx.ID_CANCEL)
        else: self.Destroy()
