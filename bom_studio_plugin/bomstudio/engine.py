"""Workspace, effective values, validation, procurement, and undo/redo."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
import csv
import io
import json
import math
import os
import re
import tempfile
from .native import Project, BASE, FLAGS, natural, sha, variant_lookup, is_generated_field

ALIASES = {
 'MPN':['MPN','Manufacturer Part Number','Manufacturer_Part_Number','Mfr Part Number','Mfr_PN','Part Number'],
 'Manufacturer':['Manufacturer','Mfr','MFG'],
 'Supplier':['Supplier','Distributor','Vendor'],
 'SKU':['SKU','Supplier Part Number','Supplier_Part_Number','Distributor Part Number'],
 'UnitPrice':['UnitPrice','Unit Price','Price','Cost'],
 'Currency':['Currency'], 'Stock':['Stock','Available'], 'MOQ':['MOQ'], 'OrderMultiple':['OrderMultiple','Order Multiple'],
 'LeadTime':['LeadTime','Lead Time','Lead Time (weeks)'], 'Lifecycle':['Lifecycle','Life Cycle'],
 'InternalPN':['InternalPN','Internal Part Number','Company Part Number'],
 'LCSC':['LCSC','LCSC Part #','JLCPCB Part #','JLCPCB/LCSC Part #','LCSC Part Number'],
 'Assembly':['Assembly','Population'], 'Notes':['Notes','Comment'], 'PriceDate':['PriceDate','Price Date']
}
STANDARD_COLUMNS = ['Reference','Value','Footprint','MPN','Manufacturer','Assembly','Qty','Required','UnitPrice','Currency','LineCost']
TEMPLATES = {
 'Engineering':{'name':'Engineering','columns':[{'field':x,'label':x} for x in STANDARD_COLUMNS], 'group_by':['Value','Footprint','MPN','Manufacturer'], 'population':'all','include_excluded':False,'delimiter':',','ref_ranges':True},
 'Assembly':{'name':'Assembly','columns':[{'field':x,'label':x} for x in ['Reference','Qty','Value','Footprint','MPN','Assembly','Notes']], 'group_by':['Value','Footprint','MPN'],'population':'all','include_excluded':False,'delimiter':',','ref_ranges':False},
 'Purchasing':{'name':'Purchasing','columns':[{'field':x,'label':x} for x in ['MPN','Manufacturer','Supplier','SKU','Required','OrderQty','UnitPrice','Currency','OrderCost','Stock','MOQ','OrderMultiple','LeadTime','PriceDate','Reference']], 'group_by':['MPN','Manufacturer','Value','Footprint'],'population':'fitted','include_excluded':False,'delimiter':',','ref_ranges':False},
 'Not fitted':{'name':'Not fitted','columns':[{'field':x,'label':x} for x in ['Reference','Value','Footprint','MPN','Assembly','Notes']], 'group_by':[],'population':'not_fitted','include_excluded':True,'delimiter':',','ref_ranges':False},
 'Full audit':{'name':'Full audit','columns':[{'field':x,'label':x} for x in ['Reference','Value','Footprint','MPN','Manufacturer','Assembly','InBOM','OnBoard','InPosFiles','ExcludeFromSim','Sheet','UUID','Source','Notes']], 'group_by':[],'population':'all','include_excluded':True,'delimiter':'\t','ref_ranges':False}
}
STATES = {'FIT','DNP','DNI'}
COMPUTED = {'Qty','Required','OrderQty','LineCost','OrderCost','Item','Reference','UUID','Source'}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def decimal_value(value, default=None):
    if value is None or str(value).strip() == '':
        return default
    try:
        n = Decimal(str(value).strip())
        return n if n.is_finite() and 0 <= n <= Decimal('1e18') and (not n or n.adjusted() >= -18) else default
    except (InvalidOperation,ValueError):
        return default


def integer_value(value, default=1):
    n = decimal_value(value)
    return int(n) if n is not None and n >= 1 and n == int(n) else default


def canonical(fields, name, aliases):
    if fields.get(name,'') != '':
        return str(fields[name])
    folded = {k.casefold():v for k,v in fields.items()}
    for key in aliases.get(name,[name]):
        if str(folded.get(key.casefold(),'')) != '':
            return str(folded[key.casefold()])
    return ''


def validate_name(name: str):
    if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(c)<32 for c in name):
        raise ValueError('Use a nonempty name of at most 128 characters, without control characters.')


class Resolver:
    pattern = re.compile(r'\$\{([^{}]+)\}')
    def __init__(self, variables: dict[str,str]):
        self.variables = variables
        self.errors: list[str] = []
        self.cache: dict[str,str] = {}
        self.steps=0
    def value(self, key, stack=()):
        self.steps+=1
        if self.steps>8192:
            if self.steps==8193:self.errors.append('Variable evaluation limit exceeded; expressions were preserved.')
            return '${'+key+'}'
        if key in self.cache:
            return self.cache[key]
        if key in stack or len(stack)>32:
            self.errors.append('Variable cycle: ' + ' → '.join(stack+(key,)))
            return '${'+key+'}'
        if key not in self.variables:
            self.errors.append('Unresolved variable: '+key)
            return '${'+key+'}'
        result = self.text(str(self.variables[key]),stack+(key,))
        if '${' not in result:
            self.cache[key] = result
        return result
    def text(self, text, stack=()):
        text=str(text);pieces=[];last=0;length=0
        # Preserve unsupported KiCad expression grammars rather than produce a
        # plausible but wrong purchasing value. Draft/raw inspection is allowed.
        if re.search(r'\\[$@]\{|@\{|\$\{[^}]*\$\{|\$\{\}',text):
            self.errors.append('Unsupported escaped/nested/math expression requires KiCad evaluation; raw expression preserved: '+text[:160])
            return text
        if text.count('${')!=len(list(self.pattern.finditer(text))):
            self.errors.append('Malformed or unsupported variable expression preserved: '+text[:160])
            return text
        for match in self.pattern.finditer(text):
            value=self.value(match[1],stack);prefix=text[last:match.start()]
            length+=len(prefix)+len(value)
            if length>262144:
                self.errors.append('Variable expansion exceeds 262144 characters; expression was preserved.')
                return text
            pieces.extend((prefix,value));last=match.end()
        pieces.append(text[last:])
        return ''.join(pieces)


def fresh_state():
    return {'schema':1,'app_version':'3.1.1','base':{},'variants':{},'variables':{},
            'project_variables':{},'aliases':deepcopy(ALIASES),'templates':deepcopy(TEMPLATES),
            'settings':{'boards':1,'attrition':0,'currency':'INR','required_fields':['MPN','Footprint'], 'quote_age_days':90},
            'alternates':{},'history':[],'baseline':None,
            'view':{'columns':[]},'view_presets':{},'field_profiles':{},'field_schema_edits':{},
            'assembler_export_settings':{},'vendor_export_settings':{},'analytics_settings':{},'native_field_templates':None,'native_bom_presets':{},'native_bom_settings':None,'native_export_settings':None,'bom_preferences':{},'evidence':[], 'health_settings':{},'grouping':{'fields':[],'raw':False}}


class Workspace:
    def __init__(self, project: Project, load=True):
        self.project = project
        self.sidecar = project.root.with_suffix('.wayricad-bom.json')
        self.sidecar_hash = sha(self.sidecar.read_bytes()) if self.sidecar.exists() else None
        self.state = fresh_state()
        if load and self.sidecar.exists():
            raw = json.loads(self.sidecar.read_text(encoding='utf-8-sig'))
            if raw.get('schema') != 1:
                raise ValueError('Unsupported workspace schema. Nothing has been changed.')
            self.state.update(raw)
        from .catalog import upgrade_state
        upgrade_state(self.state)
        self.state.setdefault('evidence',[])
        self.state.setdefault('health_settings',{})
        self.state.setdefault('grouping',{'fields':[],'raw':False})
        self.state['app_version']='3.1.1'
        self._validate_state()
        for name,desc in project.variant_descriptions.items():
            if name.casefold() not in {n.casefold() for n in self.state['variants']}:
                self.state['variants'][name] = {'description':desc,'parent':BASE,'overrides':{},'variables':{},'native':True}
        self.state.setdefault('source_hashes', project.hashes)
        self.saved_json = self._serialize()
        self.undo_stack: list[str] = []
        self.redo_stack: list[str] = []
        self.preview_cache = None
        self.revision = 0

    def _validate_state(self):
        from .assembler_export import validate_config as validate_assembler
        validate_assembler(self.state.get('assembler_export_settings',{}))
        from .vendor_export import validate_config as validate_vendor
        validate_vendor(self.state.get('vendor_export_settings',{}))
        from .nativefirst import preferences, validate_native
        preferences(self)
        if self.state.get('native_bom_settings') is not None:validate_native(self.state['native_bom_settings'])
        if self.state.get('native_export_settings') is not None:validate_native(self.state['native_export_settings'])
        eng=self.state.get('engineering',{})
        if not isinstance(eng,dict) or set(eng)-{'library','shared_alternates'} or not isinstance(eng.get('library',''),str) or len(eng.get('library',''))>4096:
            raise ValueError('Invalid engineering library settings.')
        from .sharedparts import validate_alternates
        validate_alternates(eng.get('shared_alternates',{}))
        from .analytics import validate_config
        validate_config(self.state.get('analytics_settings',{}))
        from .search import validate_filters
        validate_filters(self.state.get('saved_filters',{}))
        if not isinstance(self.state.get('evidence',[]),list) or not isinstance(self.state.get('health_settings',{}),dict) or not isinstance(self.state.get('grouping',{}),dict):
            raise ValueError('Invalid health/evidence/grouping state.')
        from .evidence import validate_ledger
        from .intelligence import validated_settings
        validate_ledger(self.state.get('evidence',[]))
        validated_settings(self.state.get('health_settings',{}))
        g=self.state.get('grouping',{});fields=g.get('fields',[])
        if not isinstance(fields,list) or len(fields)>30 or any(not isinstance(x,str) or not x or len(x)>1000 for x in fields) or len(set(fields))!=len(fields) or type(g.get('raw',False)) is not bool:
            raise ValueError('Invalid presentation grouping.')
        for key in ['base','variants','variables','project_variables','aliases','templates','settings','alternates','view','view_presets','field_profiles','field_schema_edits','native_bom_presets']:
            if not isinstance(self.state.get(key),dict):
                raise ValueError('Invalid workspace section: '+key)
        for name,v in self.state['variants'].items():
            validate_name(name)
            if name.casefold() in (BASE.casefold(),'default') or not isinstance(v,dict):
                raise ValueError('Invalid variant data.')
        from .variantlab import validate as validate_variants
        validate_variants(self)
        if len({x.casefold() for x in self.state['variants']}) != len(self.state['variants']):
            raise ValueError('Variant names conflict ignoring case.')
        for name,t in self.state['templates'].items():
            self.validate_template(t)
        self.validate_settings(self.state['settings'])
        from .catalog import validate_profile, validate_view
        for profile in self.state['field_profiles'].values():validate_profile(profile)
        for view in self.state['view_presets'].values():validate_view(view)
        if self.state['view'].get('columns'):validate_view(self.state['view'])

    def _serialize(self):
        return json.dumps(self.state,ensure_ascii=False,sort_keys=True,separators=(',',':'))

    @property
    def dirty(self):
        return self._serialize() != self.saved_json

    def commit(self, description, function):
        before = self._serialize()
        try:
            result = function()
            self._validate_state()
        except Exception:
            self.state = json.loads(before)
            raise
        after = self._serialize()
        if before != after:
            self.undo_stack.append(before)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.state['history'].append({'time':now(),'action':description})
            self.state['history'] = self.state['history'][-500:]
            self.preview_cache = None
            self.revision += 1
        return result

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._serialize())
            self.state = json.loads(self.undo_stack.pop())
            self.revision += 1
            self.preview_cache = None

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._serialize())
            self.state = json.loads(self.redo_stack.pop())
            self.revision += 1
            self.preview_cache = None

    def variant_chain(self, name):
        if name == BASE:
            return []
        if name not in self.state['variants']:
            raise ValueError('Unknown variant: '+name)
        chain=[]
        while name != BASE:
            if name in chain or len(chain)>64 or name not in self.state['variants']:
                raise ValueError('Invalid variant inheritance or cycle.')
            chain.insert(0,name)
            name = self.state['variants'][name].get('parent',BASE)
        return chain

    def variables(self, variant=BASE):
        values=dict(self.project.variables)
        for k,v in self.state['project_variables'].items():
            if v is None:
                values.pop(k,None)
            else:
                values[k]=v
        values.update(self.state['variables'])
        for v in self.variant_chain(variant):
            values.update(self.state['variants'][v].get('variables',{}))
        return values

    def own(self, c, variant=BASE):
        fields, flags, origins = dict(c.fields),dict(c.flags),{}
        for key,value in self.state['base'].get(c.id,{}).items():
            (flags if key in FLAGS else fields)[key]=value
            origins[key]='Workspace base'
        staged = self.state.get('field_schema_edits',{}).get(BASE,{}).get(c.id)
        if staged is not None:
            fields={k:staged['fields'][k] for k in dict.fromkeys([*staged.get('order',[]),*staged['fields']]) if k in staged['fields']}
            origins.update({k:'Reviewed field schema' for k in fields})
        base_fields,base_flags=dict(fields),dict(flags)
        for v in self.variant_chain(variant):
            parent_fields=dict(fields)
            native = variant_lookup(c.native,v,{})
            fields.update(native.get('fields',{}));flags.update(native.get('flags',{}))
            for key in [*native.get('fields',{}),*native.get('flags',{})]:origins[key]='Native: '+v
            for key,value in self.state['variants'][v].get('overrides',{}).get(c.id,{}).items():
                target=flags if key in FLAGS else fields
                if value is None:
                    target[key]=(base_flags if key in FLAGS else base_fields).get(key,'')
                    origins[key]='Reset to base'
                else:target[key]=value;origins[key]='Workspace: '+v
            staged=self.state.get('field_schema_edits',{}).get(v,{}).get(c.id)
            if staged is not None:
                fields={k:staged['fields'][k] for k in dict.fromkeys([*staged.get('order',[]),*staged['fields']]) if k in staged['fields']}
                for key in staged.get('inherit',[]):
                    if key in parent_fields:fields[key]=parent_fields[key]
                for key in staged.get('reset_base',[]):fields[key]=base_fields.get(key,'')
                origins.update({k:'Reviewed field schema' for k in fields})
        return fields,flags,origins

    def rows(self, variant=BASE):
        chain=self.variant_chain(variant)
        variables=self.variables(variant)
        result=[]
        own_data={c.id:self.own(c,variant) for c in self.project.components}
        ref_map={c.ref:c for c in self.project.components}
        for c in self.project.components:
            fields,flags,origins=own_data[c.id]
            fields,flags=dict(fields),dict(flags)
            sheet_vars={}
            inherited=[]
            for a in c.ancestors:
                af,ff=dict(a.flags),dict(a.fields)
                for v in chain:
                    n=variant_lookup(a.native,v,{})
                    af.update(n.get('flags',{}));ff.update(n.get('fields',{}))
                sheet_vars.update(ff)
                for k in FLAGS:
                    active=af[k] if k in ('dnp','exclude_from_sim') else not af[k]
                    if active:
                        flags[k]=af[k]
                        inherited.append(a.name+': '+k)
            builtins={'PROJECTNAME':self.project.name,'KIPRJMOD':str(self.project.root.parent),
                      'VARIANT':'' if variant==BASE else variant,
                      'VARIANT_DESC':self.state['variants'].get(variant,{}).get('description',''),
                      'REFERENCE':c.ref,'VALUE':fields.get('Value',''),'FOOTPRINT':fields.get('Footprint',''),
                      'SHEETNAME':c.ancestors[-1].name if c.ancestors else self.project.name,
                      'SHEETPATH':c.sheet,'DNP':'DNP' if flags['dnp'] else '',
                      'EXCLUDE_FROM_BOM':'Excluded from BOM' if not flags['in_bom'] else '',
                      'EXCLUDE_FROM_BOARD':'Excluded from board' if not flags['on_board'] else '',
                      'EXCLUDE_FROM_SIM':'Excluded from simulation' if flags['exclude_from_sim'] else '',
                      'EXCLUDE_FROM_POS_FILES':'Excluded from position files' if not flags['in_pos_files'] else '',
                      'SYMBOL_LIBRARY':c.lib_id.rsplit(':',1)[0] if ':' in c.lib_id else '',
                      'SYMBOL_NAME':c.lib_id.rsplit(':',1)[-1],
                      'DATASHEET':fields.get('Datasheet',''),'DESCRIPTION':fields.get('Description',''),
                      'FOOTPRINT_LIBRARY':fields.get('Footprint','').rsplit(':',1)[0] if ':' in fields.get('Footprint','') else '',
                      'FOOTPRINT_NAME':fields.get('Footprint','').rsplit(':',1)[-1]}
            context={**variables,**sheet_vars,**fields,**builtins}
            context.update({'PROJECT:'+k:v for k,v in variables.items()})
            context.update({'FIELD:'+k:v for k,v in fields.items()})
            # One-hop reference lookups; recursively resolve variables within the referenced value.
            for text in [*fields, *fields.values()]:
                for match in Resolver.pattern.finditer(str(text)):
                    key=match[1]
                    if ':' in key and key.split(':',1)[0] in ref_map:
                        ref,f=key.split(':',1)
                        context[key]=own_data[ref_map[ref].id][0].get(f,'${'+key+'}')
            resolver=Resolver(context)
            for k,v in fields.items():
                if is_generated_field(k) and v != k:
                    resolver.errors.append('Generated KiCad field '+k+' must have the same expression as its value; stored value differs. Repair explicitly before release/native sync.')
            resolved={k:resolver.text(k if is_generated_field(k) else v) for k,v in fields.items()}
            output=dict(resolved)
            resolved_names={k:(k[2:-1] if is_generated_field(k) else resolver.text(k)) for k in fields}
            name_sources={}
            for raw_name, name in resolved_names.items():
                if not name.strip():
                    resolver.errors.append('Field name resolves to an empty name: '+raw_name)
                if name in name_sources and name_sources[name]!=raw_name:
                    resolver.errors.append('Resolved field-name collision: '+name_sources[name]+' / '+raw_name+' -> '+name)
                if name != raw_name and name in resolved:
                    resolver.errors.append('Resolved field-name collision: '+raw_name+' -> '+name)
                name_sources[name]=raw_name
                if name not in output: output[name]=resolved[raw_name]
            # Keep the exact physical source for alias editing and raw exports.
            # A generated ${NAME} displays NAME, not the variable's value.
            source_map={**{k:k for k in fields},**name_sources}
            alias_conflicts=[]
            for key,aliases in self.state['aliases'].items():
                candidates=[key]+list(aliases)
                wanted={x.casefold() for x in candidates}
                observed={k:str(v) for k,v in resolved.items() if k.casefold() in wanted and str(v).strip()}
                if len(set(observed.values()))>1:
                    alias_conflicts.append({'alias':key,'values':observed,'message':'Different nonempty physical values map to '+key+'. Exact columns remain unchanged.'})
                folded={k.casefold():k for k in output}
                chosen=key if output.get(key,'')!='' else next((folded[a.casefold()] for a in aliases if a.casefold() in folded and str(output[folded[a.casefold()]])!=''),None)
                output[key]=canonical(output,key,self.state['aliases'])
                if chosen is not None and chosen in source_map:source_map[key]=source_map[chosen]
            name_sources.update(source_map)
            label=output.get('Assembly','').strip().upper()
            # Legacy text fields NEVER silently override the native DNP boolean.
            assembly = (label if label in ('DNP','DNI') else 'DNP') if flags['dnp'] else 'FIT'
            if flags['dnp'] and any(item.endswith(': dnp') for item in inherited):
                assembly='DNP'
            output.update({'Reference':c.ref,'Assembly':assembly,'InBOM':flags['in_bom'],
                           'OnBoard':flags['on_board'],'InPosFiles':flags['in_pos_files'],
                           'ExcludeFromSim':flags['exclude_from_sim'],'Sheet':c.sheet,'UUID':c.id,
                           'Source':str(c.members[0].doc.path),'Qty':1,
                           'Currency':output.get('Currency','') or self.state['settings']['currency']})
            output.update({'@field:'+k:v for k,v in resolved.items()})
            output.update({'@attribute:exclude_bom':not flags['in_bom'],'@attribute:exclude_board':not flags['on_board'],'@attribute:exclude_pos':not flags['in_pos_files']})
            name_sources.update({'@field:'+k:k for k in fields})
            result.append({'id':c.id,'ref':c.ref,'fields':output,'raw':fields,'physical':resolved,'alias_conflicts':alias_conflicts,'flags':flags,
                           'origins':origins,'inherited':inherited,'variables':context,
                           'resolved_names':resolved_names,'field_name_sources':name_sources,
                           'generated_fields':[k for k in fields if is_generated_field(k)],
                           'errors':list(dict.fromkeys(resolver.errors)),
                           'legacy_population': label if (label in ('DNP','DNI') and not flags['dnp']) else '',
                           'units':len(c.members),'lib_id':c.lib_id})
        return result

    def edit(self, ids: list[str], variant: str, changes: dict):
        if self.state['variants'].get(variant,{}).get('locked'):raise ValueError('Independent BOM variant is locked.')
        if not ids or len(ids)>100000 or not changes:
            raise ValueError('Select at least one component and one field.')
        self.variant_chain(variant)
        for key,value in changes.items():
            validate_name(key)
            if is_generated_field(key) and value is not None and value!=key:
                raise ValueError('Generated KiCad field '+key+' has a linked value. Use the same expression as its value, change the project variable, or explicitly bake/rename the field through Enforce.')
            if key in ('Reference','UUID') or key in ('Source','Qty') and not all(key in self.own(self.project.by_id[cid],variant)[0] for cid in ids if cid in self.project.by_id):
                raise ValueError(f'{key} is read-only. References are managed by KiCad annotation.')
            if key in FLAGS and value is not None and type(value) is not bool:
                raise ValueError(f'{key} requires a boolean, not text.')
            if key not in FLAGS and value is not None and (not isinstance(value,str) or len(value)>32767 or any(ord(c)<32 and c not in '\t\n\r' for c in value)):
                raise ValueError('Fields must contain text of at most 32767 characters.')
        for cid in ids:
            if cid not in self.project.by_id:
                raise ValueError('A selected component no longer exists. Reopen the project.')
        selected=set(ids)
        if variant==BASE:
            # Base properties belong to a symbol definition in a shared sheet. Expand to
            # all occurrences, transitively across multiple units, just as KiCad does.
            while True:
                memberkeys={(str(m.doc.path),m.uuid) for cid in selected for m in self.project.by_id[cid].members}
                more={c.id for c in self.project.components if any((str(m.doc.path),m.uuid) in memberkeys for m in c.members)}
                if more<=selected: break
                selected |= more
        def apply():
            target=self.state['base'] if variant==BASE else self.state['variants'][variant].setdefault('overrides',{})
            for cid in selected:
                entry=target.setdefault(cid,{})
                staged=self.state.get('field_schema_edits',{}).get(variant,{}).get(cid)
                for k,v in changes.items():
                    if staged is not None and k not in FLAGS:
                        staged['inherit']=[x for x in staged.get('inherit',[]) if x!=k]
                        staged['reset_base']=[x for x in staged.get('reset_base',[]) if x!=k]
                        if v is not None: staged['fields'][k]=v
                        elif variant==BASE: staged['fields'][k]=self.project.by_id[cid].fields.get(k,'')
                        else:
                            staged['fields'][k]=self.own(self.project.by_id[cid],BASE)[0].get(k,'')
                            staged['reset_base'].append(k)
                        # A field added after enforcement must remain inheritable.
                        for descendant,records in self.state.get('field_schema_edits',{}).items():
                            if descendant==BASE or descendant==variant:continue
                            if variant!=BASE and variant not in self.variant_chain(descendant):continue
                            record=records.get(cid)
                            if record is not None and k not in record['fields']:
                                record['fields'][k]=staged['fields'][k]
                                record.setdefault('inherit',[]).append(k)
                    if v is None and variant==BASE:
                        entry.pop(k,None)
                    else:entry[k]=v
                if not entry:target.pop(cid,None)
            return len(selected)
        return self.commit(f'Edit {len(selected)} components in {variant}: '+', '.join(changes),apply)

    def set_population(self,ids,variant,state):
        if state not in STATES:
            raise ValueError('Population must be FIT, DNP, or DNI.')
        return self.edit(ids,variant,{'dnp':state!='FIT','Assembly':state})

    def new_variant(self,name,parent=BASE,description=''):
        validate_name(name)
        name=name.strip()
        if name.casefold() in {BASE.casefold(),'default',*(v.casefold() for v in self.state['variants'])}:
            raise ValueError('Variant name is already in use or reserved.')
        self.variant_chain(parent)
        def apply():
            self.state['variants'][name]={'description':description,'parent':parent,'overrides':{},'variables':{},'native':False,'bom_only':bool(self.state['variants'].get(parent,{}).get('bom_only'))}
        self.commit('Create variant '+name,apply)
        return name

    def remove_variant(self,name):
        if self.state['variants'].get(name,{}).get('locked'):raise ValueError('Independent BOM variant is locked.')
        if name==BASE or name not in self.state['variants']:
            raise ValueError('The default variant cannot be removed.')
        if self.state['variants'][name].get('native'):
            raise ValueError('Delete native variants in KiCad. This preview never silently removes native variant records.')
        if any(v.get('parent')==name for v in self.state['variants'].values()):
            raise ValueError('Remove or reparent the derived variants first.')
        self.commit('Remove variant '+name,lambda:self.state['variants'].pop(name))

    def set_variables(self,scope,values,variant=BASE):
        if scope=='variant' and self.state['variants'].get(variant,{}).get('locked'):raise ValueError('Independent BOM variant is locked.')
        if not isinstance(values,dict) or len(values)>1000:
            raise ValueError('Variables must be a name/value object.')
        for k,v in values.items():
            validate_name(k)
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',k):
                raise ValueError('Variable names use letters, digits, and underscores and cannot start with a digit.')
            if v is not None and (not isinstance(v,str) or len(v)>32767):
                raise ValueError('Variable values must be text.')
        def apply():
            if scope=='project': self.state['project_variables']=values
            elif scope=='workspace':self.state['variables']={k:v for k,v in values.items() if v is not None}
            elif scope=='variant' and variant!=BASE:
                self.state['variants'][variant]['variables']={k:v for k,v in values.items() if v is not None}
            else:raise ValueError('Choose a valid variable scope.')
        self.commit('Update '+scope+' variables',apply)

    @staticmethod
    def validate_settings(settings):
        boards=settings.get('boards',1)
        attrition=settings.get('attrition',0)
        if type(boards) is not int or not 1<=boards<=1000000:
            raise ValueError('Board quantity must be an integer from 1 to 1,000,000.')
        if type(attrition) not in (int,float) or not math.isfinite(attrition) or not 0<=attrition<=100:
            raise ValueError('Attrition must be 0–100 percent.')
        if not re.fullmatch(r'[A-Z]{3}',settings.get('currency','')):
            raise ValueError('Currency must be a three-letter code, such as INR or USD.')
        req=settings.get('required_fields',[])
        if not isinstance(req,list) or any(not isinstance(k,str) for k in req):
            raise ValueError('Required fields must be a list of field names.')
        age=settings.get('quote_age_days',90)
        if type(age) is not int or not 1<=age<=3650:raise ValueError('Quote age must be 1–3650 days.')

    def settings(self,settings):
        merged=dict(self.state['settings'],**settings)
        self.validate_settings(merged)
        self.commit('Update build settings',lambda:self.state.update(settings=merged))

    @staticmethod
    def validate_template(t):
        from .catalog import validate_export_template
        validate_export_template(t)

    def template(self,t):
        self.validate_template(t)
        self.commit('Save template '+t['name'],lambda:self.state['templates'].update({t['name']:deepcopy(t)}))

    def set_aliases(self,aliases):
        if not isinstance(aliases,dict) or any(not isinstance(v,list) or any(not isinstance(x,str) for x in v) for v in aliases.values()):
            raise ValueError('Aliases must map canonical field names to lists of field names.')
        self.commit('Update field aliases',lambda:self.state.update(aliases=deepcopy(aliases)))

    def checks(self,variant=BASE,rows=None):
        rows=self.rows(variant) if rows is None else rows
        issues=[]
        def add(level,ref,code,message):issues.append({'severity':level,'reference':ref,'code':code,'message':message})
        for message in self.project.blockers:add('error','Project','ADAPTER',message)
        for message in self.project.warnings:add('warning','Project','FORMAT',message)
        if self.state.get('source_hashes')!=self.project.hashes:
            add('error','Workspace','SOURCE_DRIFT','Source files changed since this workspace baseline. Review pending overrides and explicitly REBASE before release.')
        known=set(self.project.by_id)
        for label,changes in [('Base',self.state['base'])]+[(k,v.get('overrides',{})) for k,v in self.state['variants'].items()]:
            for cid in changes:
                if cid not in known:add('error','Project','ORPHAN',f'{label}: a saved edit targets a missing UUID. Review the sidecar after reannotation/restructuring.')
        for r in rows:
            f=r['fields'];ref=r['ref']
            for msg in r['errors']:add('error',ref,'VARIABLE',msg)
            for conflict in r.get('alias_conflicts',[]):add('error',ref,'ALIAS_CONFLICT',conflict['message'])
            if r['legacy_population']:
                add('error',ref,'POPULATION_CONFLICT',f'Text field says {r["legacy_population"]}, but native DNP is false. Use the Population control to synchronize intent.')
            if r['inherited'] and self.state['variants'].get(variant,{}).get('overrides',{}).get(r['id'],{}).get('dnp') is False:
                add('warning',ref,'SHEET_PRECEDENCE','FIT override cannot undo a sheet-level DNP. Edit that sheet in KiCad.')
            if f['Assembly']=='FIT' and f['InBOM']:
                for key in dict.fromkeys([*self.state['settings']['required_fields'], *self.state.get('field_enforcement',{}).get('required',[])]):
                    if not f.get(key,''):add('error',ref,'MISSING_FIELD','Missing '+key)
                if decimal_value(f.get('UnitPrice')) is None:
                    add('warning',ref,'MISSING_PRICE','Unit price is absent or not a nonnegative decimal. Cost is incomplete, not zero.')
                for key in ('MOQ','OrderMultiple'):
                    raw=f.get(key,'');n=decimal_value(raw)
                    if raw and (n is None or n<1 or n!=int(n)):add('error',ref,'ORDER_QUANTITY',key+' must be a positive integer.')
                for key in ('Stock','LeadTime'):
                    if f.get(key,'') and decimal_value(f[key]) is None:add('warning',ref,'INVALID_NUMBER',key+' is not a nonnegative number.')
                if f.get('Lifecycle','').casefold() in ('obsolete','eol','nrnd','end of life'):
                    add('warning',ref,'LIFECYCLE','Lifecycle: '+f['Lifecycle'])
                raw=f.get('PriceDate','')
                if raw:
                    try:
                        date=datetime.fromisoformat(raw.replace('Z','+00:00'))
                        if (datetime.now(timezone.utc).date()-date.date()).days>self.state['settings']['quote_age_days']:
                            add('warning',ref,'STALE_QUOTE','Price date exceeds the configured quote age.')
                    except ValueError:add('warning',ref,'PRICE_DATE','Use an ISO date such as 2026-09-09.')
                elif f.get('UnitPrice',''):
                    add('warning',ref,'UNDATED_PRICE','Price has no quote date; current availability/cost is not verified.')
            c=self.project.by_id[r['id']]
            if f.get('Currency') and not re.fullmatch(r'[A-Z]{3}',f['Currency']):
                add('error',ref,'CURRENCY','Use a 3-letter uppercase currency code.')
            if f.get('Footprint') != c.fields.get('Footprint'):
                add('error',ref,'FOOTPRINT_CHANGE','Footprint changed. Package/pin compatibility and PCB placement require engineering review in KiCad.')
        by_mpn=defaultdict(list)
        for r in rows:
            if r['fields'].get('MPN'):by_mpn[(r['fields'].get('Manufacturer',''),r['fields']['MPN'])].append(r)
        from .intelligence import normalized_value
        for key,items in by_mpn.items():
            if len({(normalized_value(r['fields'].get('Value',''),r['ref'],r['lib_id']) or r['fields'].get('Value',''),r['fields'].get('Footprint','')) for r in items})>1:
                add('error',', '.join(r['ref'] for r in items),'MPN_CONFLICT','Same manufacturer/MPN is assigned inconsistent value or footprint.')
        return issues

    def compare(self,left=BASE,right=BASE):
        a={r['id']:r for r in self.rows(left)}
        result=[]
        ignore={'Source','UUID','Qty'}
        for b in self.rows(right):
            af=a[b['id']]['fields'];bf=b['fields']
            for field in sorted((set(af)|set(bf))-ignore):
                if af.get(field,'')!=bf.get(field,''):
                    result.append({'Reference':b['ref'],'Field':field,'Before':af.get(field,''),'After':bf.get(field,'')})
        return result

    def snapshot(self,variant=BASE):
        self.commit('Capture BOM baseline: '+variant,lambda:self.state.update(baseline={'time':now(),'variant':variant,'rows':self.rows(variant)}))

    def baseline_diff(self,variant=BASE):
        baseline=self.state.get('baseline')
        if not baseline:return []
        before={r['id']:r for r in baseline['rows']};after={r['id']:r for r in self.rows(variant)}
        changes=[]
        for cid in sorted(set(before)|set(after)):
            a,b=before.get(cid),after.get(cid)
            if not a or not b:
                changes.append({'Reference':(a or b)['ref'],'Field':'Component','Before':'Present' if a else '','After':'Present' if b else ''})
            else:
                for k in sorted(set(a['fields'])|set(b['fields'])):
                    if k in ('Source','UUID'):continue
                    if a['fields'].get(k,'')!=b['fields'].get(k,''):
                        changes.append({'Reference':b['ref'],'Field':k,'Before':a['fields'].get(k,''),'After':b['fields'].get(k,'')})
        return changes

    def alternate(self,mpn,record):
        if not mpn:raise ValueError('Primary MPN is required.')
        if not record.get('MPN') or record.get('status') not in ('candidate','approved','rejected'):
            raise ValueError('Alternate needs an MPN and candidate/approved/rejected status.')
        if record['status']=='approved' and (not record.get('reviewer') or not record.get('reason')):
            raise ValueError('Approval needs a reviewer and compatibility-review note.')
        record=dict(record,updated=now())
        self.commit('Record alternate for '+mpn,lambda:self.state['alternates'].setdefault(mpn,[]).append(record))

    def csv_preview(self,text,variant=BASE):
        if len(text)>10*1024*1024:raise ValueError('CSV exceeds 10 MiB.')
        try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t|')
        except csv.Error:dialect=csv.excel
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),dialect=dialect)
        if not reader.fieldnames:raise ValueError('CSV requires a header row.')
        refkey=next((k for k in reader.fieldnames if k.casefold() in ('reference','references','ref','refs','designator','designators')),None)
        if not refkey:raise ValueError('CSV must contain a Reference (or Designator) column. Use ungrouped references or comma-separated refs, not ranges.')
        byref={c.ref:c.id for c in self.project.components}
        changes=[];unmatched=[];seen=set()
        flag_alias={'InBOM':'in_bom','OnBoard':'on_board','InPosFiles':'in_pos_files','ExcludeFromSim':'exclude_from_sim','DNP':'dnp'}
        current={r['id']:r for r in self.rows(variant)}
        for line in reader:
            if None in line:raise ValueError('CSV contains extra unheaded columns. Check its delimiter/quoting.')
            refs=[x for x in re.split(r'[,;\s]+',line.get(refkey,'') or '') if x]
            for ref in refs:
                if ref not in byref:unmatched.append(ref);continue
                if ref in seen:raise ValueError('CSV contains duplicate reference '+ref)
                seen.add(ref);delta={}
                for key,value in line.items():
                    if key==refkey or key in COMPUTED or key in ('Sheet','LineCost','OrderCost'):continue
                    value='' if value is None else value
                    if key in flag_alias:
                        lower=value.strip().casefold()
                        if lower not in ('yes','no','true','false','1','0','dnp',''):
                            raise ValueError(f'{ref}: invalid boolean {key}={value}')
                        delta[flag_alias[key]]=lower in ('yes','true','1','dnp')
                    elif key=='Assembly':
                        state=value.strip().upper()
                        if state not in STATES:raise ValueError('Assembly must be FIT/DNP/DNI.')
                        delta.update(Assembly=state,dnp=state!='FIT')
                    else:delta[key]=value
                row=current[byref[ref]]
                delta={k:v for k,v in delta.items() if (row['flags'] if k in FLAGS else row['raw']).get(k,'')!=v}
                if delta:changes.append({'id':byref[ref],'ref':ref,'changes':delta})
        return {'changes':changes,'unmatched':unmatched,'count':len(changes)}

    def csv_apply(self,text,variant):
        plan=self.csv_preview(text,variant)
        if plan['unmatched']:raise ValueError('CSV contains unmatched references. Fix them before importing.')
        if variant==BASE:
            assigned={}
            for entry in plan['changes']:
                for m in self.project.by_id[entry['id']].members:
                    for field,value in entry['changes'].items():
                        key=(str(m.doc.path),m.uuid,field)
                        if key in assigned and assigned[key]!=value:
                            raise ValueError('CSV assigns conflicting base values to a repeated-sheet symbol. Use per-instance variants.')
                        assigned[key]=value
        # Use the same edit validator, but aggregate history into one undo transaction.
        before=self._serialize();old_undo=list(self.undo_stack);old_redo=list(self.redo_stack);rev=self.revision
        try:
            for entry in plan['changes']:self.edit([entry['id']],variant,entry['changes'])
        except Exception:
            self.state=json.loads(before);self.undo_stack=old_undo;self.redo_stack=old_redo;self.revision=rev;raise
        if plan['changes']:
            self.undo_stack=(old_undo+[before])[-100:];self.redo_stack=[]
        self.preview_cache=None
        return plan['count']

    def acknowledge_sources(self, confirmation):
        if confirmation!='REBASE':raise ValueError('Type REBASE after reviewing source/workspace differences.')
        self.commit('Acknowledge refreshed source baseline',lambda:self.state.update(source_hashes=self.project.hashes))

    def save(self):
        current=sha(self.sidecar.read_bytes()) if self.sidecar.exists() else None
        if current!=self.sidecar_hash:
            raise ValueError('Workspace file changed in another session. Save is blocked to avoid overwriting it.')
        data=(json.dumps(self.state,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
        if self.sidecar.exists():
            backup=self.sidecar.parent/'.wayricad-bom-backups'
            backup.mkdir(exist_ok=True)
            (backup/(self.sidecar.name+'.'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.bak')).write_bytes(self.sidecar.read_bytes())
        fd,temp=tempfile.mkstemp(prefix='.'+self.sidecar.name+'.',dir=self.sidecar.parent)
        try:
            with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
            latest=sha(self.sidecar.read_bytes()) if self.sidecar.exists() else None
            if latest!=self.sidecar_hash:raise ValueError('Concurrent workspace write detected.')
            os.replace(temp,self.sidecar)
        finally:
            if os.path.exists(temp):os.unlink(temp)
        self.sidecar_hash=sha(data);self.saved_json=self._serialize()
        return str(self.sidecar)

    def public(self,variant=BASE):
        rows=self.rows(variant);issues=self.checks(variant,rows)
        fitted=[r for r in rows if r['fields']['Assembly']=='FIT' and r['flags']['in_bom']]
        from .analytics import price_overview
        costs,unpriced,analytics_settings=price_overview(self,rows)
        from .field_registry import inventory
        field_inventory=inventory(self,variant,rows)
        result={'project':self.project.status(),'engineering':self.state.get('engineering',{}),'variant':variant,'variants':self.state['variants'],
                'rows':rows,'field_inventory':field_inventory,'issues':issues,'dirty':self.dirty,'revision':self.revision,
                'undo':bool(self.undo_stack),'redo':bool(self.redo_stack),
                'stats':{'parts':len(rows),'fitted':len(fitted),'not_fitted':sum(r['flags']['dnp'] for r in rows),
                         'excluded':sum(not r['flags']['in_bom'] for r in rows),'cost':{k:str(v) for k,v in costs.items()},'unpriced':unpriced},
                'assembler_export_settings':self.state.get('assembler_export_settings',{}),
                'analytics_settings':analytics_settings,'vendor_export_settings':self.state.get('vendor_export_settings',{}),
                'settings':self.state['settings'],'templates':self.state['templates'],
                'evidence':self.state.get('evidence',[]),'health_settings':self.state.get('health_settings',{}),'grouping':self.state.get('grouping',{}),
                'view':self.state['view'],'view_presets':self.state['view_presets'],'saved_filters':self.state.get('saved_filters',{}),
                'field_profiles':self.state['field_profiles'],
                'native_field_templates':self.state.get('native_field_templates') if self.state.get('native_field_templates') is not None else self.project.pro.get('schematic',{}).get('drawing',{}).get('field_names',[]),
                'field_schema_pending':sum(len(v) for v in self.state.get('field_schema_edits',{}).values()),
                'project_variables':self.project.variables,'project_variable_edits':self.state['project_variables'],
                'workspace_variables':self.state['variables'],'resolved_variables':self.variables(variant),
                'aliases':self.state['aliases'],'alternates':self.state['alternates'],'history':self.state['history'],
                'baseline':{k:v for k,v in (self.state.get('baseline') or {}).items() if k!='rows'}}
        from .nativefirst import decorate_public
        return decorate_public(self,result)
