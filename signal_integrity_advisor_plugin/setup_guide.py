"""Reviewed route/edge setup for the existing Quick SI screening model."""
from __future__ import annotations

import math
import re


FIELDS = (
    ('rise_ns', '10–90% rise time · ns', False, True),
    ('frequency_mhz', 'Evaluation frequency · MHz', False, False),
    ('source_ohm', 'Driver resistance · Ω', False, False),
    ('load_ohm', 'Receiver resistance · Ω (blank = open)', True, False),
    ('z0_ohm', 'Assumed uniform Z0 · Ω (blank = geometry)', True, True),
    ('epsilon_eff', 'Assumed effective Er (blank = stackup)', True, True),
    ('eye_bitrate_mbps', 'NRZ bit rate · Mbps', False, True),
    ('eye_swing_v', 'Open-circuit source swing · V', False, True),
    ('eye_load_pf', 'Receiver capacitance · pF (blank = 0)', True, False),
    ('eye_via_l_nh', 'Reviewed loop L per via · nH', True, True),
    ('eye_via_c_pf', 'Reviewed shunt C per via · pF', True, False),
)


def validate_setup(net, source, receiver, labels, values, eye_enabled):
    """Validate reviewed controls without substituting model assumptions.

    ``labels`` are exact pad labels on the chosen net. Empty optional model
    fields remain empty, and eye fields are ignored when the eye is disabled.
    No direction, shared terminal, impedance or dielectric value is inferred.
    """
    if not net:
        raise ValueError('Choose a signal net.')
    if source == receiver or source not in labels or receiver not in labels:
        raise ValueError('Choose distinct source and receiver pads on this net.')
    if labels.count(source) != 1 or labels.count(receiver) != 1:
        raise ValueError('Endpoint labels are ambiguous; resolve duplicate references/pad numbers.')
    clean = {}
    for name, caption, optional, positive in FIELDS:
        raw = str(values.get(name, '')).strip()
        if name.startswith('eye_') and not eye_enabled:
            clean[name] = raw
            continue
        if not raw and optional:
            clean[name] = ''
            continue
        try:
            number = float(raw)
        except (ValueError, TypeError) as error:
            raise ValueError('Enter a number for '+caption+'.') from error
        if not math.isfinite(number) or number < 0 or (positive and number == 0):
            raise ValueError(caption+' must be finite and '+('positive.' if positive else 'nonnegative.'))
        if name == 'epsilon_eff' and number < 1:
            raise ValueError('Effective Er must be at least 1.')
        clean[name] = raw
    return dict(net=net, start=source, end=receiver, values=clean, eye_enabled=bool(eye_enabled))


def peer_labels(terminals, label, net):
    """List same-footprint/same-net pads by saved identity, never short them."""
    matches = [row for row in terminals if row['label'] == label and row['net'] == net]
    if len(matches) != 1 or not matches[0].get('footprint_uuid'):
        return []
    owner = matches[0]['footprint_uuid']
    return sorted({row['label'] for row in terminals
                   if row.get('footprint_uuid') == owner and row['net'] == net and row['label'] != label})




def timing_report_cases(report, selected=None):
    """Select completed route records for advice without loading models/boards."""
    schema=report.get('schema')
    if schema=='wayricad.quick-si/v1':available=[dict(id='route',report=report)]
    elif schema=='wayricad.quick-si-study/v1':available=report.get('cases')
    else:raise ValueError('Choose a Quick SI route or study JSON report.')
    if not isinstance(available,list) or not 1<=len(available)<=64:
        raise ValueError('Select one to 64 route cases.')
    ids=[row.get('id') for row in available if isinstance(row,dict)]
    if len(ids)!=len(available) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Report case IDs must be nonempty and unique.')
    chosen=list(ids if selected is None else selected)
    if not chosen or len(set(chosen))!=len(chosen) or set(chosen)-set(ids):
        raise ValueError('Select distinct existing case IDs.')
    cases=[available[ids.index(i)] for i in chosen]
    if any(not isinstance(row.get('report'),dict) for row in cases):
        raise ValueError('Every chosen case needs a completed route report.')
    return chosen,[row['report'] for row in cases]


def circuit_timing_suggestion(reports):
    """Suggest a bounded export grid from declared edges and route delays.

    Twenty points cover the fastest declared edge/delay and 100 a period.
    Duration covers ten slowest periods and eight longest one-way delays.
    This is numerical setup advice, not IBIS bandwidth/convergence evidence.
    """
    if not reports:raise ValueError('Screen a route before suggesting circuit timing.')
    rises=[];delays=[];periods=[]
    for report in reports:
        inputs=report.get('inputs',{})
        for name,value,output in [('rise time',inputs.get('rise_ns'),rises),
                                  ('route delay',report.get('delay_ns'),delays)]:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('A positive resolved '+name+' is needed for every selected route.')
            output.append(value)
        frequency=inputs.get('frequency_mhz')
        if isinstance(frequency,bool) or not isinstance(frequency,(int,float)) or not math.isfinite(frequency) or frequency<=0:
            raise ValueError('A positive stimulus frequency is needed for every selected route.')
        periods.append(1000./frequency)
    step=min(min(rises)/20.,min(delays)/20.,min(periods)/100.)
    duration=max(10.*max(periods),8.*max(delays),10.*max(rises))
    count=duration/step
    if not math.isfinite(count) or count>2_000_000:
        raise ValueError('Timing suggestion exceeds the two-million duration/step ratio; review duration and fastest edges explicitly.')
    return dict(duration_ns=duration,timestep_ns=step,frequency_mhz=1000./max(periods),
                estimated_points=math.ceil(count))


def readiness_rows(report):
    """Expose structured model blockers and channel coverage beside results."""
    rows = []
    for blocker in report.get('blockers', []):
        rows.append(('Needs review · '+str(blocker.get('code', 'MODEL')),
                     str(blocker.get('message', ''))+' Next: '+str(blocker.get('action', 'Review inputs.'))))
    topology = report.get('circuit_topology')
    if topology:
        rows.append(('Whole-net circuit coverage', 'Complete point-to-point routing inventory' if topology.get('complete')
                     else 'Incomplete / unverified: this route is not a complete branched-channel simulation'))
        rows.extend(('Channel coverage review', str(note)) for note in topology.get('notes', []))
    return rows



def _break_long_tokens(text, width, measure):
    """Keep unbroken PCB identifiers inside a wrapped native instruction."""
    def split(match):
        token=match.group();chunks=[]
        while token and measure(token)>width:
            low,high=1,len(token)
            while low<high:
                middle=(low+high+1)//2
                if measure(token[:middle])<=width:low=middle
                else:high=middle-1
            chunks.append(token[:low]);token=token[low:]
        if token:chunks.append(token)
        return '\n'.join(chunks)
    broken=re.sub(r'\S+',split,text)
    lines=[]
    for paragraph in broken.split('\n'):
        current=''
        for word in paragraph.split():
            candidate=(current+' '+word).strip()
            if current and measure(candidate)>width:
                lines.append(current);current=word
            else:current=candidate
        lines.append(current)
    return '\n'.join(lines)


def setup_dialog(parent, pads_by_net, terminals, current, values, eye_enabled, returns):
    """Return an atomic reviewed setup, or None after cancel; no design writes."""
    import wx
    from wayricad_runtime.readable_choice import ReadableComboBox
    from wayricad_runtime.net_filter import filter_combo
    dialog = wx.Dialog(parent, title='Quick SI · Set up path and response',
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(690, 760))
    dialog.SetMinSize(dialog.FromDIP((560, 520)))
    root = wx.BoxSizer(wx.VERTICAL)
    scroll = wx.ScrolledWindow(dialog); scroll.SetScrollRate(0, 12)
    form = wx.BoxSizer(wx.VERTICAL)
    canonical_notes = {}; wrap_state = dict(width=None, busy=False)
    def wrap_notes(force=False):
        if wrap_state['busy']:return
        width = max(200, scroll.GetClientSize().width-28)
        if not force and wrap_state['width'] == width:return
        wrap_state.update(width=width,busy=True)
        try:
            for control, text in canonical_notes.items():
                rendered=_break_long_tokens(text,width,lambda value:control.GetTextExtent(value).width)
                control.SetLabel(rendered); control.SetMinSize((1,-1)); control.Wrap(width); control.InvalidateBestSize()
                control.SetToolTip(text)
            form.Layout(); scroll.FitInside()
        finally:wrap_state['busy']=False
    def set_note(control,text):
        canonical_notes[control] = text; wrap_notes(True)
    def note(text):
        control = wx.StaticText(scroll, label=text); control.SetMinSize((1,-1))
        canonical_notes[control] = text
        form.Add(control, 0, wx.EXPAND | wx.ALL, 7)
        return control
    note('1. Choose the physical source-to-receiver path.\nDirection is your choice; other pads are not combined into ideal SI terminals.')
    search = wx.SearchCtrl(scroll); search.SetHint('Find net · * wildcard, ~ fuzzy')
    form.Add(search, 0, wx.EXPAND | wx.ALL, 7)
    grid = wx.FlexGridSizer(0, 2, 6, 8); grid.AddGrowableCol(1)
    names = list(pads_by_net)
    net = ReadableComboBox(scroll, choices=names, value=current.get('net', ''), style=wx.CB_READONLY)
    source = ReadableComboBox(scroll, choices=[], style=wx.CB_READONLY)
    receiver = ReadableComboBox(scroll, choices=[], style=wx.CB_READONLY)
    for caption, control in [('Signal net', net), ('Source pad', source), ('Receiver pad', receiver)]:
        control.SetMinSize((1, -1)); grid.Add(wx.StaticText(scroll, label=caption), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(control, 1, wx.EXPAND)
    form.Add(grid, 0, wx.EXPAND | wx.ALL, 7)
    peers = note('')
    swap = wx.Button(scroll, label='Swap source and receiver')
    form.Add(swap, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
    note('Return review: '+(', '.join(returns) if returns else 'off — choose the actual return net in the main workspace.')+
         '\nThis setup retains the existing return choices. It does not infer a return-current loop.')
    note('2. Review the edge and line model. Empty Z0 / Er use existing geometry and stackup evidence; unavailable results stay unknown. Entered values are explicit assumptions, not extracted PCB data.')
    inputs = {}; model = wx.FlexGridSizer(0, 2, 6, 8); model.AddGrowableCol(1)
    for key, caption, _, _ in FIELDS:
        if key.startswith('eye_'):continue
        control = wx.TextCtrl(scroll, value=str(values.get(key, ''))); inputs[key] = control
        model.Add(wx.StaticText(scroll, label=caption), 0, wx.ALIGN_CENTER_VERTICAL); model.Add(control, 1, wx.EXPAND)
    form.Add(model, 0, wx.EXPAND | wx.ALL, 7)
    note('3. Optional board RLC eye. Uses ordered extracted trace R/L/C and explicit receiver C. Via routes need reviewed loop L and shunt C per via; the same equivalent applies to every traversed via. Missing references, branches or unsupported geometry block the eye. Skin/dielectric loss and IBIS are not included.')
    eye = wx.CheckBox(scroll, label='Simulate board RLC eye and step response'); eye.SetValue(eye_enabled)
    form.Add(eye, 0, wx.ALL, 7)
    eye_grid = wx.FlexGridSizer(0, 2, 6, 8); eye_grid.AddGrowableCol(1)
    for key, caption, _, _ in FIELDS:
        if not key.startswith('eye_'):continue
        control = wx.TextCtrl(scroll, value=str(values.get(key, ''))); inputs[key] = control
        eye_grid.Add(wx.StaticText(scroll, label=caption), 0, wx.ALIGN_CENTER_VERTICAL); eye_grid.Add(control, 1, wx.EXPAND)
    form.Add(eye_grid, 0, wx.EXPAND | wx.ALL, 7)
    note('For IBIS simulation, load the actual source/receiver models in the main workspace and use Export KiCad circuit. Extra signal pads, branches and unresolved geometry require explicit channel review.')
    error = note(''); error.SetForegroundColour(wx.Colour(170, 45, 35))
    scroll.SetSizer(form); root.Add(scroll, 1, wx.EXPAND)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    cancel = wx.Button(dialog, wx.ID_CANCEL); apply = wx.Button(dialog, label='Apply setup'); run = wx.Button(dialog, label='Apply and screen')
    for button in (cancel, apply, run):buttons.Add(button, 0, wx.ALL, 6)
    root.Add(buttons, 0, wx.ALIGN_RIGHT); dialog.SetSizer(root)
    result = {}
    def refresh_peers(event=None):
        lines = []
        for title, control in [('Source', source), ('Receiver', receiver)]:
            other = peer_labels(terminals, control.GetValue(), net.GetValue())
            if other:lines.append(title+' same-part pads on this net: '+', '.join(other))
        set_note(peers,'\n'.join(lines) if lines else 'No other unambiguous same-part pads on this net.')
    def refresh_net(event=None):
        labels = pads_by_net.get(net.GetValue(), [])
        for control, key in [(source, 'start'), (receiver, 'end')]:
            previous = control.GetValue() or current.get(key, '')
            control.Set(labels); control.SetStringSelection(previous) if previous in labels else control.SetSelection(wx.NOT_FOUND)
        refresh_peers()
    def search_net(event):
        previous = net.GetValue(); filter_combo(net, names, search.GetValue())
        if net.GetValue() != previous:refresh_net()
    def enable_eye(event=None):
        for key, control in inputs.items():
            if key.startswith('eye_'):control.Enable(eye.GetValue())
    def accept(run_after):
        try:
            output = validate_setup(net.GetValue(), source.GetValue(), receiver.GetValue(),
                                    pads_by_net.get(net.GetValue(), []), {key:c.GetValue() for key,c in inputs.items()}, eye.GetValue())
        except ValueError as caught:set_note(error,str(caught));return
        output['run'] = run_after; result.update(output); dialog.EndModal(wx.ID_OK)
    search.Bind(wx.EVT_TEXT, search_net); net.Bind(wx.EVT_COMBOBOX, refresh_net)
    for control in (source, receiver):control.Bind(wx.EVT_COMBOBOX, refresh_peers)
    def swap_roles(event):
        before = source.GetValue(); source.SetValue(receiver.GetValue()); receiver.SetValue(before); refresh_peers()
    swap.Bind(wx.EVT_BUTTON, swap_roles); eye.Bind(wx.EVT_CHECKBOX, enable_eye)
    apply.Bind(wx.EVT_BUTTON, lambda event:accept(False)); run.Bind(wx.EVT_BUTTON, lambda event:accept(True))
    def resized(event):
        wrap_notes(); event.Skip()
    scroll.Bind(wx.EVT_SIZE,resized)
    refresh_net(); enable_eye(); wrap_notes(True)
    # Exposed only for native automation/accessibility; handlers still validate.
    dialog.setup_controls = dict(net=net, source=source, receiver=receiver, values=inputs,
                                 eye=eye, apply=apply, run=run, swap=swap, peers=peers, error=error, scroll=scroll)
    try:
        return result if dialog.ShowModal() == wx.ID_OK else None
    finally:
        dialog.Destroy()
