"""Shared planar preview contours without a native-renderer dependency."""
from .model import validate_config


def rectangle(x, y, w, h):
    return {'outer_mm': [(x,y),(x+w,y),(x+w,y+h),(x,y+h)], 'holes_mm': []}


def geometry_parts(config, region=None):
    """Return (category, polygon, z, RGB, opacity) and port line segments."""
    parts, ports = [], []
    if region is not None:
        th = region['substrate']['thickness_mm']
        for shape in region['substrate']['outline']: parts.append(('show_context', shape, -th/2, (.13,.53,.42), .3))
        for row in region['copper']:
            for shape in row['polygons']:
                parts.append(('copper', shape, 0 if row['layer']=='F.Cu' else -th, (.87,.68,.32) if row['layer']=='F.Cu' else (.4,.55,.68), .95))
        for port in region['ports']:
            a,b = port['a_mm'], port['b_mm']; x,y = (a[0]+b[0])/2,(a[1]+b[1])/2
            ports.append(((x,y,-th),(x,y,0)))
    else:
        c = validate_config(config); sx,sy,th = c['substrate_x_mm'],c['substrate_y_mm'],c['thickness_mm']
        base = rectangle(-sx/2,-sy/2,sx,sy)
        parts.extend([('show_context',base,-th/2,(.13,.53,.42),.3),('copper',base,-th,(.72,.54,.27),1)])
        if c['mode']=='patch':
            w,l,f,s,i=(c[k] for k in ('patch_width_mm','patch_length_mm','feed_width_mm','inset_width_mm','inset_length_mm'))
            rects=[rectangle(-w/2,-l/2+i,w,l-i),rectangle(-w/2,-l/2,w/2-f/2-s,i),rectangle(f/2+s,-l/2,w/2-f/2-s,i),rectangle(-f/2,-l/2,f,i)]
            extension=c['advanced']['patch_feed_extension_mm']; offset=c['advanced']['patch_offset_y_mm']
            if extension: rects.append(rectangle(-f/2,-l/2-extension,f,extension))
            rects=[{'outer_mm':[[x,y+offset] for x,y in shape['outer_mm']], 'holes_mm':[]} for shape in rects]
            centers=[(0,-l/2-extension+offset)]
        else:
            l,w=c['line_length_mm'],c['line_width_mm']; rects=[rectangle(-l/2,-w/2,l,w)]; centers=[(-l/2,0),(l/2,0)]
        parts.extend(('copper',shape,0,(.85,.66,.32),1) for shape in rects)
        ports.extend(((x,y,-th),(x,y,0)) for x,y in centers)
    return parts, ports
