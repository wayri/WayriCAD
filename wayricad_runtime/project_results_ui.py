"""Project-local saved simulations and read-only numerical inspection.

The archive viewer consumes only embedded arrays. It never reconstructs native
board objects, invokes a solver or enables editor selection/current changes.
"""
from __future__ import annotations

import math
from itertools import islice
from pathlib import Path
import threading
import time


MAX_PLOT_SAMPLES = 200000


def _unavailable(label, reason):
    return dict(label=label, kind='unavailable', reason=reason+'; complete values remain in Advanced data.')


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def plot_specs(bundle):
    """Describe stored plots without changing payloads or deriving missing samples."""
    specs = []
    queue = [('Result', bundle, None, None)]
    visited = 0
    while queue and visited < 512:
        label, node, inherited_axis, inherited_times = queue.pop(0)
        visited += 1
        if not isinstance(node, dict):
            continue
        mesh, result = node.get('mesh', {}), node.get('result', {})
        if isinstance(mesh,dict) and isinstance(result,dict) and mesh:
            points=mesh.get('points_mm')
            if not isinstance(points,list) and result.get('potential_V'):
                specs.append(_unavailable(label+' / volume data','This mesh layout has no supported saved points_mm field; full 3D reconstruction is unavailable'))
            if isinstance(points,list) and points:
                for key,unit in [('potential_V','V'),('cell_power_W','W')]:
                    values=result.get(key)
                    if not isinstance(values,list) or not values:
                        continue
                    positions=points if key=='potential_V' else result.get('cell_centroid_mm',[])
                    if len(values)>MAX_PLOT_SAMPLES:
                        specs.append(_unavailable(label+' / '+key,'Plot budget exceeded (200,000 stored samples)'))
                        continue
                    if not isinstance(positions,list) or len(positions)!=len(values):
                        continue
                    groups={}
                    for index,point in enumerate(positions):
                        if not isinstance(point,(list,tuple)) or len(point)<2 or not all(_number(v) for v in point[:min(3,len(point))]):
                            groups={};break
                        elevation=point[2] if len(point)>2 else None
                        groups.setdefault(elevation,[]).append(index)
                    if len(groups)>64:
                        specs.append(_unavailable(label+' / '+key,'Unstructured 3D field has more than 64 stored elevations; full volume reconstruction is unavailable'))
                        continue
                    for elevation,indices in groups.items():
                        plane='' if elevation is None else ' / saved Z = '+str(elevation)+' mm'
                        specs.append(dict(label=label+plane+' / '+key,kind='points',
                            x=[positions[i][0] for i in indices],y=[positions[i][1] for i in indices],
                            z=elevation,values=[values[i] for i in indices],unit=unit))
        if all(isinstance(node.get(key), list) and node[key] for key in ('x_centers_mm', 'y_centers_mm', 'values_c')):
            specs.append(dict(label=label+' / temperature', kind='grid', x=node['x_centers_mm'],
                              y=node['y_centers_mm'], values=node['values_c'], unit='°C'))
        spatial, frames = node.get('spatial_index'), node.get('frames')
        if isinstance(spatial, dict) and isinstance(frames, list) and frames:
            cells = spatial.get('cells', [])
            count = spatial.get('active_cells_per_layer')
            if type(count) is int and count > 0 and isinstance(cells,list) and len(cells) == count and isinstance(spatial.get('x_centers_mm'),list) and isinstance(spatial.get('y_centers_mm'),list):
                for index, layer in enumerate(spatial.get('layers', [])):
                    if not isinstance(layer,dict):
                        specs.append(_unavailable(label,'Malformed saved thermal layer descriptor'))
                        continue
                    specs.append(dict(label=label+' / '+str(layer.get('name', index)), kind='frames',
                        x=spatial['x_centers_mm'], y=spatial['y_centers_mm'], cells=cells,
                        layer=index, count=count, frames=frames, unit='°C'))
        if isinstance(node.get('time_ui'), list) and isinstance(node.get('traces_v'), list):
            eye_size=sum(len(row) if isinstance(row,list) else MAX_PLOT_SAMPLES+1 for row in node['traces_v'])
            if eye_size > MAX_PLOT_SAMPLES:
                specs.append(_unavailable(label+' / saved eye', 'Eye plot budget exceeded (200,000 stored samples)'))
            else:
                specs.append(dict(label=label+' / saved eye', kind='eye', x=node['time_ui'], values=node['traces_v'], unit='V'))
        time_context=next(((axis,node[axis]) for axis in ('times_s','time_s','time_ns') if isinstance(node.get(axis),list)),(inherited_axis,inherited_times))
        axes=[(axis,node.get(axis)) for axis in ('times_s', 'time_s', 'time_ns', 'frequency_hz', 'frequency_Hz')]
        if inherited_times is not None and not any(isinstance(node.get(axis),list) for axis in ('times_s','time_s','time_ns')):
            axes.append((inherited_axis,inherited_times))
        for axis,times in axes:
            if not isinstance(times, list) or not times:
                continue
            if len(times)>MAX_PLOT_SAMPLES:
                specs.append(_unavailable(label+' / '+axis,'Line plot budget exceeded (200,000 stored samples)'))
                continue
            if not all(_number(v) for v in times):
                continue
            for key, values in node.items():
                if key == axis or not isinstance(values, list) or len(values) != len(times):
                    continue
                if all(v is None or _number(v) for v in values):
                    specs.append(dict(label=label+' / '+key, kind='line', x=times, values=values, axis=axis, unit=key))
        segments = node.get('segments')
        if isinstance(segments, list) and segments and all(isinstance(s, dict) for s in segments):
            distance, positions, impedances = 0., [], []
            for segment in segments:
                length = segment.get('length_mm')
                if not _number(length):
                    continue
                positions.append(distance + length / 2)
                distance += length
                impedances.append(segment.get('impedance_ohm', segment.get('screening_z0_ohm')))
            if positions:
                specs.append(dict(label=label+' / route impedance', kind='line', x=positions,
                                  values=impedances, axis='distance_mm', unit='Ω'))
        harmonics = node.get('harmonics')
        if isinstance(harmonics, list) and harmonics and all(isinstance(s, dict) for s in harmonics):
            for key in ('loss_W', 'resistance_ohm', 'reactance_ohm'):
                rows = [r for r in harmonics if _number(r.get('frequency_hz')) and key in r]
                if rows:
                    specs.append(dict(label=label+' / '+key, kind='line', x=[r['frequency_hz'] for r in rows],
                                      values=[r[key] for r in rows], axis='frequency_hz', unit=key))
        for key, value in node.items():
            if isinstance(value, dict):
                queue.append((label+' / '+key, value, *time_context))
            elif isinstance(value, list) and value and isinstance(value[0], dict) and key not in ('frames', 'segments', 'cells'):
                queue.extend((label+' / '+key+' '+str(index), child, *time_context) for index, child in enumerate(value[:max(0, 512-len(queue))]) if isinstance(child, dict))
    return specs


def frame_grid(spec, index=0):
    """Unflatten actual layer-major thermal frames; inactive cells remain unknown."""
    if len(spec['x'])*len(spec['y'])>MAX_PLOT_SAMPLES:
        raise ValueError('Field plot budget exceeded (200,000 cells); complete values remain in Advanced data.')
    if spec['kind'] != 'frames':
        values=spec['values']
        if len(values)!=len(spec['y']) or any(not isinstance(row,list) or len(row)!=len(spec['x']) for row in values):
            raise ValueError('Saved thermal grid dimensions do not match its coordinates.')
        return values
    frame = spec['frames'][index]
    values = frame['temperatures_c']
    offset = spec['layer'] * spec['count']
    if not isinstance(values,list) or offset+spec['count']>len(values):
        raise ValueError('Saved thermal frame is shorter than its declared layer indexing.')
    grid = [[None for _ in spec['x']] for _ in spec['y']]
    for cell, position in enumerate(spec['cells']):
        if not isinstance(position,list) or len(position)!=2 or any(type(v)is not int for v in position):
            raise ValueError('Saved thermal cell indices must be integer XY pairs.')
        x,y=position
        if not 0<=x<len(spec['x']) or not 0<=y<len(spec['y']):
            raise ValueError('Saved thermal cell index lies outside its grid.')
        grid[y][x] = values[offset+cell]
    return grid


def probe_sample(spec, x, y=None, *, frame=0):
    """Return a nearest stored sample, never an interpolated or re-solved value."""
    if spec.get('kind')=='unavailable' or not spec.get('x'):
        return None
    if spec['kind'] in ('grid', 'frames'):
        column = min(range(len(spec['x'])), key=lambda i: abs(spec['x'][i]-x))
        row = min(range(len(spec['y'])), key=lambda i: abs(spec['y'][i]-(y if y is not None else 0)))
        return dict(x=spec['x'][column], y=spec['y'][row], value=frame_grid(spec, frame)[row][column], unit=spec['unit'])
    if spec['kind'] == 'points':
        index = min(range(len(spec['x'])), key=lambda i: (spec['x'][i]-x)**2+(spec['y'][i]-(y if y is not None else 0))**2)
        distance=(spec['x'][index]-x)**2+(spec['y'][index]-(y if y is not None else 0))**2
        tied=[i for i in range(len(spec['x'])) if abs((spec['x'][i]-x)**2+(spec['y'][i]-(y if y is not None else 0))**2-distance)<1e-14]
        ambiguous=any(spec['values'][i]!=spec['values'][index] for i in tied)
        return dict(x=spec['x'][index],y=spec['y'][index],z=spec.get('z'),
                    value=None if ambiguous else spec['values'][index],unit=spec['unit'],ambiguous=ambiguous)
    index = min(range(len(spec['x'])), key=lambda i: abs(spec['x'][i]-x))
    values = spec['values']
    if spec['kind'] == 'eye':
        traces = [row for row in values if index < len(row)]
        if not traces:
            return None
        row = min(traces, key=lambda row: abs(row[index]-(y if y is not None else 0)))
        value = row[index]
    else:
        value = values[index]
    return dict(x=spec['x'][index], value=value, unit=spec['unit'])


def binding_text(receipt):
    state = receipt.get('source_state', 'unverified')
    if state == 'current':
        return 'Saved simulation • read-only. Saved source matches current project files. No solver or editor actions are enabled.'
    return ('Saved simulation • read-only. '+state.capitalize()+' source; historical data only. '
            'Editor selection, automatic correction and current editing are disabled.')


def _canvas_types():
    """Use WxAgg where complete; KiCad may omit optional wx.svg binaries."""
    import wx
    try:
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg, NavigationToolbar2WxAgg
        return FigureCanvasWxAgg, NavigationToolbar2WxAgg
    except (ImportError, ModuleNotFoundError):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.backend_bases import MouseEvent

    class Canvas(wx.Panel, FigureCanvasAgg):
        def __init__(self, parent, identifier, figure):
            wx.Panel.__init__(self,parent,identifier)
            FigureCanvasAgg.__init__(self,figure)
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self._bitmap=None;self._pending=None;self._closed=False;self._drag=None;self._home=[]
            self.Bind(wx.EVT_PAINT,self.paint)
            self.Bind(wx.EVT_SIZE,lambda event:(event.Skip(),self.draw_idle()))
            self.Bind(wx.EVT_WINDOW_DESTROY,self.destroy)
            self.Bind(wx.EVT_MOTION,self.motion)
            self.Bind(wx.EVT_LEFT_DOWN,self.down)
            self.Bind(wx.EVT_LEFT_UP,self.up)
            self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
            self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda event:setattr(self,'_drag',None))

        def destroy(self,event):
            if event.GetEventObject() is self:
                self._closed=True
                if self._pending:self._pending.Stop()
            event.Skip()

        def draw_idle(self,*args,**kwargs):
            if not self._closed and self._pending is None:
                self._pending=wx.CallLater(35,self.draw)

        def draw(self):
            if self._pending:self._pending.Stop();self._pending=None
            if self._closed:return
            width,height=self.GetClientSize()
            if width<2 or height<2:return
            self.figure.set_size_inches(width/self.figure.dpi,height/self.figure.dpi,forward=False)
            FigureCanvasAgg.draw(self)
            buffer=self.buffer_rgba()
            self._bitmap=wx.Bitmap.FromBufferRGBA(buffer.shape[1],buffer.shape[0],bytes(buffer))
            self.Refresh(False)

        def paint(self,event):
            dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('white'));dc.Clear()
            if self._bitmap:dc.DrawBitmap(self._bitmap,0,0)

        def mouse(self,event,name):
            return MouseEvent(name,self,event.GetX(),self.GetClientSize().height-event.GetY(),button=1 if name!='motion_notify_event' else None)

        def down(self,event):
            self._drag=(event.GetPosition(),False)
            self.CaptureMouse()

        def motion(self,event):
            motion=self.mouse(event,'motion_notify_event')
            if self._drag and event.Dragging() and motion.inaxes:
                origin,moved=self._drag
                dx,dy=event.GetX()-origin.x,event.GetY()-origin.y
                axis=motion.inaxes
                if abs(dx)+abs(dy)>3:
                    xlim,ylim=axis.get_xlim(),axis.get_ylim()
                    axis.set_xlim([x-dx*(xlim[1]-xlim[0])/max(1,axis.bbox.width) for x in xlim])
                    axis.set_ylim([y+dy*(ylim[1]-ylim[0])/max(1,axis.bbox.height) for y in ylim])
                    self._drag=(event.GetPosition(),True);self.draw_idle()
            motion._process()

        def up(self,event):
            clicked=self._drag and not self._drag[1]
            self._drag=None
            if self.HasCapture():self.ReleaseMouse()
            if clicked:self.mouse(event,'button_press_event')._process()

        def wheel(self,event):
            point=self.mouse(event,'motion_notify_event')
            if point.inaxes and point.xdata is not None:
                self.zoom(.8 if event.GetWheelRotation()>0 else 1.25,point.inaxes,point.xdata,point.ydata)

        def zoom(self,factor,axis=None,x=None,y=None):
            for target in ([axis] if axis is not None else self.figure.axes[:1]):
                xlim,ylim=target.get_xlim(),target.get_ylim()
                cx=sum(xlim)/2 if x is None else x;cy=sum(ylim)/2 if y is None else y
                target.set_xlim([cx+(v-cx)*factor for v in xlim]);target.set_ylim([cy+(v-cy)*factor for v in ylim])
            self.draw_idle()

    class Toolbar(wx.Panel):
        def __init__(self,canvas):
            super().__init__(canvas.GetParent())
            row=wx.BoxSizer(wx.HORIZONTAL)
            def home():
                for axis,limits in zip(canvas.figure.axes,getattr(canvas,'_home',[])):
                    axis.set_xlim(limits[0]);axis.set_ylim(limits[1])
                canvas.draw_idle()
            for label,operation in [('Fit',home),('Zoom +',lambda:canvas.zoom(.8)),('Zoom −',lambda:canvas.zoom(1.25))]:
                button=wx.Button(self,label=label,style=wx.BU_EXACTFIT)
                button.Bind(wx.EVT_BUTTON,lambda event,action=operation:action())
                row.Add(button,0,wx.RIGHT,5)
            row.Add(wx.StaticText(self,label='Wheel: zoom · drag: pan · click: pin stored sample'),0,wx.ALIGN_CENTER_VERTICAL)
            self.SetSizer(row)

    return Canvas,Toolbar


def create_viewer(parent, loaded):
    """Build a native archive inspector using only the loaded numerical payload."""
    import wx
    from matplotlib.figure import Figure
    FigureCanvasWxAgg, NavigationToolbar2WxAgg = _canvas_types()
    bundle, receipt = loaded['bundle'], loaded['receipt']

    class SavedSimulationWindow(wx.Frame):
        def __init__(self):
            super().__init__(parent, title='Saved simulation • read-only', size=(1080, 780))
            self.bundle, self.receipt = bundle, receipt
            self.specs, self.pins = plot_specs(bundle), []
            self.frame_index = 0
            panel = wx.Panel(self)
            layout = wx.BoxSizer(wx.VERTICAL)
            banner = wx.StaticText(panel, label=binding_text(receipt))
            banner.Wrap(1000)
            banner.SetForegroundColour('#27644b' if receipt.get('source_state') == 'current' else '#8c5120')
            layout.Add(banner, 0, wx.EXPAND | wx.ALL, 10)
            self.book = wx.Notebook(panel)
            graph = wx.Panel(self.book)
            graph_layout = wx.BoxSizer(wx.VERTICAL)
            self.choice = wx.Choice(graph, choices=[s['label'] for s in self.specs])
            if self.specs:
                self.choice.SetSelection(0)
            graph_layout.Add(self.choice, 0, wx.EXPAND | wx.ALL, 6)
            self.figure = Figure(figsize=(8, 4), tight_layout=True)
            self.canvas = FigureCanvasWxAgg(graph, -1, self.figure)
            graph_layout.Add(self.canvas, 1, wx.EXPAND)
            graph_layout.Add(NavigationToolbar2WxAgg(self.canvas), 0, wx.EXPAND)
            self.time = wx.Slider(graph, minValue=0, maxValue=1, value=0)
            self.time_label = wx.StaticText(graph, label='')
            graph_layout.Add(self.time, 0, wx.EXPAND | wx.ALL, 5)
            graph_layout.Add(self.time_label, 0, wx.LEFT | wx.RIGHT, 8)
            self.probe = wx.StaticText(graph, label='Hover for nearest stored sample. Click to pin a probe; saved values are never recalculated.')
            graph_layout.Add(self.probe, 0, wx.EXPAND | wx.ALL, 8)
            self.probes = wx.ListCtrl(graph, style=wx.LC_REPORT)
            for index, label in enumerate(('Plot', 'X', 'Y', 'Stored value', 'Unit', 'Frame')):
                self.probes.InsertColumn(index, label, width=145)
            self.probes.SetMinSize((-1, 100))
            graph_layout.Add(self.probes, 0, wx.EXPAND | wx.ALL, 6)
            graph.SetSizer(graph_layout)
            self.book.AddPage(graph, 'Plots + probes')
            summary = wx.ListCtrl(self.book, style=wx.LC_REPORT)
            summary.InsertColumn(0, 'Result', width=330)
            summary.InsertColumn(1, 'Stored value', width=600)
            def scalar_rows(node, prefix='', depth=0):
                if depth > 3 or not isinstance(node, dict):
                    return
                for key, value in node.items():
                    if summary.GetItemCount()>=200:
                        break
                    name = prefix+str(key)
                    if isinstance(value, dict):
                        scalar_rows(value, name+' / ', depth+1)
                    elif not isinstance(value, list) and summary.GetItemCount() < 200:
                        index = summary.InsertItem(summary.GetItemCount(), name)
                        summary.SetItem(index, 1, 'Unknown' if value is None else str(value))
            scalar_rows(bundle)
            self.book.AddPage(summary, 'Summary (first 200 scalars)')
            self.tree = wx.TreeCtrl(self.book, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT)
            root = self.tree.AddRoot('Complete saved data • expand to inspect every field')
            self.tree.SetItemData(root, bundle)
            self.tree.AppendItem(root, 'Expand…')
            self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.expand_data)
            self.book.AddPage(self.tree, 'Advanced data')
            layout.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
            panel.SetSizer(layout)
            self.choice.Bind(wx.EVT_CHOICE, self.select_plot)
            self.time.Bind(wx.EVT_SLIDER, self.time_changed)
            self.canvas.mpl_connect('motion_notify_event', self.hover)
            self.canvas.mpl_connect('button_press_event', self.pin)
            self.draw()

        def expand_data(self, event):
            item = event.GetItem()
            value = self.tree.GetItemData(item)
            if not isinstance(value, (dict, list, tuple)):
                return
            self.tree.DeleteChildren(item)
            if isinstance(value, tuple):
                container, offset = value
            else:
                container, offset = value, 0
            entries = container.items() if isinstance(container, dict) else enumerate(container)
            for key, child in islice(entries, offset, offset+100):
                text = str(key)+(' · '+str(len(child))+' entries' if isinstance(child, (dict, list)) else ': '+('Unknown' if child is None else str(child)))
                node = self.tree.AppendItem(item, text[:700])
                if isinstance(child, (dict, list)):
                    self.tree.SetItemData(node, child)
                    if child:
                        self.tree.AppendItem(node, 'Expand…')
            if len(container) > offset+100:
                more = self.tree.AppendItem(item, 'Next 100 entries…')
                self.tree.SetItemData(more, (container, offset+100))
                self.tree.AppendItem(more, 'Expand…')

        def current_spec(self):
            return self.specs[max(0, self.choice.GetSelection())] if self.specs else None

        def select_plot(self, event):
            self.frame_index = 0
            self.time.SetValue(0)
            self.draw()

        def time_changed(self, event):
            spec=self.current_spec()
            self.frame_index = min(self.time.GetValue(),len(spec['frames'])-1) if spec and spec['kind']=='frames' else 0
            self.draw()

        def draw(self):
            try:
                self.draw_saved()
            except (ValueError,TypeError,IndexError,KeyError,OverflowError) as error:
                self.figure.clear()
                axis=self.figure.add_subplot(111)
                axis.text(.5,.5,'Stored plot could not be displayed:\n'+str(error)+'\nComplete data remains in Advanced data.',ha='center',va='center',wrap=True,transform=axis.transAxes)
                self.canvas.draw_idle()

        def draw_saved(self):
            import numpy as np
            self.figure.clear()
            axis = self.figure.add_subplot(111)
            spec = self.current_spec()
            self.probe_spec=spec
            self.time.Hide()
            self.time_label.Hide()
            if spec is None:
                axis.text(.5, .5, 'No specialized plot for this saved mode.\nComplete results are retained in Summary and Advanced data.', ha='center', va='center', transform=axis.transAxes)
            elif spec['kind']=='unavailable':
                axis.text(.5,.5,spec['reason'],ha='center',va='center',wrap=True,transform=axis.transAxes)
            elif spec['kind'] in ('grid', 'frames'):
                values = frame_grid(spec, self.frame_index)
                self.probe_spec=dict(kind='grid',x=spec['x'],y=spec['y'],values=values,unit=spec['unit'])
                field = np.array([[float('nan') if v is None else v for v in row] for row in values])
                image = axis.pcolormesh(spec['x'], spec['y'], np.ma.masked_invalid(field), shading='nearest')
                self.figure.colorbar(image, ax=axis, label=spec['unit'])
                axis.set_xlabel('Saved X (mm)');axis.set_ylabel('Saved Y (mm)');axis.set_aspect('equal')
                if spec['kind'] == 'frames':
                    self.time.SetRange(0, max(1, len(spec['frames'])-1))
                    self.time.Show();self.time_label.Show()
                    self.time_label.SetLabel('Stored frame '+str(self.frame_index+1)+' / '+str(len(spec['frames']))+' · t = '+str(spec['frames'][self.frame_index]['time_s'])+' s')
            elif spec['kind'] == 'points':
                values = [float('nan') if value is None else value for value in spec['values']]
                image = axis.scatter(spec['x'], spec['y'], c=np.ma.masked_invalid(values), s=16)
                self.figure.colorbar(image, ax=axis, label=spec['unit'])
                axis.set_xlabel('Saved X (mm) · selected stored elevation only');axis.set_ylabel('Saved Y (mm)');axis.set_aspect('equal')
            elif spec['kind'] == 'eye':
                for values in spec['values']:
                    axis.plot(spec['x'], values, color='#178b91', alpha=.12, linewidth=.8)
                axis.set_xlabel('Time (UI)');axis.set_ylabel('Voltage (V)')
            else:
                axis.plot(spec['x'], [float('nan') if value is None else value for value in spec['values']], marker='.', color='#087f8c')
                axis.set_xlabel(spec.get('axis', 'Sample'));axis.set_ylabel(spec['unit']);axis.grid(alpha=.2)
            if spec:
                axis.set_title(spec['label'])
            self.canvas._home=[(axis.get_xlim(),axis.get_ylim()) for axis in self.figure.axes]
            self.canvas.draw_idle()
            self.book.GetPage(0).Layout()

        def sampled(self, event):
            spec = self.current_spec()
            if spec is None or event.inaxes not in self.figure.axes[:1] or event.xdata is None:
                return None
            try:
                return probe_sample(getattr(self,'probe_spec',spec), event.xdata, event.ydata, frame=self.frame_index)
            except (ValueError,TypeError,IndexError,KeyError) as error:
                self.probe.SetLabel('Stored probe unavailable: '+str(error))
                return None

        def hover(self, event):
            now=time.monotonic()
            if now-getattr(self,'_last_hover',0)<.08:
                return
            self._last_hover=now
            value = self.sampled(event)
            if value:
                self.probe.SetLabel('Nearest stored sample: '+('Ambiguous overlapping samples' if value.get('ambiguous') else 'Unknown' if value['value'] is None else str(value['value']))+' '+value['unit']+' · click to pin')

        def pin(self, event):
            value = self.sampled(event)
            if value and event.button == 1:
                index = self.probes.InsertItem(self.probes.GetItemCount(), self.current_spec()['label'])
                for column, key in enumerate(('x', 'y', 'value', 'unit'), 1):
                    self.probes.SetItem(index, column, str(value.get(key, '—')))
                self.probes.SetItem(index, 5, str(self.frame_index))
                self.pins.append(dict(value, plot=self.current_spec()['label'], frame=self.frame_index))

    return SavedSimulationWindow()


class ProjectResultActions:
    """Small native project-library controller shared by the three quick tools."""
    def __init__(self, owner, parent, sizer, plugin, board_path, bundles, *, certify=True, status=None, module_file=None):
        import wx
        self.owner, self.plugin = owner, plugin
        self.project_root = Path(board_path).resolve().parent
        self.board_path, self.bundles, self.certify = Path(board_path).resolve(), bundles, certify
        self.status = status or (lambda text: None)
        self.module_file = module_file
        self.busy = False
        row = wx.WrapSizer(wx.HORIZONTAL)
        self.save = wx.Button(parent, label='Save simulation…')
        self.load = wx.Button(parent, label='Load simulation…')
        self.save.SetToolTip('Keep complete computed values in this project’s .wayricad/results library')
        self.load.SetToolTip('Open saved numerical results read-only, without running a solver')
        self.save.Bind(wx.EVT_BUTTON, self.on_save)
        self.load.Bind(wx.EVT_BUTTON, self.on_load)
        row.Add(self.save, 0, wx.RIGHT | wx.BOTTOM, 5)
        row.Add(self.load, 0, wx.BOTTOM, 5)
        sizer.Add(row, 0, wx.EXPAND | wx.TOP, 5)

    def task(self, operation, completed):
        import wx
        if self.busy:
            return
        self.busy = True
        self.save.Disable();self.load.Disable()
        # Freeze the active numerical snapshot against live-current interactions;
        # the worker still permits normal native painting and window movement.
        was_enabled = self.owner.IsEnabled()
        self.owner.Disable()
        def deliver(answer, error):
            self.busy = False
            if not self.owner or self.owner.IsBeingDeleted():
                return
            self.owner.Enable(was_enabled);self.save.Enable();self.load.Enable()
            if error:
                self.status(str(error))
                wx.MessageBox(str(error), 'Simulation library', wx.OK | wx.ICON_WARNING, self.owner)
            else:
                completed(answer)
        def work():
            answer = error = None
            try:
                answer = operation()
            except Exception as caught:
                error = caught
            wx.CallAfter(deliver, answer, error)
        threading.Thread(target=work, daemon=True, name='WayriCAD saved simulation').start()

    def available(self):
        return [(label, bundle) for label, bundle in self.bundles() if isinstance(bundle, dict) and bundle]

    def on_save(self, event=None):
        import wx
        if self.busy or getattr(self.owner, '_busy', False) or getattr(self.owner, '_circuit_busy', False) or getattr(self.owner, '_live_running', False) or getattr(self.owner, '_live_pending', None) is not None:
            self.status('Wait for the current analysis before saving its completed data.')
            return
        options = self.available()
        if not options:
            self.status('Run a simulation first; there are no completed numerical results to save.')
            return
        index = 0
        if len(options) > 1:
            with wx.SingleChoiceDialog(self.owner, 'Which completed simulation should be retained?', 'Save simulation', [label for label, bundle in options]) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                index = dialog.GetSelection()
        label, bundle = options[index]
        self.status('Saving complete simulation in the project library…')
        def save():
            from .project_results import save_result
            from .pocket_report import evidence_context, producer_version
            evidence = None
            if self.certify:
                evidence = evidence_context(bundle, tool=self.plugin, board_path=self.board_path,
                    version=producer_version(module_file=self.module_file))
            return save_result(self.project_root, self.plugin, bundle, pocket_kivi=evidence,
                               version=producer_version(module_file=self.module_file))
        self.task(save, lambda receipt: self.status('Saved '+label+': '+receipt['relative_path']))

    def on_load(self, event=None):
        import wx
        from .project_results import load_result
        if self.busy or getattr(self.owner, '_busy', False):
            return
        # Choose one immutable JSON; do not parse every full record merely to
        # open the library. A large archive remains proportional to one load.
        directory=self.project_root/'.wayricad'/'results'/self.plugin
        with wx.FileDialog(self.owner,'Load simulation • read-only',defaultDir=str(directory),
                           wildcard='Saved simulation JSON (*.json)|*.json',
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:
                return
            path=dialog.GetPath()
        self.status('Loading the selected saved simulation without solving…')
        def show(loaded):
            viewer=create_viewer(self.owner,loaded)
            viewer.Show()
            self.status(binding_text(loaded['receipt']))
        self.task(lambda:load_result(self.project_root,path,plugin=self.plugin),show)


def add_project_results(owner, parent, sizer, plugin, board_path, bundles, *, certify=True, status=None, module_file=None):
    return ProjectResultActions(owner, parent, sizer, plugin, board_path, bundles, certify=certify, status=status, module_file=module_file)


def add_study_results(dialog, plugin, board_path):
    """Attach archive actions to a supported existing modal study's actual result."""
    if getattr(dialog, '_project_result_actions', None) is not None:
        return
    status = getattr(dialog, 'status', None)
    dialog._project_result_actions = add_project_results(dialog, dialog, dialog.GetSizer(), plugin,
        board_path, lambda: [('Completed study', getattr(dialog, 'result', None))], certify=False,
        status=status.SetLabel if status is not None else None,
        module_file=__import__('sys').modules[dialog.__class__.__module__].__file__)
    dialog.Layout()
