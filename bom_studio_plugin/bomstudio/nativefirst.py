"""Native-first BOM configuration; reads never change native fields or settings.

Global field-name templates, project field templates, BOM columns and CSV
formatting are distinct. The reverse path only stages a reviewed project change.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import difflib
import hashlib
import json
import os
import sys
from .native import BASE

DEFAULTS = {'mode':'native', 'preset':'@current', 'format_preset':'@current', 'custom_template':''}
FORMAT = {'name':'CSV','field_delimiter':',','string_delimiter':'"',
          'ref_delimiter':',','ref_range_delimiter':'','keep_tabs':False,'keep_line_breaks':False}
MANDATORY = ('Reference','Value','Footprint','Datasheet','Description')


def preferences(ws):
    p=dict(DEFAULTS, **ws.state.get('bom_preferences', {}))
    if set(p)!=set(DEFAULTS) or p['mode'] not in ('native','custom'):
        raise ValueError('Invalid BOM authority settings.')
    if any(not isinstance(p[k],str) or len(p[k])>500 for k in ('preset','format_preset','custom_template')):
        raise ValueError('Invalid BOM preset selection.')
    return p


def _field_templates(value, source):
    """Modern project array and the actual global (templatefields ...) string."""
    if value in (None,'',[]): return []
    if isinstance(value,str):
        from .sexpr import parse
        tree=parse(value)
        if tree.tag!='templatefields': raise ValueError('Expected native templatefields expression.')
        result=[]
        for node in tree.nodes('field'):
            # visible/url are bare atoms in KiCad's global settings.
            atoms=[x.value for x in node.atoms if hasattr(x,'value')]
            result.append({'name':node.get('name'), 'visible':'visible' in atoms, 'url':'url' in atoms})
        value=result
    if not isinstance(value,list) or len(value)>2000: raise ValueError('Invalid native field-name template list.')
    result={}
    for entry in value:
        if not isinstance(entry,dict) or not isinstance(entry.get('name'),str): raise ValueError('Invalid native field-name entry.')
        n=entry['name']
        if not n or len(n)>500: raise ValueError('Invalid native field-name length.')
        if n.casefold() in {x.casefold() for x in MANDATORY}: continue
        if any(type(entry.get(k,False)) is not bool for k in ('visible','url')):raise ValueError('Invalid native template attribute.')
        result[n]={'name':n,'visible':entry.get('visible',False),'url':entry.get('url',False),'source':source}
    return list(result.values())


def global_paths():
    # Explicit override or KiCad's own config root; never scan another major version.
    explicit=os.environ.get('WAYRICAD_KICAD_CONFIG_DIR')
    if explicit:return [Path(explicit).expanduser()/'eeschema.json']
    home=os.environ.get('KICAD_CONFIG_HOME')
    if home:
        base=Path(home).expanduser()
        return [base/'eeschema.json',base/'10.0'/'eeschema.json']
    if sys.platform=='win32':base=Path(os.environ.get('APPDATA',str(Path.home()/'AppData'/'Roaming')))/'kicad'
    elif sys.platform=='darwin':base=Path.home()/'Library'/'Preferences'/'kicad'
    else:base=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'kicad'
    return [base/'10.0'/'eeschema.json']


@lru_cache(maxsize=8)
def _global_read(path, mtime, size):
    p=Path(path)
    if size>2*1024*1024:raise ValueError('KiCad preferences exceed the 2 MiB read limit.')
    data=p.read_bytes();j=json.loads(data.decode('utf-8-sig'))
    return _field_templates(j.get('drawing',{}).get('field_names'), 'global'),hashlib.sha256(data).hexdigest()


def templates(ws):
    warnings=[];global_fields=[];path='';digest=''
    for p in global_paths():
        if not p.is_file():continue
        path=str(p.resolve())
        try:
            s=p.stat();global_fields,digest=_global_read(path,s.st_mtime_ns,s.st_size);global_fields=deepcopy(global_fields)
        except (OSError,ValueError,TypeError,AttributeError) as exc:warnings.append('Global KiCad field-name templates could not be read: '+str(exc))
        break
    try:project_fields=_field_templates(ws.project.pro.get('schematic',{}).get('drawing',{}).get('field_names'), 'project')
    except (ValueError,TypeError,AttributeError) as exc:
        project_fields=[];warnings.append('Project field-name templates could not be read: '+str(exc))
    names={f['name'] for f in project_fields}
    return {'project':project_fields,'global':global_fields,
            'effective':project_fields+[f for f in global_fields if f['name'] not in names],
            'global_path':path,'global_sha256':digest,'warnings':warnings,
            'notice':'Project names override identical global names. Schematic visibility is not BOM column visibility. No value defaults are inferred.'}


def _default_preset(ws, template_info):
    # Native default-editing order, not a WayriCAD procurement schema.
    cols=[('Reference','Reference',False),('${QUANTITY}','Qty',False),('Value','Value',True),
          ('${DNP}','DNP',True),('${EXCLUDE_FROM_BOM}','Exclude from BOM',True),
          ('${EXCLUDE_FROM_BOARD}','Exclude from Board',True),('${EXCLUDE_FROM_SIM}','Exclude from Simulation',True),
          ('${EXCLUDE_FROM_POS_FILES}','Exclude from Position Files',True),('Footprint','Footprint',True),('Datasheet','Datasheet',False)]
    used={c[0] for c in cols}
    extra=[f['name'] for f in template_info['effective']]
    for component in ws.project.components:
        extra.extend(component.fields)
    for n in extra:
        if n not in used:cols.append((n,n,False));used.add(n)
    return {'name':'Default Editing','fields_ordered':[{'name':n,'label':l,'show':True,'group_by':g} for n,l,g in cols],
            'sort_field':'Reference','sort_asc':True,'filter_string':'','group_symbols':True,'exclude_dnp':False,'include_excluded_from_bom':True}


def validate_native(settings):
    if not isinstance(settings,dict) or set(settings)!={'bom_settings','bom_fmt_settings'}:raise ValueError('Invalid native BOM settings payload.')
    p=settings['bom_settings'];f=settings['bom_fmt_settings']
    if not isinstance(p,dict) or not isinstance(f,dict):raise ValueError('Native settings must be objects.')
    if set(p)-{'name','fields_ordered','sort_field','sort_asc','filter_string','filter_scope','group_symbols','exclude_dnp','include_excluded_from_bom'}:raise ValueError('Unsupported native BOM option.')
    if set(f)-set(FORMAT):raise ValueError('Unsupported native BOM formatting option.')
    fields=p.get('fields_ordered')
    if not isinstance(fields,list) or len(fields)>500:raise ValueError('Provide at most 500 native columns.')
    names=[]
    for c in fields:
        if not isinstance(c,dict) or set(c)-{'name','label','show','group_by'}:raise ValueError('Invalid native column.')
        for k in ('name','label'):
            if not isinstance(c.get(k),str) or len(c[k])>500 or ('\x00' in c[k]):raise ValueError('Invalid native column '+k)
        if not c['name']:raise ValueError('Empty native field name.')
        for k in ('show','group_by'):
            if type(c.get(k)) is not bool:raise ValueError('Invalid native column Boolean.')
        names.append(c['name'])
    if len(set(names))!=len(names):raise ValueError('Duplicate native fields.')
    for k in ('sort_asc','group_symbols','exclude_dnp','include_excluded_from_bom'):
        if k in p and type(p[k]) is not bool:raise ValueError('Invalid native Boolean '+k)
    for k in ('name','sort_field','filter_string'):
        if k in p and (not isinstance(p[k],str) or len(p[k])>4096):raise ValueError('Invalid native text '+k)
    for k in ('name','field_delimiter','string_delimiter','ref_delimiter','ref_range_delimiter'):
        if k in f and (not isinstance(f[k],str) or len(f[k])>500 or '\x00' in f[k]):raise ValueError('Invalid native format text '+k)
    for k in ('keep_tabs','keep_line_breaks'):
        if k in f and type(f[k]) is not bool:raise ValueError('Invalid native format Boolean.')
    return deepcopy(settings)


def context(ws):
    pref=preferences(ws);t=templates(ws);s=ws.project.pro.get('schematic',{})
    current=s.get('bom_settings')
    if not isinstance(current,dict) or 'fields_ordered' not in current:
        current=_default_preset(ws,t);basis='Native Default Editing fallback (no saved BOM preset)'
    else:basis='Saved KiCad BOM settings'
    presets=[{'id':'@current','name':'Current saved KiCad settings','preset':deepcopy(current)}]
    presets += [{'id':str(i),'name':p.get('name','Preset '+str(i+1)),'preset':deepcopy(p)} for i,p in enumerate(s.get('bom_presets',[])) if isinstance(p,dict)]
    formats=[{'id':'@current','name':'Current saved KiCad formatting','format':dict(FORMAT,**s.get('bom_fmt_settings',{}))}]
    formats += [{'id':str(i),'name':f.get('name','Format '+str(i+1)),'format':dict(FORMAT,**f)} for i,f in enumerate(s.get('bom_fmt_presets',[])) if isinstance(f,dict)]
    override = ws.state.get('native_export_settings')
    if override is not None:
        override = validate_native(override)
        presets.append({'id':'@workspace','name':'Workspace BOM settings','preset':override['bom_settings']})
        formats.append({'id':'@workspace','name':'Workspace formatting','format':dict(FORMAT,**override['bom_fmt_settings'])})
    selected=next((p for p in presets if p['id']==pref['preset']),None)
    selected_format=next((f for f in formats if f['id']==pref['format_preset']),None)
    if selected is None or selected_format is None:raise ValueError('Selected native preset no longer exists. Choose current saved KiCad settings.')
    p=selected['preset'];fmt=selected_format['format'];validate_native({'bom_settings':p,'bom_fmt_settings':fmt})
    physical={k for c in ws.project.components for k in c.fields}
    from .field_registry import source_key
    def key(n):return source_key(n,physical) if n.startswith('${') else '@field:'+n
    visible=[key(f['name']) for f in p['fields_ordered'] if f.get('show')]
    labels={key(f['name']):f.get('label',f['name']) for f in p['fields_ordered']}
    view={'columns':visible[:200],'labels':labels,'field_mode':'project','native_preset':selected['name'],
          'sort_field':key(p.get('sort_field','Reference')),'sort_asc':p.get('sort_asc',True)}
    group=[key(f['name']) for f in p['fields_ordered'] if f.get('group_by')] if p.get('group_symbols') else []
    return {'schema':'wayricad-bom-authority-1','preferences':pref,'basis':basis,'preset':p,'format':fmt,
            'presets':presets,'formats':formats,'field_templates':t,'view':view,'grouping':{'fields':group,'raw':False},
            'pending_reverse':ws.state.get('native_bom_settings') is not None,
            'warnings':t['warnings']+(['View limited to 200 columns; native output retains all configured columns.'] if len(visible)>200 else []),
            'notice':'Following saved native settings by default. Custom formats, aliases and field enforcement are opt-in. Native export uses KiCad; workspace inspection is not native-attribute qualification.'}


def decorate_inventory(ws, rows, inv):
    ctx=context(ws);seen={e['name'] for e in inv['fields']};n=len(rows)
    for f in ctx['field_templates']['effective']+ctx['preset']['fields_ordered']:
        name=f['name']
        if name in seen or name.startswith('${'):continue
        seen.add(name)
        inv['fields'].append({'key':'@field:'+name,'name':name,'label':name,'kind':'native_definition',
            'present':0,'nonempty':0,'missing':n,'blank':0,'variable_cells':0,'samples':[],
            'origins':[f.get('source','native BOM preset')],'generated':False})
    inv['default_columns']=ctx['view']['columns'];inv['labels'].update(ctx['view']['labels'])
    inv['default_basis']=ctx['basis'];inv['template_defaults']=ctx['field_templates']['effective']
    inv['native_presets']=ctx['presets'];inv['native_format_settings']=ctx['format']
    inv['native_template_sources']=ctx['field_templates']
    return inv


def decorate_public(ws, data):
    ctx=context(ws);data['bom_authority']=ctx
    if ctx['preferences']['mode']=='native':
        data['saved_custom_view']=deepcopy(data['view']);data['view']=ctx['view'];data['grouping']=ctx['grouping']
        # Unassigned template fields are absent, never materialized into components.
        from .engine import Resolver
        for index,r in enumerate(data['rows'],1):
            for c in ctx['preset']['fields_ordered']:
                name=c['name']
                if not name.startswith('${'):r['fields'].setdefault('@field:'+name,'')
                elif name not in ('${QUANTITY}','${ITEM_NUMBER}','${DNP}','${EXCLUDE_FROM_BOM}','${EXCLUDE_FROM_BOARD}','${EXCLUDE_FROM_SIM}','${EXCLUDE_FROM_POS_FILES}'):
                    # Read-only supported expression display; unresolved tokens stay
                    # visible, never silently become a blank/qualified native value.
                    if '@field:'+name not in r['fields']:
                        resolver=Resolver(r.get('variables',{}));r['fields'][name]=resolver.text(name)
                        if resolver.errors:r.setdefault('native_view_warnings',[]).extend(resolver.errors)
            r['fields']['DNP']=r['flags']['dnp']
            r['fields']['Item']=index
    return data


def select(ws, mode='native', preset=None, format_preset=None, custom_template=None):
    if mode not in ('native','custom'):raise ValueError('Unknown BOM authority mode.')
    p=preferences(ws);p['mode']=mode
    for k,v in [('preset',preset),('format_preset',format_preset),('custom_template',custom_template)]:
        if v is not None:p[k]=v
    if mode=='custom' and p['custom_template'] and p['custom_template'] not in ws.state['templates']:raise ValueError('Unknown custom template.')
    # Validate on a shadow before committing.
    from types import SimpleNamespace
    context(SimpleNamespace(state=dict(ws.state,bom_preferences=p),project=ws.project))
    ws.commit('Select '+mode+' BOM format',lambda:ws.state.update(bom_preferences=p))
    return context(ws)


def configure_export(ws, settings):
    """Edit native-engine export settings without modifying a KiCad project."""
    settings = validate_native(settings)
    if not any(c['show'] for c in settings['bom_settings']['fields_ordered']):
        raise ValueError('Show at least one BOM column.')
    pref = dict(preferences(ws), mode='native', preset='@workspace', format_preset='@workspace')
    ws.commit('Edit BOM columns and formatting', lambda: ws.state.update(
        native_export_settings=settings, bom_preferences=pref))
    return context(ws)


def inherited_options(ws,variant=BASE):
    ctx=context(ws);p=ctx['preset'];f=ctx['format']
    if p.get('filter_scope') not in (None,0,'all'):raise ValueError('This native filter scope needs the native GUI; it is not silently converted.')
    fields=[c for c in p['fields_ordered'] if c.get('show')]
    if not fields:raise ValueError('The saved KiCad BOM has no visible columns. Select a native preset or deliberately customize it.')
    options={'variant':variant,'fields':[c['name'] for c in fields],'labels':[c['label'] for c in fields],
         'group_by':[c['name'] for c in p['fields_ordered'] if c.get('group_by')] if p.get('group_symbols') else [],
         'sort_field':p.get('sort_field','Reference'),'sort_asc':p.get('sort_asc',True),
         'filter':p.get('filter_string',''),'exclude_dnp':p.get('exclude_dnp',False)}
    options.update({k:f[k] for k in FORMAT if k!='name'})
    # Named presets preserve names with embedded commas without CLI list encoding.
    if ctx['preferences']['preset'] not in ('@current','@workspace'):
        options={k:v for k,v in options.items() if k not in ('fields','labels','group_by','sort_field','sort_asc','filter','exclude_dnp')}
        options['preset']=p['name']
    if ctx['preferences']['format_preset'] not in ('@current','@workspace'):
        options={k:v for k,v in options.items() if k not in FORMAT}
        options['format_preset']=f['name']
    return options


def _template(ws,name):
    ctx=context(ws);p=ctx['preset'];f=ctx['format'];warnings=[]
    def field(n):return n if n=='Reference' or n.startswith('${') else '@field:'+n
    t={'name':name,'description':'Explicit copy of KiCad settings. WayriCAD grouping/format semantics apply; native export remains separate.',
       'columns':[{'field':field(c['name']),'label':c['label'],'export':c['show']} for c in p['fields_ordered']],
       'group_by':[field(c['name']) for c in p['fields_ordered'] if c['group_by']] if p.get('group_symbols') else [],
       'sort_field':field(p.get('sort_field','Reference')),'population':'fitted' if p.get('exclude_dnp') else 'all',
       'include_excluded':p.get('include_excluded_from_bom',False),'delimiter':f['field_delimiter'],
       'ref_ranges':bool(f['ref_range_delimiter']),
       'options':{'reference_separator':f['ref_delimiter'],'range_separator':f['ref_range_delimiter'] or '-','text_mode':'resolved'}}
    if t['delimiter'] not in (',',';','\t','|'):t['delimiter']=',';warnings.append('Custom exporter uses comma: native multi-character delimiter is not representable.')
    if f['string_delimiter']!='"':warnings.append('Custom exporter uses double-quote CSV quoting; native string delimiter differs.')
    if f['keep_tabs'] or f['keep_line_breaks']:warnings.append('Custom text normalization differs from native keep-tabs/line-break settings.')
    if p.get('filter_string'):warnings.append('Native reference filter not imported as a WayriCAD query.')
    if not p.get('sort_asc',True):warnings.append('Custom template sort is ascending; native setting was descending.')
    if t['options']['range_separator']=='':t['options']['range_separator']='-'
    return t,warnings


def customize(ws,name,merge=False):
    from .catalog import validate_export_template
    if not isinstance(name,str) or not name.strip():raise ValueError('Name the custom copy.')
    t,warnings=_template(ws,name)
    if merge:
        if name not in ws.state['templates']:raise ValueError('Select an existing custom template to merge.')
        old=deepcopy(ws.state['templates'][name]);seen={c['field'].removeprefix('@field:') for c in old['columns']}
        old['columns'] += [c for c in t['columns'] if c['field'].removeprefix('@field:') not in seen]
        t=old;warnings.append('Existing custom columns and options take precedence; only absent native columns were appended.')
    elif name in ws.state['templates']:raise ValueError('Template already exists. Name a new copy or explicitly merge.')
    validate_export_template(t)
    ctx=context(ws);p=dict(ctx['preferences'],mode='custom',custom_template=name)
    def update():
        ws.state['templates'][name]=t;ws.state['bom_preferences']=p
        if not ws.state['view'].get('columns'):ws.state['view']=deepcopy(ctx['view'])
    ws.commit('Merge native columns' if merge else 'Customize native BOM copy',update)
    return {'template':t,'warnings':warnings,'notice':'Workspace only. No native files or component fields changed.'}


def reverse_preview(ws,template_name):
    if template_name not in ws.state['templates']:raise ValueError('Unknown custom BOM template.')
    t=ws.state['templates'][template_name];ctx=context(ws)
    before={'bom_settings':deepcopy(ws.project.pro.get('schematic',{}).get('bom_settings',ctx['preset'])),
            'bom_fmt_settings':deepcopy(ws.project.pro.get('schematic',{}).get('bom_fmt_settings',FORMAT))}
    map_virtual={'Qty':'${QUANTITY}','Item':'${ITEM_NUMBER}','DNP':'${DNP}','InBOM':'${EXCLUDE_FROM_BOM}',
                 'OnBoard':'${EXCLUDE_FROM_BOARD}','InPosFiles':'${EXCLUDE_FROM_POS_FILES}','ExcludeFromSim':'${EXCLUDE_FROM_SIM}'}
    physical={k for c in ws.project.components for k in c.fields}
    def native_field(value):
        if any(token in value for token in ('${PROJECT:','${FIELD:','${WORKSPACE:','${VARIANT:')):
            raise ValueError('WayriCAD-only scoped expressions cannot be written as a native BOM column.')
        if value.startswith('@field:'):return value[7:]
        if value in ('InBOM','OnBoard','InPosFiles'):
            raise ValueError('Positive inclusion column '+value+' cannot be silently inverted. Use an explicit native ${EXCLUDE_FROM_...} column.')
        if value in map_virtual:return map_virtual[value]
        if value in physical or '${' in value:return value
        raise ValueError('Column '+value+' is an alias/computed field with no native source. Select its exact physical property first.')
    if any(any(token in c.get('label','') for token in ('${PROJECT:','${FIELD:','${WORKSPACE:','${VARIANT:')) for c in t['columns']):
        raise ValueError('WayriCAD-only scoped expressions cannot be written as native BOM labels.')
    cols=[{'name':native_field(c['field']),'label':c.get('label',c['field']), 'show':c.get('export',True),
           'group_by':c['field'] in t.get('group_by',[])} for c in t['columns']]
    names={c['name'] for c in cols}
    for f in t.get('group_by',[]):
        n=native_field(f)
        if n not in names:cols.append({'name':n,'label':n,'show':False,'group_by':True});names.add(n)
    if t.get('population')=='not_fitted':raise ValueError('DNP-only population is not representable by native exclude-DNP. Use the native editor or keep this custom format.')
    o=t.get('options',{});f=dict(ctx['format']);f.update(name='WayriCAD '+template_name,
        field_delimiter=t.get('delimiter',','),string_delimiter='"',ref_delimiter=o.get('reference_separator',', '),
        ref_range_delimiter=o.get('range_separator','-') if t.get('ref_ranges') else '')
    p=dict(ctx['preset']);p.update(name='WayriCAD '+template_name,fields_ordered=cols,
        sort_field=native_field(t.get('sort_field','Reference')),sort_asc=True,filter_string='',
        group_symbols=bool(t.get('group_by')),exclude_dnp=t.get('population')=='fitted',
        include_excluded_from_bom=bool(t.get('include_excluded',False)))
    after=validate_native({'bom_settings':p,'bom_fmt_settings':f})
    payload={'template':template_name,'settings':after,'global_templates_sha256':ctx['field_templates']['global_sha256']}
    from .bulkedit import digest
    diff=''.join(difflib.unified_diff(json.dumps(before,indent=2,ensure_ascii=False).splitlines(True),
             json.dumps(after,indent=2,ensure_ascii=False).splitlines(True),fromfile='saved KiCad format',tofile='proposed format'))
    return {'schema':'wayricad-format-plan-1','template':template_name,'settings':after,'before':before,'diff':diff,
            'fingerprint':digest(ws,payload),'warnings':['Replaces this project\'s saved BOM columns and formatting, not symbol fields or global preferences.',
            'Native grouping, expression and exclusion behavior differ from WayriCAD. No pricing arithmetic or custom-only settings are written.',
            'Native reference filters are reset; sort is ascending. Review the complete diff.'],
            'notice':'FORMAT stages workspace settings. The separate backed-up native APPLY writes them after editors are closed.'}


def reverse_apply(ws,template_name,fingerprint,confirmation,acknowledge=False):
    if confirmation!='FORMAT' or acknowledge is not True:raise ValueError('Review the format diff, acknowledge replacement, and type FORMAT.')
    ws.project.check_unchanged();p=reverse_preview(ws,template_name)
    if p['fingerprint']!=fingerprint:raise ValueError('Format review is stale. Preview again.')
    ws.commit('Stage reviewed custom-to-KiCad format',lambda:ws.state.update(native_bom_settings=deepcopy(p['settings'])))
    return {'staged':True,'native_files_changed':False}
