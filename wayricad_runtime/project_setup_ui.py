"""Native Save/Load setup actions with an explicit project-folder file chooser."""
from pathlib import Path

from .project_setup import make_setup, save_setup, load_setup, SourceChangedError


class ProjectSetupActions:
    def __init__(self, owner, parent, sizer, plugin, board_path, capture, restore,
                 *, validate=None, invalidate=None, status=None):
        import wx
        self.owner, self.plugin, self.board_path = owner, plugin, Path(board_path).resolve()
        self.capture, self.restore, self.validate = capture, restore, validate
        self.invalidate, self.status = invalidate, status or (lambda text: None)
        row = wx.WrapSizer(wx.HORIZONTAL)
        self.save = wx.Button(parent, label='Save setup…')
        self.load = wx.Button(parent, label='Load setup…')
        self.save.SetToolTip('Save editable simulation inputs to a chosen JSON file in the project folder')
        self.load.SetToolTip('Restore saved simulation inputs. Results are loaded separately.')
        for button, handler in ((self.save,self.on_save),(self.load,self.on_load)):
            button.Bind(wx.EVT_BUTTON,handler);row.Add(button,0,wx.RIGHT|wx.BOTTOM,5)
        sizer.Add(row,0,wx.EXPAND|wx.TOP,5)

    def _blocked(self):
        if any(getattr(self.owner,key,False) for key in ('_busy','_circuit_busy','_live_running')):
            self.status('Wait for the current analysis before changing or saving its setup.')
            return True
        return False

    def _choose(self, save):
        import wx
        with wx.FileDialog(self.owner,'Save simulation setup' if save else 'Load simulation setup',
                defaultDir=str(self.board_path.parent),defaultFile=getattr(self,'default_name',self.board_path.stem+'.'+self.plugin+'.setup.json') if save else '',
                wildcard='Simulation setup (*.json)|*.json',
                style=(wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) if save else (wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return None
            path=dialog.GetPath()
        if save and not Path(path).suffix:
            path += '.json'
            if Path(path).exists() and wx.MessageBox('Replace '+str(path)+'?', 'Replace setup file',
                    wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self.owner)!=wx.YES:
                return None
        return path

    def _error(self,error):
        import wx
        self.status(str(error));wx.MessageBox(str(error),'Simulation setup',wx.OK|wx.ICON_WARNING,self.owner)

    def on_save(self,event=None):
        if self._blocked():return
        path=self._choose(True)
        if not path:return
        try:
            state=self.capture()
            if self.validate is not None:state=self.validate(state)
            record=make_setup(self.plugin,self.board_path,state)
            protected=[self.board_path,self.board_path.with_suffix('.kicad_pro'),self.board_path.with_suffix('.kicad_sch')]
            from .project_results import _protected_inputs
            protected.extend(_protected_inputs(state,self.board_path.parent))
            for key in ('input_path','_input_path'):
                original=getattr(self.owner,key,None)
                if original:protected.append(original)
            result=save_setup(path,record,protected_sources=protected)
            self.status('Saved setup: '+result)
        except Exception as error:self._error(error)

    def on_load(self,event=None):
        import wx
        if self._blocked():return
        path=self._choose(False)
        if not path:return
        try:
            try:record=load_setup(path,self.plugin,self.board_path,validate_state=self.validate)
            except SourceChangedError as error:
                answer=wx.MessageBox(str(error)+'\n\nLoad and review these inputs against the current board? Existing results will be cleared.',
                    'Review changed PCB setup',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self.owner)
                if answer!=wx.YES:return
                record=load_setup(path,self.plugin,self.board_path,validate_state=self.validate,allow_changed_source=True)
            previous=self.capture()
            self.owner.Freeze()
            try:
                try:self.restore(record['state'])
                except Exception:
                    self.restore(previous)
                    raise
                if self.invalidate is not None:self.invalidate()
            finally:self.owner.Thaw()
            self.status('Loaded setup: '+str(path)+(' · Review inputs for the changed PCB before running.' if record['source_changed'] else ' · Run to compute new results.'))
        except Exception as error:self._error(error)


def add_project_setup(owner,parent,sizer,plugin,board_path,capture,restore,**kwargs):
    return ProjectSetupActions(owner,parent,sizer,plugin,board_path,capture,restore,**kwargs)
