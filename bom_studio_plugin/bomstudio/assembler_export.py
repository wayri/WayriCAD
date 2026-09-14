"""Assembler-specific, per-board BOM handoffs. No website requests or native writes.

Unlike distributor requests, each profile describes the same ONE board. Project
build count, attrition, MOQ and supplier-routing overrides never alter placement
quantities. Profiles are mappings, not manufacturer approval or CPL generation.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import io
import json
import re
import zipfile
from . import __version__
from .native import BASE, natural, sha
from .engine import ALIASES, now
from .vendor_export import _get, _delimited, _xlsx, digest, safe_upload_cell, MIME

SCHEMA = 'wayricad-assembler-config-1'
REPORT = 'wayricad-assembler-report-1'
# Deliberately separate provider identifiers; HQPCB is not an alias of NextPCB.
PROFILES = {
    'jlcpcb': {
        'name':'JLCPCB', 'headers':['Comment','Designator','Footprint','LCSC Part #'],
        'keys':['comment','references','footprint','sku'],
        'required':['comment','footprint'], 'identity':'description',
        'sku_fields':['LCSC Part #','LCSC Part Number','LCSC','LCSC_PN','JLCPCB Part #','JLCPCB Part Number'],
        'status':'documented_fields',
        'source':'https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly',
        'note':'Four-column JLCPCB handoff. Quantity is represented by the explicit designator list. LCSC code is optional; blank codes require manual part selection on the website. Never substitute a Mouser/DigiKey SKU.'},
    'pcbway': {
        'name':'PCBWay',
        'headers':['Item','Quantity','Reference(s)','Value','Footprint','Manufacturer','Manufacturer Part Number','Description'],
        'keys':['item','qty_per_board','references','value','footprint','manufacturer','mpn','description'],
        'required':['footprint','mpn'], 'identity':'mpn', 'sku_fields':[],
        'status':'review_required', 'source':'https://www.pcbway.com/',
        'note':'Editable PCBWay assembly mapping. Confirm the current supplied template/column mapping with PCBWay; this layout has not been portal-tested.'},
    'hqpcb': {
        'name':'HQPCB',
        'headers':['Designator','Quantity','Description','Package','Manufacturer','Manufacturer Part Number'],
        'keys':['references','qty_per_board','description','footprint','manufacturer','mpn'],
        'required':['footprint','mpn'], 'identity':'mpn', 'sku_fields':[],
        'status':'review_required', 'source':'https://www.hqpcb.com/',
        'note':'Separate HQPCB mapping, not a NextPCB alias. Current official template could not be verified; confirm headers and per-board quantity interpretation with the recipient.'},
    'nextpcb': {
        'name':'NextPCB',
        'headers':['Comment','Designator','Footprint','Quantity','Manufacturer','Manufacturer Part Number'],
        'keys':['comment','references','footprint','qty_per_board','manufacturer','mpn'],
        'required':['comment','footprint','mpn'], 'identity':'mpn', 'sku_fields':[],
        'status':'review_required', 'source':'https://www.nextpcb.com/',
        'note':'NextPCB accepts spreadsheet/CSV BOMs; this is an editable column-mapping layout, not a reproduction of its current workbook template. Set assembly board count separately.'},
    'sierra': {
        'name':'Sierra Circuits',
        'headers':['Quantity per board','Manufacturer Part Number','Reference Designators','DNI/DNP','Value','Size/Footprint','Part Description','Manufacturer'],
        'keys':['qty_per_board','mpn','references','dnp','value','footprint','description','manufacturer'],
        'required':['footprint','mpn','description'], 'identity':'mpn', 'sku_fields':[],
        'status':'documented_fields', 'source':'https://www.protoexpress.com/kb/pcb-bom-file/',
        'note':'Maps Sierra\'s documented BOM fields. Export contains fitted parts only; excluded DNP/DNI records are retained in the ZIP audit, not silently populated.'},
    'pcbpower': {
        'name':'PCB Power',
        'headers':['MPN','Quantity','Reference Designator','Manufacturer Name','Description','Footprint'],
        'keys':['mpn','qty_per_board','references','manufacturer','description','footprint'],
        'required':['mpn','manufacturer','footprint'], 'identity':'mpn', 'sku_fields':[],
        'status':'documented_fields',
        'source':'https://www.pcbpower.com/blog-detail/introducing-a-smart-tool-powerbom-how-to-use-it-a-step-by-step-guide',
        'note':'PowerBoM documents four mandatory mapped fields: MPN, Quantity, Reference Designator and Manufacturer Name. Confirm per-board scope when uploading; select consigned/turnkey supply mode on the website.'},
    'seeed': {
        'name':'Seeed Fusion',
        'headers':['Designator','Comment','Footprint','Quantity','Manufacturer','Manufacturer Part Number'],
        'keys':['references','comment','footprint','qty_per_board','manufacturer','mpn'],
        'required':['comment','footprint','mpn'], 'identity':'mpn', 'sku_fields':[],
        'status':'review_required', 'source':'https://www.seeedstudio.com/fusion_pcb.html',
        'note':'Editable assembly mapping. Confirm current Fusion importer/OPL requirements. No OPL identity is inferred from a package name.'},
    'generic': {
        'name':'Generic assembler',
        'headers':['Reference Designators','Quantity per board','Value','Footprint','Manufacturer','Manufacturer Part Number','Description'],
        'keys':['references','qty_per_board','value','footprint','manufacturer','mpn','description'],
        'required':['footprint','mpn'], 'identity':'mpn', 'sku_fields':[],
        'status':'review_required', 'source':'',
        'note':'Editable general assembly mapping; agree the column contract with the recipient before use.'}
}
COLUMNS={'item','references','qty_per_board','value','comment','description','footprint','manufacturer','mpn','sku','customer','dnp'}
MAPPINGS={'value':'Value','comment':'','description':'','footprint':'Footprint','manufacturer':'','mpn':'','customer':''}
DEFAULT={'schema':SCHEMA, 'profiles':['jlcpcb'], 'formats':['csv','xlsx'],
         'fields':MAPPINGS, 'sku_fields':{}, 'profile_overrides':{},
         'footprint_mode':'identifier', 'require_supplier_code':False,
         'acknowledge_review_required':False}
CONTROL=re.compile(r'[\x00-\x1f\x7f]')


def _plain(value, label, limit=200, blank=True):
    if not isinstance(value,str) or len(value)>limit or CONTROL.search(value) or (not blank and not value.strip()):
        raise ValueError('Invalid '+label+'. Use bounded text without control characters.')
    return value


def validate_config(config=None):
    if config is None: config={}
    if not isinstance(config,dict) or set(config)-set(DEFAULT):
        raise ValueError('Unknown assembler configuration keys. Assembly quantities are always per board; no build/MOQ/attrition setting is accepted.')
    c=deepcopy(DEFAULT)
    for k,v in config.items():
        if k=='fields':
            if not isinstance(v,dict) or set(v)-set(MAPPINGS):raise ValueError('Unknown assembler field mapping.')
            c[k].update(deepcopy(v))
        else:c[k]=deepcopy(v)
    if c['schema']!=SCHEMA:raise ValueError('Expected '+SCHEMA)
    ps=c['profiles']
    if not isinstance(ps,list) or not 1<=len(ps)<=len(PROFILES) or any(not isinstance(p,str) or p not in PROFILES for p in ps) or len(set(ps))!=len(ps):
        raise ValueError('Select unique assembler profile IDs from the built-in profile list.')
    fs=c['formats']
    if not isinstance(fs,list) or not fs or len(fs)>3 or any(not isinstance(f,str) or f not in ('csv','xlsx','tsv') for f in fs) or len(set(fs))!=len(fs):
        raise ValueError('Choose unique assembler output formats: csv, xlsx, tsv.')
    for k,v in c['fields'].items():_plain(v,k+' field',1000)
    if c['footprint_mode'] not in ('identifier','name'):raise ValueError('footprint_mode must be identifier or name (library nickname removed).')
    for k in ('require_supplier_code','acknowledge_review_required'):
        if type(c[k]) is not bool:raise ValueError(k+' must be true or false.')
    if not isinstance(c['sku_fields'],dict) or set(c['sku_fields'])-set(PROFILES):raise ValueError('SKU mappings require a known assembler ID.')
    for k,v in c['sku_fields'].items():_plain(v,k+' SKU field',1000)
    overrides=c['profile_overrides']
    if not isinstance(overrides,dict) or set(overrides)-set(PROFILES):raise ValueError('Override only a listed profile; use generic for another assembler.')
    for pid,p in overrides.items():
        if not isinstance(p,dict) or set(p)-{'headers','keys'}:raise ValueError('Profile overrides allow headers and keys only. Input-field mappings are separate.')
        merged={**PROFILES[pid],**p}
        for key in ('headers','keys'):
            vals=merged[key]
            if not isinstance(vals,list) or not 1<=len(vals)<=30 or any(not isinstance(x,str) for x in vals):raise ValueError('Invalid profile '+key)
            for v in vals:_plain(v,key,200,False)
            if len(vals)!=len(set(vals)):raise ValueError('Duplicate profile '+key)
        keys=merged['keys']
        if len(keys)!=len(merged['headers']) or set(keys)-COLUMNS or 'references' not in keys:raise ValueError('Matching headers/keys and a references column are required.')
        # Do not make a quantity-bearing assembly profile silently lose quantity.
        if pid!='jlcpcb' and 'qty_per_board' not in keys:raise ValueError('This assembler profile requires a per-board quantity column.')
        if merged['identity']=='mpn' and 'mpn' not in keys:raise ValueError('This profile must carry its full manufacturer part number.')
        if pid=='jlcpcb' and not {'comment','footprint'}<=set(keys):raise ValueError('JLCPCB requires Comment, Designator and Footprint.')
        if not set(merged['required']) <= set(keys):raise ValueError('Do not remove required part, package or description columns from this profile.')
        if pid=='jlcpcb' and c['require_supplier_code'] and 'sku' not in keys:raise ValueError('Required supplier code must be carried by an output column.')
        for h in merged['headers']:safe_upload_cell(h)
    return c


def profiles(config=None):
    c=validate_config(config);result=deepcopy(PROFILES)
    for pid,p in result.items():
        p.update(c['profile_overrides'].get(pid,{}));p['id']=pid
        p['quantity_basis']='per_board';p['portal_tested']=False
        p['documentation_checked']='2026-09-10' if p['status']=='documented_fields' else None
        if pid in c['profile_overrides']:p['status']='custom_review_required'
    return result


def configuration(ws):return validate_config(ws.state.get('assembler_export_settings',{}))


def configure(ws, config):
    c=validate_config(config)
    ws.commit('Save assembler mappings (no native or distributor changes)',lambda:ws.state.update(assembler_export_settings=c))
    return c


def _values(row,c):
    values={};origins={}
    aliases={'mpn':ALIASES['MPN'],'manufacturer':ALIASES['Manufacturer'],
             'customer':ALIASES['InternalPN'],'description':['Description','Part Description','Component Description'],
             'comment':['Comment'],'value':['Value'],'footprint':['Footprint']}
    for key in MAPPINGS:
        value,source=_get(row,c['fields'][key],aliases[key],key)
        values[key]=value.strip();origins[key]=source
    # Fall back only in auto mode. Explicit blanks are authoritative.
    if not c['fields']['comment'] and not values['comment']:
        values['comment']=values['value'];origins['comment']='Value (auto fallback)'
    if not c['fields']['description'] and not values['description']:
        values['description']=values['value'];origins['description']='Value (auto fallback)'
    values['original_footprint']=values['footprint']
    if c['footprint_mode']=='name' and ':' in values['footprint']:
        values['footprint']=values['footprint'].split(':',1)[1]
    return values,origins


def _upload_text(value,label):
    _plain(value,label,32000)
    safe_upload_cell(value)
    if '${' in value or '@{' in value:raise ValueError('Unresolved expression in '+label+'.')


def preview(ws, variant=BASE, config=None):
    c=validate_config(config if config is not None else configuration(ws))
    ws.project.check_unchanged()
    rows=ws.rows(variant);checks=ws.checks(variant,rows)
    global_errors=[deepcopy(i) for i in checks if i['severity']=='error']
    eligible=[];excluded=[];problems=[];seen={}
    for row in rows:
        flags=row['flags'];why=[]
        if flags['dnp']:why.append('DNP/DNI')
        if not flags['in_bom']:why.append('Excluded from BOM')
        if not flags['on_board']:why.append('Excluded from board')
        if why:
            excluded.append({'id':row['id'],'reference':row['ref'],'reason':'; '.join(why)});continue
        ref=row['ref']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.+-]*[0-9]',ref):
            problems.append({'severity':'error','code':'ASSEMBLY_REFERENCE','reference':ref,'message':'Reference is unannotated or not representable as a comma-separated assembly designator. No reference was rewritten.'})
        if ref.casefold() in seen:
            problems.append({'severity':'error','code':'ASSEMBLY_DUPLICATE_REFERENCE','reference':ref,'message':'Duplicate/case-only designators cannot safely identify distinct parts for assembly.'})
        seen[ref.casefold()]=row['id']
        try:
            values,origins=_values(row,c)
            eligible.append({'id':row['id'],'reference':ref,**values,'mapping':origins,'row':row})
        except ValueError as exc:
            problems.append({'severity':'error','code':'ASSEMBLY_FIELD_MAPPING','reference':ref,'message':str(exc)})
            eligible.append({'id':row['id'],'reference':ref,'invalid':True,'row':row})
    global_errors+=problems
    outputs=[];available=profiles(c)
    for pid in c['profiles']:
        p=available[pid];groups={};errors=[];warnings=[]
        for entry in eligible:
            if entry.get('invalid'):continue
            row=entry['row'];item={k:v for k,v in entry.items() if k!='row'}
            try:
                sku,origin=_get(row,c['sku_fields'].get(pid,''),p['sku_fields'],p['name']+' part code')
                item['sku']=sku.strip();item['mapping']=dict(item['mapping'],sku=origin)
                if pid=='jlcpcb' and item['sku'] and not re.fullmatch(r'C[0-9]+',item['sku']):
                    raise ValueError('JLCPCB/LCSC part code must be an exact C-prefixed numeric code; generic distributor SKUs are not LCSC codes.')
                if c['require_supplier_code'] and 'sku' in p['keys'] and not item['sku']:
                    raise ValueError('A supplier code is required by the selected export policy.')
                for key in p['required']:
                    if not item[key]:raise ValueError('Missing '+key+' for '+p['name']+'. Map the correct field; no part identity is guessed.')
                for key in set(p['keys'])-{'item','references','qty_per_board','dnp'}:_upload_text(item[key],key)
                if not item['manufacturer'] and item['mpn']:
                    warnings.append({'severity':'warning','code':'ASSEMBLY_MFR_UNKNOWN','reference':item['reference'],'message':'Manufacturer is blank; verify the exact manufacturer/MPN pair.'})
                if pid=='jlcpcb' and not item['sku']:
                    warnings.append({'severity':'warning','code':'ASSEMBLY_LCSC_MANUAL','reference':item['reference'],'message':'No LCSC code supplied. Match the intended exact part on JLCPCB before submitting.'})
                # Even columns omitted from a portal layout must not merge distinct
                # part identities, selected land patterns or recorded constraints.
                constraints=tuple(sorted((k,v) for k,v in row.get('physical',{}).items()
                    if re.search(r'tolerance|voltage|power|dielectric|current|temp|qualif|packaging',k,re.I)))
                identity=tuple(item[k] for k in ('mpn','manufacturer','sku','value','comment','description','original_footprint','footprint','customer'))+(constraints,)
                if not item['mpn'] and not item['sku']:identity+=('unpooled',item['id'])
                g=groups.setdefault(identity,{**item,'ids':[],'refs':[],'dnp':'No'})
                g['ids'].append(item['id']);g['refs'].append(item['reference'])
            except ValueError as exc:
                errors.append({'severity':'error','code':'ASSEMBLY_PROFILE_FIELD','reference':entry['reference'],'message':str(exc)})
        lines=[]
        for g in groups.values():
            refs=sorted(g.pop('refs'),key=natural);g['references']=', '.join(refs)
            g['qty_per_board']=len(g['ids']);g['reference_list']=refs
            if len(g['references'])>32000:
                errors.append({'severity':'error','code':'ASSEMBLY_REF_LENGTH','reference':refs[0],'message':'Reference list is too long for a spreadsheet cell; split the design or use smaller BOM groups. No truncation occurred.'})
            lines.append(g)
        lines.sort(key=lambda g:natural(g['reference_list'][0]))
        for i,g in enumerate(lines,1):g['item']=i
        # A local code used for incompatible exact identities needs human correction.
        skus=defaultdict(set)
        for l in lines:
            if l['sku']:skus[l['sku']].add((l['manufacturer'],l['mpn'],l['value'],l['original_footprint']))
        for sku,ids in skus.items():
            if len(ids)>1:errors.append({'severity':'error','code':'ASSEMBLY_SKU_CONFLICT','reference':sku,'message':'The same supplier code is assigned to conflicting part/footprint records.'})
        n=sum(l['qty_per_board'] for l in lines)
        complete=n==len(eligible) and not errors and not global_errors
        needs_review=p['status']!='documented_fields'
        if needs_review:
            warnings.append({'severity':'warning','code':'ASSEMBLY_PROFILE_REVIEW','reference':p['name'],'message':p['note']})
        if 'tsv' in c['formats']:
            warnings.append({'severity':'warning','code':'ASSEMBLY_TSV_REVIEW','reference':p['name'],'message':'TSV is a text handoff option; portal support is not established. Use CSV/XLSX where specified.'})
            needs_review=True
        status='BLOCKED' if not complete else 'NO_ASSEMBLY_DEMAND' if not eligible else 'REVIEW_REQUIRED' if needs_review and not c['acknowledge_review_required'] else 'READY_FOR_REVIEW'
        outputs.append({'id':pid,'name':p['name'],'profile':p,'lines':lines,'line_count':len(lines),
                        'quantity_per_board':n,'complete':complete,'status':status,
                        'issues':errors+warnings,'requires_acknowledgement':needs_review})
    blocked=bool(global_errors or any(x['status']=='BLOCKED' for x in outputs))
    review=any(x['status']=='REVIEW_REQUIRED' for x in outputs)
    status='BLOCKED' if blocked else 'REVIEW_REQUIRED' if review else 'NO_ASSEMBLY_DEMAND' if not eligible else 'READY_FOR_REVIEW'
    ws.project.check_unchanged()
    summary={'physical_components':len(rows),'fitted_on_board_components':len(eligible),
             'excluded_components':len(excluded),'profiles':len(outputs),'per_board':True,
             'reconciled':all(x['complete'] for x in outputs),'build_multiplier_applied':False}
    # Include effective values, profile definitions and checks in stale-review binding.
    fingerprint=digest({'config':c,'profiles':available,'variant':variant,'sources':ws.project.hashes,
                        'rows':[{'id':r['id'],'raw':r['raw'],'physical':r.get('physical',{}),'flags':r['flags']} for r in rows],
                        'checks':checks,'outputs':outputs})
    return {'schema':REPORT,'app_version':__version__,'generated_at':now(),
            'project':ws.project.name,'variant':variant,'config':c,'status':status,
            'quantity_basis':'per_board','fingerprint':fingerprint,'summary':summary,
            'profiles':outputs,'excluded':excluded,'source_checks':checks,'blocking_checks':global_errors,
            'source_sha256':dict(ws.project.hashes),
            'notice':'Each profile describes the SAME single board, not an additional or split order. Quantities equal explicit reference counts; project boards, attrition, MOQ and supplier routing are NOT applied. Enter the intended build count separately on the assembler site. No CPL/Gerber, automatic upload, stock reservation or order is generated.'}


def table(profile_report):
    p=profile_report['profile']
    return p['headers'],[[safe_upload_cell(l[k]) for k in p['keys']] for l in profile_report['lines']]


def _render(profile_report,fmt):
    headers,values=table(profile_report)
    if fmt=='xlsx':
        keys=['upload_qty' if k in ('qty_per_board','item') else k for k in profile_report['profile']['keys']]
        return _xlsx(headers,values,keys)
    return _delimited(headers,values,fmt)


def _check_export(report):
    if report.get('schema')!=REPORT:raise ValueError('Expected assembler report.')
    if report['status']=='BLOCKED':raise ValueError('Assembly BOM is blocked by missing/conflicting data or source checks. No partial assembly file is generated.')
    if report['status']=='REVIEW_REQUIRED':raise ValueError('Review the provider-specific mapping notes and acknowledge unverified/custom layouts before export.')


def package_files(report):
    _check_export(report)
    files={'reports/REPORT.json':(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode(),
           'reports/EXCLUDED.csv':_delimited(['Reference','Reason'],[[r['reference'],r['reason']] for r in report['excluded']],audit=True)}
    instructions=['WayriCAD assembler handoff '+__version__, 'Status: '+report['status'],report['notice'],'',
                  'Upload ONE format for the chosen assembler. Other assembler folders are ALTERNATIVE quotations of the same design.',
                  'Do not upload the ZIP audit/report files as a BOM. CSV/XLSX are alternative representations, not separate quantities.',
                  'Save native data and verify the active variant, DNP/DNI list, packaging, full MPNs and references before uploading.',
                  'The quantity is PER BOARD, even if project purchasing settings specify a larger build or attrition.',
                  'The manufacturing order still requires a separately generated matching CPL/position file, Gerbers and other assembly documentation.',
                  'No live portal import has been tested. Map columns when prompted and confirm provider-specific instructions.','']
    for p in report['profiles']:
        if not p['complete']:raise ValueError('Incomplete profile cannot produce assembly upload files.')
        # All excluded is audit-only: do not invent an empty placement request.
        if p['lines']:
            for fmt in report['config']['formats']:
                files[f'uploads/{p["id"]}/{p["id"]}_BOM_PER_BOARD.{fmt}']=_render(p,fmt)
        info=p['profile']
        instructions.extend([p['name']+' — '+info['status'],info['note'],'Documentation: '+info['source'],
                             'Headers: '+' | '.join(info['headers']),f'{p["line_count"]} lines, {p["quantity_per_board"]} components per board.',''])
    files['README_UPLOAD.txt']=('\n'.join(instructions)+'\n').encode()
    manifest={'schema':'wayricad-assembler-package-1','version':__version__,'status':report['status'],
              'quantity_basis':'per_board','variant':report['variant'],'fingerprint':report['fingerprint'],
              'profiles':[p['id'] for p in report['profiles']],
              'files':{k:{'bytes':len(v),'sha256':sha(v)} for k,v in sorted(files.items())}}
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    return files


def export(ws,variant=BASE,config=None,fmt='zip',profile=None,fingerprint=None):
    if fmt not in MIME:raise ValueError('Unknown assembler export format.')
    r=preview(ws,variant,config)
    if fingerprint and r['fingerprint']!=fingerprint:raise ValueError('Assembly preview is stale. Preview again before exporting.')
    if fmt=='json':return (json.dumps(r,ensure_ascii=False,indent=2)+'\n').encode(),'Assembler_BOM_review.json',MIME[fmt]
    _check_export(r)
    if fmt!='zip':
        chosen=[p for p in r['profiles'] if p['id']==profile] if profile else r['profiles']
        if len(chosen)!=1:raise ValueError('Choose exactly one assembler for a single file; ZIP contains every selected alternative.')
        if not chosen[0]['lines']:raise ValueError('No assembly demand. Export ZIP for the excluded-parts audit instead of an empty BOM.')
        if fmt=='tsv' and not r['config']['acknowledge_review_required']:
            raise ValueError('TSV portal support is unverified; acknowledge mapping review or use CSV/XLSX.')
        return _render(chosen[0],fmt),chosen[0]['id']+'_BOM_PER_BOARD.'+fmt,MIME[fmt]
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(package_files(r).items()):z.writestr(name,data)
    return out.getvalue(),'Assembler_BOMs_PER_BOARD.zip',MIME[fmt]
