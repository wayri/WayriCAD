"""On-demand placement, typography and explicit component formatting controls."""
from copy import deepcopy
import math
import wx


PRESETS = [
    dict(name='Test points', ref_pattern='TP*', knockout=True),
    dict(name='Programming headers', value_pattern='*SWD*,*JTAG*,*ISP*,*ICSP*,*PROG*', bold=True),
    dict(name='Input connectors', value_pattern='*INPUT*,*POWER_IN*', italic=True),
]


class RuleDialog(wx.Dialog):
    def __init__(self, parent, rule=None):
        super().__init__(parent, title='Formatting rule')
        rule = rule or {}; self.controls = {}; root = wx.BoxSizer(wx.VERTICAL)
        for key, label in [('name','Rule name'), ('ref_pattern','References'), ('value_pattern','Component values'), ('text_pattern','Label text')]:
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
            control = wx.TextCtrl(self,value=rule.get(key,''),size=(330,-1)); self.controls[key]=control
            control.SetToolTip('Comma-separated wildcards, for example J1,J4 or TP*. Empty means any. Filled criteria must all match.')
            row.Add(control,1);root.Add(row,0,wx.EXPAND|wx.ALL,8)
        for key in ('bold','italic','knockout'):
            row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(self,label=key.title()),1,wx.ALIGN_CENTER_VERTICAL)
            control=wx.Choice(self,choices=['Keep existing','On','Off']);control.SetSelection(0 if key not in rule else 1 if rule[key] else 2)
            self.controls[key]=control;row.Add(control);root.Add(row,0,wx.EXPAND|wx.ALL,8)
        root.Add(wx.StaticText(self,label='First matching rule wins. Check connector patterns before applying.'),0,wx.ALL,8)
        root.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.EXPAND|wx.ALL,10);self.SetSizerAndFit(root)
    def result(self):
        rule={key:self.controls[key].GetValue().strip() for key in ('name','ref_pattern','value_pattern','text_pattern')}
        if not any(rule[key] for key in ('ref_pattern','value_pattern','text_pattern')):raise ValueError('Enter at least one matching pattern.')
        for key in ('bold','italic','knockout'):
            selection=self.controls[key].GetSelection()
            if selection:rule[key]=selection==1
        return rule


class OptionsDialog(wx.Dialog):
    def __init__(self,parent,settings):
        super().__init__(parent,title='Label options',size=(650,650))
        self.settings=deepcopy(settings);self.rules=deepcopy(settings['formatting_rules']);self.controls={}
        root=wx.BoxSizer(wx.VERTICAL);book=wx.Notebook(self);root.Add(book,1,wx.EXPAND|wx.ALL,10)
        def page(title):
            panel=wx.Panel(book);sizer=wx.BoxSizer(wx.VERTICAL);panel.SetSizer(sizer);book.AddPage(panel,title);return panel,sizer
        def check(panel,sizer,key,label):
            control=wx.CheckBox(panel,label=label);control.SetValue(bool(settings[key]));self.controls[key]=control;sizer.Add(control,0,wx.ALL,8)
        def number(panel,sizer,key,label):
            row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(panel,label=label),1,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(panel,value=str(settings[key]),size=(110,-1));self.controls[key]=control;row.Add(control);sizer.Add(row,0,wx.EXPAND|wx.ALL,8)
        panel,sizer=page('Placement')
        for key,label in [('values','Also place visible values'),('board_text','Also place existing board text'),('leaders','Guide lines for distant component labels')]:check(panel,sizer,key,label)
        for key,label in [('clearance','Spacing (mm)'),('max_radius','Search distance (mm)'),('leader_distance','Guide line beyond distance (mm)')]:number(panel,sizer,key,label)
        sizer.Add(wx.StaticText(panel,label='Hidden and locked items stay untouched. Unresolved labels retain their original placement.'),0,wx.ALL,8)
        panel,sizer=page('Size & direction')
        check(panel,sizer,'auto_size','Automatically shrink text when needed')
        for key,label in [('height','Preferred height / fixed minimum (mm)'),('min_height','Minimum automatic height (mm)'),('size_step','Automatic size step (mm)'),('thickness','Stroke at preferred size (mm)')]:number(panel,sizer,key,label)
        self.horizontal=wx.CheckBox(panel,label='Allow horizontal text');self.vertical=wx.CheckBox(panel,label='Allow vertical text')
        self.horizontal.SetValue(0 in settings['allowed_rotations']);self.vertical.SetValue(90 in settings['allowed_rotations'])
        sizer.Add(self.horizontal,0,wx.ALL,8);sizer.Add(self.vertical,0,wx.ALL,8)
        sizer.Add(wx.StaticText(panel,label='Read from'),0,wx.LEFT|wx.TOP,8)
        self.direction=wx.Choice(panel,choices=['Bottom/right (0° / 90°)','Top/left (180° / 270°)','Either direction'])
        self.direction.SetSelection(['Bottom/right','Top/left','Either'].index(settings['reading_direction']));sizer.Add(self.direction,0,wx.EXPAND|wx.ALL,8)
        note=wx.StaticText(panel,label='Automatic sizing tries up to 16 heights and scales the stroke with size. With it off, existing larger text and stroke are preserved. KiCad fabrication minimums always apply.');note.Wrap(570);sizer.Add(note,0,wx.ALL,8)
        def sizing(event=None):
            for key in ('min_height','size_step'):self.controls[key].Enable(self.controls['auto_size'].GetValue())
        self.controls['auto_size'].Bind(wx.EVT_CHECKBOX,sizing);sizing()
        panel,sizer=page('Formatting')
        note=wx.StaticText(panel,label='Rules are optional. Add a preset or your own patterns. First match wins; select a rule to edit it.');note.Wrap(570);sizer.Add(note,0,wx.ALL,8)
        self.list=wx.ListBox(panel);sizer.Add(self.list,1,wx.EXPAND|wx.ALL,8)
        self.preset=wx.Choice(panel,choices=[r['name'] for r in PRESETS]);self.preset.SetSelection(0);sizer.Add(self.preset,0,wx.EXPAND|wx.ALL,8)
        row=wx.BoxSizer(wx.HORIZONTAL)
        for label,callback in [('Add preset',self.add_preset),('Add',self.add),('Edit',self.edit),('Remove',self.remove),('Up',self.up)]:
            button=wx.Button(panel,label=label);button.Bind(wx.EVT_BUTTON,callback);row.Add(button,0,wx.RIGHT,4)
        sizer.Add(row,0,wx.ALL,8);self.refresh()
        root.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.EXPAND|wx.ALL,10);self.SetSizer(root)
    def refresh(self,selection=-1):
        self.list.Set([f"{r.get('name') or 'Rule'} — {r.get('ref_pattern') or r.get('value_pattern') or r.get('text_pattern')}" for r in self.rules])
        if 0<=selection<len(self.rules):self.list.SetSelection(selection)
    def edit_rule(self,rule=None):
        dialog=RuleDialog(self,rule)
        try:
            while dialog.ShowModal()==wx.ID_OK:
                try:return dialog.result()
                except ValueError as exc:wx.MessageBox(str(exc),'Formatting rule',wx.OK|wx.ICON_ERROR,parent=dialog)
        finally:dialog.Destroy()
    def add_preset(self,event):
        rule=self.edit_rule(PRESETS[self.preset.GetSelection()])
        if rule:self.rules.append(rule);self.refresh(len(self.rules)-1)
    def add(self,event):
        rule=self.edit_rule()
        if rule:self.rules.append(rule);self.refresh(len(self.rules)-1)
    def edit(self,event):
        i=self.list.GetSelection()
        if i<0:return
        rule=self.edit_rule(self.rules[i])
        if rule:self.rules[i]=rule;self.refresh(i)
    def remove(self,event):
        i=self.list.GetSelection()
        if i>=0:self.rules.pop(i);self.refresh(min(i,len(self.rules)-1))
    def up(self,event):
        i=self.list.GetSelection()
        if i>0:self.rules[i-1],self.rules[i]=self.rules[i],self.rules[i-1];self.refresh(i-1)
    def result(self):
        result=deepcopy(self.settings)
        for key,control in self.controls.items():
            value=control.GetValue() if isinstance(control,wx.CheckBox) else float(control.GetValue())
            if not isinstance(value,bool) and (not math.isfinite(value) or value<=0):raise ValueError(key+' must be positive and finite.')
            result[key]=value
        result['allowed_rotations']=tuple(x for x,control in [(0,self.horizontal),(90,self.vertical)] if control.GetValue())
        if not result['allowed_rotations']:raise ValueError('Allow at least one text orientation.')
        if result['auto_size'] and result['min_height']>result['height']:raise ValueError('Minimum height cannot exceed preferred height.')
        if result['auto_size'] and (result['height']-result['min_height'])/result['size_step']>15:raise ValueError('Choose a larger size step: at most 16 heights are supported.')
        result['reading_direction']=['Bottom/right','Top/left','Either'][self.direction.GetSelection()]
        result['formatting_rules']=deepcopy(self.rules)
        return result
