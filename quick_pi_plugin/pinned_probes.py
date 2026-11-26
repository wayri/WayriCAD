"""Coordinate-anchored Quick PI probes and readable board callouts."""

import math

from .report import VOLTAGE_FIELDS, probe_result


def reading(bundle, pin, metric):
    """Re-resolve physical coordinates on the current mesh, never reuse cell IDs."""
    row = probe_result(bundle, pin['layer'], *pin['point'], metric)
    if row is None or (pin.get('net') and row.get('net') != pin['net']):
        return None
    row = dict(row, location_mm=pin['point'])
    if row['kind'] == 'sheet' and metric in VOLTAGE_FIELDS and row.get('value') is not None:
        import numpy as np
        from .report import _nodal_values

        mesh = bundle['mesh']
        nodes = mesh['triangles'][row['id']]
        a, b, c = np.asarray([mesh['points_mm'][i][:2] for i in nodes])
        u, v = b - a, c - a
        d = np.asarray(pin['point']) - a
        determinant = u[0]*v[1] - u[1]*v[0]
        if determinant:
            wb = (d[0]*v[1] - d[1]*v[0])/determinant
            wc = (u[0]*d[1] - u[1]*d[0])/determinant
            values = _nodal_values(bundle['result'], metric)[nodes]
            if np.isfinite(values).all():
                row['value'] = float(values @ [1-wb-wc, wb, wc])
    return row


def value_text(row):
    if row is None or row.get('value') is None:
        return 'Unavailable'
    value = row['value']
    return f"{value:.5g} {row['unit']}" if math.isfinite(value) else 'Unavailable'


def callout_positions(points, sizes, bounds, pixels_per_point):
    """Place the largest number of visible callouts at bounded offsets."""
    x0, y0, x1, y1 = bounds
    occupied = []
    result = []
    padding = 6*pixels_per_point
    for (x,y),(width,height) in zip(points,sizes):
        choice = None
        if x0 <= x <= x1 and y0 <= y <= y1:
            for radius in (12, 27, 46, 70, 100, 135):
                gap = radius*pixels_per_point
                offsets = ((gap,gap),(-width-gap,gap),(gap,-height-gap),
                           (-width-gap,-height-gap),(-width/2,gap),
                           (-width/2,-height-gap),(gap,-height/2),(-width-gap,-height/2))
                for dx,dy in offsets:
                    box = (x+dx,y+dy,x+dx+width,y+dy+height)
                    if (box[0]-padding < x0 or box[1]-padding < y0 or
                            box[2]+padding > x1 or box[3]+padding > y1):
                        continue
                    if any(box[0] < right+padding and box[2] > left-padding and
                           box[1] < top+padding and box[3] > bottom-padding
                           for left,bottom,right,top in occupied):
                        continue
                    choice = (dx/pixels_per_point,dy/pixels_per_point)
                    occupied.append(box)
                    break
                if choice is not None:
                    break
        result.append(choice)
    return result


def draw_callouts(axes, pins, rows, layer, nets=None):
    """Keep board markers visible when clustered text cannot fit."""
    labels, points = [], []
    for index,(pin,row) in enumerate(zip(pins,rows),1):
        if (layer != 'all' and str(layer) != str(pin['layer'])) or (nets is not None and pin.get('net') not in nets):
            continue
        x,y=pin['point']
        axes.plot(x,y,marker='o',ms=5,mfc='#123d55',mec='white',mew=1.2,
                  zorder=16,clip_on=True,scalex=False,scaley=False)
        label=axes.annotate(f'P{index}   {value_text(row)}',(x,y),xytext=(12,12),textcoords='offset points',
                            fontsize=8,color='#123d55',zorder=17,
                            bbox=dict(boxstyle='round,pad=.36',fc='#ffffff',ec='#8aa9b8',alpha=.97),
                            arrowprops=dict(arrowstyle='-',color='#325969',lw=.8), annotation_clip=True)
        labels.append(label);points.append((x,y))
    if not labels:
        return None
    figure=axes.figure
    def layout(renderer):
        from matplotlib.font_manager import FontProperties
        sizes=[renderer.get_text_width_height_descent(item.get_text(),FontProperties(size=8),False)[:2] for item in labels]
        positions=callout_positions(axes.transData.transform(points),sizes,axes.bbox.extents,renderer.points_to_pixels(1))
        changed=False
        for item,position in zip(labels,positions):
            if item.get_visible()!=(position is not None):
                item.set_visible(position is not None);changed=True
            if position is not None and item.get_position()!=position:
                item.set_position(position);changed=True
        return changed
    canvas=figure.canvas
    layout(canvas.get_renderer())
    def refresh(event):
        if layout(event.renderer):
            canvas.draw_idle()
    return canvas.mpl_connect('draw_event',refresh)
