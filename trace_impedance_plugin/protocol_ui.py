"""Cancellable isolated protocol scan and exact-evidence review window."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def scan_saved(board,request,cancelled,timeout=300):
    from .bulk_ui import source_fingerprints,verify_sources
    from wayricad_runtime.analysis_process import worker_options,stop_worker
    from wayricad_runtime.runtime_setup import child_environment
    fingerprints=source_fingerprints(board)
    with tempfile.TemporaryDirectory(prefix='wayricad-protocol-scan-') as folder:
        folder=Path(folder);source=folder/'request.json';response=folder/'result.json'
        for name in ('rules','targets'):
            if name in request:
                file=folder/(name+'.json');file.write_text(json.dumps(request[name]),encoding='utf-8')
                request={**request,name:str(file)}
        source.write_text(json.dumps(dict(request,board=str(board))),encoding='utf-8')
        with (folder/'worker.log').open('w+b') as log:
            process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('protocol_worker.py')),str(source),str(response)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=child_environment(),**worker_options())
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if cancelled():raise InterruptedError('Protocol scan cancelled; PCB unchanged.')
                    if time.monotonic()-started>timeout:raise TimeoutError('Protocol scan timed out; reduce net/section budgets.')
                    time.sleep(.1)
            finally:
                if process.poll() is None:stop_worker(process)
            log.seek(0,2);end=log.tell();log.seek(max(0,end-8000));details=log.read().decode('utf-8',errors='replace')[-4000:]
            if process.returncode or not response.is_file():
                raise RuntimeError(f'Protocol worker failed (exit {process.returncode}); KiCad remains open. '+details)
            if response.stat().st_size>64*1024**2:raise ValueError('Protocol report exceeds the 64 MiB review budget.')
            result=json.loads(response.read_text(encoding='utf-8'))
    verify_sources(fingerprints)
    result['source_files']=fingerprints
    return result


def report_html(document):
    from html import escape
    rows=[]
    for finding in document['result']['findings']:
        issues=''.join('<li><b>'+escape(issue['code'])+'</b>: '+escape(issue['message'])+'<br>'+escape(issue['suggestion'])+'</li>' for issue in finding['issues'])
        checks='<details><summary>Section checks, targets and estimates (ohm)</summary><pre>'+escape(json.dumps(finding.get('checks',[]),indent=2))+'</pre></details>'
        rows.append('<tr><td>'+escape(finding['net'])+'</td><td>'+escape(finding['profile_id'])+'</td><td>'+escape(finding['status'])+'</td><td><ul>'+issues+'</ul>'+checks+'</td></tr>')
    metadata='<p>Generated UTC: '+escape(document.get('generated_utc','Not recorded'))+'; schema: '+escape(document['result'].get('schema','Not recorded'))+'</p>'
    return '<!doctype html><meta charset="utf-8"><title>RLC protocol screen</title><style>body{font:15px system-ui;max-width:1400px;margin:24px auto;padding:12px}td,th{border-bottom:1px solid #ccd4da;padding:10px;text-align:left;vertical-align:top}table{border-collapse:collapse;width:100%}</style><h1>RLC protocol discovery and screening</h1><p>Read-only screening, not protocol compliance. Fuzzy matches require review. Differential coupling and device-specific timing remain unresolved where unsupported.</p>'+metadata+'<p>Source SHA-256: '+escape(document['board_sha256'])+'</p><table><thead><tr><th>Net</th><th>Candidate</th><th>Result</th><th>Evidence and corrective suggestions</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'


def export_report(path,document):
    from .bulk_ui import verify_sources
    from wayricad_runtime.report_ui import publish_documents,report_paths
    from wayricad_runtime.report_context import organize_report
    fingerprints=document['source_files']
    verify_sources(fingerprints)
    output,evidence=report_paths(path)
    documents={output:organize_report(report_html(document),document),
               evidence:json.dumps(document,ensure_ascii=False,allow_nan=False)+'\n'}
    publish_documents(documents,sources=list(fingerprints),source_guard=lambda:verify_sources(fingerprints))
    return {'html':str(output),'json':str(evidence)}


def create_protocol_frame(parent):
    import wx
    from .bulk_ui import BulkController,source_fingerprints,verify_sources
    class ProtocolFrame(wx.Frame):
        def __init__(self):
            super().__init__(parent,title='RLC Protocol Discovery',size=(1120,760))
            self.SetMinSize((800,540))
            self.controller=BulkController();self.document=None;self.rows=[];self.sort_reverse=False
            self.source=Path(parent.board.GetFileName()).resolve();source_fingerprints(self.source)
            panel=wx.Panel(self);layout=wx.BoxSizer(wx.VERTICAL);bar=wx.WrapSizer(wx.HORIZONTAL)
            self.run=wx.Button(panel,label='Discover and check');self.run.Bind(wx.EVT_BUTTON,self.on_run);bar.Add(self.run,0,wx.ALL,5)
            self.cancel=wx.Button(panel,label='Cancel');self.cancel.Bind(wx.EVT_BUTTON,lambda e:self.controller.cancel());bar.Add(self.cancel,0,wx.ALL,5)
            bar.Add(wx.StaticText(panel,label='Analysis MHz'),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,5)
            self.frequency=wx.TextCtrl(panel,value='100',size=(85,-1));bar.Add(self.frequency,0,wx.ALL,5)
            bar.Add(wx.StaticText(panel,label='Target tolerance %'),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,5)
            self.tolerance=wx.SpinCtrlDouble(panel,min=.1,max=99,initial=10,inc=.5,size=(90,-1));bar.Add(self.tolerance,0,wx.ALL,5)
            self.export=wx.Button(panel,label='Export report');self.export.Bind(wx.EVT_BUTTON,self.on_export);bar.Add(self.export,0,wx.ALL,5)
            help_button=wx.Button(panel,wx.ID_HELP);help_button.Bind(wx.EVT_BUTTON,lambda e:parent.on_help(None) if hasattr(parent,'on_help') else wx.LaunchDefaultBrowser(Path(__file__).with_name('help.html').as_uri()));bar.Add(help_button,0,wx.ALL,5)
            layout.Add(bar,0,wx.EXPAND)
            settings=wx.CollapsiblePane(panel,label='Custom matching rules and impedance targets',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
            inner=wx.BoxSizer(wx.VERTICAL)
            self.rules=wx.TextCtrl(settings.GetPane(),value='[]',style=wx.TE_MULTILINE,size=(-1,65))
            self.rules.SetToolTip('JSON rules: [{"kind":"wildcard","pattern":"*CUSTOM_RF*","profile_id":"rf"}]. Regex rules use kind regex.')
            self.targets=wx.TextCtrl(settings.GetPane(),value='{}',style=wx.TE_MULTILINE,size=(-1,45));self.targets.SetToolTip('JSON exact net or profile ID to positive target ohms. No board edits.')
            inner.Add(wx.StaticText(settings.GetPane(),label='Rules JSON'),0,wx.ALL,4);inner.Add(self.rules,0,wx.EXPAND|wx.ALL,4)
            inner.Add(wx.StaticText(settings.GetPane(),label='Target overrides JSON'),0,wx.ALL,4);inner.Add(self.targets,0,wx.EXPAND|wx.ALL,4)
            settings.GetPane().SetSizer(inner);settings.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:panel.Layout());layout.Add(settings,0,wx.EXPAND|wx.ALL,5)
            self.status=wx.StaticText(panel,label='Saved-board scan. Protocol identity and nominal targets are screening assumptions, not compliance.');layout.Add(self.status,0,wx.EXPAND|wx.ALL,6)
            self.table=wx.ListCtrl(panel,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
            for i,(name,width) in enumerate([('Net',300),('Protocol',130),('Confidence',95),('Mate',230),('Status',165)]):self.table.InsertColumn(i,name,width=width)
            self.table.Bind(wx.EVT_LIST_ITEM_SELECTED,self.on_select);self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED,self.on_activate)
            self.table.Bind(wx.EVT_LIST_COL_CLICK,self.on_sort);layout.Add(self.table,1,wx.EXPAND|wx.ALL,5)
            self.details=wx.TextCtrl(panel,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,170));layout.Add(self.details,0,wx.EXPAND|wx.ALL,5)
            panel.SetSizer(layout);self.Bind(wx.EVT_CLOSE,self.on_close)
            for ctrl,event in ((self.frequency,wx.EVT_TEXT),(self.tolerance,wx.EVT_SPINCTRLDOUBLE),(self.rules,wx.EVT_TEXT),(self.targets,wx.EVT_TEXT)):
                ctrl.Bind(event,self.invalidate)
            self.buttons()
        def buttons(self):
            self.run.Enable(not self.controller.busy);self.cancel.Enable(self.controller.busy)
            self.export.Enable(bool(self.document) and not self.controller.busy)
            for ctrl in (self.frequency,self.tolerance,self.rules,self.targets):ctrl.Enable(not self.controller.busy)
        def invalidate(self,event=None):
            self.document=None;self.rows=[];self.table.DeleteAllItems();self.details.Clear();self.buttons()
        def on_run(self,event):
            try:
                request=dict(rules=json.loads(self.rules.GetValue()),targets=json.loads(self.targets.GetValue()),
                             frequency_mhz=float(self.frequency.GetValue()),tolerance_pct=self.tolerance.GetValue())
                self.invalidate();self.controller.start(lambda cancel,progress:scan_saved(self.source,request,cancel),self.finished,wx.CallAfter)
                self.status.SetLabel('Discovering nets and checking saved copper in an isolated worker...');self.buttons()
            except Exception as exc:self.status.SetLabel(str(exc))
        def finished(self,document,error):
            if error:self.status.SetLabel(error);self.buttons();return
            self.document=document;self.rows=list(document['result']['findings']);self.populate()
            self.status.SetLabel(f"{len(self.rows)} candidates; {sum(r['status']=='outside_target' for r in self.rows)} outside target; {sum(r['status'] in ('needs_review','unresolved') for r in self.rows)} need review. No protocol compliance pass is implied.");self.buttons()
        def populate(self):
            self.table.DeleteAllItems()
            for row in self.rows:
                i=self.table.InsertItem(self.table.GetItemCount(),row['net'])
                for col,value in enumerate((row['profile_id'],f"{row['confidence']:.0%}",row.get('mate') or 'Unknown',row['status']),1):self.table.SetItem(i,col,str(value))
        def on_sort(self,event):
            key=('net','profile_id','confidence','mate','status')[event.GetColumn()]
            self.sort_reverse=not self.sort_reverse;self.rows.sort(key=lambda r:r.get(key) or '',reverse=self.sort_reverse);self.populate()
        def on_select(self,event):
            row=self.rows[event.GetIndex()];self.details.SetValue(json.dumps(row,indent=2,ensure_ascii=False))
        def on_activate(self,event):
            row=self.rows[event.GetIndex()]
            try:verify_sources(self.document['source_files'])
            except ValueError as exc:self.invalidate();self.status.SetLabel(str(exc));return
            parent.net.SetValue(row['net']);parent._load_pads(None)
            if not parent.saved_board:parent.highlight_net(None)
            parent.Raise()
        def on_export(self,event):
            try:
                verify_sources(self.document['source_files'])
                with wx.FileDialog(self,'Export protocol screen',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
                    if dialog.ShowModal()!=wx.ID_OK:return
                    target=Path(dialog.GetPath()).resolve().with_suffix('.html')
                export_report(target,self.document)
            except Exception as exc:self.status.SetLabel(str(exc))
        def on_close(self,event):self.controller.close();self.Destroy()
    return ProtocolFrame()
