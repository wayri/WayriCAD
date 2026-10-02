"""Stable source identities and electrical change classification for linked imports.

Connectivity is compared by UUID occurrence and pin number, not by reference or
net label. Renaming a net cannot hide a changed pin partition.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from collections import defaultdict
import hashlib
import copy
import json
import tempfile

from . import sexpr as sx
from .model import SourceSpec, MergeError
from .schematic import discover, new_uuid, canonical_path
from .engine import export_selected_netlist, _assert_sources_unchanged
from .netlist import KiCadCLI
from .board import geometry_signature, net_table, net_name, ITEMS, fp_reference
from .sections import _geometry_signature
from .variants import effective_board_flags


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot_source(spec, cli_path='', include_layout=True):
    """Read and independently export a selected saved source; never write it."""
    if isinstance(spec, dict):
        spec = SourceSpec(**spec)
    source = discover(spec, new_uuid(), require_board=False)
    if not isinstance(include_layout,bool):
        raise MergeError('Choose whether the source snapshot includes layout.')
    if not include_layout:
        source.files.discard(source.pcb_file)
    for path in source.files:
        path=Path(path)
        if path.is_file() and str(path) not in source.hashes:
            source.hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    initial_hashes=dict(source.hashes)
    cli = KiCadCLI(cli_path)
    with tempfile.TemporaryDirectory(prefix='fusion-link-snapshot-') as folder:
        xml = export_selected_netlist(source, cli, Path(folder)/'source.xml')
    by_ref = defaultdict(list)
    symbols = {}
    schematic_items = {}
    for sheet in source.sheets:
        for item in sx.children(sheet.tree):
            uid = sx.value(item,'uuid')
            if not uid:
                continue
            geometry = [n for n in item if not isinstance(n,list) or sx.tag(n) not in {'uuid','instances','property'}]
            schematic_items[sheet.old_path+'/'+uid] = {'kind':sx.tag(item),'geometry':_digest(geometry)}
    for record in source.symbols:
        fields = {str(p[1]): str(p[2]) for p in sx.children(record.node, 'property') if len(p)>2}
        identity = canonical_path(record.old_path)
        by_ref[record.old_ref].append(identity)
        symbols[identity] = {'reference': record.old_ref, 'unit': record.unit,
            'uuid': record.old_uuid, 'sheet_path': record.sheet.old_path,
            'lib_id': record.lib_id, 'value': fields.get('Value',''),
            'footprint': fields.get('Footprint',''),
            'fields': {k:v for k,v in fields.items() if k not in {'Reference','Value','Footprint'}},
            'flags': effective_board_flags(record)}
        library=source.libraries[record.lib_id]
        symbols[identity]['pin_definitions']=[{'number':sx.value(pin,'number'),'name':sx.value(pin,'name'),
            'electrical_type':str(pin[1]) if len(pin)>1 else '',
            'style':str(pin[2]) if len(pin)>2 else '', 'at':sx.child(pin,'at'), 'length':sx.value(pin,'length')}
            for pin in sx.walk(library) if sx.tag(pin)=='pin']
    # All units of a component share its pin identity. Ordinary reannotation
    # retains the same component identity; adding/removing a unit is structural.
    ref_ids = {ref: sorted(paths)[0] for ref,paths in by_ref.items()}
    components = {}
    for ref, component in xml.components.items():
        if ref not in ref_ids:
            raise MergeError('Native component has no stable schematic occurrence: '+ref)
        components[ref_ids[ref]] = {'reference': ref, 'occurrences': sorted(by_ref[ref]),
                                  'value': component['value'], 'footprint': component['footprint']}
    nets = []
    for name, endpoints in xml.nets.items():
        pins = []
        for ref,pin in endpoints:
            if ref not in ref_ids:
                raise MergeError('Native pin has no stable schematic occurrence: '+ref+'.'+pin)
            pins.append([ref_ids[ref], pin])
        nets.append({'name':name, 'pins':sorted(pins)})
    board_items = {}
    if include_layout and source.pcb_file.is_file():
        board = sx.load(source.pcb_file, source.hashes)
        geometry = geometry_signature(board)
        table=net_table(board); board_endpoints=defaultdict(set)
        for footprint in sx.children(board,'footprint'):
            link=source.link_map.get(canonical_path(sx.value(footprint,'path')))
            ref=link.old_ref if link else fp_reference(footprint)
            identity=ref_ids.get(ref, 'pcb-only/'+str(sx.value(footprint,'uuid') or sx.value(footprint,'tstamp')))
            for pad in sx.children(footprint,'pad'):
                name=net_name(pad,table)
                if name:board_endpoints[name].add((identity,str(pad[1])))
        def electrical_identity(name):
            if not name:return ''
            return _digest(sorted(board_endpoints[name])) if name in board_endpoints else 'unproven:'+name
        for item in sx.children(board):
            kind = sx.tag(item)
            if kind not in ITEMS:
                continue
            uid = sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')
            if not uid:
                raise MergeError('Source PCB object lacks a stable UUID: '+kind)
            if kind=='footprint':
                physical=copy.deepcopy(item)
                physical[:]=[node for node in physical if not (
                    isinstance(node,list) and (sx.tag(node)=='property' and len(node)>1 and str(node[1]).casefold() in {'reference','value'}
                    or sx.tag(node)=='fp_text' and len(node)>1 and str(node[1]) in {'reference','value'}))]
                value=(geometry.get(uid),_geometry_signature(physical))
            else:
                value = geometry.get(uid, _geometry_signature(item))
            identity = canonical_path(sx.value(item,'path')) if kind=='footprint' else ''
            board_items[uid] = {'kind':kind,'geometry':_digest(value), 'symbol':identity,
                               'net':electrical_identity(net_name(item,table)) if kind in {'segment','arc','via','zone'} else ''}
            if kind=='footprint':
                board_items[uid]['pad_connections']=sorted(
                    (sx.value(pad,'uuid'),str(pad[1]),electrical_identity(net_name(pad,table)))
                    for pad in sx.children(item,'pad'))
    if source.hashes != initial_hashes:
        raise MergeError('Source changed while collecting linked-update geometry; save and scan again.')
    _assert_sources_unchanged([source])
    return {'schema':1, 'spec':asdict(spec), 'root_uuid':source.old_root_uuid, 'include_layout':include_layout,
            'variant':source.selected_variant, 'symbols':symbols, 'components':components,
            'sheets':[{'path':s.old_path,'name':s.display_path,'symbols':len(s.symbols)} for s in source.sheets],
            'nets':sorted(nets,key=lambda n:(n['pins'],n['name'])), 'board_items':board_items,
            'schematic_items':schematic_items,
            'project_settings':{k:source.project.get(k) for k in
                                (('board','net_settings','text_variables') if include_layout else ('net_settings','text_variables'))},
            'hashes':dict(source.hashes)}


def _pin_connections(snapshot):
    connections = {}
    for net in snapshot.get('nets',[]):
        pins = {tuple(pin) for pin in net['pins']}
        for pin in pins:
            connections[pin] = sorted([list(other) for other in pins-{pin}])
    return connections


def compare_snapshots(before, after):
    """Classify changes with exact pin-neighbour differences and explicit severity."""
    before=json.loads(json.dumps(before));after=json.loads(json.dumps(after))
    changes = []
    def add(category, severity, identity, old, new, message, **extra):
        changes.append({'category':category,'severity':severity,'identity':identity,
                        'before':old,'after':new,'message':message,**extra})
    old_symbols, new_symbols = before.get('symbols',{}), after.get('symbols',{})
    for identity in sorted(set(old_symbols)|set(new_symbols)):
        old, new = old_symbols.get(identity), new_symbols.get(identity)
        if old is None or new is None:
            add('symbol_added' if old is None else 'symbol_removed', 'major', identity,old,new,
                'Symbol added to source' if old is None else 'Symbol removed from source')
            continue
        reference = new['reference']
        for key, category, severity in [('footprint','footprint','major'), ('lib_id','symbol_library','major'),
                ('unit','unit','major'), ('flags','assembly_flags','major'), ('value','value','minor'),
                ('pin_definitions','pin_definition','major'),
                ('fields','fields','minor'), ('reference','reference','minor')]:
            if old.get(key) != new.get(key):
                add(category,severity,identity,old.get(key),new.get(key), reference+': '+category.replace('_',' ')+' changed',reference=reference)
    old_pins,new_pins = _pin_connections(before),_pin_connections(after)
    for identity in sorted(set(before.get('components',{}))&set(after.get('components',{}))):
        old,new = before['components'][identity],after['components'][identity]
        for key,severity in (('value','minor'),('footprint','major')):
            if old.get(key)!=new.get(key) and not any(c['identity']==identity and c['category']==key for c in changes):
                add('resolved_'+key,severity,identity,old.get(key),new.get(key),
                    new['reference']+': resolved '+key+' changed',reference=new['reference'])
    for pin in sorted(set(old_pins)|set(new_pins)):
        old,new = old_pins.get(pin),new_pins.get(pin)
        if old != new:
            component = after.get('components',{}).get(pin[0],before.get('components',{}).get(pin[0],{}))
            reference = component.get('reference',pin[0])
            def display_connections(snapshot, connections):
                if connections is None:return '(no exported net)'
                if not connections:return '(unconnected singleton)'
                return ', '.join(snapshot.get('components',{}).get(identity,{}).get('reference',identity)+'.'+number
                                 for identity,number in connections)
            add('pin_connection','major',pin[0],old,new,reference+'.'+pin[1]+': electrical connection changed',
                reference=reference,pin=pin[1],pin_added=pin not in old_pins,pin_removed=pin not in new_pins,
                before_display=display_connections(before,old),after_display=display_connections(after,new))
    old_sheets={s['path']:s for s in before.get('sheets',[])}
    new_sheets={s['path']:s for s in after.get('sheets',[])}
    for path in sorted(set(old_sheets)|set(new_sheets)):
        if path not in old_sheets or path not in new_sheets:
            add('hierarchy','major',path,old_sheets.get(path),new_sheets.get(path),'Source hierarchy changed')
        elif old_sheets[path].get('name') != new_sheets[path].get('name'):
            add('sheet_name','minor',path,old_sheets[path]['name'],new_sheets[path]['name'],'Sheet name changed')
    old_nets={tuple(tuple(p) for p in n['pins']):n['name'] for n in before.get('nets',[])}
    new_nets={tuple(tuple(p) for p in n['pins']):n['name'] for n in after.get('nets',[])}
    for pins in sorted(set(old_nets)&set(new_nets)):
        if old_nets[pins]!=new_nets[pins]:
            add('net_label','minor',repr(pins),old_nets[pins],new_nets[pins],'Net renamed; electrical pin partition is unchanged')
    old_board,new_board = before.get('board_items',{}),after.get('board_items',{})
    for uid in sorted(set(old_board)|set(new_board)):
        if old_board.get(uid)!=new_board.get(uid):
            item = new_board.get(uid,old_board.get(uid))
            add('layout','major',uid,old_board.get(uid),new_board.get(uid),item['kind']+': layout or copper changed')
    old_geometry,new_geometry = before.get('schematic_items',{}),after.get('schematic_items',{})
    for uid in sorted(set(old_geometry)|set(new_geometry)):
        if old_geometry.get(uid)!=new_geometry.get(uid):
            item = new_geometry.get(uid,old_geometry.get(uid))
            add('schematic_geometry','minor',uid,old_geometry.get(uid),new_geometry.get(uid),
                item['kind']+': schematic geometry changed; electrical changes are listed by pin')
    for key in ('board','net_settings','text_variables'):
        old = before.get('project_settings',{}).get(key)
        new = after.get('project_settings',{}).get(key)
        if old!=new:
            add('project_settings','minor' if key=='text_variables' else 'major',key,old,new,
                'Source '+key.replace('_',' ')+' changed')
    major = sum(c['severity']=='major' for c in changes)
    return {'changes':changes,'major_changes':major,'minor_changes':len(changes)-major,
            'requires_major_acknowledgement':bool(major),
            'summary':{'total':len(changes),'major':major,'minor':len(changes)-major,
                       'pin_connections':sum(c['category']=='pin_connection' for c in changes)}}


def suggest_auto_links(before, after):
    """Exact stable identities auto-match; heuristic matches are review proposals."""
    old,new = before.get('symbols',{}),after.get('symbols',{})
    matches = [{'before':key,'after':key,'method':'UUID occurrence','automatic':True}
               for key in sorted(set(old)&set(new))]
    used_old={m['before'] for m in matches};used_new={m['after'] for m in matches}
    for key,item in old.items():
        if key in used_old:continue
        candidates=[other for other,value in new.items() if other not in used_new
                    and value.get('uuid')==item.get('uuid') and value.get('unit')==item.get('unit')]
        if len(candidates)==1:
            matches.append({'before':key,'after':candidates[0],'method':'UUID moved between sheets','automatic':False})
        else:
            candidates=[other for other,value in new.items() if other not in used_new
                        and value.get('reference')==item.get('reference') and value.get('lib_id')==item.get('lib_id')]
            if candidates:
                matches.append({'before':key,'candidates':candidates,'method':'Reference and symbol library','automatic':False})
    return matches
