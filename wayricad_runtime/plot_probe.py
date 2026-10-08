"""Native Matplotlib exact-sample hover and persistent click probes."""
import math


def attach_probes(canvas, axes, rows, unit='', polygons=None, on_select=None):
    """Attach [x,y,value,label,z] samples; polygon cells require containment.

    Returns a controller holding probe artists and a disconnect method. In 3D,
    samples are picked by their current projected screen positions. No values
    are interpolated across missing cells, holes or disconnected conductors.
    """
    from matplotlib.path import Path
    from mpl_toolkits.mplot3d import proj3d
    state={'rows':rows,'probes':[],'ids':[],'press':None}
    paths=[Path(poly) for poly in polygons] if polygons is not None else None
    bounds=[(min(p[0] for p in poly),max(p[0] for p in poly),min(p[1] for p in poly),max(p[1] for p in poly)) for poly in polygons] if polygons is not None else None
    tip=axes.annotate('',xy=(0,0),xycoords='axes fraction',xytext=(.02,.98),
                      textcoords='axes fraction',va='top',bbox={'facecolor':'white','alpha':.9})
    tip.set_visible(False)
    def pick(event):
        if event.inaxes is not axes:return None
        if polygons is not None:
            if event.xdata is None or event.ydata is None:return None
            for row,path,b in zip(rows,paths,bounds):
                if b[0]<=event.xdata<=b[1] and b[2]<=event.ydata<=b[3] and path.contains_point((event.xdata,event.ydata)):return row
            return None
        best=None;distance=12
        for row in rows:
            if not all(math.isfinite(float(v)) for v in row[:2]):continue
            if hasattr(axes,'get_proj'):
                x,y,_=proj3d.proj_transform(row[0],row[1],row[4] if len(row)>4 else 0,axes.get_proj())
            else:x,y=row[:2]
            sx,sy=axes.transData.transform((x,y));d=math.hypot(event.x-sx,event.y-sy)
            if d<distance:distance=d;best=row
        return best
    def text(row):
        value=row[2]
        result=f'{float(value):.7g} {unit}' if value is not None and math.isfinite(float(value)) else 'Unknown'
        return str(row[3])+' | '+result
    def motion(event):
        row=pick(event);tip.set_visible(row is not None)
        if row is not None:tip.set_text(text(row))
        canvas.draw_idle()
    def clear():
        for artist in state['probes']:artist.remove()
        state['probes'].clear();canvas.draw_idle()
    state['clear']=clear
    def press(event):
        state['press']=(event.x,event.y) if event.button==1 else None
        if event.button==3 and event.key=='control':clear()
    def release(event):
        start=state['press'];state['press']=None
        if start is not None and math.hypot(event.x-start[0],event.y-start[1])<4:click(event)
    def click(event):
        if event.button!=1 or getattr(getattr(canvas,'toolbar',None),'mode',''):return
        row=pick(event)
        if row is None:return
        if on_select:on_select(row)
        if row[2] is None or not math.isfinite(float(row[2])):return
        index=len(state['probes'])+1
        if hasattr(axes,'get_proj'):
            artist=axes.text(row[0],row[1],row[4] if len(row)>4 else 0,f'P{index}: '+text(row),fontsize=8)
        else:
            artist=axes.annotate(f'P{index}: '+text(row),row[:2],xytext=(8,8),textcoords='offset points',fontsize=8,
                                 bbox={'facecolor':'white','alpha':.85})
        state['probes'].append(artist);canvas.draw_idle()
    def scroll(event):
        if event.inaxes is not axes or not hasattr(axes,'get_proj'):return
        factor=.85 if event.button=='up' else 1/.85
        for getter,setter in ((axes.get_xlim,axes.set_xlim),(axes.get_ylim,axes.set_ylim),(axes.get_zlim,axes.set_zlim)):
            low,high=getter();mid=(low+high)/2;half=(high-low)*factor/2;setter(mid-half,mid+half)
        canvas.draw_idle()
    state['ids']=[canvas.mpl_connect('scroll_event',scroll),canvas.mpl_connect('motion_notify_event',motion),canvas.mpl_connect('button_press_event',press),canvas.mpl_connect('button_release_event',release)]
    state['disconnect']=lambda:[canvas.mpl_disconnect(cid) for cid in state['ids']]
    return state
