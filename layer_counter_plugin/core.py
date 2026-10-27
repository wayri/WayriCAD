"""Native copper layer markers and reversible, explicit group insertion.

Dimensions use millimetres. Physical layer numbers follow the enabled copper
stack, including when KiCad's numeric layer IDs are not sequential.
"""
from dataclasses import dataclass
import hashlib
import math
import re

STYLES = {
    'row': 'Horizontal ladder', 'column': 'Vertical ladder',
    'staircase': 'Staircase', 'zigzag': 'Staggered / zigzag',
    'circle': 'Circular cells', 'square': 'Square cells',
    'rectangle': 'Rectangular cells', 'diamond': 'Diamond cells',
    'octagon': 'Octagonal cells', 'bar': 'Bars with labels',
    'core-mirrored': 'Core pairs - mirrored',
    'core-overlap': 'Core pairs - overlapping',
    'two-row': 'Two-row layer bank', 'serpentine': 'Serpentine grid',
    'radial': 'Radial layer ring', 'triangle': 'Triangular cells',
    'pentagon': 'Pentagonal cells', 'hexagon': 'Hexagonal cells',
    'chevron': 'Chevron cells', 'capsule': 'Capsule cells',
    'double-circle': 'Double-ring cells', 'brackets': 'Corner brackets',
    'crosshair': 'Crosshair labels', 'ruler': 'Ruler / tick labels',
}
MIRROR_MODES = {
    'lower-half': 'Lower half of physical stack',
    'bottom-only': 'Bottom copper only (legacy)',
    'core-faces': 'Second face of each explicit core pair',
    'none': 'No mirroring',
}


def copper_layers(board, api):
    """Return (native ID, name, physical L-number) in front-to-back order."""
    return [(int(layer), board.GetLayerName(layer), number)
            for number, layer in enumerate(board.GetEnabledLayers().CuStack(), 1)]


def defaults(board, api):
    layers = copper_layers(board, api)
    pairs = ','.join(f'L{a[2]}/L{b[2]}' for a, b in zip(layers[::2], layers[1::2]))
    return dict(style='row', layers=[row[0] for row in layers], x=10., y=10.,
                size=1., stroke=.2, pitch=4., margin=.5,
                mirror_bottom=True, mirror_mode='lower-half', core_pairs=pairs)


def fingerprint(board, api):
    """Hash native serialization without changing the board or saving a file."""
    output = api.STRING_FORMATTER()
    api.PCB_IO_KICAD_SEXPR().FormatBoardToFormatter(output, board)
    return hashlib.sha256(output.GetString().encode('utf-8')).hexdigest()


def _board_identity(board):
    """Unwrap native/SWIG proxies; KiCad 10 may nest BOARD wrappers."""
    pointer=board
    for _ in range(8):
        try:return int(pointer)
        except (TypeError,ValueError):pointer=getattr(pointer,'this',None)
        if pointer is None:break
    raise ValueError('Cannot identify the originating native board.')


def _uid(item):
    return item.m_Uuid.AsString()


def _members(board):
    return {str(_uid(item)): item for getter in
            (board.GetDrawings, board.GetTracks, board.GetFootprints, board.Zones, board.Groups)
            for item in getter()}


def _pairs(value, numbers):
    pairs = []
    for entry in value.split(','):
        match = re.fullmatch(r'\s*L?(\d+)\s*/\s*L?(\d+)\s*', entry, re.I)
        if match is None:
            raise ValueError('Core pairs use physical numbers, for example L1/L2,L3/L4.')
        a, b = map(int, match.groups())
        if a >= b or b != a+1:
            raise ValueError('Each core pair must name adjacent physical layers, front side first.')
        pairs.append((a, b))
    flat = [n for pair in pairs for n in pair]
    if len(flat) != len(set(flat)) or set(flat) != set(numbers):
        raise ValueError('Core pairs must cover every selected layer exactly once, without duplicates.')
    return sorted(pairs)


@dataclass
class Plan:
    settings: dict
    labels: list
    shapes: list
    keepouts: list
    bounds: tuple
    items: list
    source_fingerprint: str
    board_identity: int
    geometry_fingerprint: str
    group_name: str


def _item_fingerprint(items, api):
    """Use a temporary native board so all item-specific properties are checked."""
    # Item clones remain independent of both the source board and the preview.
    temporary = api.BOARD()
    temporary.SetCopperLayerCount(32)
    for item in items:
        clone = api.Cast_to_BOARD_ITEM(item.Clone())
        temporary.Add(clone)
    return fingerprint(temporary, api)


def plan(board, api, settings=None):
    """Build detached text, copper outlines and a zone-only keepout for review.

    ``layers`` are native layer IDs, not physical numbers. Core pair strings use
    physical L-numbers. No pad/net/schematic objects are created or changed.
    """
    source = fingerprint(board, api)
    options = defaults(board, api)
    if settings:
        unknown = set(settings)-set(options)
        if unknown:
            raise ValueError('Unknown settings: '+', '.join(sorted(unknown)))
        options.update(settings)
        if 'mirror_mode' not in settings and 'mirror_bottom' in settings:
            options['mirror_mode'] = 'bottom-only' if settings['mirror_bottom'] else 'none'
        if ('mirror_mode' in settings and 'mirror_bottom' in settings and
                settings['mirror_bottom'] != (settings['mirror_mode'] != 'none')):
            raise ValueError('Conflicting mirror_mode and legacy mirror_bottom settings.')
    if options['style'] not in STYLES:
        raise ValueError('Choose a supported layer-counter style.')
    for key in ('x', 'y', 'size', 'stroke', 'pitch', 'margin'):
        value = options[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key+' must be a finite number.')
        if key not in ('x', 'y') and not .01 <= value <= 100:
            raise ValueError(key+' must be between 0.01 and 100 mm.')
        if abs(value) > 10000:
            raise ValueError('Coordinates must be within 10,000 mm of the origin.')
    if options['stroke'] > options['size']/4:
        raise ValueError('Text height must be at least four times the stroke.')
    if not isinstance(options['mirror_bottom'], bool) or not isinstance(options['core_pairs'], str):
        raise ValueError('Invalid mirroring or core-pair setting.')
    if not isinstance(options['mirror_mode'], str) or options['mirror_mode'] not in MIRROR_MODES:
        raise ValueError('Choose a supported text mirroring mode.')
    options['mirror_bottom'] = options['mirror_mode'] != 'none'
    available = copper_layers(board, api)
    selected = options['layers']
    if not isinstance(selected, (list, tuple)) or not selected or any(type(x) is not int for x in selected):
        raise ValueError('Select at least one enabled copper layer.')
    if len(selected) != len(set(selected)) or set(selected)-{row[0] for row in available}:
        raise ValueError('Selected layers must be distinct enabled copper layers.')
    rows = [row for row in available if row[0] in selected]
    options['layers'] = [row[0] for row in rows]
    pairs = _pairs(options['core_pairs'], [row[2] for row in rows]) if (
        options['style'].startswith('core-') or options['mirror_mode']=='core-faces') else []
    size, stroke = options['size'], options['stroke']
    x0, y0 = options['x'], options['y']
    # Enough room for L32 plus a surrounding frame; caller pitch is a minimum.
    framed = options['style'] in ('circle','square','rectangle','diamond','octagon','bar',
                                  'triangle','pentagon','hexagon','chevron','capsule',
                                  'double-circle','brackets','crosshair','ruler')
    scale = (6.5 if options['style'] in ('circle','square','rectangle','diamond','octagon','bar') else 9) if framed else 4
    pitch = max(options['pitch'], size*scale+stroke*2)
    # Native VECTOR2I coordinates are signed 32-bit nanometres. Reject oversized
    # counters before constructing any geometry instead of overflowing a binding.
    envelope_limit=(len(rows)+1)*pitch*2+size*8+options['margin']
    if max(abs(x0),abs(y0))+envelope_limit>2000:
        raise ValueError('Counter exceeds the native coordinate range; reduce size, pitch or position.')
    labels, shapes, items = [], [], []
    vector = lambda x,y: api.VECTOR2I(api.FromMM(x), api.FromMM(y))
    style = options['style']
    pair_by_number = {number: (index, side) for index, pair in enumerate(pairs) for side, number in enumerate(pair)}
    for index, (layer, name, number) in enumerate(rows):
        x, y = x0+index*pitch, y0
        mode = options['mirror_mode']
        mirror = (number > (len(available)+1)//2 if mode == 'lower-half' else
                  layer == api.B_Cu if mode == 'bottom-only' else
                  bool(pair_by_number[number][1]) if mode == 'core-faces' else False)
        if style == 'column': x, y = x0, y0+index*pitch
        elif style == 'staircase': y = y0+index*pitch*.6
        elif style == 'zigzag': y = y0+(index%2)*pitch*.65
        elif style == 'two-row':
            columns = (len(rows)+1)//2
            x, y = x0+(index%columns)*pitch, y0+(index//columns)*pitch
        elif style == 'serpentine':
            columns = math.ceil(math.sqrt(len(rows)))
            row, column = divmod(index, columns)
            x, y = x0+(columns-1-column if row%2 else column)*pitch, y0+row*pitch
        elif style == 'radial':
            angle = -math.pi/2+index*2*math.pi/len(rows)
            radius = max(pitch, pitch*len(rows)/(2*math.pi))
            x, y = x0+radius*math.cos(angle), y0+radius*math.sin(angle)
        elif style.startswith('core-'):
            pair_index, side = pair_by_number[number]
            x, y = x0+pair_index*pitch*2, y0
            if style == 'core-mirrored':
                x += (-.5 if side == 0 else .5)*pitch
        text = api.PCB_TEXT(board)
        text.SetText('L'+str(number)); text.SetPosition(vector(x,y))
        text.SetLayer(layer); text.SetTextSize(vector(size,size)); text.SetTextThickness(api.FromMM(stroke))
        text.SetMirrored(mirror)
        items.append(text)
        labels.append(dict(text='L'+str(number), layer=layer, name=name, x=x, y=y, mirror=mirror))
        def line(a,b):
            shape=api.PCB_SHAPE(board);shape.SetShape(api.SHAPE_T_SEGMENT);shape.SetLayer(layer)
            shape.SetWidth(api.FromMM(stroke));shape.SetStart(vector(*a));shape.SetEnd(vector(*b));items.append(shape)
            shapes.append(dict(kind='line',layer=layer,x1=a[0],y1=a[1],x2=b[0],y2=b[1],width=stroke))
        def polygon(points):
            for a,b in zip(points,points[1:]+points[:1]):line(a,b)
        box=text.GetBoundingBox()
        rx=max(abs(api.ToMM(box.GetLeft())-x),abs(api.ToMM(box.GetRight())-x))+stroke+size*.25
        ry=max(abs(api.ToMM(box.GetTop())-y),abs(api.ToMM(box.GetBottom())-y))+stroke+size*.25
        if style in ('circle','double-circle'):
            radius=math.hypot(rx,ry)+size*.25
            radii=[radius] if style=='circle' else [radius, radius+size*.4+stroke]
            for radius in radii:
                shape=api.PCB_SHAPE(board);shape.SetShape(api.SHAPE_T_CIRCLE);shape.SetLayer(layer)
                shape.SetWidth(api.FromMM(stroke));shape.SetStart(vector(x,y));shape.SetEnd(vector(x+radius,y));items.append(shape)
                shapes.append(dict(kind='circle',layer=layer,x=x,y=y,r=radius,width=stroke))
        elif style in ('square','rectangle'):
            if style == 'square':rx=ry=max(rx,ry)
            polygon([(x-rx,y-ry),(x+rx,y-ry),(x+rx,y+ry),(x-rx,y+ry)])
        elif style in ('diamond','octagon'):
            sides = 4 if style == 'diamond' else 8
            radius = rx+ry+size*.2 if style=='diamond' else math.hypot(rx,ry)*1.2
            polygon([(x+radius*math.cos(i*2*math.pi/sides),y+radius*math.sin(i*2*math.pi/sides)) for i in range(sides)])
        elif style == 'bar':
            polygon([(x-rx,y+ry),(x+rx,y+ry),(x+rx,y+ry+stroke*2),(x-rx,y+ry+stroke*2)])
        elif style in ('triangle','pentagon','hexagon'):
            sides={'triangle':3,'pentagon':5,'hexagon':6}[style]
            radius=(math.hypot(rx,ry)+size*.1)/math.cos(math.pi/sides)
            offset=0 if sides==6 else -math.pi/2
            polygon([(x+radius*math.cos(offset+i*2*math.pi/sides),
                      y+radius*math.sin(offset+i*2*math.pi/sides)) for i in range(sides)])
        elif style == 'chevron':
            pad=size*.5+stroke
            polygon([(x-rx-pad,y-ry),(x+rx+pad,y-ry),(x+rx+2*pad,y),
                     (x+rx+pad,y+ry),(x-rx-pad,y+ry),(x-rx,y)])
        elif style == 'capsule':
            points=[]
            for center, start in [(x+rx,-math.pi/2),(x-rx,math.pi/2)]:
                points.extend([(center+ry*math.cos(start+i*math.pi/16),
                                y+ry*math.sin(start+i*math.pi/16)) for i in range(17)])
            polygon(points)
        elif style == 'brackets':
            for sx in (-1,1):
                for sy in (-1,1):
                    corner=(x+sx*rx,y+sy*ry)
                    line(corner,(corner[0]-sx*rx*.4,corner[1]))
                    line(corner,(corner[0],corner[1]-sy*ry*.4))
        elif style == 'crosshair':
            pad=size*.7+stroke
            for sign in (-1,1):
                line((x+sign*rx,y),(x+sign*(rx+pad),y))
                line((x,y+sign*ry),(x,y+sign*(ry+pad)))
        elif style == 'ruler':
            line((x-rx,y+ry),(x+rx,y+ry))
            for step in range(5):
                tick=x-rx+step*rx*.5
                height=size*(.5 if step in (0,4) else .3)
                line((tick,y+ry-height),(tick,y+ry+height))
    # Include actual native glyph and outline bounds, not estimated text widths.
    bounds = items[0].GetBoundingBox()
    for item in items[1:]:bounds.Merge(item.GetBoundingBox())
    margin=api.FromMM(options['margin'])
    bounds.Inflate(margin)
    left,top,right,bottom = (api.ToMM(v) for v in (bounds.GetLeft(),bounds.GetTop(),bounds.GetRight(),bounds.GetBottom()))
    zone=api.ZONE(board);zone.SetIsRuleArea(True)
    zone.SetZoneName('WayriCAD layer counter - zones only')
    layer_set=api.LSET()
    for layer,_,_ in rows:layer_set.AddLayer(layer)
    zone.SetLayerSet(layer_set)
    for method in ('SetDoNotAllowTracks','SetDoNotAllowVias','SetDoNotAllowPads','SetDoNotAllowFootprints'):
        getattr(zone,method)(False)
    zone.SetDoNotAllowZoneFills(True)
    outline=zone.Outline();outline.NewOutline()
    for x,y in ((left,top),(right,top),(right,bottom),(left,bottom)):outline.Append(api.FromMM(x),api.FromMM(y))
    items.append(zone)
    existing_names={g.GetName() for g in board.Groups()}
    name='WayriCAD Layer Counter';suffix=1
    while name in existing_names:
        suffix+=1;name='WayriCAD Layer Counter '+str(suffix)
    if fingerprint(board,api)!=source:
        raise ValueError('Board changed while generating the counter; preview again.')
    return Plan(options, labels, shapes, [dict(layer=layer,bounds=(left,top,right,bottom)) for layer,_,_ in rows],
                (left,top,right,bottom), items,source,_board_identity(board),_item_fingerprint(items,api),name)


class Transaction:
    """Own only new items; source changes reject Apply, Undo and Redo."""
    def __init__(self, board, api, preview):
        if _board_identity(board)!=preview.board_identity:
            raise ValueError('Preview belongs to another board; generate it again in the target editor.')
        self.board,self.api,self.preview=board,api,preview
        self.expected=preview.source_fingerprint
        self.group=api.PCB_GROUP(board);self.group.SetName(preview.group_name)
        self.applied=False

    def _check(self):
        if fingerprint(self.board,self.api)!=self.expected:
            raise ValueError('Board changed; preview again. Existing edits were preserved.')

    def _presence(self,item,present):
        current=str(_uid(item)) in _members(self.board)
        if current!=present:
            (self.board.Add if present else self.board.Remove)(item)
        if (str(_uid(item)) in _members(self.board))!=present:
            raise RuntimeError('Native board insertion/removal did not complete.')

    def _set(self,present):
        # Snapshot all relationships first. Restore them even if a native call
        # mutates the board before raising an exception.
        rows=[(item,str(_uid(item)) in _members(self.board),
               item.GetParentGroupId().AsString()==_uid(self.group)) for item in self.preview.items]
        group_present=str(_uid(self.group)) in _members(self.board)
        try:
            if present:self._presence(self.group,True)
            for item,_,_ in rows:
                if present:
                    self._presence(item,True)
                    self.group.AddItem(item)
                    if item.GetParentGroupId().AsString()!=_uid(self.group):raise RuntimeError('Counter group membership was not added.')
                else:
                    self.group.RemoveItem(item)
                    if item.GetParentGroupId().AsString()==_uid(self.group):raise RuntimeError('Counter group membership was not removed.')
                    self._presence(item,False)
            if not present:self._presence(self.group,False)
        except Exception as original:
            try:
                if group_present:self._presence(self.group,True)
                for item,was_present,was_member in reversed(rows):
                    if item.GetParentGroupId().AsString()==_uid(self.group):self.group.RemoveItem(item)
                    self._presence(item,was_present)
                    if was_member:self.group.AddItem(item)
                self._presence(self.group,group_present)
            except Exception as recovery:
                raise RuntimeError('Counter edit failed and rollback needs inspection: '+str(recovery)) from original
            raise

    def redo(self):
        self._check()
        if self.applied:return
        if _item_fingerprint(self.preview.items,self.api)!=self.preview.geometry_fingerprint:
            raise ValueError('Counter preview geometry changed; preview again.')
        self._set(True);self.applied=True;self.expected=fingerprint(self.board,self.api)

    def undo(self):
        self._check()
        if not self.applied:return
        self._set(False);self.applied=False;self.expected=fingerprint(self.board,self.api)


def apply(board,api,preview):
    transaction=Transaction(board,api,preview)
    transaction.redo()
    return transaction
