"""Deterministic, spreadsheet-safe exports and reproducible release manifests.

XLSX is minimal OOXML generated with the standard library. All user text is an
inline string; no imported text is executed as an Excel formula.
"""
from __future__ import annotations
from . import __version__
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import csv
import html
import io
import json
import math
import re
import zipfile
from xml.sax.saxutils import escape
from copy import deepcopy
from .textformats import MIME as EXTRA_MIME, EXT, render_extra, ascii_text
from .engine import Resolver, decimal_value, integer_value, now
from .native import BASE, natural, sha

MIME = {'csv':'text/csv; charset=utf-8','tsv':'text/tab-separated-values; charset=utf-8',
        'json':'application/json','html':'text/html; charset=utf-8',
        'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','zip':'application/zip'}
MIME.update(EXTRA_MIME)
NUMERIC = {'Qty','Required','OrderQty','LineCost','OrderCost','UnitPrice','Stock','MOQ','OrderMultiple','LeadTime','Item'}
DERIVED = {'Reference','UUID','Source','Qty','Required','OrderQty','LineCost','OrderCost','Item'}
GUARD_FIELDS = ['Value','Footprint','MPN','Manufacturer','Assembly','Currency','UnitPrice','Supplier','SKU','MOQ','OrderMultiple']

def filename(value: str) -> str:
    return (re.sub(r'[^\w.\-]+','_',str(value),flags=re.UNICODE).strip('._') or 'BOM')[:90]


def references(refs: list[str], ranges=False):
    refs=sorted(set(refs),key=natural)
    if not ranges:return ', '.join(refs)
    parts=[];i=0
    while i<len(refs):
        m=re.fullmatch(r'(.*?)(\d+)',refs[i]);j=i
        if m and not (len(m[2])>1 and m[2].startswith('0')):
            while j+1<len(refs):
                n=re.fullmatch(r'(.*?)(\d+)',refs[j+1])
                if not n or n[1]!=m[1] or n[2]!=str(int(m[2])+j+1-i):break
                j+=1
        if j-i>=2:parts.append(refs[i]+'–'+refs[j])
        else:parts.extend(refs[i:j+1])
        i=j+1
    return ', '.join(parts)


def _field(row,key,raw=False):
    source=row.get('field_name_sources',{}).get(key,key)
    if raw and key not in DERIVED and source in row.get('raw',{}):return row['raw'][source]
    if key in row['fields']:return row['fields'][key]
    if '${' in key:
        resolver=Resolver({**row['variables'],**{k:str(v) for k,v in row['fields'].items()}})
        return resolver.text(key)
    return ''


def table(workspace,variant=BASE,template='Engineering'):
    t=workspace.state['templates'].get(template)
    if t is None:raise ValueError('Unknown export template.')
    workspace.validate_template(t)
    t=deepcopy(t)
    for key,value in {'population':'all','group_by':[],'delimiter':',','include_excluded':False,'ref_ranges':False}.items():t.setdefault(key,value)
    t['columns']=[c for c in t['columns'] if c.get('export',True)]
    raw_mode=t.get('options',{}).get('text_mode','resolved')=='raw'
    rows=workspace.rows(variant)
    rows=[r for r in rows if (t.get('include_excluded',False) or r['flags']['in_bom']) and
          (t['population']=='all' or (t['population']=='fitted')==(r['fields']['Assembly']=='FIT'))]
    groups={}
    extra=[c['field'] for c in t['columns'] if c['field'] not in DERIVED and c['field'] not in ('Sheet','${QUANTITY}','${ITEM_NUMBER}')]
    for r in rows:
        # Procurement-critical attributes always split groups, even in a permissive
        # custom template. Never combine different packages or prices invisibly.
        keys=list(dict.fromkeys(t['group_by']+GUARD_FIELDS+extra))
        key=tuple(str(_field(r,k,raw_mode and k in extra)) for k in keys)+(tuple(r['flags'].values()),) if t['group_by'] else (r['id'],)
        groups.setdefault(key,[]).append(r)
    result=[];totals=defaultdict(Decimal);order_totals=defaultdict(Decimal);unpriced=0;alerts=[]
    boards=workspace.state['settings']['boards']
    attrition=Decimal(str(workspace.state['settings']['attrition']))/100
    for members in groups.values():
        first=members[0];fields=dict(first['fields']);qty=len(members)
        fitted=first['fields']['Assembly']=='FIT' and first['flags']['in_bom']
        required=int((Decimal(qty*boards)*(1+attrition)).to_integral_value(rounding=ROUND_CEILING)) if fitted else 0
        multiple=integer_value(fields.get('OrderMultiple'),1);moq=integer_value(fields.get('MOQ'),1)
        order=((max(moq,required)+multiple-1)//multiple)*multiple if required else 0
        price=decimal_value(fields.get('UnitPrice'));currency=fields.get('Currency','')
        cost=price*required if price is not None else None
        ordercost=price*order if price is not None else None
        if required and price is None:unpriced+=1
        if cost is not None:totals[currency]+=cost;order_totals[currency]+=ordercost
        stock=decimal_value(fields.get('Stock'))
        if stock is not None and stock<order:
            alerts.append({'severity':'warning','reference':references([r['ref'] for r in members]),'code':'STOCK_SHORTAGE',
                           'message':f'Order quantity {order} exceeds recorded stock {stock}. Stock is offline, not live.'})
        fields.update(Reference=references([r['ref'] for r in members],t.get('ref_ranges',False)).replace('–',t.get('options',{}).get('range_separator','–')).replace(', ',t.get('options',{}).get('reference_separator',', ')),Qty=qty,
                      Required=required,OrderQty=order,LineCost='' if cost is None else str(cost),
                      OrderCost='' if ordercost is None else str(ordercost),
                      UUID=', '.join(r['id'] for r in members),
                      Sheet=', '.join(sorted({r['fields']['Sheet'] for r in members})),
                      Source=', '.join(sorted({r['fields']['Source'] for r in members})))
        result.append({'fields':fields,'variables':first['variables'],'raw':first.get('raw',{}),'field_name_sources':first.get('field_name_sources',{}),'refs':[r['ref'] for r in members]})
    sort=t.get('sort_field','Reference')
    result.sort(key=lambda r:natural(r['fields'].get(sort,'')))
    for i,r in enumerate(result,1):r['fields']['Item']=i
    values=[];issues=workspace.checks(variant)+alerts
    for r in result:
        line=[]
        for c in t['columns']:
            field=c['field']
            source=r.get('field_name_sources',{}).get(field,field)
            if raw_mode and field not in DERIVED and source in r.get('raw',{}):
                value=r['raw'][source]
            elif field in r['fields']:
                value=r['fields'][field]
            elif '${' in field:
                resolver=Resolver({**r['variables'],**{k:str(v) for k,v in r['fields'].items()},'QUANTITY':str(r['fields'].get('Qty',1)),'ITEM_NUMBER':str(r['fields'].get('Item',''))})
                value=resolver.text(field)
                for error in resolver.errors:
                    issues.append({'severity':'error','reference':r['fields']['Reference'],'code':'TEMPLATE_VARIABLE','message':error})
            else:value=r['fields'].get(field,'')
            if isinstance(value,bool):value='Yes' if value else 'No'
            line.append(value)
        values.append(line)
    headers=[]
    for c in t['columns']:
        resolver=Resolver({**workspace.variables(variant),'PROJECTNAME':workspace.project.name,'VARIANT':'' if variant==BASE else variant})
        label=resolver.text(c['label'])
        headers.append(label)
        for error in resolver.errors:issues.append({'severity':'error','reference':'Header','code':'TEMPLATE_HEADER_VARIABLE','message':error})
    if len(set(headers))!=len(headers):issues.append({'severity':'error','reference':'Header','code':'HEADER_COLLISION','message':'Two column headers resolve to the same name.'})
    return {'project':workspace.project.name,'variant':variant,'template':t,'columns':headers,
            'rows':values,'groups':len(values),'boards':boards,'attrition':float(attrition*100),
            'totals':{k:str(v) for k,v in totals.items()},'order_totals':{k:str(v) for k,v in order_totals.items()},
            'unpriced_lines':unpriced,'issues':issues}


def safe_csv(value):
    value=str(value)
    # Spreadsheet consumers may trim whitespace before interpreting a formula.
    if value.lstrip(' \t\r\n').startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):
        return "'"+value
    return value


def _col(index):
    result=''
    while index:index,r=divmod(index-1,26);result=chr(65+r)+result
    return result


def xlsx(payload,draft=False):
    sheets=[('BOM',[payload['columns']]+payload['rows']),
            ('Release notes',[
                ['Status','DRAFT — NOT FOR MANUFACTURING' if draft else 'Checked export'],
                ['Project',payload['project']],['Variant',payload['variant']],['Generated UTC',now()],
                ['Boards',payload['boards']],['Attrition %',payload['attrition']],
                ['Unpriced lines',payload['unpriced_lines']],
                ['Cost note','Currencies remain separate. Prices/stock are user-supplied, not live.'],
                *[[f'Required cost ({k})',v] for k,v in payload['totals'].items()],
                *[[f'Order cost ({k})',v] for k,v in payload['order_totals'].items()]]),
            ('Checks',[['Severity','Reference','Code','Message']]+[[i['severity'],i['reference'],i['code'],i['message']] for i in payload['issues']])]
    out=io.BytesIO()
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        content='<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        for i in range(1,len(sheets)+1):content+=f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        z.writestr('[Content_Types].xml',content+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        rels=''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+rels+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00;[Red](#,##0.00);–"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF153D48"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for si,(name,rows) in enumerate(sheets,1):
            cols=len(rows[0]) if rows else 1
            chunks=[f'<worksheet xmlns="{ns}"><dimension ref="A1:{_col(cols)}{max(1,len(rows))}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols>']
            for ci in range(cols):
                width=min(70,max(14,max((len(str(row[ci])) if ci<len(row) else 0 for row in rows[:100]),default=14)+2))
                chunks.append(f'<col min="{ci+1}" max="{ci+1}" width="{width}" customWidth="1"/>')
            chunks.append('</cols><sheetData>')
            for ri,row in enumerate(rows,1):
                chunks.append(f'<row r="{ri}"'+(' ht="28" customHeight="1"' if ri==1 else '')+'>')
                for ci,v in enumerate(row,1):
                    is_numeric=ri>1 and si==1 and payload['template']['columns'][ci-1]['field'] in NUMERIC and decimal_value(v) is not None
                    address=f'{_col(ci)}{ri}'
                    if is_numeric:
                        n=decimal_value(v);style=2 if payload['template']['columns'][ci-1]['field'] in ('UnitPrice','LineCost','OrderCost') else 0
                        chunks.append(f'<c r="{address}" s="{style}" t="n"><v>{n}</v></c>')
                    else:
                        # XML 1.0 forbids control chars other than tab/newline/CR.
                        text=''.join(c for c in str(v) if ord(c)>=32 or c in '\t\r\n')
                        chunks.append(f'<c r="{address}" s="{1 if ri==1 else 0}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>')
                chunks.append('</row>')
            chunks.append('</sheetData>')
            if si in (1,3) and rows:chunks.append(f'<autoFilter ref="A1:{_col(cols)}{len(rows)}"/>')
            chunks.append('<pageMargins left="0.3" right="0.3" top="0.4" bottom="0.4" header="0.2" footer="0.2"/></worksheet>')
            z.writestr(f'xl/worksheets/sheet{si}.xml',''.join(chunks))
    return out.getvalue()


def render(payload,fmt,draft=False):
    if fmt in EXTRA_MIME:return render_extra(payload,fmt,draft)
    if fmt in ('csv','tsv'):
        options=payload['template'].get('options',{})
        out=io.StringIO(newline='');writer=csv.writer(out,delimiter='\t' if fmt=='tsv' else payload['template'].get('delimiter',','),lineterminator='\r\n' if options.get('line_ending','crlf')=='crlf' else '\n',quoting=csv.QUOTE_ALL if options.get('quoting','minimal')=='all' else csv.QUOTE_MINIMAL)
        writer.writerow([safe_csv(x) for x in payload['columns']])
        writer.writerows([safe_csv(v) for v in row] for row in payload['rows'])
        encoding=options.get('encoding','utf-8-sig');value=out.getvalue()
        if encoding=='ascii':value=ascii_text(value,options.get('ascii_policy','escape'))
        try:return value.encode(encoding)
        except UnicodeEncodeError as e:raise ValueError('Selected encoding cannot represent the BOM. Choose UTF-8 or escaped ASCII; no characters were replaced.') from e
    if fmt=='json':
        return (json.dumps(dict(payload,status='draft' if draft else 'checked',generated=now()),ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if fmt=='xlsx':return xlsx(payload,draft)
    if fmt=='html':
        esc=lambda x:html.escape(str(x),quote=True)
        heading=f"{payload['project']} · {payload['variant']}"
        body=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in payload['rows'])
        issues=''.join('<li>'+esc(i['severity'].upper()+' '+i['reference']+' — '+i['message'])+'</li>' for i in payload['issues'])
        return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(heading)}</title><style>body{{font:14px system-ui;margin:36px;color:#172f38}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #dce5e8;vertical-align:top}}th{{background:#153d48;color:white;position:sticky;top:0}}.status{{padding:12px;border:2px solid #153d48}}@media print{{th{{position:static}}body{{margin:0}}tr{{break-inside:avoid}}}}</style><h1>{esc(heading)}</h1><p class="status">'+('DRAFT — NOT FOR MANUFACTURING' if draft else 'Checked BOM export')+f'</p><p>{payload["boards"]} boards · {payload["attrition"]}% attrition · {payload["groups"]} lines · {esc(now())}</p><table><thead><tr>'+''.join('<th>'+esc(c)+'</th>' for c in payload['columns'])+'</tr></thead><tbody>'+body+'</tbody></table><h2>Cost by currency</h2><p>'+esc(json.dumps(payload['order_totals']))+f' · {payload["unpriced_lines"]} unpriced lines. Prices and stock are manually recorded, not live.</p><h2>Checks</h2><ul>'+issues+'</ul></html>').encode('utf-8')
    raise ValueError('Supported formats: '+', '.join(k.upper() for k in MIME if k!='zip'))


def export(workspace,variant,template,fmt,draft=False):
    workspace.project.check_unchanged()
    payload=table(workspace,variant,template)
    errors=[i for i in payload['issues'] if i['severity']=='error']
    if errors and not draft:raise ValueError(f'{len(errors)} release-blocking checks. Resolve them or explicitly export a DRAFT.')
    data=render(payload,fmt,draft)
    name=f'{filename(workspace.project.name)}_{filename(variant)}_{filename(template)}'+('_DRAFT' if draft else '')+'.'+EXT.get(fmt,fmt)
    mime=MIME[fmt]
    if fmt in ('csv','tsv'):
        enc=payload['template'].get('options',{}).get('encoding','utf-8-sig')
        mime=mime.split(';')[0]+'; charset='+{'utf-8-sig':'utf-8','ascii':'us-ascii','cp1252':'windows-1252'}.get(enc,enc)
    return data,name,mime


def release(workspace,variants=None,template='Purchasing',draft=False):
    variants=variants or [BASE]+list(workspace.state['variants'])
    if len(set(variants))!=len(variants):raise ValueError('Duplicate release variants.')
    workspace.project.check_unchanged()
    files={};summaries={}
    for index,v in enumerate(variants,1):
        payload=table(workspace,v,template)
        errors=[i for i in payload['issues'] if i['severity']=='error']
        if errors and not draft:raise ValueError(f'{v}: {len(errors)} blocking checks. Release cancelled; no partial ZIP.')
        folder=f'{index:02d}_{filename(v)}'
        for fmt in ('csv','xlsx','html','json','txt','xml'):files[folder+'/BOM.'+fmt]=render(payload,fmt,draft)
        if v!=BASE:files[folder+'/changes-vs-default.json']=(json.dumps(workspace.compare(BASE,v),ensure_ascii=False,indent=2)+'\n').encode()
        summaries[v]={'lines':payload['groups'],'totals':payload['order_totals'],'unpriced':payload['unpriced_lines'],'checks':payload['issues']}
    files['workspace-snapshot.json']=(json.dumps(workspace.state,ensure_ascii=False,indent=2)+'\n').encode()
    files['README.txt']=(('DRAFT — NOT FOR MANUFACTURING\n' if draft else 'CHECKED BOM RELEASE\n')+
        'BOM and procurement data only. This is not a complete manufacturing release.\n'
        'No Gerbers, PCB placement, ERC/DRC, schematic integrity or package-pin equivalence is certified.\n'
        'Source and workspace paths may disclose local directory names; review before sharing.\n'
        'Prices/stock/lifecycle are manually recorded, not live or supplier-validated.\n'
        'The manifest uses SHA-256 for integrity, not digital signatures or regulatory approval.\n').encode()
    manifest={'schema':1,'app':'WayriCAD BOM Studio '+__version__,'status':'DRAFT' if draft else 'CHECKED',
              'generated':now(),'project':workspace.project.name,'template':template,'variants':summaries,
              'source_sha256':workspace.project.hashes,'files':{k:sha(v) for k,v in files.items()}}
    files['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for path,data in files.items():z.writestr(path,data)
    return out.getvalue(),filename(workspace.project.name)+('_DRAFT' if draft else '')+'_bom-release.zip',MIME['zip']
