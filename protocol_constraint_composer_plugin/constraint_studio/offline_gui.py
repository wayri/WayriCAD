"""Small native apply utility that runs AFTER the source project is closed.
Uses wx if available (KiCad Python), otherwise Tk (standard Windows Python).
"""
import json, pathlib, sys
from .workspace import apply_bundle
from .apply_worker import ApplyWorker

def summary(folder):
    data=json.loads((pathlib.Path(folder)/'constraint-studio-manifest.json').read_text('utf-8'))
    changed=[n for n,e in data['files'].items() if e['changed']]
    return 'SOURCE PROJECT\n'+data['source_board']+'\n\nFILES TO REPLACE\n'+('\n'.join(changed) or 'None')+'\n\nNative DRC results must be reviewed separately. A successful export is NOT validation.\nFingerprints, local lint and backups are checked before applying.\nDo not use this with any source-project KiCad editor open.'

def main(folder=''):
    try:import wx
    except ImportError:return main_tk(folder)
    app=wx.App(False)
    if not folder:
        with wx.DirDialog(None,'Choose a Constraint Studio review folder') as d:
            if d.ShowModal()!=wx.ID_OK:return
            folder=d.GetPath()
    frame=wx.Frame(None,title='Constraint Studio — offline review apply',size=(800,610));panel=wx.Panel(frame);s=wx.BoxSizer(wx.VERTICAL);panel.SetSizer(s)
    try:details=summary(folder)
    except Exception as e:wx.MessageBox(str(e),'Invalid review bundle',wx.OK|wx.ICON_ERROR);return
    text=wx.TextCtrl(panel,value=details,style=wx.TE_MULTILINE|wx.TE_READONLY);s.Add(text,1,wx.EXPAND|wx.ALL,16)
    closed=wx.CheckBox(panel,label='All KiCad editors for the SOURCE project are closed.');reviewed=wx.CheckBox(panel,label='I reviewed the changes, scope, fabrication limits and native DRC results.')
    s.Add(closed,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16);s.Add(reviewed,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
    status=wx.StaticText(panel,label='Ready for review.');s.Add(status,0,wx.LEFT|wx.RIGHT,16)
    b=wx.Button(panel,label='Apply reviewed changes with backups');s.Add(b,0,wx.ALL|wx.ALIGN_RIGHT,16)
    worker=ApplyWorker(lambda:apply_bundle(folder,True))
    def poll():
        result=worker.poll()
        if result is None:
            wx.CallLater(100,poll);return
        if result.error is not None:
            status.SetLabel('Apply failed. Review the error before retrying.');b.Enable();closed.Enable();reviewed.Enable()
            wx.MessageBox('NOT APPLIED: '+str(result.error),'Constraint Studio',wx.OK|wx.ICON_ERROR,frame)
        else:
            status.SetLabel('Apply finished.')
            wx.MessageBox('Applied. Backups: '+str(result.backup) if result.backup else 'No changes to apply.','Constraint Studio',wx.OK|wx.ICON_INFORMATION,frame)
    def close(event):
        if worker.busy:
            status.SetLabel('Applying changes; wait for completion before closing.');event.Veto();return
        event.Skip()
    frame.Bind(wx.EVT_CLOSE,close)
    def apply(event):
        if worker.busy:return
        if not closed.GetValue() or not reviewed.GetValue():wx.MessageBox('Confirm both review statements first.','Not applied',wx.OK|wx.ICON_WARNING);return
        if wx.MessageBox('Replace the listed source files with this reviewed bundle?','Confirm source project update',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING)!=wx.YES:return
        try:
            if not worker.start():return
            b.Disable();closed.Disable();reviewed.Disable()
            status.SetLabel('Applying reviewed changes and writing backups. Please wait; do not close the helper.')
            wx.CallLater(100,poll)
        except Exception as e:wx.MessageBox('NOT APPLIED: '+str(e),'Constraint Studio',wx.OK|wx.ICON_ERROR)
    b.Bind(wx.EVT_BUTTON,apply);frame.Center();frame.Show();app.MainLoop()

def main_tk(folder):
    try:import tkinter as tk;from tkinter import ttk,filedialog,messagebox
    except ImportError:
        raise SystemExit('A Python installation with wxPython or Tk is required. Alternatively use apply_review.py with --project-closed from the source release.')
    root=tk.Tk();root.title('Constraint Studio — offline review apply');root.geometry('850x630')
    if not folder:folder=filedialog.askdirectory(title='Select review bundle',parent=root)
    if not folder:root.destroy();return
    try:details=summary(folder)
    except Exception as e:messagebox.showerror('Invalid review bundle',str(e),parent=root);root.destroy();return
    f=ttk.Frame(root,padding=18);f.pack(fill='both',expand=True)
    text=tk.Text(f,wrap='word',height=17);text.insert('1.0',details);text.configure(state='disabled');text.pack(fill='both',expand=True,pady=(0,18))
    closed=tk.BooleanVar();reviewed=tk.BooleanVar()
    ttk.Checkbutton(f,text='All KiCad editors for the SOURCE project are closed.',variable=closed).pack(anchor='w',pady=7)
    ttk.Checkbutton(f,text='I reviewed the changes, scope, fabrication limits and native DRC results.',variable=reviewed).pack(anchor='w',pady=7)
    status=tk.StringVar(value='Ready for review.');ttk.Label(f,textvariable=status).pack(anchor='w',pady=7)
    worker=ApplyWorker(lambda:apply_bundle(folder,True))
    def poll():
        result=worker.poll()
        if result is None:
            root.after(100,poll);return
        if result.error is not None:
            status.set('Apply failed. Review the error before retrying.');b.configure(state='normal')
            messagebox.showerror('Not applied',str(result.error),parent=root)
        else:
            status.set('Apply finished.')
            messagebox.showinfo('Applied','Backup folder: '+str(result.backup) if result.backup else 'No changes to apply.',parent=root)
    def close():
        if worker.busy:
            status.set('Applying changes; wait for completion before closing.');return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    def apply():
        if worker.busy:return
        if not closed.get() or not reviewed.get():messagebox.showwarning('Not applied','Confirm both review statements first.',parent=root);return
        if not messagebox.askyesno('Confirm source update','Replace the listed source files with this reviewed bundle?',default='no',parent=root):return
        try:
            if not worker.start():return
            b.configure(state='disabled');status.set('Applying reviewed changes and writing backups. Please wait; do not close the helper.')
            root.after(100,poll)
        except Exception as e:messagebox.showerror('Not applied',str(e),parent=root)
    b=ttk.Button(f,text='Apply reviewed changes with backups',command=apply);b.pack(anchor='e',pady=20)
    root.mainloop()
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '')
