"""Physical geometry framing for board-style views, independent of the solver."""


def geometry_bounds(arguments, *, focus=True):
    """Return the selected crop or active template bounds in mm, not board context."""
    scene=arguments.get('scene_geometry')
    if isinstance(scene,dict):
        if scene.get('kind')=='research_solids':
            from .paper_scene import bounds
            return bounds(scene)
        if scene.get('board_mm'):
            sx,sy=scene['board_mm']; h=scene.get('substrate_height_mm',scene.get('lower_layer_height_mm',0))
            top=scene.get('upper_layer_height_mm',0)+scene.get('air_gap_mm',0)+scene.get('prs_height_mm',0)
            return (-sx/2,sx/2,-sy/2,sy/2,-h,top)
    if 'substrate' in arguments:
        points = [point for shape in arguments['substrate']['outline'] for point in shape['outer_mm']]
        thickness = arguments['substrate']['thickness_mm']
        if focus:
            nets = {port['signal_net'] for port in arguments.get('ports', []) if port.get('signal_net')}
            signal = [point for row in arguments.get('copper', []) if row['layer']=='F.Cu' and row['net'] in nets
                      for shape in row['polygons'] for point in shape['outer_mm']]
            if signal:
                points = signal+[point for port in arguments['ports'] for point in (port['a_mm'],port['b_mm'])]
    elif 'board_outline' in arguments:
        points = [point for shape in arguments['board_outline'] for point in shape['outer_mm']]
        thickness = 0
    else:
        from .model import validate_config
        config = validate_config(arguments)
        if config['advanced']['study']=='research_antenna':
            from .paper_scene import descriptor, bounds
            scene=descriptor(config)
            if scene is not None: return bounds(scene)
        if config['advanced']['study'] not in ('driven', 'optimization'):
            return None
        thickness = config['thickness_mm']
        if not focus:
            points = [(-config['substrate_x_mm']/2,-config['substrate_y_mm']/2),
                      (config['substrate_x_mm']/2,config['substrate_y_mm']/2)]
        elif config['mode'] == 'patch':
            width, length = config['patch_width_mm'], config['patch_length_mm']
            offset = config['advanced']['patch_offset_y_mm']
            extension = config['advanced']['patch_feed_extension_mm']
            points = [(-width/2, -length/2-extension+offset), (width/2, length/2+offset)]
        elif config['mode'] == 'pcb_line':
            length, width = config['line_length_mm'], config['line_width_mm']
            points = [(-length/2, -width/2), (length/2, width/2)]
        else:
            return None
    if not points:
        return None
    return (min(p[0] for p in points), max(p[0] for p in points),
            min(p[1] for p in points), max(p[1] for p in points), -thickness, 0)


def fit_2d(bounds, width, height, margin=.06):
    """Fit mm bounds to a full canvas without stretching either physical axis."""
    x0,x1,y0,y1 = bounds[:4]
    aspect = max(1, width)/max(1, height)
    span_x,span_y = max(x1-x0, .01),max(y1-y0, .01)
    span_y = max(span_y, span_x/aspect)*(1+2*margin)
    span_x = span_y*aspect
    cx,cy = (x0+x1)/2,(y0+y1)/2
    return (cx-span_x/2,cx+span_x/2), (cy-span_y/2,cy+span_y/2)


def framing_bounds(name, arguments, *, focus=True):
    """Focus spatial results within actual sample coverage, never extrapolate."""
    if name in ('PCB enclosure', '3D setup'):
        return geometry_bounds(arguments, focus=focus)
    field = arguments.get('thermal', arguments.get('field'))
    if not field: return None
    xs,ys = field['x_mm'],field['y_mm']; z = field['z_mm']
    coverage = (min(xs),max(xs),min(ys),max(ys),z,z)
    if not focus: return coverage
    active = geometry_bounds(arguments.get('region',arguments.get('config',{})))
    if active:
        x0,x1,y0,y1 = max(active[0],coverage[0]),min(active[1],coverage[1]),max(active[2],coverage[2]),min(active[3],coverage[3])
        if x1>x0 and y1>y0:
            return (x0,x1,y0,y1,min(active[4],z),max(active[5],z))
    return coverage


def full_bleed(figure, *, legend=False):
    """Remove graph furniture from geometry while retaining actual object labels."""
    axes = figure.axes[0]
    axes.set_axis_off(); axes.set_title('')
    axes.set_position([0,0,.9 if legend and len(figure.axes)>1 else 1,1], which='both')
    for text in list(figure.texts): text.remove()
    if getattr(axes, 'name', '') != '3d':
        axes.set_aspect('auto')
    if legend and len(figure.axes)>1:
        colorbar = figure.axes[1]
        colorbar.set_position([.965,.1,.012,.8])
        colorbar.yaxis.set_ticks_position('left')
        colorbar.set_ylabel('')
