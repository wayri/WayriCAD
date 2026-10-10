"""Explicit lumped component thermal storage inputs; no material inference."""
import math


def storage_from_rows(rows):
    """Rows: (reference, enabled, kind, R K/W, C J/K, initial °C)."""
    output = {}
    for ref, enabled, kind, resistance, capacity, initial, *surface in rows:
        if not enabled:
            continue
        if kind not in ('body','junction'):
            raise ValueError(ref+': choose body or junction temperature.')
        values = {}
        for key, raw, label in [('resistance_k_per_w',resistance,'R (K/W)'),
                                 ('capacity_j_k',capacity,'C (J/K)')]:
            try:
                value = float(raw)
            except (ValueError, TypeError):
                raise ValueError(ref+': enter explicit positive '+label+'.') from None
            if not math.isfinite(value) or value <= 0:
                raise ValueError(ref+': enter explicit positive '+label+'.')
            values[key] = value
        values['temperature_kind'] = kind
        if str(initial).strip():
            try:
                value = float(initial)
            except (ValueError,TypeError):
                raise ValueError(ref+': initial temperature must be finite °C.') from None
            if not math.isfinite(value) or not -273.15 < value <= 10000:
                raise ValueError(ref+': initial temperature must exceed absolute zero and be <=10000 °C.')
            values['initial_c'] = value
        if len(surface)>3:
            contact=surface.pop()
            if str(contact).strip():values['contact_pad_number']=str(contact).strip()
        if surface and any(str(value).strip() for value in surface):
            if len(surface)!=3 or any(not str(value).strip() for value in surface):
                raise ValueError(ref+': enter exposed area, convection h and emissivity together.')
            for key,raw in zip(('exposed_area_mm2','h_w_m2k','emissivity'),surface):
                try:value=float(raw)
                except (ValueError,TypeError):raise ValueError(ref+': '+key+' must be finite.') from None
                if not math.isfinite(value) or value<0 or (key=='exposed_area_mm2' and value==0) or (key=='emissivity' and value>1):
                    raise ValueError(ref+': invalid '+key+'.')
                values[key]=value
        output[ref] = values
    return output


def edit_storage(parent, references, previous):
    """A compact reviewed table; blank properties never become defaults."""
    import wx
    import wx.grid
    with wx.Dialog(parent,title='Component heating · thermal RC',size=(1140,490),
                   style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER) as dialog:
        layout = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(dialog,label=(
            'Each enabled part has one stored temperature. R connects it to the board/sink; C stores heat.\n'
            'Body temperature does not establish junction limits. STEP models supply shape, not R or C.\n'
            'Blank initial uses the study initial. Optional surface cooling needs reviewed exposed area, h and emissivity.\n'
            'Use h=0 in vacuum. Blank surface fields mean no direct package cooling.\n'
            'Enter a thermal contact pad when known; blank uses the saved footprint bounding box as a contact proxy.'))
        layout.Add(note,0,wx.ALL,10)
        grid = wx.grid.Grid(dialog)
        grid.CreateGrid(len(references),10)
        grid.SetRowLabelSize(0)
        for col,label in enumerate(('Part','Enable RC','Temperature','R (K/W)','C (J/K)','Initial °C','Exposed mm²','h W/m²/K','Emissivity','Contact pad')):
            grid.SetColLabelValue(col,label)
            grid.SetColSize(col,110 if col != 1 else 80)
        grid.SetColFormatBool(1)
        for row,ref in enumerate(references):
            definition = previous.get(ref,{})
            grid.SetCellValue(row,0,ref);grid.SetReadOnly(row,0)
            grid.SetCellValue(row,1,'1' if definition else '')
            grid.SetCellEditor(row,2,wx.grid.GridCellChoiceEditor(['body','junction'],False))
            for col,key in ((2,'temperature_kind'),(3,'resistance_k_per_w'),(4,'capacity_j_k'),(5,'initial_c'),
                            (6,'exposed_area_mm2'),(7,'h_w_m2k'),(8,'emissivity'),(9,'contact_pad_number')):
                grid.SetCellValue(row,col,str(definition.get(key,'body' if col == 2 else '')))
        layout.Add(grid,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        error = wx.StaticText(dialog,label='');layout.Add(error,0,wx.EXPAND|wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10)
        result = None
        def apply(event):
            nonlocal result
            grid.SaveEditControlValue();grid.DisableCellEditControl()
            try:
                edited = storage_from_rows([(ref,grid.GetCellValue(row,1)=='1',
                    *[grid.GetCellValue(row,col) for col in range(2,10)]) for row,ref in enumerate(references)])
            except ValueError as exc:
                error.SetLabel(str(exc));return
            # Keep hidden, unselected definitions until the owner explicitly filters the request.
            result = {ref:values for ref,values in previous.items() if ref not in references}
            result.update(edited);dialog.EndModal(wx.ID_OK)
        dialog.Bind(wx.EVT_BUTTON,apply,id=wx.ID_OK)
        dialog.SetSizer(layout)
        return result if dialog.ShowModal()==wx.ID_OK else None
