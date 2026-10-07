"""PCB composition using rigid XY translations and explicit identity/net maps."""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
import copy
import math
from pathlib import Path

from . import sexpr as sx
from .model import MergeError
from .layers import apply_stack_header, remap_item, verify_layers
from .schematic import new_uuid, canonical_path, pcb_association_path, namespace_text, remap_footprint_id

HEADER={'kicad_pcb','version','generator','generator_version','general','paper','title_block','layers','setup','net','property','embedded_fonts','embedded_files','variants','variant'}
ITEMS={'footprint','segment','arc','via','zone','group','gr_line','gr_arc','gr_circle','gr_rect','gr_poly',
       'gr_text','gr_text_box','gr_curve','dimension','target','image','point'}


def fp_reference(fp):
    ref=sx.propval(fp,'Reference')
    if ref:
        return ref
    return next((str(n[2]) for n in sx.children(fp,'fp_text') if len(n)>2 and n[1]=='reference'),'')


def net_table(board):
    return {str(n[1]):str(n[2]) for n in sx.children(board,'net') if len(n)>2}


def net_name(item,table):
    n=sx.child(item,'net')
    if n is None:
        return ''
    if len(n)>2:
        return str(n[2])
    if len(n)==2:
        return str(n[1]) if isinstance(n[1],sx.Quoted) else table.get(str(n[1]),'')
    raise MergeError('Unrecognized net assignment in source PCB.')


def prepare_board(source):
    board=sx.load(source.pcb_file, source.hashes)
    if sx.tag(board)!='kicad_pcb':
        raise MergeError(f'{source.alias}: invalid board file.')
    for n in sx.children(board):
        if sx.tag(n) not in HEADER|ITEMS:
            raise MergeError(f'{source.alias}: board object {sx.tag(n)!r} is not yet supported. Live tuning generators/design-block metadata are not silently discarded.')
    ids=sx.declared_uuids(board)
    if len(set(ids))!=len(ids):
        raise MergeError(f'{source.alias}: duplicate PCB UUIDs.')
    refs=set()
    linked=set()
    for fp in sx.children(board,'footprint'):
        ref=fp_reference(fp)
        if not ref or ref in refs:
            raise MergeError(f'{source.alias}: missing or duplicate PCB reference {ref!r}.')
        refs.add(ref)
        path=sx.value(fp,'path')
        attr=sx.child(fp,'attr',[])
        board_only='board_only' in [x for x in attr if isinstance(x,str)]
        if path and not board_only:
            record=source.link_map.get(canonical_path(path))
            if record is None:
                raise MergeError(f'{source.alias}: {ref} points to unknown schematic UUID path {path}. Update/synchronize the source first; reference-only relinking is never used.')
            if record.old_ref!=ref:
                raise MergeError(f'{source.alias}: footprint {ref} is linked to schematic {record.old_ref}; source is out of sync.')
            if ref in linked:
                raise MergeError(f'{source.alias}: multiple footprints linked to {ref}.')
            linked.add(ref)
            source.footprint_links[sx.value(fp,'uuid') or sx.value(fp,'tstamp')]=record
            from .variants import synchronize_footprint
            synchronize_footprint(fp,record,source)
        elif board_only:
            if ref in {r.old_ref for r in source.symbols}:
                raise MergeError(f'{source.alias}: board-only {ref} clashes with a schematic component.')
            source.board_ref_map[ref]=''
        else:
            raise MergeError(f'{source.alias}: footprint {ref} has no schematic path. Mark truly mechanical items Board Only, or synchronize the source first.')
    for r in source.symbols:
        from .variants import effective_board_flags
        physical=effective_board_flags(r)['on_board']=='yes' and bool(sx.propval(r.node,'Footprint')) and not r.old_ref.startswith('#')
        if physical and r.old_ref not in linked:
            raise MergeError(f'{source.alias}: schematic {r.old_ref} has a footprint assignment but no linked PCB footprint.')
    sx.remove(board,'variant'); sx.remove(board,'variants')
    source.board=board
    source.bbox=board_bounds(board)


def number(n):
    try:
        v=float(n)
    except (ValueError,TypeError) as e:
        raise MergeError(f'Invalid geometry coordinate: {n!r}') from e
    if not math.isfinite(v):
        raise MergeError('Non-finite geometry coordinate.')
    return v


def board_bounds(board):
    points=[]
    edge_found=False
    for n in sx.children(board):
        t=sx.tag(n)
        if t=='footprint':
            # Footprint pads use local coordinates. Pad radius gives a
            # conservative bound, including rotated/back-side footprints.
            at=sx.child(n,'at')
            if at is None:
                raise MergeError('A footprint has no board position.')
            x,y=map(number,at[1:3])
            theta=math.radians(number(at[3]) if len(at)>3 else 0)
            for pad in sx.children(n,'pad'):
                a=sx.child(pad,'at',['at','0','0'])
                u,v=map(number,a[1:3])
                # KiCad footprint local placement axes are rotated clockwise.
                px=x+u*math.cos(theta)+v*math.sin(theta)
                py=y-u*math.sin(theta)+v*math.cos(theta)
                sz=sx.child(pad,'size',['size','0','0'])
                r=math.hypot(number(sz[1]),number(sz[2]))/2
                points.extend(((px-r,py-r),(px+r,py+r)))
            continue
        if sx.value(n,'layer')=='Edge.Cuts':
            edge_found=True
        if t not in ITEMS or t=='group':
            continue
        coords=[]
        for sub in sx.walk(n):
            if sx.tag(sub) in {'at','start','mid','end','center','xy'} and len(sub)>=3:
                coords.append((number(sub[1]),number(sub[2])))
        points.extend(coords)
        if t=='gr_circle':
            c=sx.child(n,'center'); e=sx.child(n,'end')
            if c and e:
                x,y=number(c[1]),number(c[2]); r=math.hypot(number(e[1])-x,number(e[2])-y)
                points.extend(((x-r,y-r),(x+r,y+r)))
        if t in {'gr_arc','arc'}:
            a,b,c=(sx.child(n,key) for key in ('start','mid','end'))
            if a and b and c:
                ax,ay=map(number,a[1:3]); bx,by=map(number,b[1:3]); cx,cy=map(number,c[1:3])
                d=2*(ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
                if abs(d)>1e-12:
                    ux=((ax*ax+ay*ay)*(by-cy)+(bx*bx+by*by)*(cy-ay)+(cx*cx+cy*cy)*(ay-by))/d
                    uy=((ax*ax+ay*ay)*(cx-bx)+(bx*bx+by*by)*(ax-cx)+(cx*cx+cy*cy)*(bx-ax))/d
                    r=math.hypot(ax-ux,ay-uy)
                    points.extend(((ux-r,uy-r),(ux+r,uy+r)))
    if not edge_found:
        raise MergeError('Each source must have a top-level Edge.Cuts outline. Footprint-only outlines are not sufficient for automatic placement.')
    if not points:
        raise MergeError('Could not determine source board extent.')
    xs,ys=zip(*points)
    return min(xs),min(ys),max(xs),max(ys)


def arrange(sources,columns,gap):
    x=y=20.0
    row_height=0.0
    placed=[]
    for i,s in enumerate(sources):
        xmin,ymin,xmax,ymax=s.bbox
        w,h=xmax-xmin,ymax-ymin
        if i and i%columns==0:
            x=20.0; y+=row_height+gap; row_height=0.0
        if s.spec.x_mm is not None:
            px,py=s.spec.x_mm,s.spec.y_mm
        else:
            px,py=x,y
        s.translation=(round(px-xmin,6),round(py-ymin,6))
        bounds=(px,py,px+w,py+h)
        for other,b in placed:
            if min(bounds[2],b[2])>max(bounds[0],b[0])+1e-8 and min(bounds[3],b[3])>max(bounds[1],b[1])+1e-8:
                raise MergeError(f'Placement envelopes overlap: {s.alias} and {other}. Increase gap or edit X/Y positions.')
        placed.append((s.alias,bounds))
        x+=w+gap
        row_height=max(row_height,h)
    return placed


def translate(item,dx,dy):
    def shift(n):
        for i,delta in ((1,dx),(2,dy)):
            number(n[i])
            v=Decimal(str(n[i]))+Decimal(str(delta))
            n[i]=format(v.quantize(Decimal('0.000000001')),'f').rstrip('0').rstrip('.') or '0'
    if sx.tag(item)=='footprint':
        shift(sx.child(item,'at'))
        # Pads and graphics use footprint-local coordinates, but owned zones
        # serialize their contours in board/world coordinates. Translate the
        # complete zone, including nested contours or retained fill caches.
        # compose() normally drops stale fills before reaching this helper.
        for zone in sx.children(item,'zone'):
            translate(zone,dx,dy)
        return
    for n in sx.walk(item):
        if sx.tag(n) in {'at','start','mid','end','center','xy'} and len(n)>=3:
            shift(n)


def map_board_nets(source,merged):
    table=net_table(source.board)
    mapping=defaultdict(set)
    reverse=defaultdict(set)
    physical_refs=set()
    pads_seen=set()
    unnumbered_nets=[]
    for fp in sx.children(source.board,'footprint'):
        oldref=fp_reference(fp)
        if oldref in source.board_ref_map:
            if any(net_name(p,table) for p in sx.children(fp,'pad')):
                raise MergeError(f'{source.alias}: net-bearing Board Only footprint {oldref} requires an explicit schematic symbol before merge.')
            continue
        physical_refs.add(oldref)
        for pad in sx.children(fp,'pad'):
            oldpin=(oldref,str(pad[1]))
            old=net_name(pad,table)
            if not str(pad[1]):
                if old: unnumbered_nets.append((oldref,old))
                continue
            newpin=(source.ref_map[oldref],str(pad[1]))
            pads_seen.add(oldpin)
            expected_old=source.xml.pins.get(oldpin)
            target=merged.pins.get(newpin)
            if target is None:
                if old:
                    raise MergeError(f'{source.alias}: PCB pad {oldpin} has a net but no schematic netlist node.')
                continue
            # Empty nets are acceptable only for genuinely unconnected singleton pins.
            if not old and len(source.xml.nets.get(expected_old,set()))>1:
                raise MergeError(f'{source.alias}: pad {oldpin} is not assigned to its connected schematic net. Synchronize source first.')
            if old:
                mapping[old].add(target)
                reverse[target].add(old)
    missing={ep for ep in source.xml.pins if ep[0] in physical_refs}-pads_seen
    if missing:
        raise MergeError(f'{source.alias}: schematic pins missing from PCB pads: {sorted(missing)[:8]}')
    for old,names in mapping.items():
        if len(names)!=1:
            raise MergeError(f'{source.alias}: PCB net {old!r} shorts multiple schematic nets; source is not in parity.')
    for new,names in reverse.items():
        if len(names)>1:
            raise MergeError(f'{source.alias}: multiple PCB net names map to {new}; synchronize the source first.')
    for ref,old in unnumbered_nets:
        if old not in mapping:
            raise MergeError(f'{source.alias}: unnumbered pad on {ref} has no numbered-pin correspondence for net {old!r}.')
    result={old:next(iter(names)) for old,names in mapping.items()}
    for old,new in source.net_map.items():
        if old in result and result[old]!=new:
            raise MergeError(f'{source.alias}: ambiguous net-name/endpoint mapping for {old}.')
        result.setdefault(old,new)
    for n in sx.walk(source.board):
        if sx.tag(n)=='net':
            old=str(n[2]) if len(n)>2 else (str(n[1]) if len(n)>1 and isinstance(n[1],sx.Quoted) else table.get(str(n[1]),'') if len(n)>1 else '')
            if old and old not in result:
                raise MergeError(f'{source.alias}: PCB net {old!r} has no recoverable schematic correspondence (orphan copper/net).')
    return result


def merge_embedded(target,source):
    src=sx.child(source,'embedded_files')
    if src is None:
        return
    dest=sx.child(target,'embedded_files')
    if dest is None:
        dest=sx.put(target,'embedded_files')
    from .embedded import filename
    known={filename(n):sx.dumps(n) for n in sx.children(dest)}
    for entry in sx.children(src):
        from .embedded import filename
        name=filename(entry)
        if not name:
            raise MergeError('Unknown embedded-file entry structure; refusing to discard it.')
        serialized=sx.dumps(entry)
        if name in known and known[name]!=serialized:
            raise MergeError(f'Conflicting embedded attachment {name!r}. Extract/rename this asset in a source before merging.')
        if name not in known:
            dest.append(copy.deepcopy(entry)); known[name]=serialized


def compose(sources,merged,outline,margin,stack_board=None):
    base=sources[0].board
    board=[copy.deepcopy(n) for n in base if not isinstance(n,list) or sx.tag(n) in HEADER-{'net','embedded_files'}]
    sx.put(board,'version',str(max(int(sx.value(s.board,'version')) for s in sources)))
    apply_stack_header(board,sources,stack_board=stack_board)
    sx.remove(board,'variant'); sx.remove(board,'variants')
    sx.put(board,'generator',sx.q('wayri_project_fusion'))
    sx.remove(board,'generator_version')
    namespace_text(board,sources[0])
    if any(sx.value(s.board,'embedded_fonts')=='yes' for s in sources):
        sx.put(board,'embedded_fonts','yes')
    direct=any(isinstance(n[1],sx.Quoted) for s in sources for n in sx.walk(s.board) if sx.tag(n)=='net' and len(n)==2)
    code_map={name:str(i+1) for i,name in enumerate(sorted(merged.nets))}
    if not direct:
        board.append(['net','0',sx.q('')])
        board.extend(['net',code,sx.q(name)] for name,code in code_map.items())
    board_ids=[]
    for s in sources:
        mapping=map_board_nets(s,merged)
        s.pcb_net_map=mapping
        oldtable=net_table(s.board)
        ids={x:new_uuid() for x in sx.declared_uuids(s.board)}
        s.pcb_uuid_map=dict(ids)
        merge_embedded(board,s.board)
        items=[]
        for orig in sx.children(s.board):
            if sx.tag(orig) not in ITEMS:
                continue
            item=copy.deepcopy(orig)
            kind=sx.tag(item)
            sx.remap_identifiers(item,ids)
            namespace_text(item,s)
            if kind=='footprint':
                oldref=fp_reference(orig)
                ref=s.ref_map[oldref]
                p=sx.prop(item,'Reference')
                if p is not None:
                    p[2]=sx.q(ref)
                for txt in sx.children(item,'fp_text'):
                    if len(txt)>2 and txt[1]=='reference':
                        txt[2]=sx.q(ref)
                item[1]=sx.q(remap_footprint_id(str(item[1]),s))
                if oldref not in s.board_ref_map:
                    rec=s.footprint_links[sx.value(orig,'uuid') or sx.value(orig,'tstamp')]
                    root_uuid=rec.sheet.new_path.split('/')[1]
                    sx.put(item,'path',sx.q(pcb_association_path(rec.new_path,root_uuid)))
                    sx.put(item,'sheetname',sx.q(rec.sheet.display_path))
                    sx.put(item,'sheetfile',sx.q(rec.sheet.relative_file))
                else:
                    sx.remove(item,'path')
                    sx.remove(item,'sheetname'); sx.remove(item,'sheetfile')
                if outline=='rectangle' and any(sx.value(n,'layer')=='Edge.Cuts' for n in sx.walk(item)):
                    raise MergeError(f'{s.alias}: {oldref} contains footprint-owned Edge.Cuts. Rectangular outline mode cannot classify these slots/cuts; use Preserve outlines or move/edit them in a source copy first.')
            for n in sx.walk(item):
                if sx.tag(n)=='net':
                    old=str(n[2]) if len(n)>2 else (str(n[1]) if isinstance(n[1],sx.Quoted) else oldtable.get(str(n[1]),''))
                    new=mapping.get(old,'')
                    if direct:
                        n[:]=['net',sx.q(new)]
                    elif len(n)>2:
                        n[:]=['net',code_map.get(new,'0'),sx.q(new)]
                    else:
                        n[:]=['net',code_map.get(new,'0')]
                if sx.tag(n)=='net_name' and len(n)>1:
                    n[1]=sx.q(mapping.get(str(n[1]),''))
                if sx.tag(n)=='zone':
                    sx.remove(n,'filled_polygon'); sx.remove(n,'fill_segments')
            if kind=='footprint':
                # Assign each pad from the independently re-exported netlist,
                # including source pads that had an empty singleton net.
                for pad in sx.children(item,'pad'):
                    target=merged.pins.get((s.ref_map[fp_reference(orig)],str(pad[1])))
                    if target is not None:
                        sx.put(pad,'net',*( [sx.q(target)] if direct else [code_map[target],sx.q(target)] ))
            if outline=='rectangle':
                # Dimensions have nested text layer records as well as an
                # owning layer; move every original outline-layer record.
                for node in sx.walk(item):
                    if sx.tag(node)=='layer' and len(node)>1 and str(node[1])=='Edge.Cuts':
                        node[1]=sx.q('Dwgs.User')
            remap_item(item,s)
            translate(item,*s.translation)
            items.append(item)
        contained={str(v) for item in items if sx.tag(item)=='group' for n in sx.children(item,'members') for v in n[1:] if isinstance(v,str)}
        top_ids=[sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id') for n in items]
        top_ids=[x for x in top_ids if x and x not in contained]
        board.extend(items)
        if top_ids:
            s.fusion_group_uuid=new_uuid()
            board.append(['group',sx.q('Fusion_'+s.alias),['id',sx.q(s.fusion_group_uuid)],['members',*[sx.q(x) for x in top_ids]]])
        board_ids.extend(ids.values())
    if outline=='rectangle':
        bounds=[(s.bbox[0]+s.translation[0],s.bbox[1]+s.translation[1],s.bbox[2]+s.translation[0],s.bbox[3]+s.translation[1]) for s in sources]
        x1=min(b[0] for b in bounds)-margin; y1=min(b[1] for b in bounds)-margin
        x2=max(b[2] for b in bounds)+margin; y2=max(b[3] for b in bounds)+margin
        board.append(['gr_rect',['start',str(x1),str(y1)],['end',str(x2),str(y2)],
                      ['stroke',['width','0.05'],['type','default']],['fill','none'],['layer',sx.q('Edge.Cuts')],['uuid',sx.q(new_uuid())]])
    return board


def verify_board(board,sources,merged):
    verify_layers(board,sources)
    expected={r.new_ref for s in sources for r in s.footprint_links.values()}
    expected |= {s.ref_map[ref] for s in sources for ref in s.board_ref_map}
    refs=[fp_reference(fp) for fp in sx.children(board,'footprint')]
    if len(set(refs))!=len(refs) or set(refs)!=expected:
        raise MergeError('Final PCB footprint/reference count mismatch.')
    ids=sx.declared_uuids(board)
    if len(set(ids))!=len(ids):
        raise MergeError('Final PCB contains duplicate UUIDs.')
    all_ids=set(ids)
    membership={}
    for g in sx.children(board,'group'):
        for m in sx.children(g,'members'):
            for uid in m[1:]:
                if str(uid) not in all_ids:
                    raise MergeError('Final PCB group references a nonexistent UUID.')
                if str(uid) in membership:
                    raise MergeError('Final PCB item belongs to multiple groups.')
                membership[str(uid)]=g
    table=net_table(board)
    valid_paths={pcb_association_path(r.new_path,r.sheet.new_path.split('/')[1]):r.new_ref
                 for s in sources for r in s.symbols}
    board_only={s.ref_map[r] for s in sources for r in s.board_ref_map}
    unnumbered_expected={}
    for source in sources:
        table_old=net_table(source.board)
        for original in sx.children(source.board,'footprint'):
            ref_new=source.ref_map[fp_reference(original)]
            unnumbered_expected[ref_new]=sorted(source.pcb_net_map.get(net_name(p,table_old),'')
                for p in sx.children(original,'pad') if not str(p[1]))
    for fp in sx.children(board,'footprint'):
        ref=fp_reference(fp)
        actual=sorted(net_name(p,table) for p in sx.children(fp,'pad') if not str(p[1]))
        if actual!=unnumbered_expected.get(ref,[]):
            raise MergeError(f'Final unnumbered-pad net mismatch for {ref}.')
        path=canonical_path(sx.value(fp,'path'))
        if ref not in board_only:
            if valid_paths.get(path)!=ref:
                raise MergeError(f'Broken final schematic link for {ref}.')
            paths=merged.components.get(ref,{}).get('paths',set())
            if not paths or path not in paths:
                raise MergeError(f'KiCad-exported UUID path does not agree with PCB link for {ref}.')
        for pad in sx.children(fp,'pad'):
            if not str(pad[1]): continue
            expected_net=merged.pins.get((ref,str(pad[1])), '')
            if net_name(pad,table)!=expected_net:
                raise MergeError(f'Final pad net mismatch for {ref}.{pad[1]}')
    return len(refs)


def verify_native_associations(board, exported):
    """Check every schematic footprint against the literal native XML paths."""
    for fp in sx.children(board,'footprint'):
        attr=sx.child(fp,'attr',[])
        if 'board_only' in [value for value in attr if isinstance(value,str)]:
            continue
        ref=fp_reference(fp)
        path=canonical_path(sx.value(fp,'path'))
        native=exported.components.get(ref,{}).get('paths',set())
        if path not in native:
            raise MergeError(f'PCB footprint {ref} has association path {path}, but KiCad exports '
                             f'{sorted(native)}. Repair the saved PCB association before importing or updating; '
                             'schematic instance paths must keep their root UUID.')


def geometry_signature(board):
    """Post-native-save geometry/layer/span checks, including pad stacks.

    Numeric formatting and child ordering are normalized; geometry, copper-layer
    membership and through-via type must not be changed by the native reader.
    """
    def atom(v):
        try: return round(float(v),6)
        except (ValueError,TypeError): return str(v)
    def signature(node):
        parts=[sx.tag(node)]
        for v in node[1:]:
            if not isinstance(v,list): parts.append(atom(v))
        fields=[]
        for child in sx.children(node):
            if sx.tag(child) in {'uuid','tstamp','net','pinfunction','pintype','property','fp_text','sheetfile','sheetname','path','locked','unlocked','tenting'}:
                continue
            if sx.tag(child)=='layers':
                fields.append(('layers',tuple(sorted(map(str,child[1:])))))
            else:
                fields.append(signature(child))
        return tuple(parts)+tuple(sorted(fields,key=repr))
    result={}
    for n in sx.children(board):
        if sx.tag(n) not in {'footprint','segment','arc','via'}: continue
        uid=sx.value(n,'uuid') or sx.value(n,'tstamp')
        if sx.tag(n)=='footprint':
            # Native KiCad may refresh library metadata, but not pad geometry,
            # model transforms, or the rigid placement/layer of a routed part.
            value=[('layer',sx.value(n,'layer')),('at',signature(sx.child(n,'at',['at','0','0'])))]
            value += sorted([signature(p) for p in sx.children(n,'pad')],key=repr)
            value += sorted([signature(p) for p in sx.children(n,'model')],key=repr)
            result[uid]=tuple(value)
        else: result[uid]=signature(n)
    return result
