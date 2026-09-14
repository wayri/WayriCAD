"""Read-only vendor routing and upload packages. No supplier requests or orders.

A routing preference is NOT a KiCad field template. Each physical occurrence is
accounted for once, with native population flags respected. All quantities are
component pieces, never reels; stock allocation remains in buildplan.py.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import csv
import hashlib
import io
import json
import re
import zipfile
from . import __version__
from .native import BASE, natural, sha
from .engine import ALIASES, now
from .evidence import integer

SCHEMA = 'wayricad-vendor-config-1'
REPORT = 'wayricad-vendor-split-1'
MIME = {'zip':'application/zip', 'csv':'text/csv; charset=utf-8',
        'tsv':'text/tab-separated-values; charset=utf-8',
        'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'json':'application/json; charset=utf-8'}
PROFILES = {
    'digikey': {'name':'DigiKey', 'aliases':['DigiKey','Digi-Key','Digi Key','Digi-Key Electronics','DigiKey Electronics'],
                'sku_fields':['DigiKey Part Number','Digi-Key Part Number','DigiKey_PN','DigiKey PN','DigiKey','Digi-Key'],
                'headers':['DigiKey Part Number','Manufacturer Part Number','Quantity','Customer Reference'],
                'keys':['sku','mpn','upload_qty','customer_reference'], 'max_lines':1000,
                'url':'https://www.digikey.com/en/mylists',
                'mapping':'Map DigiKey Part Number and/or Manufacturer Part Number; Quantity is TOTAL pieces. Customer Reference is optional.',
                'source':'https://www.digikey.com/en/help-support/place-an-order/build-a-bom'},
    'mouser': {'name':'Mouser', 'aliases':['Mouser','Mouser Electronics'],
               'sku_fields':['Mouser Part Number','Mouser_PN','Mouser PN','Mouser'],
               'headers':['Mouser Part Number','Manufacturer Part Number','Quantity 1','Customer Part Number'],
               'keys':['sku','mpn','upload_qty','customer_reference'], 'max_lines':200,
               'url':'https://www.mouser.com/bom/',
               'mapping':'Use the BOM worksheet. Map Mouser Part Number and/or Manufacturer Part Number, Quantity 1, and Customer Part Number. Review exact matches.',
               'source':'https://www.youtube.com/watch?v=xwwTFMKBxjg'},
    'generic': {'name':'Generic vendor', 'aliases':[], 'sku_fields':[],
                'headers':['Supplier Part Number','Manufacturer Part Number','Manufacturer','Quantity','Customer Part Number','References'],
                'keys':['sku','mpn','manufacturer','upload_qty','customer_reference','references'], 'max_lines':1000,
                'url':'', 'mapping':'Configurable generic mapping, not a certified importer for this vendor. Map columns manually.', 'source':''}
}
DEFAULT = {'schema':SCHEMA,'vendor_field':'','mpn_field':'','manufacturer_field':'',
           'sku_field':'','customer_field':'','moq_field':'','multiple_field':'',
           'boards':None,'attrition_percent':None,'quantity_basis':'order',
           'formats':['csv','xlsx'],'profiles':{},'assignments':{}}
def safe_upload_cell(value):
    if isinstance(value,str) and (CONTROL.search(value) or value.lstrip().startswith(('=','+','-','@'))):
        raise ValueError('Upload text contains controls or a formula-like prefix. Correct the value; identifiers are never silently altered.')
    return value


UPLOAD_KEYS = {'sku','mpn','manufacturer','upload_qty','customer_reference','references','value','footprint','required_qty','installed_qty','order_qty','overbuy_qty'}
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def digest(value):
    return sha(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())


def normalized_vendor(value):
    return re.sub(r'[\s_.-]+','',str(value).strip()).casefold()


def _text(value, label, limit=1000, blank=True):
    if not isinstance(value,str) or len(value)>limit or CONTROL.search(value) or (not blank and not value.strip()):
        raise ValueError('Invalid '+label+'. Use plain text without control characters.')
    return value


def validate_config(config=None):
    if config is None: config={}
    if not isinstance(config,dict) or set(config)-set(DEFAULT):raise ValueError('Unknown vendor-export configuration keys.')
    c=deepcopy(DEFAULT);c.update(deepcopy(config))
    if c['schema']!=SCHEMA:raise ValueError('Expected '+SCHEMA)
    for key in ('vendor_field','mpn_field','manufacturer_field','sku_field','customer_field','moq_field','multiple_field'):
        _text(c[key],key)
    if c['boards'] is not None and (type(c['boards']) is not int or not 1<=c['boards']<=1000000):raise ValueError('boards must be an integer from 1 to 1000000, or null for project settings.')
    if c['attrition_percent'] is not None:
        a=str(c['attrition_percent'])
        if not re.fullmatch(r'\d{1,3}(?:\.\d{1,6})?',a) or not 0<=Decimal(a)<=100:raise ValueError('Attrition must be a decimal percentage from 0 to 100.')
        c['attrition_percent']=str(Decimal(a))
    if c['quantity_basis'] not in ('installed','required','order'):raise ValueError('quantity_basis must be installed, required or order.')
    f=c['formats']
    if not isinstance(f,list) or not f or len(f)>3 or any(not isinstance(x,str) or x not in ('csv','tsv','xlsx') for x in f) or len(set(f))!=len(f):raise ValueError('Choose unique vendor formats: csv, tsv, xlsx.')
    if not isinstance(c['profiles'],dict) or len(c['profiles'])>40:raise ValueError('Use at most 40 custom vendor profiles.')
    for pid,p in c['profiles'].items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',pid):raise ValueError('Profile ID must be portable lowercase letters/digits/_/-.')
        if not isinstance(p,dict) or set(p)-{'name','aliases','sku_fields','headers','keys','max_lines','url'}:raise ValueError('Invalid vendor profile.')
        merged={**deepcopy(PROFILES.get(pid,PROFILES['generic'])),**p}
        _text(merged['name'],'vendor name',100,False)
        for key in ('aliases','sku_fields','headers','keys'):
            values=merged[key]
            if not isinstance(values,list) or len(values)>50 or any(not isinstance(x,str) or not x.strip() or len(x)>200 or CONTROL.search(x) for x in values):raise ValueError('Invalid profile '+key)
            if len(set(values))!=len(values):raise ValueError('Duplicate profile '+key)
        if not merged['keys'] or len(merged['keys'])!=len(merged['headers']) or set(merged['keys'])-UPLOAD_KEYS or 'upload_qty' not in merged['keys'] or not {'sku','mpn'}&set(merged['keys']):
            raise ValueError('Profile columns need Quantity (upload_qty) and sku and/or mpn with matching headers.')
        if type(merged['max_lines']) is not int or not 1<=merged['max_lines']<=50000:raise ValueError('max_lines must be 1–50000.')
        if merged['url']:
            from .evidence import safe_url
            safe_url(merged['url'])
        for h in merged['headers']:
            if h.lstrip().startswith(('=','+','-','@')):raise ValueError('Upload headers cannot resemble spreadsheet formulas.')
    # Routing names may not be claimed by multiple profiles.
    aliases={}
    for pid,p in profiles(c).items():
        if pid=='generic':continue
        for name in [p['name'],*p['aliases']]:
            n=normalized_vendor(name)
            if n in aliases and aliases[n]!=pid:raise ValueError('Two vendor profiles claim the same alias: '+name)
            aliases[n]=pid
    if not isinstance(c['assignments'],dict) or len(c['assignments'])>100:raise ValueError('Invalid variant assignments.')
    count=0
    for variant,items in c['assignments'].items():
        _text(variant,'assignment variant',128,False)
        if not isinstance(items,dict):raise ValueError('Assignments must be keyed by physical instance ID.')
        count+=len(items)
        for cid,entry in items.items():
            _text(cid,'instance ID',4096,False)
            if not isinstance(entry,dict) or set(entry)-{'vendor','sku','signature'} or 'vendor' not in entry or not re.fullmatch('[0-9a-f]{64}',str(entry.get('signature',''))):raise ValueError('A manual assignment requires vendor and the part signature returned by Preview.')
            _text(entry['vendor'],'assigned vendor',100)
            if 'sku' in entry:_text(entry['sku'],'assigned SKU',200)
    if count>100000:raise ValueError('Too many vendor assignments.')
    return c


def profiles(c):
    ps=deepcopy(PROFILES)
    for pid,p in c.get('profiles',{}).items():ps[pid]={**deepcopy(ps.get(pid,PROFILES['generic'])),**deepcopy(p),'source':PROFILES.get(pid,{}).get('source','')}
    return ps


def configuration(ws):
    return validate_config(ws.state.get('vendor_export_settings',{}))


def configure(ws, config):
    c=validate_config(config)
    ws.commit('Save vendor export mappings (no native changes)',lambda:ws.state.update(vendor_export_settings=c))
    return c


def _get(row, explicit, aliases, label, normalize=lambda x:x):
    """Explicit physical mapping preserves blanks. Auto aliases fail on conflicts."""
    physical=row.get('physical',row.get('raw',{}))
    if explicit:
        key=explicit[7:] if explicit.startswith('@field:') else explicit
        if key in physical:return str(physical[key]),key
        # A displayed variable-bearing name may resolve to an exact property.
        source=row.get('field_name_sources',{}).get(key)
        return (str(physical[source]),source) if source in physical else ('',key)
    wanted={x.casefold() for x in aliases}
    hits={k:str(v) for k,v in physical.items() if k.casefold() in wanted and str(v).strip()}
    if len({normalize(v.strip()) for v in hits.values()})>1:raise ValueError('Conflicting '+label+' fields: '+', '.join(hits)+'. Choose one explicit field mapping.')
    return next(iter(hits.items()))[::-1] if hits else ('','')


def _route(name, ps):
    if not name.strip():return '',None
    norm=normalized_vendor(name)
    for pid,p in ps.items():
        if pid!='generic' and any(normalized_vendor(x)==norm for x in [p['name'],*p['aliases']]):return pid,p
    # Unknown free text stays an explicit generic vendor; never choose one of a list.
    if re.search(r'[/;|\n,]',name) or re.search(r'\s+(?:or|and)\s+',name,re.I):raise ValueError('Vendor contains multiple choices. Assign exactly one vendor before export.')
    _text(name,'vendor',100,False)
    pid='other-'+sha(norm.encode())[:16]
    return pid,{**ps['generic'],'name':name.strip()}


def part_signature(row):
    return digest({'id':row['id'],'physical':row.get('physical',row['raw']),'flags':row['flags']})


def preview(ws,variant=BASE,config=None):
    c=validate_config(config) if config is not None else configuration(ws)
    ws.project.check_unchanged();rows=ws.rows(variant)
    if len(rows)>100000:raise ValueError('Vendor export limited to 100000 physical components.')
    ps=profiles(c);boards=c['boards'] if c['boards'] is not None else ws.state['settings']['boards']
    if type(boards) is not int or not 1<=boards<=1000000:raise ValueError('Invalid board count.')
    attr=Decimal(str(c['attrition_percent'] if c['attrition_percent'] is not None else ws.state['settings']['attrition']))
    if not attr.is_finite() or not 0<=attr<=100:raise ValueError('Invalid project attrition percentage.')
    issues=[];global_errors=[];source_checks=ws.checks(variant,rows)
    # Engineering checks must not be bypassed by a purchasing-export shortcut.
    global_errors=[i for i in source_checks if i['severity']=='error']
    items=[];excluded=[];missing=[];groups={};used_profiles={}
    overrides=c['assignments'].get(variant,{})
    known={r['id'] for r in rows}
    for cid in overrides:
        if cid not in known:global_errors.append({'severity':'error','code':'STALE_VENDOR_TARGET','reference':cid,'message':'Routing assignment targets a missing instance. Remove it or remap after review.'})
    for row in rows:
        if row['flags']['dnp'] or not row['flags']['in_bom']:
            excluded.append({'id':row['id'],'reference':row['ref'],'reason':'DNP/DNI' if row['flags']['dnp'] else 'Excluded from BOM'})
            continue
        item={'id':row['id'],'reference':row['ref'],'signature':part_signature(row),'vendor':'','vendor_id':'',
              'mpn':'','manufacturer':'','sku':'','value':row['physical'].get('Value',''),
              'footprint':row['physical'].get('Footprint',''),'status':'ready','reasons':[],'mapping':{}}
        items.append(item)
        try:
            original,source=_get(row,c['vendor_field'],ALIASES['Supplier'],'vendor',normalized_vendor)
            item['mapping']['vendor']=source
            assigned=overrides.get(row['id'])
            if assigned and assigned['signature']!=item['signature']:raise ValueError('Manual routing is stale after a part/flag change. Review and assign again.')
            vendor=assigned['vendor'] if assigned else original
            pid,p=_route(vendor,ps);item.update(vendor=p['name'] if p else '',vendor_id=pid)
            for key,field,aliases in [('mpn','mpn_field',ALIASES['MPN']),('manufacturer','manufacturer_field',ALIASES['Manufacturer']),('customer','customer_field',ALIASES['InternalPN']),('moq','moq_field',ALIASES['MOQ']),('multiple','multiple_field',ALIASES['OrderMultiple'])]:
                value,source=_get(row,c[field],aliases,key)
                item[key]=value.strip();item['mapping'][key]=source
            if not p:
                item['status']='unassigned';item['reasons'].append('No vendor assigned.');missing.append(item);continue
            if assigned and 'sku' in assigned:
                sku=assigned['sku'];source='Reviewed routing override'
            elif c['sku_field']:
                # A general column's vendor must agree with the route. A manual
                # route change cannot carry a stale distributor SKU with it.
                if normalized_vendor(vendor)!=normalized_vendor(original):sku='';source='Generic SKU ignored after vendor override'
                else:sku,source=_get(row,c['sku_field'],[],'supplier part number')
            else:
                sku,source=_get(row,'',p['sku_fields'],'vendor-specific SKU')
                if not sku and normalized_vendor(vendor)==normalized_vendor(original):sku,source=_get(row,'',ALIASES['SKU'],'supplier part number')
            item['sku']=sku.strip();item['mapping']['sku']=source
            for key in ('sku','mpn','manufacturer','customer'):
                value=item[key]
                if CONTROL.search(value) or '${' in value or '@{' in value:raise ValueError('Unresolved expression or control character in '+key+'.')
                if value.lstrip().startswith(('=','+','-','@')):raise ValueError('Formula-like '+key+' cannot be changed safely for upload. Correct the source or use a reviewed safe identifier.')
                if len(value)>200:raise ValueError(key+' is longer than 200 characters; review the mapped identifier.')
            if not (item['sku'] or item['mpn']):raise ValueError('No distributor SKU or full manufacturer part number. Value/footprint cannot be used as a purchase identifier.')
            if not (('sku' in p['keys'] and item['sku']) or ('mpn' in p['keys'] and item['mpn'])):raise ValueError('Profile hides the only usable part identifier. Include its SKU or MPN column.')
            moq=integer(item['moq'],False) if item['moq'] else 1
            multiple=integer(item['multiple'],False) if item['multiple'] else 1
            # Check custom upload text without altering identifiers or cell values.
            for key in p['keys']:
                if key in ('value','footprint'):safe_upload_cell(item[key])
            # Deliberately never strip ordering suffixes or merge ratings.
            constraints=tuple(sorted((k,v) for k,v in row['physical'].items() if re.search(r'tolerance|voltage|power|dielectric|current|temp|qualif|packaging',k,re.I)))
            identity=(pid,' '.join(item['manufacturer'].split()).casefold(),item['mpn'],item['sku'],item['value'],item['footprint'],moq,multiple,item['customer'],constraints)
            if not item['sku'] and not item['manufacturer']:identity+=('unpooled',row['id'])
            group=groups.setdefault(identity,{'vendor':item['vendor'],'vendor_id':pid,'mpn':item['mpn'],'manufacturer':item['manufacturer'],
                        'sku':item['sku'],'value':item['value'],'footprint':item['footprint'],'customer_reference':item['customer'],
                        'ids':[],'refs':[],'moq':moq,'multiple':multiple})
            group['ids'].append(row['id']);group['refs'].append(row['ref']);used_profiles[pid]=p
        except ValueError as exc:
            item['status']='blocked';item['reasons'].append(str(exc));missing.append(item)
    # A distributor SKU cannot safely identify contradictory exact parts.
    sku_identities=defaultdict(set)
    for g in groups.values():
        if g['sku']:sku_identities[(g['vendor_id'],g['sku'])].add((' '.join(g['manufacturer'].split()).casefold(),g['mpn']))
    bad_skus={k for k,v in sku_identities.items() if len(v)>1}
    vendor_lines=defaultdict(list);items_by_id={x['id']:x for x in items}
    for g in groups.values():
        if (g['vendor_id'],g['sku']) in bad_skus:
            for cid in g['ids']:
                item=items_by_id[cid]
                item['status']='blocked';item['reasons'].append('Same vendor SKU identifies conflicting manufacturer/MPN records.');missing.append(item)
            continue
        installed=len(g['ids'])*boards
        required=int((Decimal(installed)*(1+attr/100)).to_integral_value(rounding=ROUND_CEILING))
        order=((max(required,g['moq'])+g['multiple']-1)//g['multiple'])*g['multiple']
        if order>10**12:raise ValueError('Calculated order quantity exceeds 10^12 pieces.')
        refs=', '.join(sorted(g.pop('refs'),key=natural))
        line={**g,'references':refs,'qty_per_board':len(g['ids']),'installed_qty':installed,'required_qty':required,
              'order_qty':order,'attrition_qty':required-installed,'overbuy_qty':order-required,
              'upload_qty':{'installed':installed,'required':required,'order':order}[c['quantity_basis']]}
        # The full reference list always remains in the internal audit. Long lists
        # use a deterministic line marker rather than silent string truncation.
        if not line['customer_reference']:
            line['customer_reference']=refs if len(refs)<=100 else 'KW-'+digest(sorted(g['ids']))[:16]
        vendor_lines[g['vendor_id']].append(line)
    vendors=[]
    for pid,lines in sorted(vendor_lines.items(),key=lambda kv:used_profiles[kv[0]]['name'].casefold()):
        p=used_profiles[pid];lines.sort(key=lambda l:(l['mpn'],l['sku'],natural(l['references'])))
        if pid.startswith('other-') or (pid in c['profiles']):
            issues.append({'severity':'warning','reference':p['name'],'code':'CUSTOM_VENDOR_PROFILE','message':'Generic/custom upload mapping; review importer column mapping. No live site acceptance has been executed.'})
        if any(not x['sku'] for x in lines):issues.append({'severity':'warning','reference':p['name'],'code':'MPN_MATCH_REVIEW','message':'Some rows use manufacturer MPN only. Review supplier part matching and packaging before purchase.'})
        vendors.append({'id':pid,'name':p['name'],'profile':p,'lines':lines,'line_count':len(lines),
                        'components':sum(l['qty_per_board'] for l in lines),'upload_qty':sum(l['upload_qty'] for l in lines),
                        'file_parts':(len(lines)+p['max_lines']-1)//p['max_lines']})
    for i in missing:issues.append({'severity':'error','reference':i['reference'],'code':'VENDOR_'+i['status'].upper(),'message':' '.join(i['reasons'])})
    ready=sum(v['components'] for v in vendors)
    if ready+len(missing)!=len(items):raise ValueError('Vendor reconciliation failed. No upload files can be created.')
    summary={'physical_components':len(rows),'eligible_components':len(items),'routed_components':ready,
             'unassigned_components':sum(x['status']=='unassigned' for x in missing),'blocked_components':sum(x['status']=='blocked' for x in missing),
             'excluded_components':len(excluded),'vendors':len(vendors),'upload_lines':sum(v['line_count'] for v in vendors),
             'installed_pieces':len(items)*boards,'routed_installed_pieces':ready*boards,'unresolved_installed_pieces':len(missing)*boards,
             'upload_pieces':sum(v['upload_qty'] for v in vendors),'reconciled':True}
    ws.project.check_unchanged()
    fingerprint=digest({'config':c,'variant':variant,'rows':[{'id':r['id'],'raw':r['raw'],'flags':r['flags']} for r in rows],
                        'resolved':[{k:v for k,v in r['physical'].items()} for r in rows],'source':ws.project.hashes,
                        'checks':source_checks,'boards':boards,'attrition':str(attr)})
    return {'schema':REPORT,'app_version':__version__,'generated_at':now(),'project':ws.project.name,'variant':variant,
            'config':c,'boards':boards,'attrition_percent':str(attr),'quantity_basis':c['quantity_basis'],
            'status':'BLOCKED' if global_errors else 'NEEDS_ROUTING' if missing else 'NO_PURCHASING_DEMAND' if not items else 'READY_FOR_REVIEW',
            'fingerprint':fingerprint,'source_sha256':dict(ws.project.hashes),'summary':summary,
            'vendors':vendors,'components':items,'unassigned':missing,'excluded':excluded,'issues':issues,
            'blocking_checks':global_errors,'source_checks':source_checks,
            'notice':'Read-only purchasing handoff. All quantities are total component PIECES. Set vendor assembly multiplier to 1 and additional attrition to 0. No stock check, reservation, upload or order has occurred.'}


def _delimited(headers,rows,fmt='csv', audit=False):
    from .exporters import safe_csv
    out=io.StringIO(newline='');writer=csv.writer(out,delimiter='\t' if fmt=='tsv' else ',',lineterminator='\r\n')
    writer.writerow(headers)
    for row in rows:writer.writerow([safe_csv(v) if audit else v for v in row])
    return out.getvalue().encode('utf-8-sig')


def upload_table(vendor):
    p=vendor['profile']
    return p['headers'],[[safe_upload_cell(l[k]) for k in p['keys']] for l in vendor['lines']]


def _xlsx(headers, rows, quantity_keys):
    """Use the existing formula-free OOXML writer, then keep one clean BOM sheet.

    One header row + data: no metadata banner that an importer could count as a
    part. IDs stay text (including leading zeros), quantities are numeric pieces.
    """
    from .exporters import xlsx
    payload={'columns':headers,'rows':rows,'template':{'columns':[{'field':'Qty' if k in ('upload_qty','required_qty','installed_qty','order_qty','overbuy_qty') else 'Text'} for k in quantity_keys]},
             'project':'Vendor upload','variant':'','boards':1,'attrition':0,'unpriced_lines':0,'totals':{},'order_totals':{},'issues':[]}
    original=xlsx(payload);out=io.BytesIO()
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            if name in ('xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml'):continue
            data=source.read(name)
            if name in ('[Content_Types].xml','xl/workbook.xml','xl/_rels/workbook.xml.rels'):
                tree=ET.fromstring(data)
                if name=='xl/workbook.xml':
                    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                    parent=tree.find('m:sheets',ns)
                    for elem in list(parent)[1:]:parent.remove(elem)
                else:
                    for elem in list(tree):
                        if elem.get('PartName','').endswith(('sheet2.xml','sheet3.xml')) or elem.get('Target','').endswith(('sheet2.xml','sheet3.xml')):tree.remove(elem)
                # Preserve conventional OOXML default namespaces for strict importers.
                ET.register_namespace('',tree.tag.split('}')[0][1:])
                ET.register_namespace('r','http://schemas.openxmlformats.org/officeDocument/2006/relationships')
                data=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            target.writestr(name,data)
    return out.getvalue()


def _audit_files(report):
    # This is the private master report; never upload it to a distributor.
    cols=['Vendor','References','Manufacturer','MPN','Supplier SKU','Value','Footprint','Per board','Installed pieces','Required pieces','Order pieces','Overbuy pieces','Upload pieces','Customer reference']
    keys=['vendor','references','manufacturer','mpn','sku','value','footprint','qty_per_board','installed_qty','required_qty','order_qty','overbuy_qty','upload_qty','customer_reference']
    rows=[[l[k] for k in keys] for v in report['vendors'] for l in v['lines']]
    audit={'reports/MASTER_ROUTING.csv':_delimited(cols,rows,audit=True),
           'reports/UNASSIGNED.csv':_delimited(['Reference','Vendor','MPN','Supplier SKU','Status','Reason'],[[r['reference'],r['vendor'],r['mpn'],r['sku'],r['status'],'; '.join(r['reasons'])] for r in report['unassigned']],audit=True),
           'reports/EXCLUDED.csv':_delimited(['Reference','Reason'],[[r['reference'],r['reason']] for r in report['excluded']],audit=True),
           'reports/REPORT.json':(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()}
    return audit


def package_files(report, allow_partial=False):
    if report.get('schema')!=REPORT:raise ValueError('Expected vendor report.')
    if report['blocking_checks']:raise ValueError('BOM checks block purchasing uploads. Resolve them first; partial export cannot bypass source/rule-area/variable checks.')
    if report['unassigned'] and allow_partial is not True:raise ValueError('Unassigned or blocked parts remain. Resolve them or explicitly allow a PARTIAL package with an unresolved-parts report.')
    if not report['vendors'] and report['summary']['eligible_components']:raise ValueError('No safely routed vendor lines. Preview the unresolved-parts report first.')
    prefix='PARTIAL_' if report['unassigned'] else ''
    files=_audit_files(report)
    instructions=['WayriCAD vendor-split purchasing handoff — '+report['app_version'],
                  'Status: '+('PARTIAL — UNRESOLVED PARTS OMITTED FROM UPLOADS' if prefix else 'NO PURCHASING DEMAND; AUDIT ONLY' if not report['vendors'] else 'READY FOR HUMAN REVIEW; NOT AN ORDER'),
                  report['notice'],'','Upload ONLY a file under uploads/. The files under reports/ contain private project/audit data.',
                  'CSV, TSV and XLSX files in the same vendor/chunk are ALTERNATIVE representations of the SAME demand. Upload ONE format, not all three.',
                  'Map columns when prompted. Verify exact full MPN, manufacturer, SKU packaging and quantities on the vendor site.',
                  'Assembly/build multiplier = 1. Additional supplier attrition = 0. Quantities already include selected build/allowance/order policies.',
                  'No API keys are required by this offline export. Supplier sites may require a free login.',
                  'File chunk sizes are configurable convenience defaults, not claims of universal vendor/account limits.','']
    for v in report['vendors']:
        p=v['profile'];name=re.sub('[^A-Za-z0-9_-]+','_',v['name']).strip('_')[:40] or 'Vendor'
        name+='__'+v['id']
        rows=v['lines'];size=p['max_lines'];chunks=(len(rows)+size-1)//size
        for part,start in enumerate(range(0,len(rows),size),1):
            table_vendor={**v,'lines':rows[start:start+size]};headers,values=upload_table(table_vendor)
            stem=f'uploads/{prefix}{name}'+(f'_{part:03d}-of-{chunks:03d}' if chunks>1 else '')
            for fmt in report['config']['formats']:
                files[stem+'.'+fmt]=_xlsx(headers,values,p['keys']) if fmt=='xlsx' else _delimited(headers,values,fmt)
        instructions.extend([v['name']+': '+p['url'],p['mapping'],'Columns: '+' | '.join(p['headers']),
                            'Documentation: '+p['source'],f'{len(rows)} lines; {v["upload_qty"]} total requested pieces; {chunks} chunk(s).',''])
    files['README_UPLOAD.txt']=('\n'.join(instructions)+'\n').encode()
    manifest={'schema':'wayricad-vendor-package-1','version':__version__,'status':'PARTIAL' if prefix else 'NO_PURCHASING_DEMAND' if not report['vendors'] else 'READY_FOR_REVIEW',
              'variant':report['variant'],'fingerprint':report['fingerprint'],'quantities':'total_component_pieces',
              'summary':report['summary'],'files':{n:{'bytes':len(b),'sha256':sha(b)} for n,b in sorted(files.items())}}
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    return files


def export(ws,variant=BASE,config=None,fmt='zip',vendor=None,allow_partial=False,fingerprint=None):
    if fmt not in MIME:raise ValueError('Unknown vendor export format.')
    report=preview(ws,variant,config)
    if fingerprint and report['fingerprint']!=fingerprint:raise ValueError('Vendor review is stale. Preview again.')
    if fmt=='json':return (json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode(),'Vendor_split_report.json',MIME[fmt]
    files=package_files(report,allow_partial)
    if fmt!='zip':
        if report['unassigned']:raise ValueError('Partial handoffs require ZIP so the unresolved-parts report stays with the uploads.')
        match=[v for v in report['vendors'] if vendor in (v['id'],v['name'])]
        if len(match)!=1:raise ValueError('Select exactly one vendor by ID/name for an individual upload file.')
        v=match[0]
        if len(v['lines'])>v['profile']['max_lines']:raise ValueError('Vendor needs multiple files; export ZIP to retain all chunks.')
        headers,values=upload_table(v)
        raw=_xlsx(headers,values,v['profile']['keys']) if fmt=='xlsx' else _delimited(headers,values,fmt)
        name=('PARTIAL_' if report['unassigned'] else '')+re.sub('[^A-Za-z0-9_-]+','_',v['name'])+'_upload.'+fmt
        return raw,name,MIME[fmt]
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):z.writestr(name,data)
    return out.getvalue(),('PARTIAL_' if report['unassigned'] else '')+'Vendor_BOMs.zip',MIME[fmt]
