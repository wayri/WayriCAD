"""Offline evidence ledger: manual records, supplier CSV/XLSX, browser snapshots.

No keys, requests, hidden endpoints, scraped search snippets or fabricated stock.
Supplier observations are timestamps, not reservations. Exact MPN and explicit
manufacturer identity are required for an eligible match; suffixes are retained.
"""
from __future__ import annotations
import base64
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, quote
from .engine import now
from .bulkedit import digest
from .engine import BASE

FIELDS=['manufacturer','mpn','supplier','sku','stock','observed_at','source_url','package','pin_count',
        'pitch_mm','body_x_mm','body_y_mm','mounting','exposed_pad','pin_numbers','pin_names','lifecycle',
        'moq','order_multiple','lead_time','packaging','region','currency','unit_price','notes',
        'value','tolerance','voltage_rating','power_rating','dielectric']
ALIASES={
 'value':['Value','Resistance','Capacitance','Inductance'], 'tolerance':['Tolerance'],
 'voltage_rating':['Voltage Rating','Voltage - Rated'], 'power_rating':['Power Rating','Power (Watts)'], 'dielectric':['Dielectric','Temperature Coefficient'],
 'mpn':['MPN','Manufacturer Part Number','Mfr. Part #','Mfr Part Number','Manufacturer P/N','Mfr Part #','Mfr. No.','Mfr No'],
 'manufacturer':['Manufacturer','Mfr','Mfr.','MFG'],
 'supplier':['Supplier','Distributor'], 'sku':['SKU','DigiKey Part Number','Digi-Key Part Number','Mouser Part Number','Mouser Part #','Mouser No','Part Number'],
 'stock':['Stock','Quantity Available','Available Quantity','Availability','In Stock','Stock Quantity','Available'],
 'package':['Package','Package / Case','Package Case','Supplier Device Package','Package/Case'],
 'observed_at':['Observed At','Timestamp','Stock Date','Date Checked'],
 'source_url':['Source URL','Product URL','Product Link','URL'],
 'pin_count':['Pin Count','Number of Pins','Number of Terminations'],
 'pitch_mm':['Pitch mm','Pitch (mm)'],'body_x_mm':['Body X mm'],'body_y_mm':['Body Y mm'],
 'mounting':['Mounting','Mounting Type','Mounting Style'], 'exposed_pad':['Exposed Pad'],
 'lifecycle':['Lifecycle','Product Status','Life Cycle'], 'moq':['MOQ','Minimum Order Quantity','Minimum Order'],
 'order_multiple':['Order Multiple','OrderMultiple','Multiples'], 'lead_time':['Lead Time','Standard Lead Time'],
 'region':['Region','Market','Country'], 'currency':['Currency'], 'unit_price':['Unit Price','Price'],
 'packaging':['Packaging'], 'notes':['Notes'], 'pin_numbers':['Pin Numbers'], 'pin_names':['Pin Names']}


def identity(manufacturer,mpn):
    # Manufacturer case/whitespace are cosmetic; MPN case, punctuation and suffix
    # are NOT discarded. Company acquisition/brand aliases are not guessed.
    return (' '.join(str(manufacturer).split()).casefold(),str(mpn).strip())


def safe_url(url):
    if not url:return ''
    p=urlsplit(str(url))
    if p.scheme!='https' or not p.hostname or p.username or p.password or len(url)>4096:
        raise ValueError('Source links must be HTTPS URLs without embedded credentials.')
    return str(url)


def integer(text,allow_zero=True):
    if text is None or str(text).strip()=='':return None
    if type(text) is bool:raise ValueError('Expected a quantity, not a boolean.')
    s=str(text).strip()
    # English grouped integers only: ambiguous locale decimals remain rejected.
    if not re.fullmatch(r'\d+|\d{1,3}(?:,\d{3})+',s):raise ValueError('Quantity must be an exact integer (English comma thousands allowed): '+s[:80])
    n=int(s.replace(',',''))
    if n>10**12 or n<(0 if allow_zero else 1):raise ValueError('Quantity out of range.')
    return n


def numeric(value):
    if value in ('',None):return None
    s=str(value).strip()
    if not re.fullmatch(r'\d+(?:\.\d+)?',s):raise ValueError('Dimensions/prices use nonnegative decimal numbers without units.')
    n=float(s)
    if not 0<=n<=1e12:raise ValueError('Numeric value out of range.')
    return n


def validate_record(record):
    if not isinstance(record,dict):raise ValueError('Evidence record must be an object.')
    r={k:record.get(k,'') for k in FIELDS}
    numbers={'stock','pin_count','moq','order_multiple','pitch_mm','body_x_mm','body_y_mm','unit_price','exposed_pad','pin_numbers','pin_names'}
    for k in FIELDS:
        if k not in numbers and r[k] is None:r[k]=''
    for k in FIELDS:
        if k in ('pin_names','pin_numbers'):continue
        if isinstance(r[k],(dict,list)) or len(str(r[k]))>32767:raise ValueError('Invalid evidence field '+k)
    r['manufacturer']=str(r['manufacturer']).strip();r['mpn']=str(r['mpn']).strip()
    if not r['mpn']:raise ValueError('Exact manufacturer part number is required.')
    r['supplier']=str(r['supplier']).strip() or 'Manual'
    r['source_url']=safe_url(str(r['source_url']))
    for k in ('stock','pin_count','moq','order_multiple'):r[k]=integer(r[k],k=='stock')
    for k in ('pitch_mm','body_x_mm','body_y_mm','unit_price'):r[k]=numeric(r[k])
    for k in ('pitch_mm','body_x_mm','body_y_mm'):
        if r[k] is not None and r[k]<=0:raise ValueError('Dimensions must be positive.')
    raw=str(r['observed_at']).strip()
    if raw:
        try:
            d=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            r['observed_at']=d.isoformat(timespec='seconds')
        except ValueError:raise ValueError('Observation date must use ISO format, e.g. 2026-09-09T10:00:00Z.')
    else:r['observed_at']=''
    mounting=str(r['mounting']).strip().upper()
    mounting={'SURFACE MOUNT':'SMD','SURFACE MOUNT TECHNOLOGY':'SMD','SMT':'SMD','THROUGH HOLE':'THT','TH':'THT'}.get(mounting,mounting)
    if mounting not in ('','SMD','THT','MIXED'):raise ValueError('Mounting must be SMD, THT, MIXED or blank.')
    r['mounting']=mounting
    ep=r['exposed_pad']
    if type(ep) is bool:r['exposed_pad']=ep
    elif str(ep).strip().lower() in ('yes','true','1'):r['exposed_pad']=True
    elif str(ep).strip().lower() in ('no','false','0'):r['exposed_pad']=False
    elif ep in ('',None):r['exposed_pad']=None
    else:raise ValueError('Exposed pad must be yes/no or blank.')
    pins=r['pin_numbers']
    if isinstance(pins,str):pins=[s.strip() for s in re.split(r'[,;\s]+',pins) if s.strip()]
    if pins is None:pins=[]
    if not isinstance(pins,list) or len(pins)>3000 or any(not isinstance(x,str) or len(x)>50 for x in pins):raise ValueError('Invalid pin-number list.')
    if len(pins)!=len(set(pins)):raise ValueError('Duplicate expected pin numbers.')
    r['pin_numbers']=pins
    names=r['pin_names']
    if names in ('',None):names={}
    elif isinstance(names,str):
        try:names=json.loads(names)
        except ValueError:raise ValueError('Pin names must be a JSON object mapping number to name.')
    if not isinstance(names,dict) or len(names)>3000 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>50 or len(v)>200 for k,v in names.items()):raise ValueError('Invalid pin-name map.')
    r['pin_names']=names
    if r['currency'] and not re.fullmatch('[A-Z]{3}',str(r['currency'])):raise ValueError('Use a 3-letter uppercase currency code.')
    r['reviewed']=record.get('reviewed') is True
    r['origin']=str(record.get('origin','manual'))[:120]
    r['captured_text']=str(record.get('captured_text',''))[:5000]
    r['imported_at']=now()
    r['id']=hashlib.sha256(json.dumps({k:v for k,v in r.items() if k not in ('imported_at','reviewed')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    return r



def validate_ledger(records):
    """Reject malformed sidecars; hashes are consistency checks, not signatures."""
    if not isinstance(records,list) or len(records)>100000:raise ValueError('Invalid evidence ledger.')
    ids=set()
    for record in records:
        checked=validate_record(record)
        if record.get('id')!=checked['id'] or record.get('id') in ids:raise ValueError('Invalid or duplicate evidence record ID. Re-import the source evidence.')
        if any(record.get(k)!=checked[k] for k in FIELDS):raise ValueError('Noncanonical evidence data. Re-import through the reviewed evidence workflow.')
        if type(record.get('reviewed')) is not bool:raise ValueError('Invalid evidence review flag.')
        ids.add(record['id'])

def decode_table(text):
    if not isinstance(text,str) or len(text)>10*1024*1024:raise ValueError('Table text must be below 10 MiB.')
    try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t|')
    except csv.Error:dialect=csv.excel
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff')),dialect))
    if len(rows)>50001:raise ValueError('Import limited to 50,000 rows.')
    return rows


def _xlsx_table(encoded,sheet_index=0):
    """Read a bounded plain-data XLSX worksheet; no macros, formulas or links run."""
    try:raw=base64.b64decode(encoded,validate=True)
    except Exception:raise ValueError('Invalid XLSX encoding.')
    if len(raw)>10*1024*1024:raise ValueError('XLSX limited to 10 MiB compressed.')
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        if len(infos)>2000 or sum(i.file_size for i in infos)>50*1024*1024:raise ValueError('XLSX exceeds archive limits.')
        def xml(name):
            b=z.read(name)
            if b'<!DOCTYPE' in b.upper() or b'<!ENTITY' in b.upper():raise ValueError('XML entities are not supported.')
            return ET.fromstring(b)
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():strings=[''.join(s.itertext()) for s in xml('xl/sharedStrings.xml').findall('m:si',ns)]
        book=xml('xl/workbook.xml');sheets=book.findall('m:sheets/m:sheet',ns)
        if type(sheet_index) is not int or not 0<=sheet_index<len(sheets):raise ValueError('Choose a valid worksheet index (0-based).')
        relid=sheets[sheet_index].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        rels={x.get('Id'):x for x in xml('xl/_rels/workbook.xml.rels')}
        rel=rels.get(relid)
        if rel is None or rel.get('TargetMode')=='External':raise ValueError('Invalid worksheet relationship.')
        import posixpath
        target=posixpath.normpath('xl/'+rel.get('Target','')) if not rel.get('Target','').startswith('/') else rel.get('Target')[1:]
        if not target.startswith('xl/worksheets/'):raise ValueError('Only ordinary XLSX worksheets are supported.')
        table=[]
        for row in xml(target).findall('m:sheetData/m:row',ns):
            if len(table)>=50001:raise ValueError('XLSX limited to 50,000 data rows.')
            values={}
            for cell in row.findall('m:c',ns):
                address=cell.get('r','');m=re.fullmatch(r'([A-Z]+)[1-9]\d*',address)
                if not m:raise ValueError('Invalid XLSX cell address.')
                index=0
                for ch in m[1]:index=index*26+ord(ch)-64
                if index>200:raise ValueError('Import limited to 200 columns; trim the supplier worksheet first.')
                if cell.find('m:f',ns) is not None:raise ValueError('Formula cells are not imported as evidence. Save a values-only copy or CSV.')
                value=cell.findtext('m:v','',ns)
                if cell.get('t')=='s':value=strings[int(value)]
                elif cell.get('t')=='inlineStr':value=''.join(cell.find('m:is',ns).itertext()) if cell.find('m:is',ns) is not None else ''
                values[index-1]=value
            table.append([values.get(i,'') for i in range(max(values,default=-1)+1)])
        return table,[s.get('name','') for s in sheets]


def xlsx_table(encoded,sheet_index=0):
    try:return _xlsx_table(encoded,sheet_index)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, UnicodeError) as exc:
        raise ValueError('Invalid/unsupported XLSX structure: '+str(exc)) from exc


def table_info(payload):
    if payload.get('format')=='xlsx':rows,sheets=xlsx_table(payload.get('base64',''),payload.get('sheet_index',0))
    else:rows=decode_table(payload.get('text',''));sheets=[]
    header_index=payload.get('header_index',0)
    if type(header_index) is not int or not 0<=header_index<len(rows):raise ValueError('Choose a valid header row (0-based).')
    headers=rows[header_index]
    if not headers or len(headers)>200 or len(set(headers))!=len(headers):raise ValueError('Headers must be nonempty, unique and at most 200 columns.')
    mapping={}
    for key,aliases in ALIASES.items():
        accepted={re.sub(r'[^a-z0-9]','',x.lower()) for x in aliases+[key]}
        matches=[h for h in headers if re.sub(r'[^a-z0-9]','',h.lower()) in accepted]
        if len(matches)==1:mapping[key]=matches[0]
    return rows[header_index+1:],{'headers':headers,'mapping':mapping,'samples':rows[header_index+1:header_index+6],'sheets':sheets,'rows':len(rows)-header_index-1}


def preview(ws,payload):
    mode=payload.get('format','csv');records=[];errors=[]
    if mode=='json':
        text=payload.get('text','')
        if len(text)>10*1024*1024:raise ValueError('Evidence JSON too large.')
        data=json.loads(text)
        if not isinstance(data,dict) or data.get('schema')!='wayricad-evidence-1':raise ValueError('Use a wayricad-evidence-1 JSON bundle.')
        records=data.get('records',[])
        if not isinstance(records,list):raise ValueError('records must be a list.')
    elif mode=='manual':records=[payload.get('record',{})]
    else:
        rows,info=table_info(payload);mapping=payload.get('mapping',info['mapping'])
        if not isinstance(mapping,dict) or any(k not in FIELDS or v not in info['headers'] for k,v in mapping.items() if v):raise ValueError('Invalid field mapping.')
        if not mapping.get('mpn'):raise ValueError('Map the exact manufacturer part number column, not the distributor SKU.')
        for line,row in enumerate(rows,1):
            if not any(str(x).strip() for x in row):continue
            if len(row)>len(info['headers']):errors.append({'row':line,'message':'Extra columns in row.'});continue
            source=dict(zip(info['headers'],row))
            r={k:source.get(v,'') for k,v in mapping.items() if v}
            for k in ('supplier','region','observed_at','source_url'):r[k]=r.get(k) or payload.get(k,'')
            r['origin']='supplier-table';records.append(r)
    if not records or len(records)>50000:raise ValueError('Import 1–50,000 evidence records.')
    output=[];bykey=set()
    for variant in [BASE,*ws.state['variants']]:
        bykey.update(identity(r['fields'].get('Manufacturer',''),r['fields'].get('MPN','')) for r in ws.rows(variant))
    for i,raw in enumerate(records,1):
        try:
            r=validate_record(raw);r['reviewed']=True # staged only after explicit user attestation
            matched=bool(r['manufacturer']) and identity(r['manufacturer'],r['mpn']) in bykey
            output.append({'record':r,'match':'exact identity present' if matched else 'unmatched / manufacturer missing'})
        except (ValueError,TypeError) as exc:errors.append({'row':i,'message':str(exc)})
    return {'items':output,'errors':errors,'fingerprint':digest(ws,payload),
        'warning':'Review manufacturer, exact MPN including suffix, stock units, source and observation time. Imported observations are not live stock or independently authenticated.'}


def apply(ws,payload,fingerprint,confirmation,reviewed):
    if confirmation!='IMPORT' or reviewed is not True:raise ValueError('Review the evidence, acknowledge it, and type IMPORT.')
    if digest(ws,payload)!=fingerprint:raise ValueError('Import preview is stale; preview again.')
    plan=preview(ws,payload)
    if plan['errors']:raise ValueError('Fix all import errors before applying; no rows have been imported.')
    def save():
        ledger=ws.state.setdefault('evidence',[]);existing={r['id'] for r in ledger};count=0
        for item in plan['items']:
            r=item['record']
            if r['id'] not in existing:ledger.append(r);existing.add(r['id']);count+=1
        if len(ledger)>100000:raise ValueError('Evidence ledger limit exceeded; remove old records first.')
        return count
    return {'imported':ws.commit('Import reviewed supplier/package evidence',save)}


def remove(ws,ids):
    if not isinstance(ids,list) or len(ids)>100000:raise ValueError('Invalid evidence ID list.')
    ws.commit('Remove evidence records',lambda:ws.state.update(evidence=[r for r in ws.state.get('evidence',[]) if r['id'] not in ids]))


def supplier_links(mpn):
    q=quote(str(mpn),safe='')
    return {'DigiKey':'https://www.digikey.in/en/products/result?keywords='+q,
            'Mouser':'https://www.mouser.in/c/?q='+q}
