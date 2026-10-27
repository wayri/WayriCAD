"""Explicit per-load capacitor-bank editing over an existing saved inventory."""
import copy
import math

import wx
import wx.grid
from wx.lib.wordwrap import wordwrap

from wayricad_runtime.readable_choice import ReadableComboBox
from .shunt_caps import candidates, bank_from_rows, bank_rows,MAX_SHUNTS_PER_LOAD


class ShuntCapacitorDialog(wx.Dialog):
    """Return detached reviewed branches; cancelling preserves the caller's bank."""
    def __init__(self, parent, load, bank, terminals=(), signal_net='', return_nets=(), assigned=(),rise_time_s=0.):
        if len(bank)>MAX_SHUNTS_PER_LOAD:raise ValueError(f'At most {MAX_SHUNTS_PER_LOAD} capacitor branches per load.')
        super().__init__(parent, title='Quick PI · Shunt capacitors for '+str(load), size=(850,720),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize(self.FromDIP((620,520)));self.result=None;self.rise_time_s=0.
        self.terminals=terminals;self.signal_net=signal_net;self.assigned=set(assigned)
        self._ids={};self._candidates=[];self._wrapped=[]
        root=wx.BoxSizer(wx.VERTICAL);scroll=wx.ScrolledWindow(self,style=wx.VSCROLL);scroll.SetScrollRate(0,12)
        self.scroll=scroll;form=wx.BoxSizer(wx.VERTICAL)
        def note(text):
            item=wx.StaticText(scroll,label=text);self._wrapped.append((item,text));form.Add(item,0,wx.EXPAND|wx.ALL,8)
        note('Each capacitor is its own series ESR–ESL–C branch to the ideal return at this load node.\n'
             'The bank replaces this row’s aggregate C/ESR. Use effective C at operating bias and total part + connection ESL.\n'
             'This lumped model does not extract each capacitor’s routed position or return impedance.')
        rise=wx.BoxSizer(wx.HORIZONTAL);rise.Add(wx.StaticText(scroll,label='Load-current rise time · µs'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.rise=wx.TextCtrl(scroll,value=f'{rise_time_s/1e-6:.12g}');rise.Add(self.rise,1,wx.EXPAND)
        self.rise.SetToolTip('Linear prescribed load-current transition. Zero requests an ideal step; all-inductive current cutsets require a finite rise.')
        form.Add(rise,0,wx.EXPAND|wx.ALL,8)
        self.rows=wx.grid.Grid(scroll);self.rows.CreateGrid(0,4)
        for column,(label,width) in enumerate([('Capacitor',210),('C · µF or e.g. 100nF',190),('ESR · mΩ',125),('Total ESL · nH',135)]):
            self.rows.SetColLabelValue(column,label);self.rows.SetColSize(column,width)
        self.rows.SetColLabelSize(40);self.rows.SetMinSize((1,170));form.Add(self.rows,1,wx.EXPAND|wx.ALL,8)
        for branch in bank:self._append(branch)
        row=wx.WrapSizer(wx.HORIZONTAL)
        self.add=wx.Button(scroll,label='Add manual capacitor');self.remove=wx.Button(scroll,label='Remove selected');self.clear=wx.Button(scroll,label='Use aggregate C instead')
        self.fill=wx.Button(scroll,label='Set selected ESR / ESL…');self.fill.Bind(wx.EVT_BUTTON,self._fill)
        for button in (self.add,self.remove,self.fill,self.clear):row.Add(button,0,wx.RIGHT|wx.BOTTOM,6)
        self.add.Bind(wx.EVT_BUTTON,self._add);self.remove.Bind(wx.EVT_BUTTON,self._remove);self.clear.Bind(wx.EVT_BUTTON,self._clear)
        form.Add(row,0,wx.LEFT|wx.RIGHT,8)
        note('Optional board candidates: choose the actual return. Only two-pad C footprints on this net pair are listed.\n'
             'Nothing is added automatically. Saved C is a suggestion; review ESR, ESL and derating.\n'
             'The chosen return only filters candidates: use the same ideal reference as the source and loads.\n'
             'Dynamic cross-rail coupling is not modeled.')
        choices=sorted({p.get('net','') for p in terminals if p.get('net') and p.get('net')!=signal_net})
        self.returns=ReadableComboBox(scroll,choices=choices,style=wx.CB_READONLY)
        self.returns.SetMinSize((1,-1))
        selected=next((net for net in return_nets if net in choices),None)
        if selected:self.returns.SetStringSelection(selected)
        else:self.returns.SetSelection(wx.NOT_FOUND)
        self.returns.SetToolTip('Explicit return for candidate discovery; not a solved return-path model.')
        form.Add(wx.StaticText(scroll,label='Signal net: '+(signal_net or 'manual study')+' · Return net:'),0,wx.LEFT|wx.TOP,8)
        form.Add(self.returns,0,wx.EXPAND|wx.ALL,8);self.returns.Bind(wx.EVT_COMBOBOX,self._refresh_candidates)
        self.parts=wx.ListCtrl(scroll,style=wx.LC_REPORT)
        for column,(label,width) in enumerate([('Part',90),('Saved value',240),('Suggested C · µF',160)]):self.parts.InsertColumn(column,label,width=width)
        self.parts.SetMinSize((1,125));form.Add(self.parts,1,wx.EXPAND|wx.ALL,8)
        self.include=wx.Button(scroll,label='Add selected board capacitors');self.include.Bind(wx.EVT_BUTTON,self._include)
        form.Add(self.include,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.status=wx.StaticText(scroll,label='Enter explicit ESR and ESL, including zero when intentionally omitted.');form.Add(self.status,0,wx.EXPAND|wx.ALL,8)
        scroll.SetSizer(form);root.Add(scroll,1,wx.EXPAND)
        buttons=wx.BoxSizer(wx.HORIZONTAL);cancel=wx.Button(self,wx.ID_CANCEL);self.apply=wx.Button(self,label='Apply bank')
        for button in (cancel,self.apply):button.SetMinSize(self.FromDIP((120,-1)));buttons.Add(button,0,wx.ALL,8)
        self.apply.Bind(wx.EVT_BUTTON,self._apply);root.Add(buttons,0,wx.ALIGN_RIGHT);self.SetSizer(root)
        scroll.Bind(wx.EVT_SIZE,self._wrap);self._refresh_candidates();self._wrap()

    def _append(self,branch=None):
        if self.rows.GetNumberRows()>=MAX_SHUNTS_PER_LOAD:
            self.status.SetLabel(f'At most {MAX_SHUNTS_PER_LOAD} capacitor branches per load.');return
        index=self.rows.GetNumberRows();self.rows.AppendRows()
        values=bank_rows([branch])[0] if branch else ['Cap '+str(index+1),'','','']
        identifier=values[0]
        if '@' in identifier:
            self._ids[index]=identifier;values[0]=identifier.split('@',1)[0];self.rows.SetReadOnly(index,0)
        for column,value in enumerate(values):self.rows.SetCellValue(index,column,value)

    def _values(self):
        if self.rows.IsCellEditControlEnabled():self.rows.SaveEditControlValue();self.rows.DisableCellEditControl()
        rows=[[self.rows.GetCellValue(i,j) for j in range(4)] for i in range(self.rows.GetNumberRows())]
        for i,identifier in self._ids.items():rows[i][0]=identifier
        return bank_from_rows(rows)

    def _add(self,event=None):self._append()

    def _fill(self,event=None):
        if not self.rows.GetNumberRows():return
        selected=set(self.rows.GetSelectedRows())
        for start,end in zip(self.rows.GetSelectionBlockTopLeft(),self.rows.GetSelectionBlockBottomRight()):
            selected.update(range(start.GetRow(),end.GetRow()+1))
        if not selected:selected={max(0,self.rows.GetGridCursorRow())}
        dialog=wx.Dialog(self,title=f'Set parasitics for {len(selected)} selected capacitors',size=(460,240),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dialog.SetMinSize(self.FromDIP((420,240)));layout=wx.BoxSizer(wx.VERTICAL);form=wx.FlexGridSizer(0,2,8,10);form.AddGrowableCol(1)
        esr=wx.TextCtrl(dialog);esl=wx.TextCtrl(dialog)
        for label,control in [('ESR · mΩ',esr),('Total ESL · nH',esl)]:form.Add(wx.StaticText(dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        layout.Add(form,0,wx.EXPAND|wx.ALL,12);error=wx.StaticText(dialog,label='Explicit values only. Zero deliberately omits the effect. C values are retained.')
        error.Wrap(400);layout.Add(error,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        buttons=wx.BoxSizer(wx.HORIZONTAL);cancel=wx.Button(dialog,wx.ID_CANCEL);apply=wx.Button(dialog,label='Set selected rows')
        for button in (cancel,apply):buttons.Add(button,0,wx.ALL,8)
        layout.Add(buttons,0,wx.ALIGN_RIGHT);dialog.SetSizer(layout)
        def accept(_event):
            try:bank_from_rows([['validation','1',esr.GetValue(),esl.GetValue()]])
            except ValueError as caught:error.SetLabel(str(caught));error.Wrap(max(260,dialog.GetClientSize().width-24));dialog.Layout();return
            for index in selected:
                self.rows.SetCellValue(index,2,esr.GetValue());self.rows.SetCellValue(index,3,esl.GetValue())
            dialog.EndModal(wx.ID_OK)
        apply.Bind(wx.EVT_BUTTON,accept);dialog.parasitic_controls=dict(esr=esr,esl=esl,apply=apply,error=error)
        try:dialog.ShowModal()
        finally:dialog.Destroy()

    def _remove(self,event=None):
        if not self.rows.GetNumberRows():return
        row=max(0,self.rows.GetGridCursorRow());self.rows.DeleteRows(row)
        self._ids={i-(i>row):value for i,value in self._ids.items() if i!=row};self._refresh_candidates()

    def _clear(self,event=None):
        if self.rows.GetNumberRows():self.rows.DeleteRows(0,self.rows.GetNumberRows())
        self._ids={};self._refresh_candidates();self.status.SetLabel('Empty bank: the aggregate C/ESR row will be used and must be filled.')

    def _refresh_candidates(self,event=None):
        existing=set(self._ids.values())
        self._candidates=candidates(self.terminals,self.signal_net,self.returns.GetValue(),self.assigned|existing)
        self.parts.Freeze()
        try:
            self.parts.DeleteAllItems()
            for candidate in self._candidates:
                row=self.parts.InsertItem(self.parts.GetItemCount(),candidate['reference']);self.parts.SetItem(row,1,candidate['value'])
                self.parts.SetItem(row,2,'Unknown' if candidate['capacitance_F'] is None else f"{candidate['capacitance_F']/1e-6:.8g}")
        finally:self.parts.Thaw()

    def _include(self,event=None):
        index=self.parts.GetFirstSelected();selected=[]
        while index!=-1:selected.append(self._candidates[index]);index=self.parts.GetNextSelected(index)
        for candidate in selected:
            if self.rows.GetNumberRows()>=MAX_SHUNTS_PER_LOAD:break
            row=self.rows.GetNumberRows();self._append();self._ids[row]=candidate['id']
            self.rows.SetCellValue(row,0,candidate['reference']);self.rows.SetReadOnly(row,0)
            self.rows.SetCellValue(row,1,'' if candidate['capacitance_F'] is None else f"{candidate['capacitance_F']/1e-6:.12g}")
        self._refresh_candidates();self.status.SetLabel('Review effective C and enter ESR/total ESL for added parts. No values were written to the PCB.')

    def _apply(self,event=None):
        try:
            value=self._values()
            if any(row['id'] in self.assigned for row in value):raise ValueError('A capacitor is already assigned to another load. Remove the duplicate assignment.')
            rise=float(self.rise.GetValue())*1e-6 if value else 0.
            if not math.isfinite(rise) or rise<0:raise ValueError('Load-current rise must be finite and nonnegative.')
        except ValueError as error:
            self.status.SetLabel(str(error));self.status.Wrap(max(220,self.scroll.GetClientSize().width-20));self.scroll.FitInside();return
        self.result=copy.deepcopy(value);self.rise_time_s=rise;self.EndModal(wx.ID_OK)

    def _wrap(self,event=None):
        if getattr(self,'_wrapping',False):
            if event:event.Skip()
            return
        self._wrapping=True
        try:
            width=max(220,self.scroll.GetClientSize().width-25)
            for item,text in self._wrapped:
                item.SetMinSize((1,-1));item.SetLabel(wordwrap(text,width,wx.ClientDC(item)));item.InvalidateBestSize()
            self.scroll.Layout();self.scroll.FitInside()
        finally:self._wrapping=False
        if event:event.Skip()
