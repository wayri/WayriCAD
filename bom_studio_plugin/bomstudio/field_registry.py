"""Lossless field inventory and native-BOM preset interoperation.

A physical property, a displayed column label and a purchasing alias are three
separate things. @field:<exact name> always selects a real property, including
an intentionally empty one; it never falls through to an alias/default.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from .native import BASE, is_generated_field
from .engine import Resolver

VIRTUALS={'${QUANTITY}':'Qty','${ITEM_NUMBER}':'Item','${DNP}':'DNP',
          '${EXCLUDE_FROM_BOM}':'@attribute:exclude_bom','${EXCLUDE_FROM_BOARD}':'@attribute:exclude_board',
          '${EXCLUDE_FROM_SIM}':'ExcludeFromSim','${EXCLUDE_FROM_POS_FILES}':'@attribute:exclude_pos'}


def presets(project):
    schematic=project.pro.get('schematic',{})
    result=[]
    current=schematic.get('bom_settings')
    if isinstance(current,dict) and current.get('fields_ordered'):
        result.append({'id':'@current','name':'Saved KiCad view','preset':deepcopy(current)})
    for i,p in enumerate(schematic.get('bom_presets',[])):
        if isinstance(p,dict):result.append({'id':str(i),'name':str(p.get('name','Preset '+str(i+1))),'preset':deepcopy(p)})
    return result


def source_key(name, physical):
    if name in physical:return '@field:'+name
    return VIRTUALS.get(name, name)


def _inventory_base(ws,variant=BASE,rows=None):
    rows=ws.rows(variant) if rows is None else rows
    entries={};n=len(rows)
    # Keep physical schema names present only in another named variant discoverable.
    order=[]
    for row in rows:
        for name in row['raw']:
            if name not in entries:
                order.append(name);entries[name]={'key':'@field:'+name,'name':name,'label':name,
                    'kind':'physical','present':0,'nonempty':0,'variable_cells':0,'samples':[], 'origins':set()}
            e=entries[name];e['present']+=1
            raw=row['raw'][name];resolved=row.get('physical',{}).get(name,raw)
            e['nonempty']+=int(bool(str(raw).strip()));e['variable_cells']+=int('${' in str(name)+str(raw) or '@{' in str(raw))
            if str(resolved) not in e['samples'] and len(e['samples'])<3:e['samples'].append(str(resolved)[:200])
            e['origins'].add(row.get('origins',{}).get(name,'Saved schematic'))
    other=set()
    for c in ws.project.components:
        for data in c.native.values():other.update(data.get('fields',{}))
    for data in ws.state['variants'].values():
        for changes in data.get('overrides',{}).values():other.update(k for k in changes if k not in ('dnp','in_bom','on_board','in_pos_files','exclude_from_sim'))
    for name in sorted(other-set(entries)):
        entries[name]={'key':'@field:'+name,'name':name,'label':name,'kind':'other_variant','present':0,'nonempty':0,'variable_cells':0,'samples':[], 'origins':set()};order.append(name)
    for e in entries.values():
        e['missing']=n-e['present'];e['blank']=e['present']-e['nonempty'];e['origins']=sorted(e['origins'])
        e['generated']=is_generated_field(e['name'])
    template_defaults=ws.project.pro.get('schematic',{}).get('drawing',{}).get('field_names',[])
    available=presets(ws.project)
    labels={e['key']:e['name'] for e in entries.values()}
    physical_columns=['@field:'+x for x in order if entries[x]['present']]
    # Saved native table order and BOM labels are respected on first open.
    # App-only alias/computed columns are not silently substituted for them.
    default=list(physical_columns);native_note='Project property order'
    current=next((p['preset'] for p in available if p['id']=='@current'),None)
    if current:
        default=[];mentioned=set()
        for f in current.get('fields_ordered',[]):
            if not isinstance(f,dict) or not isinstance(f.get('name'),str):continue
            name=f['name'];key=source_key(name,entries);mentioned.add(name)
            labels[key]=str(f.get('label',name))
            if f.get('show',True) and key not in default:default.append(key)
        # New physical fields not known by the saved preset must be discoverable,
        # rather than silently disappearing behind an old preset schema.
        default.extend('@field:'+x for x in order if x not in mentioned and entries[x]['present'])
        native_note='Saved native order/labels; newly discovered fields appended'
    if not default:default=['Reference','Value','Footprint']
    actual_keys=set(entries)
    aliases=[]
    for key,alternatives in ws.state['aliases'].items():
        matches=[x for x in order if x.casefold() in {v.casefold() for v in [key,*alternatives]}]
        if matches:aliases.append({'alias':key,'sources':matches,'is_physical':key in actual_keys})
    return {'schema':'wayricad-field-inventory-1','component_count':n,'fields':[entries[x] for x in order],
            'physical_field_count':sum(e['present']>0 for e in entries.values()),
            'default_columns':default[:200],'all_project_columns':physical_columns[:200],'labels':labels,
            'truncated_view':len(default)>200 or len(physical_columns)>200,'native_presets':available,
            'native_format_presets':deepcopy(ws.project.pro.get('schematic',{}).get('bom_fmt_presets',[])),
            'native_format_settings':deepcopy(ws.project.pro.get('schematic',{}).get('bom_fmt_settings',{})),
            'template_defaults':template_defaults,'aliases':aliases,
            'alias_conflicts':[{'reference':r['ref'],**c} for r in rows for c in r.get('alias_conflicts',[])],
            'default_basis':native_note,'notice':'Physical names and blank values are preserved. Labels, computed values and aliases are separate. Saved files only; unsaved KiCad editor memory is not read.'}


def adopt(ws,variant=BASE,preset_id=None,all_fields=False):
    inv=inventory(ws,variant)
    view={'columns':inv['all_project_columns'] if all_fields else inv['default_columns'],
          'labels':inv['labels'],'field_mode':'project'}
    native=None
    if preset_id is not None:
        record=next((p for p in inv['native_presets'] if p['id']==str(preset_id)),None)
        if record is None:raise ValueError('Unknown saved native preset.')
        native=record['preset'];physical={e['name'] for e in inv['fields']};cols=[];labels={}
        for f in native.get('fields_ordered',[]):
            key=source_key(f['name'],physical);labels[key]=str(f.get('label',f['name']))
            if f.get('show',True) and key not in cols:cols.append(key)
        if not cols:raise ValueError('The native preset has no visible fields.')
        view.update(columns=cols,labels=labels,native_preset=record['name'],sort_field=source_key(native.get('sort_field','Reference'),physical),sort_asc=bool(native.get('sort_asc',True)))
    from .catalog import validate_view
    validate_view(view)
    from .nativefirst import preferences
    pref=preferences(ws)
    if all_fields:pref['mode']='custom'
    else:pref.update(mode='native',preset=str(preset_id) if preset_id is not None else '@current')
    ws.commit('Use exact project/native BOM fields',lambda:ws.state.update(view=deepcopy(view),bom_preferences=pref))
    return {'view':view,'native_options':native,'notice':'Only workspace layout changed. Native grouping/filter settings are shown for review; source fields and native files are unchanged.'}


def import_template(ws,preset_id,name,format_id=None):
    inv=inventory(ws)
    record=next((p for p in inv['native_presets'] if p['id']==str(preset_id)),None)
    if record is None:raise ValueError('Unknown native BOM preset.')
    p=record['preset'];physical={e['name'] for e in inv['fields']}
    cols=[{'field':'@field:'+f['name'] if f['name'] in physical and f['name']!='Reference' else f['name'],
           'label':str(f.get('label',f['name'])),'export':bool(f.get('show',True))} for f in p.get('fields_ordered',[])]
    grouping=['@field:'+f['name'] if f['name'] in physical and f['name']!='Reference' else f['name'] for f in p.get('fields_ordered',[]) if f.get('group_by')]
    template={'name':name,'columns':cols,'group_by':grouping if p.get('group_symbols') else [],
              'population':'fitted' if p.get('exclude_dnp') else 'all','include_excluded':bool(p.get('include_excluded_from_bom',False)),
              'sort_field':'@field:'+p.get('sort_field','Reference') if p.get('sort_field','Reference') in physical else p.get('sort_field','Reference'),
              'delimiter':',','ref_ranges':False,'description':'Imported native fields/labels. WayriCAD purchasing grouping safeguards still apply. Use Native BOM for exact KiCad output semantics.'}
    warnings=[]
    if p.get('filter_string'):warnings.append('Native reference filter not translated into the WayriCAD query language. Use Native BOM for exact filtered output.')
    if p.get('sort_asc') is False:warnings.append('Native descending sort requires Native BOM mode; this imported template retains the WayriCAD ascending sort.')
    fmt=inv['native_format_settings']
    if format_id is not None:
        try:fmt=inv['native_format_presets'][int(format_id)]
        except (IndexError,ValueError,TypeError):raise ValueError('Unknown native formatting preset.')
    if fmt:
        delim=fmt.get('field_delimiter',',')
        if delim in (',',';','\t','|'):template['delimiter']=delim
        else:warnings.append('Multi-character native delimiter is only supported by Native BOM mode.')
        if fmt.get('string_delimiter','"')!='"':warnings.append('Custom native string delimiters require Native BOM mode.')
        template['ref_ranges']=bool(fmt.get('ref_range_delimiter',''))
        template['options']={'reference_separator':fmt.get('ref_delimiter',', '),'range_separator':fmt.get('ref_range_delimiter') or '–'}
    if name in ws.state['templates']:raise ValueError('Template name already exists; choose a new name.')
    ws.template(template)
    return {'template':template,'warnings':warnings,'source_preset':record['name']}


def inventory(ws,variant=BASE,rows=None):
    from .nativefirst import decorate_inventory
    return decorate_inventory(ws,rows if rows is not None else ws.rows(variant),_inventory_base(ws,variant,rows))
