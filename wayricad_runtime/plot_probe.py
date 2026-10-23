"""Native Matplotlib exact-sample hover and persistent click probes."""
import math


class _CellIndex:
    """Index cell bounds; lazily construct exact paths only for local candidates."""

    def __init__(self, polygons):
        from matplotlib.path import Path
        self._path_type = Path
        self.polygons = polygons
        self.paths = {}
        self.bounds = []
        for poly in polygons:
            if len(poly):
                xs, ys = zip(*((p[0], p[1]) for p in poly))
                self.bounds.append((min(xs), max(xs), min(ys), max(ys)))
            else:
                self.bounds.append((math.inf, -math.inf, math.inf, -math.inf))
        valid = [b for b in self.bounds if all(math.isfinite(v) for v in b)]
        self.grid = {}
        self.large = []
        self.origin = (0., 0.)
        self.step = (1., 1.)
        self.size = min(256, max(1, math.ceil(math.sqrt(len(valid)))))
        if not valid:
            return
        x0, x1 = min(b[0] for b in valid), max(b[1] for b in valid)
        y0, y1 = min(b[2] for b in valid), max(b[3] for b in valid)
        self.origin = (x0, y0)
        self.step = ((x1-x0)/self.size or 1., (y1-y0)/self.size or 1.)
        for i, b in enumerate(self.bounds):
            if not all(math.isfinite(v) for v in b):
                continue
            lo = self._key(b[0], b[2])
            hi = self._key(b[1], b[3])
            # Bound index storage for large plane cells without approximating them.
            if (hi[0]-lo[0]+1)*(hi[1]-lo[1]+1) > 64:
                self.large.append(i)
                continue
            for ix in range(lo[0], hi[0]+1):
                for iy in range(lo[1], hi[1]+1):
                    self.grid.setdefault((ix, iy), []).append(i)

    def _key(self, x, y):
        return (math.floor((x-self.origin[0])/self.step[0]),
                math.floor((y-self.origin[1])/self.step[1]))

    def pick(self, x, y, count):
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        # Preserve the original first-containing-cell policy for overlapping layers.
        for i in sorted(self.grid.get(self._key(x, y), []) + self.large):
            if i >= count:
                continue
            b = self.bounds[i]
            if b[0] <= x <= b[1] and b[2] <= y <= b[3]:
                path = self.paths.get(i)
                if path is None:
                    path = self.paths[i] = self._path_type(self.polygons[i])
                if path.contains_point((x, y)):
                    return i
        return None


def attach_probes(canvas, axes, rows, unit='', polygons=None, on_select=None):
    """Attach [x,y,value,label,z] samples; polygon cells require containment.

    Returns a controller holding probe artists and a disconnect method. In 3D,
    samples are picked by their current projected screen positions. No values
    are interpolated across missing cells, holes or disconnected conductors.
    """
    from mpl_toolkits.mplot3d import proj3d
    state = {'rows': rows, 'probes': [], 'ids': [], 'press': None}
    cells = _CellIndex(polygons) if polygons is not None else None
    can_blit = bool(getattr(canvas, 'supports_blit', False))
    background = None
    tip = axes.annotate('', xy=(0, 0), xycoords='axes fraction', xytext=(.02, .98),
                        textcoords='axes fraction', va='top',
                        bbox={'facecolor': 'white', 'alpha': .9}, animated=can_blit)
    tip.set_visible(False)

    sample_grid = {}
    sample_key = None

    def pick(event):
        nonlocal sample_grid, sample_key
        if event.inaxes is not axes:
            return None
        if cells is not None:
            if event.xdata is None or event.ydata is None:
                return None
            index = cells.pick(event.xdata, event.ydata, len(rows))
            return rows[index] if index is not None else None
        # Project samples once per view, then search only a 12-pixel neighbourhood.
        # Retaining row order keeps exact-distance ties consistent with the old loop.
        import numpy as np
        projection = axes.get_proj() if hasattr(axes, 'get_proj') else None
        key = (tuple(axes.transData.get_matrix().ravel()),
               tuple(projection.ravel()) if projection is not None else None)
        if key != sample_key:
            sample_grid = {}
            indices = [i for i, row in enumerate(rows)
                       if all(math.isfinite(float(v)) for v in row[:2])]
            if indices:
                coordinates = np.asarray([[rows[i][0], rows[i][1],
                                           rows[i][4] if len(rows[i]) > 4 else 0]
                                          for i in indices], dtype=float)
                if projection is not None:
                    x, y, _ = proj3d.proj_transform(*coordinates.T, projection)
                    points = np.column_stack((x, y))
                else:
                    points = coordinates[:, :2]
                for i, (sx, sy) in zip(indices, axes.transData.transform(points)):
                    if math.isfinite(sx) and math.isfinite(sy):
                        cell = (math.floor(sx/12), math.floor(sy/12))
                        sample_grid.setdefault(cell, []).append((i, sx, sy))
            sample_key = key
        cx, cy = math.floor(event.x/12), math.floor(event.y/12)
        candidates = []
        for ix in range(cx-1, cx+2):
            for iy in range(cy-1, cy+2):
                candidates.extend(sample_grid.get((ix, iy), ()))
        best = None
        distance = 12
        for i, sx, sy in sorted(candidates):
            d = math.hypot(event.x-sx, event.y-sy)
            if d < distance:
                distance, best = d, rows[i]
        return best

    def text(row):
        value = row[2]
        result = f'{float(value):.7g} {unit}' if value is not None and math.isfinite(float(value)) else 'Unknown'
        return str(row[3]) + ' | ' + result

    def paint_tip():
        if can_blit and background is not None and not axes.figure.stale:
            canvas.restore_region(background)
            if tip.get_visible():
                axes.draw_artist(tip)
            canvas.blit(axes.figure.bbox)
        else:
            canvas.draw_idle()

    def drawn(event):
        nonlocal background
        if can_blit:
            background = canvas.copy_from_bbox(axes.figure.bbox)
            if tip.get_visible():
                axes.draw_artist(tip)
                canvas.blit(axes.figure.bbox)

    def motion(event):
        if state['press'] is not None or getattr(getattr(canvas, 'toolbar', None), 'mode', ''):
            return
        row = pick(event)
        visible = row is not None
        label = text(row) if visible else ''
        if tip.get_visible() == visible and (not visible or tip.get_text() == label):
            return
        tip.set_visible(visible)
        if visible:
            tip.set_text(label)
        paint_tip()

    def clear():
        if not state['probes']:
            return
        for artist in state['probes']:
            artist.remove()
        state['probes'].clear()
        canvas.draw_idle()

    state['clear'] = clear

    def press(event):
        # Do not carry an old hover value along with the cached pan bitmap.
        if tip.get_visible():
            tip.set_visible(False)
            paint_tip()
        state['press'] = (event.x, event.y) if event.button == 1 else None
        if event.button == 3 and event.key == 'control':
            clear()

    def release(event):
        start = state['press']
        state['press'] = None
        if start is not None and math.hypot(event.x-start[0], event.y-start[1]) < 4:
            click(event)

    def click(event):
        if event.button != 1 or getattr(getattr(canvas, 'toolbar', None), 'mode', ''):
            return
        row = pick(event)
        if row is None:
            return
        if on_select:
            on_select(row)
        if row[2] is None or not math.isfinite(float(row[2])):
            return
        index = len(state['probes']) + 1
        if hasattr(axes, 'get_proj'):
            artist = axes.text(row[0], row[1], row[4] if len(row)>4 else 0, f'P{index}: '+text(row), fontsize=8)
        else:
            artist = axes.annotate(f'P{index}: '+text(row), row[:2], xytext=(8, 8), textcoords='offset points',
                                   fontsize=8, bbox={'facecolor': 'white', 'alpha': .85})
        state['probes'].append(artist)
        canvas.draw_idle()

    def scroll(event):
        if event.inaxes is not axes or not hasattr(axes, 'get_proj'):
            return
        factor = .85 if event.button == 'up' else 1/.85
        for getter, setter in ((axes.get_xlim, axes.set_xlim), (axes.get_ylim, axes.set_ylim), (axes.get_zlim, axes.set_zlim)):
            low, high = getter()
            mid, half = (low+high)/2, (high-low)*factor/2
            setter(mid-half, mid+half)
        canvas.draw_idle()

    state['ids'] = [canvas.mpl_connect(name, callback) for name, callback in (
        ('draw_event', drawn), ('scroll_event', scroll), ('motion_notify_event', motion),
        ('button_press_event', press), ('button_release_event', release))]

    def disconnect():
        nonlocal background
        for cid in state['ids']:
            canvas.mpl_disconnect(cid)
        state['ids'].clear()
        if tip in axes.texts:
            tip.remove()
        background = None

    state['disconnect'] = disconnect
    return state
