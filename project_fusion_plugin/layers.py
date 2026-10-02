"""Explicit top-down copper mapping; physical stack supplied by the largest board.

This is NOT an outer-layers-preserving panelization map: 2 -> 4 maps B.Cu to
In1.Cu. Surface-mount pads may not become buried. Full-depth vias become blind
when their mapped endpoint is internal. PTH drills remain full depth.
"""
from __future__ import annotations
import copy
import re
from . import sexpr as sx
from .model import MergeError


def copper_sequence(board):
    declared=[str(n[1]) for n in sx.children(sx.child(board,'layers',['layers'])) if len(n)>1 and str(n[1]).endswith('.Cu')]
    if len(set(declared))!=len(declared) or 'F.Cu' not in declared or 'B.Cu' not in declared:
        raise MergeError('Invalid copper-layer sequence: unique F.Cu and B.Cu declarations are required.')
    count=len(declared)
    if count<2 or count>32 or count%2:
        raise MergeError('Invalid copper-layer sequence: use an even count of 2–32 copper layers.')
    sequence=['F.Cu',*[f'In{i}.Cu' for i in range(1,count-1)],'B.Cu']
    if set(sequence)!=set(declared):
        raise MergeError('Invalid copper-layer sequence: internal layer names must be contiguous.')
    return sequence


def plan_layers(sources, acknowledged, log=lambda m:None):
    for s in sources:
        s.copper_layers=copper_sequence(s.board)
    donor=max(sources,key=lambda s:len(s.copper_layers))
    target=donor.copper_layers
    mixed=any(len(s.copper_layers)!=len(target) for s in sources)
    for s in sources:
        s.target_copper_layers=list(target)
        s.layer_map=dict(zip(s.copper_layers,target[:len(s.copper_layers)]))
        s.stackup_donor=donor.alias
        s.layer_notes=[]
        if len(s.copper_layers)<len(target):
            s.layer_notes.append(f'{s.copper_layers[-1]} -> {s.layer_map[s.copper_layers[-1]]}; no imported planar copper on {", ".join(target[len(s.copper_layers):])}.')
            # Scan a copy in preflight; do not mutate the saved source tree.
            for item in sx.children(s.board):
                if sx.tag(item) not in {'layers','setup'}:
                    remap_item(copy.deepcopy(item),s,check_only=True)
        log(f'{s.alias}: copper map '+', '.join(f'{a} -> {b}' for a,b in s.layer_map.items()))
    if mixed and not acknowledged:
        raise MergeError('Acknowledge top-down copper-layer remapping: smaller boards use the first N layers; source B.Cu becomes internal, through vias become blind, PTH drills remain full depth, and impedance/stackup must be requalified.')
    log(f'Output physical stack: {len(target)} copper layers from {donor.alias}; ties use the first largest board.')
    return donor


def _expanded(values,source):
    out=[]
    for v in values:
        value=str(v)
        if value=='*.Cu':
            values2=[source.layer_map[x] for x in source.copper_layers]
        elif value=='F&B.Cu':
            values2=[source.layer_map['F.Cu'],source.layer_map['B.Cu']]
        elif value in source.layer_map:
            values2=[source.layer_map[value]]
        elif value.endswith('.Cu'):
            raise MergeError(f'{source.alias}: reference to undeclared/unsupported copper layer {value!r}.')
        else:
            values2=[v]
        for item in values2:
            if item not in out:
                out.append(item)
    return [sx.q(v) if str(v).endswith('.Cu') else v for v in out]


def _note(source,text):
    if text not in source.layer_notes:
        source.layer_notes.append(text)


def remap_item(item,source,check_only=False):
    mixed=len(source.copper_layers)<len(source.target_copper_layers)
    if not mixed:
        return item
    kind=sx.tag(item)
    native_pth_layers=set()
    if kind=='footprint' and sx.value(item,'layer','F.Cu')=='B.Cu':
        ref=sx.propval(item,'Reference',str(item[1]))
        raise MergeError(f'{source.alias}: bottom-side footprint {ref} would be placed on {source.layer_map["B.Cu"]} under top-down mapping. KiCad surface components must remain on an outer face; move this component to the source front side and reroute, or supply equal-layer-count sources.')
    for node in sx.walk(item):
        tag=sx.tag(node)
        if tag=='pad':
            layers=sx.child(node,'layers',['layers'])
            mapped=_expanded(layers[1:],source)
            padtype=str(node[2]) if len(node)>2 else ''
            copper=[str(v) for v in mapped if str(v).endswith('.Cu')]
            if padtype in {'smd','connect'} and any(v not in {'F.Cu','B.Cu'} for v in copper):
                raise MergeError(f'{source.alias}: SMD/edge-connector pad {node[1]} would move to internal copper. No buried SMD pads or silent pad disconnection will be created.')
            if padtype=='thru_hole':
                padstack=sx.child(node,'padstack')
                if padstack is None or sx.value(padstack,'mode','normal')=='normal':
                    # Native KiCad normal PTH pads span all copper layers.
                    # Plan that explicitly; never accept an unexpected expansion
                    # after validation or pretend these are blind drilled pads.
                    other=[v for v in layers[1:] if not str(v).endswith('.Cu')]
                    layers[:]=['layers',sx.q('*.Cu'),*other]
                    native_pth_layers.add(id(layers))
                _note(source,'Normal PTH pads retain full-stack annuli (*.Cu) and full-depth plated barrels; review clearances on every added copper layer. Planar tracks/zones still use the mapped layers.')
            if padtype=='np_thru_hole':
                _note(source,'NPTH mechanical holes continue through the whole combined board thickness.')
        if tag=='padstack':
            mode=sx.value(node,'mode','normal')
            if mode not in {'normal','custom'}:
                raise MergeError(f'{source.alias}: convert front/inner/back grouped padstacks to explicit Custom layers in a source copy before top-down layer mapping.')
        if tag=='layer' and len(node)>1 and str(node[1]) in {'Inner','In*.Cu'}:
            raise MergeError(f'{source.alias}: grouped inner-layer padstack needs explicit per-layer normalization.')
    # Layer names are rewritten only in structural layer fields, not prose,
    # library identifiers, or the source's global setup.
    for node in sx.walk(item):
        if sx.tag(node) in {'layer','layers','private_layers','zone_layer_connections'} and len(node)>1:
            if id(node) in native_pth_layers: continue
            atoms=[v for v in node[1:] if isinstance(v,str)]
            if atoms:
                # layer records can also contain nested padstack geometry.
                children=[v for v in node[1:] if isinstance(v,list)]
                node[:]=[node[0],*_expanded(atoms,source),*children]
    for node in sx.walk(item):
        if sx.tag(node)!='via':
            continue
        layers=sx.child(node,'layers')
        if layers is None or len(layers)!=3:
            raise MergeError(f'{source.alias}: via has an invalid layer span.')
        pair=tuple(map(str,layers[1:]))
        kind_tokens=[str(v) for v in node[1:] if isinstance(v,str) and str(v) in {'through','blind','buried','micro'}]
        if (not kind_tokens or kind_tokens==['through']) and set(pair)!={'F.Cu','B.Cu'}:
            node[:]=[v for v in node if not (isinstance(v,str) and str(v)=='through')]
            node.insert(1,'blind')
            _note(source,f'Through vias converted to blind/buried spans {pair[0]} -> {pair[1]}; fabricator approval is required.')
    return item


def apply_stack_header(board,sources):
    donor=max(sources,key=lambda s:len(s.copper_layers))
    declarations=copy.deepcopy(sx.child(donor.board,'layers'))
    by_name={str(n[1]):str(n[0]) for n in sx.children(declarations)}
    by_id={str(n[0]):str(n[1]) for n in sx.children(declarations)}
    for source in sources:
        for entry in sx.children(sx.child(source.board,'layers',['layers'])):
            name=str(entry[1]); ident=str(entry[0])
            if name.endswith('.Cu') or name in by_name:
                continue
            if ident in by_id and by_id[ident]!=name:
                raise MergeError(f'Non-copper layer-number conflict: {name} vs {by_id[ident]}. Save all source boards with the same KiCad 10 version first.')
            declarations.append(copy.deepcopy(entry)); by_name[name]=ident; by_id[ident]=name
    sx.put(board,'layers',*declarations[1:])
    general=sx.child(donor.board,'general')
    if general is not None:
        sx.put(board,'general',*copy.deepcopy(general[1:]))
    setup=sx.child(board,'setup')
    if setup is None:
        setup=sx.put(board,'setup')
    sx.remove(setup,'stackup')
    stack=sx.child(sx.child(donor.board,'setup',['setup']),'stackup')
    if stack is not None:
        setup.append(copy.deepcopy(stack))
    # Bitmasks/export layer selections from another source are not portable.
    # Keep the largest board's plot setup, whose layer IDs match the output.
    plot=sx.child(sx.child(donor.board,'setup',['setup']),'pcbplotparams')
    sx.remove(setup,'pcbplotparams')
    if plot is not None:
        setup.append(copy.deepcopy(plot))
    return donor


def verify_layers(board,sources):
    target=max(sources,key=lambda s:len(s.target_copper_layers)).target_copper_layers
    if copper_sequence(board)!=target:
        raise MergeError('The saved PCB copper stack differs from the planned maximum-layer stack.')
    for item in sx.children(board):
        if sx.tag(item) in {'layers','setup'}:
            continue
        for node in sx.walk(item):
            if sx.tag(node) in {'layer','layers','private_layers','zone_layer_connections'}:
                for v in node[1:]:
                    if isinstance(v,str) and v.endswith('.Cu') and v not in target and v not in {'*.Cu','F&B.Cu'}:
                        raise MergeError(f'Output refers to an undeclared copper layer: {v}.')
