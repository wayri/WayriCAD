"""Saved copper to explicit ideal-reference planar PDN study; no board writes."""
from pathlib import Path
import hashlib
import math


def configure(parent):
    import wx
    dialog=wx.Dialog(parent,title='Planar PDN - reference and sweep',size=(620,570),
                     style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    layout=wx.BoxSizer(wx.VERTICAL);form=wx.FlexGridSizer(cols=2,hgap=10,vgap=8);form.AddGrowableCol(1)
    controls={}
    for key,label,initial in (
            ('reference','Reference plane / net name',''),
            ('dielectric_height_mm','Assumed plane separation (mm)','0.2'),
            ('epsr','Relative permittivity','4.2'),('tandelta','Dielectric loss tangent','0.02'),
            ('resistivity_ohm_m','Copper resistivity at 20 C (ohm m)','1.7241e-8'),
            ('temperature_c','Copper temperature (C)','20'),
            ('start','Start frequency (MHz)','1'),('stop','Stop frequency (MHz)','3000'),
            ('count','Log-spaced samples','121')):
        form.Add(wx.StaticText(dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL)
        control=wx.TextCtrl(dialog,value=initial);controls[key]=control;form.Add(control,1,wx.EXPAND)
    layout.Add(form,1,wx.EXPAND|wx.ALL,14)
    confirmation=wx.CheckBox(dialog,label='Use a full ideal reference plane and magnetic edge walls')
    confirmation.SetToolTip('Explicit modelling assumption. Reference-plane voids, losses, vias and launches are not extracted.')
    layout.Add(confirmation,0,wx.EXPAND|wx.ALL,12)
    help_button=wx.Button(dialog,wx.ID_HELP)
    def help_event(event):
        from wayricad_runtime.help import open_help
        open_help(dialog,Path(__file__).with_name('PLANE_PORTS.html'),'Planar PDN help')
    help_button.Bind(wx.EVT_BUTTON,help_event)
    buttons=dialog.CreateButtonSizer(wx.OK|wx.CANCEL);buttons.Insert(0,help_button,0,wx.RIGHT,12)
    layout.Add(buttons,0,wx.EXPAND|wx.ALL,12);dialog.SetSizer(layout);dialog.CentreOnParent()
    try:
        if dialog.ShowModal()!=wx.ID_OK:return None
        if not confirmation.GetValue() or not controls['reference'].GetValue().strip():
            raise ValueError('Name the reference plane and explicitly confirm the ideal-plane boundary assumption.')
        values={key:float(control.GetValue()) for key,control in controls.items() if key!='reference'}
        if any(not math.isfinite(value) for value in values.values()):raise ValueError('All sweep and material inputs must be finite.')
        if not 0<values['start']<values['stop'] or not values['count'].is_integer() or not 2<=values['count']<=512:
            raise ValueError('Use positive increasing frequencies and 2-512 samples.')
        start,stop,count=values.pop('start'),values.pop('stop'),int(values.pop('count'))
        values['frequencies_hz']=[10**(math.log10(start*1e6)+i*math.log10(stop/start)/(count-1)) for i in range(count)]
        return values,controls['reference'].GetValue().strip()
    finally:dialog.Destroy()


def launch_from_board(frame):
    from .board_plane import study_from_mesh
    from .plane_ports import run_study
    from .ac_ports_ui import create_frame
    if frame._busy:return
    if not frame._snapshot_current():raise ValueError('Reload the saved board before a PDN study.')
    if frame.model_dimension.GetSelection()!=0:
        raise ValueError('Select the 2.5D sheet model before planar PDN extraction.')
    if frame._series_request or frame._extra_sinks:
        raise ValueError('Choose one net with two distinct pad ports, not a series or multi-load DC study.')
    board=Path(frame.board_path)
    digest=frame._origin_sha() or frame.inventory.get('source_sha256')
    revision=getattr(frame,'_input_revision',0)
    if not digest or hashlib.sha256(board.read_bytes()).hexdigest()!=digest:
        raise ValueError('Reload the reviewed saved-board snapshot before a PDN study.')
    parameters=configure(frame)
    if parameters is None:return
    if revision!=getattr(frame,'_input_revision',0) or hashlib.sha256(board.read_bytes()).hexdigest()!=digest:
        raise ValueError('Inputs or saved board changed during PDN configuration. Reload and review the ports again.')
    values,reference=parameters
    request=frame._request('mesh')
    first,second=frame._unit_ids('source'),frame._unit_ids('sink')
    def mesh_ready(bundle):
        geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
        if geometry.get('source_sha256')!=digest or hashlib.sha256(board.read_bytes()).hexdigest()!=digest:
            raise ValueError('Extracted copper does not match the reviewed saved-board snapshot.')
        study=study_from_mesh(bundle,first,second,values)
        def solve():
            if hashlib.sha256(board.read_bytes()).hexdigest()!=digest:raise ValueError('Saved board changed before PDN solve.')
            result=run_study(study,cancel=frame._cancel)
            if hashlib.sha256(board.read_bytes()).hexdigest()!=digest:raise ValueError('Saved board changed during PDN solve.')
            result.update(source_path=str(board),source_sha256=digest,
                          reference_plane_name=reference,net=request.get('net'))
            return result
        frame._task(solve,lambda result:create_frame(frame,result_only=result).Show(),
                    'Solving planar PDN sweep with explicit ideal reference...')
    frame._job(request,mesh_ready,'Extracting selected saved copper and pad ports...')
