"""Compact native editor for explicit lead/solder/BGA conduction paths."""
from __future__ import annotations

from .package_conduction import normalize_paths


COLUMNS = ('Path', 'Part', 'Pad', 'Layer', 'Port', 'Shape', 'Length mm',
           'Diameter / width mm', 'Thickness mm', 'rho Ω·m', 'k W/m/K',
           'Material', 'Source / evidence', 'Extra Ω', 'Extra K/W')


def paths_from_rows(rows, *, physics, previous=(), layers=()):
    """Repeated path IDs describe ordered series segments, not parallel copies."""
    saved = {path['id']: path for path in previous}
    layer_names = {row['name']: row['id'] for row in layers}
    output = {}
    for index, values in enumerate(rows):
        if not any(str(value).strip() for value in values):
            continue
        if len(values) != len(COLUMNS):
            raise ValueError('Contact row has an unexpected number of columns.')
        identity, ref, pad, layer, port, shape, length, width, thickness, rho, k, material, evidence, re, rt = values
        try:
            layer_id = layer_names[str(layer).strip()] if str(layer).strip() in layer_names else int(str(layer).strip())
        except ValueError:
            raise ValueError('Row '+str(index+1)+': enter a copper layer ID.') from None
        definition = {'id': str(identity).strip(), 'reference': str(ref).strip(),
                      'pad_number': str(pad).strip(), 'layer_id': layer_id, 'segments': []}
        if str(port).strip():
            definition['port'] = str(port).strip()
        if physics == 'electrical' and 'port' not in definition:
            raise ValueError('Row '+str(index+1)+': choose a source or sink port.')
        for key, value in (('additional_electrical_ohm', re), ('additional_thermal_k_per_w', rt)):
            if str(value).strip():
                definition[key] = value
        old = saved.get(definition['id'], {})
        for key in ('pad_uuid', 'evidence'):
            if key in old and all(old.get(field) == definition[field]
                                  for field in ('reference', 'pad_number', 'layer_id')):
                definition[key] = old[key]
        previous_path = output.get(definition['id'])
        if previous_path:
            if {key: value for key, value in previous_path.items() if key != 'segments'} != {
                    key: value for key, value in definition.items() if key != 'segments'}:
                raise ValueError(definition['id']+': series rows must use the same part, pad, layer, port and extras.')
            definition = previous_path
        else:
            output[definition['id']] = definition
        segment = {'shape': str(shape).strip(), 'length_mm': length}
        if shape == 'rectangular':
            segment.update(width_mm=width, thickness_mm=thickness)
        else:
            segment['diameter_mm'] = width
            if str(thickness).strip():
                raise ValueError(definition['id']+': thickness applies only to rectangular leads.')
        for key, value in (('rho_ohm_m', rho), ('k_w_mk', k), ('material', material), ('evidence', evidence)):
            if str(value).strip():
                segment[key] = value
        definition['segments'].append(segment)
    return [record['definition'] for record in normalize_paths(list(output.values()), physics=physics)]


def edit_package_contacts(parent, previous, *, physics, ports=(), references=(), layers=()):
    import wx
    import wx.grid

    layer_names = {row['id']: row['name'] for row in layers}
    with wx.Dialog(parent, title='Lead / solder / BGA contacts', size=(1310, 580),
                   style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) as dialog:
        layout = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(dialog, label=(
            'One path joins one saved copper pad face to a package endpoint. Repeat its Path ID for lead + solder in series.\n'
            'Different Path IDs are parallel contacts. Enter reviewed dimensions and material properties; no alloy or ball size is guessed.\n'
            'Spherical ball uses a symmetric truncated sphere: height < diameter, with finite necks. Pad copper is already in the board mesh.\n'
            + ('Port source / sink identifies an electrically common rail endpoint; all its pads must belong to the selected net.\n'
               if physics == 'electrical' else
               'Thermal contacts share the declared body/junction node for each part. Configure that node in Component heating · R / C.\n')
            + 'Extra resistance is optional reviewed internal/interface resistance, added once per path. Blank means an ideal bonded interface.'))
        layout.Add(note, 0, wx.ALL, 10)
        grid = wx.grid.Grid(dialog)
        rows = []
        for path in previous:
            for segment in path['segments']:
                rows.append([path['id'], path['reference'], path['pad_number'], layer_names.get(path['layer_id'],str(path['layer_id'])),
                    path.get('port', ''), segment['shape'], str(segment['length_mm']),
                    str(segment.get('diameter_mm', segment.get('width_mm', ''))),
                    str(segment.get('thickness_mm', '')), str(segment.get('rho_ohm_m', '')),
                    str(segment.get('k_w_mk', '')), segment.get('material', ''), segment.get('evidence', ''),
                    str(path.get('additional_electrical_ohm', '')),
                    str(path.get('additional_thermal_k_per_w', ''))])
        grid.CreateGrid(max(1, len(rows)), len(COLUMNS))
        grid.SetRowLabelSize(38)
        for col, label in enumerate(COLUMNS):
            grid.SetColLabelValue(col, label)
            grid.SetColSize(col, 85 if col not in (5, 7, 11) else 135)
        if physics == 'thermal':
            grid.HideCol(4)
        for row in range(grid.GetNumberRows()):
            for col, choices in ((1, references), (3, tuple(layer_names.values())), (4, ports),
                                 (5, ('cylinder', 'rectangular', 'spherical_ball'))):
                if choices:
                    grid.SetCellEditor(row, col, wx.grid.GridCellChoiceEditor(list(choices), True))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                grid.SetCellValue(row, col, value)
        layout.Add(grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        add = wx.Button(dialog, label='+ Segment')
        remove = wx.Button(dialog, label='− Row')
        toolbar.Add(add, 0, wx.RIGHT, 6); toolbar.Add(remove, 0)
        layout.Add(toolbar, 0, wx.ALL, 10)
        error = wx.StaticText(dialog, label='')
        layout.Add(error, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        result = None

        def add_row(event):
            grid.AppendRows(1)
            row = grid.GetNumberRows()-1
            for col, choices in ((1, references), (3, tuple(layer_names.values())), (4, ports),
                                 (5, ('cylinder', 'rectangular', 'spherical_ball'))):
                if choices:
                    grid.SetCellEditor(row, col, wx.grid.GridCellChoiceEditor(list(choices), True))
            grid.SetGridCursor(row, 0); grid.MakeCellVisible(row, 0)

        def remove_row(event):
            grid.SaveEditControlValue(); grid.DisableCellEditControl()
            selected = sorted(set(grid.GetSelectedRows()) or {grid.GetGridCursorRow()}, reverse=True)
            for row in selected:
                if 0 <= row < grid.GetNumberRows():
                    grid.DeleteRows(row, 1)
            if not grid.GetNumberRows():
                add_row(event)

        def apply(event):
            nonlocal result
            grid.SaveEditControlValue(); grid.DisableCellEditControl()
            try:
                result = paths_from_rows([[grid.GetCellValue(row, col) for col in range(len(COLUMNS))]
                    for row in range(grid.GetNumberRows())], physics=physics, previous=previous,layers=layers)
            except ValueError as exc:
                error.SetLabel(str(exc)); return
            dialog.EndModal(wx.ID_OK)

        add.Bind(wx.EVT_BUTTON, add_row); remove.Bind(wx.EVT_BUTTON, remove_row)
        dialog.Bind(wx.EVT_BUTTON, apply, id=wx.ID_OK)
        dialog.SetSizer(layout)
        return result if dialog.ShowModal() == wx.ID_OK else None
