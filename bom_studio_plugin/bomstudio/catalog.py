"""Portable data-only BOM, view and field-schema templates.

No executable template hooks, variable definitions, component rows, file paths or
project identifiers are exported implicitly. Literal template defaults can still
be sensitive, so sharing is always explicit.
"""
from __future__ import annotations
from . import __version__
from copy import deepcopy
import json
from .engine import validate_name, TEMPLATES, ALIASES

BUNDLE_FORMAT='wayricad-bom-template-bundle'
SECTIONS=('templates','field_profiles','view_presets')
PROTECTED={'Reference','Value','Footprint','Datasheet','Description','Assembly'}
DANGEROUS={'__proto__','prototype','constructor'}
EXPORT_DEFAULTS={'encoding':'utf-8-sig','line_ending':'crlf','quoting':'minimal',
                 'text_mode':'resolved','ascii_policy':'escape','ascii_width':36,
                 'reference_separator':', ','range_separator':'–'}


def text(value,limit=32767):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\t\r\n' for c in value):
        raise ValueError('Invalid text or text length exceeds '+str(limit)+'.')


def name(value):
    validate_name(value)
    if value in DANGEROUS: raise ValueError('Reserved template/field name: '+value)


def protected(field):
    return field in PROTECTED or field.casefold().startswith(('ki_','sim.','spice_'))


def validate_columns(columns,visible_required=True):
    if not isinstance(columns,list) or not 1<=len(columns)<=200:raise ValueError('Choose 1–200 columns.')
    labels=[]
    for c in columns:
        if not isinstance(c,dict):raise ValueError('A column must be an object.')
        if set(c)-{'field','label','visible','export','width'}:raise ValueError('Unknown column option.')
        text(c.get('field'),512);text(c.get('label'),512)
        if not c['field'].strip() or not c['label'].strip():raise ValueError('Field/expression and header label cannot be blank.')
        for k in ('visible','export'):
            if k in c and type(c[k]) is not bool:raise ValueError(k+' must be a checkbox value.')
        if c.get('export',True):labels.append(c['label'])
        if 'width' in c and (type(c['width']) is not int or not 8<=c['width']<=100):raise ValueError('Column width must be 8–100 characters.')
    if visible_required and not labels:raise ValueError('Keep at least one exported column.')
    if len(set(labels))!=len(labels):raise ValueError('Exported column labels must be unique.')


def validate_export_template(t):
    if not isinstance(t,dict):raise ValueError('Template must be an object.')
    if set(t)-{'name','columns','group_by','population','include_excluded','delimiter','ref_ranges','sort_field','options','author','description','revision'}:raise ValueError('Unknown BOM template key.')
    name(t.get('name',''));validate_columns(t.get('columns'))
    if t.get('population','all') not in ('all','fitted','not_fitted'):raise ValueError('Invalid population filter.')
    if t.get('delimiter',',') not in (',',';','\t','|'):raise ValueError('Invalid delimiter.')
    for key in ('include_excluded','ref_ranges'):
        if key in t and type(t[key]) is not bool:raise ValueError(key+' requires a boolean.')
    group=t.get('group_by',[])
    if not isinstance(group,list) or len(group)>100 or any(not isinstance(k,str) or len(k)>512 for k in group):raise ValueError('Invalid grouping fields.')
    options=t.get('options',{})
    if not isinstance(options,dict) or set(options)-set(EXPORT_DEFAULTS):raise ValueError('Unknown export option.')
    choices={'encoding':('utf-8-sig','utf-8','ascii','cp1252'),'line_ending':('crlf','lf'),
             'quoting':('minimal','all'),'text_mode':('resolved','raw'), 'ascii_policy':('escape','error')}
    for key,allowed in choices.items():
        if options.get(key,EXPORT_DEFAULTS[key]) not in allowed:raise ValueError('Invalid '+key+'.')
    w=options.get('ascii_width',36)
    if type(w) is not int or not 8<=w<=120:raise ValueError('ASCII width must be 8–120.')
    for key in ('reference_separator','range_separator'):
        text(options.get(key,EXPORT_DEFAULTS[key]),16)
        if any(ord(c)<32 for c in options.get(key,'')):raise ValueError('Reference delimiters must be single-line text.')
    for key in ('author','description','revision'):
        text(t.get(key,''),4096)


def validate_profile(profile):
    if not isinstance(profile,dict):raise ValueError('Field profile must be an object.')
    if set(profile)-{'name','fields','author','description','revision'}:raise ValueError('Unknown field template key.')
    name(profile.get('name',''))
    fields=profile.get('fields')
    if not isinstance(fields,list) or not 1<=len(fields)<=200:raise ValueError('Define 1–200 field names.')
    names=[]
    for f in fields:
        if not isinstance(f,dict):raise ValueError('Each field must be an object.')
        if set(f)-{'name','aliases','default','visible','url','required'}:raise ValueError('Unknown field template option.')
        name(f.get('name',''));text(f.get('default',''))
        if protected(f['name']):raise ValueError('Standard/reserved field is managed by KiCad, not the custom field schema: '+f['name'])
        names.append(f['name'])
        aliases=f.get('aliases',[])
        if not isinstance(aliases,list) or len(aliases)>100:raise ValueError('Invalid field aliases.')
        for alias in aliases:
            name(alias)
            if protected(alias):raise ValueError('Cannot rename a protected field through an alias.')
        for k in ('visible','url','required'):
            if k in f and type(f[k]) is not bool:raise ValueError(k+' must be boolean.')
    alias_owners={}
    for f in fields:
        for alias in [f['name'],*f.get('aliases',[])]:
            if alias.casefold() in alias_owners and alias_owners[alias.casefold()]!=f['name']:raise ValueError('Alias belongs to more than one field: '+alias)
            alias_owners[alias.casefold()]=f['name']
    if len({x.casefold() for x in names})!=len(names):raise ValueError('Field names conflict ignoring case.')
    for key in ('description','author','revision'):text(profile.get(key,''),4096)


def validate_view(view):
    if not isinstance(view,dict):raise ValueError('View must be an object.')
    if set(view)-{'name','columns','labels','field_mode','native_preset','sort_field','sort_asc'}:raise ValueError('Unknown column layout option.')
    labels=view.get('labels',{})
    if not isinstance(labels,dict) or len(labels)>2000:raise ValueError('Invalid column labels.')
    for k,v in labels.items():name(k);text(v,500)
    if view.get('field_mode','project') not in ('project','custom'):raise ValueError('Unknown field mode.')
    if 'sort_asc' in view and type(view['sort_asc']) is not bool:raise ValueError('Sort order must be a boolean.')
    for k in ('sort_field','native_preset'):
        if k in view:text(view[k],500)
    columns=view.get('columns')
    if not isinstance(columns,list) or not 1<=len(columns)<=200:raise ValueError('Choose 1–200 workspace columns.')
    for c in columns:name(c)
    if len(set(columns))!=len(columns):raise ValueError('Duplicate workspace column.')


def upgrade_state(state):
    state.setdefault('aliases',{}).setdefault('LCSC',deepcopy(ALIASES['LCSC']))
    state.setdefault('view',{'columns':[]});state.setdefault('view_presets',{})
    state.setdefault('field_profiles',{});state.setdefault('field_schema_edits',{})
    state.setdefault('native_field_templates',None);state.setdefault('native_bom_presets',{})
    if not state['field_profiles']:
        state['field_profiles']['Engineering standard']={'name':'Engineering standard','revision':'1','author':'',
          'description':'Normalize common purchasing fields. Existing expressions are preserved unless you explicitly bake or reset them.',
          'fields':[{'name':n,'aliases':a,'default':'','visible':False,'url':False,'required':n=='MPN'} for n,a in [
              ('MPN',['Mfr Part Number','Manufacturer Part Number','Part Number']),
              ('Manufacturer',['Mfr','MFG']),('InternalPN',['Internal Part Number']),
              ('Supplier',['Vendor']),('SKU',['Supplier Part Number']),('UnitPrice',['Unit Price']),
              ('Currency',[]),('Notes',['Comment'])]]}
    # Existing custom names always win during migration.
    if not state.get('starter_profiles_v2'):
        for title,cols in {
            'Generic ERP CSV':[('InternalPN','Part Number'),('Description','Description'),('Required','Quantity'),('MPN','Manufacturer Part Number'),('Manufacturer','Manufacturer'),('Currency','Currency'),('Reference','References')],
            'JLCPCB assembly CSV':[('Value','Comment'),('Reference','Designator'),('Footprint','Footprint'),('LCSC','LCSC Part #')],
            'ASCII engineering report':[(x,x) for x in ['Item','Reference','Qty','Value','Footprint','MPN','Assembly']],
        }.items():
            t=deepcopy(TEMPLATES['Assembly']);t.update(name=title,columns=[{'field':f,'label':l} for f,l in cols])
            if title=='JLCPCB assembly CSV':t.update(population='fitted',ref_ranges=False)
            state['templates'].setdefault(title,t)
        state['starter_profiles_v2']=True
    state['app_version']=__version__


def set_view(ws,view,preset=None):
    validate_view(view)
    if preset:name(preset)
    def change():
        ws.state['view']=deepcopy(view)
        from .nativefirst import preferences
        ws.state['bom_preferences']=dict(preferences(ws),mode='custom')
        if preset:ws.state['view_presets'][preset]=dict(deepcopy(view),name=preset)
    ws.commit('Set BOM columns'+(' / '+preset if preset else ''),change)


def save_profile(ws,profile):
    validate_profile(profile)
    ws.commit('Save field name template '+profile['name'],lambda:ws.state['field_profiles'].update({profile['name']:deepcopy(profile)}))


def manage(ws,section,operation,old,new=None):
    if section not in SECTIONS:raise ValueError('Unknown template section.')
    if old not in ws.state[section]:raise ValueError('Template no longer exists.')
    if operation not in ('rename','duplicate','delete'):raise ValueError('Invalid template operation.')
    if operation!='delete':
        name(new)
        if new.casefold() in {n.casefold() for n in ws.state[section]}:raise ValueError('Name already exists.')
    if section=='templates' and operation=='delete' and len(ws.state[section])==1:raise ValueError('Keep at least one BOM template.')
    def change():
        if operation!='delete':ws.state[section][new]=dict(deepcopy(ws.state[section][old]),name=new)
        if operation!='duplicate':ws.state[section].pop(old)
    ws.commit(operation.title()+' '+old,change)


def clean_template(t):
    # Deliberate allowlist: no proprietary component rows or executable keys.
    return {k:deepcopy(v) for k,v in t.items() if k in {'name','columns','group_by','population','include_excluded','delimiter','ref_ranges','sort_field','options','author','description','revision'}}


def bundle(ws,section=None,selected=None):
    result={'format':BUNDLE_FORMAT,'schema':1,'app_version':__version__,
            'notice':'Definitions only. No component rows, source paths or project variable definitions. Review literal defaults/expressions before sharing.'}
    if section and section not in SECTIONS:raise ValueError('Unknown template kind.')
    for key in SECTIONS:
        items=ws.state[key] if section is None or key==section else {}
        if selected:
            if section is None:raise ValueError('Choose a template kind for single-template sharing.')
            items={n:t for n,t in items.items() if n==selected}
        if key=='templates':result[key]=[clean_template(t) for t in items.values()]
        elif key=='field_profiles':result[key]=[{k:deepcopy(v) for k,v in t.items() if k in {'name','fields','author','description','revision'}} for t in items.values()]
        else:result[key]=[{'name':n,'columns':v['columns']} for n,v in items.items()]
    return result


def parse_bundle(raw):
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>2*1024*1024:raise ValueError('Template file must be JSON smaller than 2 MiB.')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d or k in DANGEROUS:raise ValueError('Duplicate or unsafe JSON key: '+k)
            d[k]=v
        return d
    b=json.loads(raw.lstrip('\ufeff'),object_pairs_hook=pairs)
    if not isinstance(b,dict) or b.get('format')!=BUNDLE_FORMAT or type(b.get('schema')) is not int or b['schema']!=1:raise ValueError('Unsupported template bundle format/version.')
    if set(b)-{'format','schema','app_version','notice',*SECTIONS}:raise ValueError('Unknown bundle section. No scripts/hooks are allowed.')
    for key,validator in [('templates',validate_export_template),('field_profiles',validate_profile),('view_presets',validate_view)]:
        entries=b.get(key,[])
        if not isinstance(entries,list) or len(entries)>100:raise ValueError('A bundle supports up to 100 templates of each type.')
        names=set()
        for item in entries:
            validator(item);name(item.get('name',''))
            if item['name'].casefold() in names:raise ValueError('Duplicate template name: '+item['name'])
            names.add(item['name'].casefold())
    if not any(b.get(k) for k in SECTIONS):raise ValueError('This bundle has no template definitions.')
    return b


def import_preview(ws,raw,policy='keep_both'):
    if policy not in ('keep_both','replace','skip'):raise ValueError('Choose keep both, replace or skip.')
    b=parse_bundle(raw);items=[]
    for section in SECTIONS:
        used={n.casefold():n for n in ws.state[section]}
        for item in b.get(section,[]):
            n=item['name'];collision=n.casefold() in used
            if collision and policy=='keep_both':
                base=n[:100];i=2;n=base+' (imported)'
                while n.casefold() in used:n=base+f' (imported {i})';i+=1
            elif collision:n=used[n.casefold()]
            used[n.casefold()]=n
            items.append({'section':section,'source':item['name'],'target':n,
                          'action':'skip' if collision and policy=='skip' else 'replace' if collision and policy=='replace' else 'add',
                          'definition':dict(deepcopy(item),name=n)})
    return {'items':items,'policy':policy,'warning':'Import changes definitions only; it never enforces fields, loads variable values, or edits native files.'}


def import_apply(ws,raw,policy='keep_both'):
    preview=import_preview(ws,raw,policy)
    def change():
        for item in preview['items']:
            if item['action']!='skip':ws.state[item['section']][item['target']]=item['definition']
    ws.commit('Import portable template definitions ('+policy+')',change)
    return preview
