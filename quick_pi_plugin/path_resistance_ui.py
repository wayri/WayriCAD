"""Read-only native view of solved DC resistance profiles."""
import threading


def show_path_resistance(parent):
    import wx
    from matplotlib.figure import Figure
    from .plot_canvas import FigureCanvasWxAgg
    from .path_resistance import resistance_profiles, draw_profile

    bundle = parent.bundle
    result = bundle.get('result')
    if not result or not parent._viewport_snapshot_current():
        parent.status.SetLabel('Run a current 2.5D solve before opening the resistance profile.')
        return
    geometry = bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    inventory = parent.inventory or {}
    evidence = (inventory.get('path_geometry') if geometry.get('source_sha256') and
                inventory.get('source_sha256')==geometry['source_sha256'] else None)
    dialog = wx.Dialog(parent,title='DC resistance along a trace',size=(870,580),
                       style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    choice = wx.Choice(dialog)
    layout.Add(choice,0,wx.EXPAND|wx.ALL,8)
    figure = Figure(figsize=(8,4),layout='constrained')
    axes = figure.add_subplot(111)
    canvas = FigureCanvasWxAgg(dialog,-1,figure)
    layout.Add(canvas,1,wx.EXPAND)
    status = wx.StaticText(dialog,label='Sampling the solved copper field…')
    layout.Add(status,0,wx.EXPAND|wx.ALL,8)
    dialog.SetSizer(layout)
    study = None
    closed = threading.Event()

    def draw(event=None):
        if closed.is_set() or study is None:
            return
        axes.clear()
        index = max(0,choice.GetSelection())
        draw_profile(axes,study,index)
        detail = study.get('reason') or ''
        if study['profiles']:
            profile=study['profiles'][index]
            valid=sum(row['resistance_ohm'] is not None for row in profile['samples'])
            detail=f"{valid} of {len(profile['samples'])} locations sampled. " + (profile.get('reason') or '')
        if study.get('omitted_routes'):
            detail += f" {study['omitted_routes']} routes exceed the display limit."
        if study.get('source_current_A') is not None:
            detail += f" Total source current {study['source_current_A']:.5g} A."
        status.SetLabel(detail+'\n'+study['notice'])
        status.Wrap(max(280,dialog.GetClientSize().width-25))
        canvas.draw_idle()
        dialog.Layout()

    def finish(value, error):
        nonlocal study
        if closed.is_set():
            return
        if error:
            status.SetLabel(error)
            return
        study = value
        choice.SetItems([str(item['label']) for item in study['profiles']])
        if choice.GetCount():
            choice.SetSelection(0)
        draw()

    def worker():
        try:
            value,error = resistance_profiles(bundle,evidence),None
        except Exception as exc:
            value,error = None,str(exc)
        if not closed.is_set():
            wx.CallAfter(finish,value,error)

    timer = wx.Timer(dialog)
    def check(event):
        if parent.bundle is not bundle or parent.bundle.get('result') is not result or not parent._viewport_snapshot_current():
            parent.status.SetLabel('The operating point or PCB changed. Open a new resistance profile.')
            dialog.EndModal(wx.ID_CANCEL)
    dialog.Bind(wx.EVT_TIMER,check,timer)
    choice.Bind(wx.EVT_CHOICE,draw)
    threading.Thread(target=worker,daemon=True,name='PI resistance profile').start()
    timer.Start(500)
    try:
        dialog.ShowModal()
    finally:
        closed.set()
        timer.Stop()
        dialog.Destroy()
