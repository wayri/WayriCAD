"""Reviewed multi-net series setups, separate from solved simulation results."""
from copy import deepcopy
import math

SCHEMA='wayricad.pi-series-batch-setup/v1'


def require_current_board(editor):
    """Never bind stale inventory assignments to a newly saved board."""
    import hashlib
    from pathlib import Path
    expected=editor.inventory.get('source_sha256')
    if not expected or hashlib.sha256(Path(editor.board_path).read_bytes()).hexdigest()!=expected:
        raise ValueError('The saved board changed. Refresh Quick PI and reopen the series editor before saving or loading batch setups.')


def make_case(path, inventory, name, voltage, current):
    from .series_editor import parse_saved_path
    from .batch import initial_study, validate_study
    parsed=parse_saved_path(path,inventory)
    if not parsed.get('series'):raise ValueError('Choose a complete series path for this batch case.')
    values=[]
    for text,label in ((voltage,'Source voltage'),(current,'Load current')):
        try:value=float(text)
        except (ValueError,TypeError):raise ValueError(label+' must be a positive finite number.') from None
        if not math.isfinite(value) or value<=0:raise ValueError(label+' must be a positive finite number.')
        values.append(value)
    study=initial_study(dict(parsed,source_voltage=values[0],sink_current=values[1]))
    study['cases'][0]['name']=name.strip()
    validate_study(study)
    return deepcopy(study['cases'][0])


def validate_state(state, inventory):
    from .batch import SCHEMA as BATCH, validate_study, MAX_CASES
    from .series_editor import draft_from_request, parse_saved_path
    if (not isinstance(state,dict) or set(state)!={'schema','cases','draft'} or state.get('schema')!=SCHEMA or
            not isinstance(state['cases'],list) or len(state['cases'])>MAX_CASES):
        raise ValueError('Invalid series batch setup.')
    draft=state['draft']
    if (not isinstance(draft,dict) or set(draft)!={'name','voltage','current'} or
            any(not isinstance(value,str) or len(value)>200 for value in draft.values())):
        raise ValueError('Invalid batch case input fields.')
    if state['cases']:
        validate_study(dict(schema=BATCH,cases=state['cases']))
        for case in state['cases']:
            electrical=case['electrical']
            if not electrical.get('series'):raise ValueError('Series batch setup contains a non-series case.')
            parse_saved_path(draft_from_request(electrical,inventory)['path'],inventory)
    return deepcopy(state)


class SeriesBatchSetup:
    """Embedded named setup list; execution uses the existing batch workspace."""
    def __init__(self,parent,editor,voltage='1',current='1'):
        import wx
        self.wx=wx;self.editor=editor;self.cases=[];self.selected=-1
        self.panel=wx.Panel(parent)
        root=wx.StaticBoxSizer(wx.VERTICAL,self.panel,'Batch series setups')
        fields=wx.FlexGridSizer(2,3,5,8)
        self.name=wx.TextCtrl(self.panel,value='Series case 1')
        self.voltage=wx.TextCtrl(self.panel,value=str(voltage));self.current=wx.TextCtrl(self.panel,value=str(current))
        for title in ('Case name','Source · V','Load · A'):fields.Add(wx.StaticText(self.panel,label=title),0)
        for control in (self.name,self.voltage,self.current):fields.Add(control,1,wx.EXPAND)
        for col in range(3):fields.AddGrowableCol(col)
        root.Add(fields,0,wx.EXPAND|wx.ALL,6)
        self.list=wx.ListCtrl(self.panel,style=wx.LC_REPORT|wx.LC_SINGLE_SEL,size=(-1,120))
        for i,(title,width) in enumerate((('Case',180),('Series path',390),('V',80),('A',80))):self.list.InsertColumn(i,title,width=width)
        root.Add(self.list,0,wx.EXPAND|wx.ALL,6)
        self.notice=wx.StaticText(self.panel,label='Add reviewed paths with explicit models. Each case keeps its own pins, parallel banks, voltage and current.')
        root.Add(self.notice,0,wx.EXPAND|wx.ALL,6)
        buttons=wx.WrapSizer(wx.HORIZONTAL)
        for title,handler in (('Add current path',self.add),('Update selected',self.update),
                ('Edit selected',self.edit),('Remove selected',self.remove),
                ('Save batch setup…',self.save),('Load batch setup…',self.load),('Run batch…',self.run)):
            button=wx.Button(self.panel,label=title);button.Bind(wx.EVT_BUTTON,handler);buttons.Add(button,0,wx.RIGHT|wx.BOTTOM,5)
        root.Add(buttons,0,wx.EXPAND|wx.ALL,6);self.panel.SetSizer(root)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select)

    def snapshot(self):
        return dict(schema=SCHEMA,cases=deepcopy(self.cases),draft=dict(
            name=self.name.GetValue(),voltage=self.voltage.GetValue(),current=self.current.GetValue()))

    def restore(self,state):
        state=validate_state(state,self.editor.inventory)
        self.cases=state['cases'];self.selected=-1
        for key in ('name','voltage','current'):getattr(self,key).ChangeValue(state['draft'][key])
        self.refresh()

    def refresh(self):
        self.list.DeleteAllItems()
        self.selected=-1
        from .series_editor import draft_from_request, display_path_command
        for case in self.cases:
            values=case['electrical'];path=draft_from_request(values,self.editor.inventory)['path']
            row=self.list.InsertItem(self.list.GetItemCount(),case['name'])
            for col,value in enumerate((display_path_command(path,self.editor.inventory),values['source_voltage'],values['sink_current']),1):
                self.list.SetItem(row,col,str(value))
        self.notice.SetLabel(str(len(self.cases))+' / 32 independent series setups. Review all models before running.')
        self.editor.body.Layout();self.editor.body.FitInside()

    def select(self,event):self.selected=event.GetIndex()

    def _case(self):
        return make_case(self.editor._reviewed_editor_path(),self.editor.inventory,
                         self.name.GetValue(),self.voltage.GetValue(),self.current.GetValue())

    def add(self,event=None):
        try:
            if len(self.cases)>=32:raise ValueError('A batch supports at most 32 cases.')
            case=self._case()
            if any(row['name']==case['name'] for row in self.cases):raise ValueError('Use a unique case name, or Update selected.')
            self.cases.append(case);self.selected=len(self.cases)-1;self.refresh()
            self.name.ChangeValue('Series case '+str(len(self.cases)+1))
        except ValueError as exc:self.notice.SetLabel(str(exc))

    def update(self,event=None):
        try:
            if not 0<=self.selected<len(self.cases):raise ValueError('Select a batch case to update.')
            case=self._case()
            if any(i!=self.selected and row['name']==case['name'] for i,row in enumerate(self.cases)):
                raise ValueError('Use a unique case name.')
            self.cases[self.selected]=case;self.refresh()
        except ValueError as exc:self.notice.SetLabel(str(exc))

    def edit(self,event=None):
        if not 0<=self.selected<len(self.cases):self.notice.SetLabel('Select a case to edit.');return
        from .series_editor import draft_from_request
        case=self.cases[self.selected];values=case['electrical']
        self.name.ChangeValue(case['name']);self.voltage.ChangeValue(str(values['source_voltage']));self.current.ChangeValue(str(values['sink_current']))
        path=draft_from_request(values,self.editor.inventory)['path']
        self.editor.inference.invalidate();self.editor._restore_path(path)
        self.editor.inference.infer(path['source'],path['sink'],
            include_unknown=self.editor.infer_unknown.GetValue(),existing=path)

    def remove(self,event=None):
        if 0<=self.selected<len(self.cases):self.cases.pop(self.selected);self.selected=-1;self.refresh()

    def save(self,event=None):
        from pathlib import Path
        from wayricad_runtime.project_setup import make_setup,save_setup
        wx=self.wx
        try:
            state=validate_state(self.snapshot(),self.editor.inventory)
            with wx.FileDialog(self.editor.dialog,'Save series batch setup',defaultDir=str(Path(self.editor.board_path).parent),
                    defaultFile='series-batch.setup.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                require_current_board(self.editor)
                save_setup(dialog.GetPath(),make_setup('quick-pi',self.editor.board_path,{'series_batch':state}),
                           protected_sources=(self.editor.board_path,))
            self.notice.SetLabel('Saved batch setup, including every series path and pin group.')
        except (OSError,ValueError) as exc:self.notice.SetLabel(str(exc))

    def load(self,event=None):
        from pathlib import Path
        from wayricad_runtime.project_setup import load_setup
        wx=self.wx
        try:
            def validate(value):
                if not isinstance(value,dict) or set(value)!={'series_batch'}:raise ValueError('Choose a series batch setup file.')
                return {'series_batch':validate_state(value['series_batch'],self.editor.inventory)}
            with wx.FileDialog(self.editor.dialog,'Load series batch setup',defaultDir=str(Path(self.editor.board_path).parent),
                    wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                require_current_board(self.editor)
                record=load_setup(dialog.GetPath(),'quick-pi',self.editor.board_path,validate_state=validate)
            require_current_board(self.editor)
            self.restore(record['state']['series_batch'])
        except (OSError,ValueError) as exc:self.notice.SetLabel(str(exc))

    def run(self,event=None):
        from .batch import SCHEMA as BATCH,validate_study
        try:
            state=validate_state(self.snapshot(),self.editor.inventory)
            study=validate_study(dict(schema=BATCH,cases=state['cases']))
            self.editor.request={'batch_study':study}
            self.editor.dialog.EndModal(self.wx.ID_OK)
        except ValueError as exc:self.notice.SetLabel(str(exc))
