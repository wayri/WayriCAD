"""Analytics snapshots; no report is labelled as an approved manufacturing BOM.

Exports contain computed snapshot values, not executable imported spreadsheet
formulas. The standard-library XLSX writer keeps the installed plugin offline.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape, quoteattr
import csv
import html
import io
import json
import textwrap
import zipfile
from .exporters import safe_csv, filename, _col
from .textformats import ascii_text
from .native import sha

MIME={'json':'application/json', 'csv':'text/csv; charset=utf-8', 'tsv':'text/tab-separated-values; charset=utf-8',
      'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'html':'text/html; charset=utf-8',
      'txt':'text/plain; charset=utf-8', 'ascii':'text/plain; charset=us-ascii', 'md':'text/markdown; charset=utf-8', 'zip':'application/zip'}
TABLES=('summary','components','groups','procurement','scenarios','statistics','issues','families')
STATUS='ADVISORY ANALYTICS SNAPSHOT — NOT A MANUFACTURING APPROVAL'


def save_project_report(workspace, report):
    """Explicit export to a unique report folder beside the originating project."""
    from pathlib import Path
    import tempfile
    workspace.project.check_unchanged()
    project=workspace.project.pro_path.resolve().parent
    parent=project/'reports'/'wayricad-bom'
    if not parent.resolve().is_relative_to(project):
        raise ValueError('Project reports folder must not redirect outside the project.')
    parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='cost-mass-',dir=parent))
    outputs=[]
    for fmt,table,name in [('json','summary','analysis.json'),('html','summary','analysis.html'),
                           ('csv','summary','summary.csv'),('csv','components','components.csv')]:
        data,_,_=render(report,fmt,table)
        path=folder/name
        with path.open('xb') as stream:stream.write(data)
        outputs.append(str(path))
    return {'folder':str(folder),'files':outputs,'native_files_written':False}


def json_bytes(value):return (json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')


def tables(r):
    tables={}
    def put(name, columns, rows, numeric=()):
        tables[name]={'columns':columns, 'rows':rows, 'numeric':{columns.index(x) for x in numeric}}
    cols=['Breakdown level','Category','Physical components','Currency','Known cost per board','Price known','Price eligible','Known mass g','Mass known','Known dissipation W','Power known','Courtyard area mm2','Pad copper area mm2','Paired courtyard power W','Paired courtyard area mm2','Power per courtyard W/mm2','Paired pad power W','Paired pad area mm2','Power per pad W/mm2','Courtyard paired components','Pad paired components']
    rows=[]
    for group in r.get('component_analysis',{}).get('groups',[]):
        for currency,cost in (group['costs'].items() or [('',{})]):
            fa,pa=group['footprint_area_mm2'],group['pad_area_mm2']
            rows.append([group['level'],group['label'],group['physical_components'],currency,cost.get('known_total'),cost.get('known'),cost.get('eligible'),group['mass']['known_total'],group['mass']['known'],group['power']['known_total'],group['power']['known'],fa['known_total'],pa['known_total'],fa['paired_power_W'],fa['paired_area_mm2'],fa['paired_W_per_mm2'],pa['paired_power_W'],pa['paired_area_mm2'],pa['paired_W_per_mm2'],fa['paired_components'],pa['paired_components']])
    family_table={'columns':cols,'rows':rows,'numeric':{cols.index(x) for x in cols[2:3]+cols[4:]}}
    summary=[]
    def add(metric,scope,unit,value,known=None,eligible=None,note=''):
        summary.append([metric,scope,unit,value,known,eligible,note])
    add('Report status',r['variant'],'',None,note=STATUS)
    add('Project',r['project'],'',None,note=r['generated_at'])
    add('Scenario',r['config']['scenario_name'],'',None,note=r['config']['query'] or 'Whole active variant')
    add('Boards','Build','count',r['config']['boards'])
    add('Attrition','Purchasing only','%',r['config']['attrition_percent'],note='Not added to installed mass or dissipation.')
    for currency,p in r['pricing']['currencies'].items():
        for key,label,scope in [('known_cost_per_board','Installed component cost','Per board'),('known_build_cost','Installed component cost','Build'),
                                ('known_required_cost','Required cost including attrition','Build'),('known_order_cost','Order cost including MOQ/multiples','Build'),
                                ('known_overbuy_cost','Overbuy beyond required quantity','Build')]:
            add(label,scope,currency,p[key],p['priced_components'],p['eligible_components'],'Known subtotal; unknown inputs not treated as zero.')
    fx=r['pricing']['fx']
    if fx['enabled']:add('FX-converted known cost','Per board',fx['base_currency'],fx['known_cost_per_board'],note=fx['status']+'; user rates dated '+fx['as_of'])
    for metric,key,unit in [('Installed component mass','mass','g'),('Average operating dissipation','thermal','W')]:
        p=r[key];add(metric,'Per board',unit,p['known_per_board'],p['known_components'],p['eligible_components'],p['status'])
    add('Installed component mass','Build','g',r['mass']['known_build_total'],r['mass']['known_components'],r['mass']['eligible_components'])
    add('Minimum recorded Temp_Max','Physical fitted parts','C',r['thermal']['minimum_known_temp_max_c'],r['thermal']['temperature_ratings_known'],r['scope']['physical_components'],'Not a predicted junction/ambient temperature.')
    pcb=r.get('pcb',{})
    for key,title,unit in [('mass_g','Bare PCB mass','g'),('assembly_mass_g','Complete component + PCB mass','g'),('expected_unit_cost','Quoted PCB cost with setup allocation',pcb.get('currency','')),('expected_batch_cost','Quoted PCB batch cost',pcb.get('currency','')),('assembly_cost_per_board','Complete component + PCB cost',pcb.get('currency',''))]:
        add(title,'Declared PCB assumptions',unit,pcb.get(key),note=pcb.get('mass_basis','') if unit=='g' else pcb.get('cost_status','unknown'))
    for key,value in pcb.get('assumptions',{}).items():
        add('PCB input: '+key,'Declared inputs','',None,note=str(value) if value is not None else 'Unknown')
    for note in pcb.get('limitations',[]):add('PCB boundary','','',None,note=note)
    for b in r['budgets']:add('Budget: '+b['metric'],b['status'],b['unit'],b['limit'],note='Known subtotal: '+str(b['known_subtotal'])+'; missing: '+str(b['unknown_components']))
    for note in r['limits']:add('Boundary','','',None,note=note)
    put('summary',['Metric','Scope','Unit / currency','Known value / limit','Known components','Eligible components','Notes'],summary,['Known value / limit','Known components','Eligible components'])
    rows=[]
    for p in r['components']:
        c=p['cost'] or {};mass=p['mass'] or {};power=p['power'] or {};temp=p['temperature'] or {};rating=p['rating'] or {}
        rows.append([p['reference'],p['type'],p['type_source'],p['value'],p['footprint'],p['manufacturer'],p['mpn'],p['assembly'],p['in_bom'],p['on_board'],
                     p['price_eligible'],p['physical_eligible'],c.get('currency',''),c.get('currency_source',''),c.get('entered_rate'),c.get('price_per'),c.get('unit_price'),c.get('status','Not applicable'),
                     c.get('quote_date',''),c.get('quote_status',''),mass.get('value'),mass.get('status','Not applicable'),power.get('input_power_w'),power.get('duty_percent'),power.get('value'),power.get('status','Not applicable'),
                     rating.get('value'),power.get('rating_utilization_percent'),temp.get('value'),temp.get('headroom_c'),p['id']])
    cols=['Reference','Component type','Classification source','Component value','Footprint','Manufacturer','MPN','Assembly','In BOM','On board',
          'Price eligible','Physical eligible','Currency','Currency source','Entered rate','Price per units','Unit price','Price status','Quote date','Quote status',
          'Mass g','Mass status','Input dissipation W','Duty percent','Average dissipation W','Dissipation status','Recorded rating W','Rating utilization percent','Temp_Max C','Temperature headroom C','UUID']
    put('components',cols,rows,['Entered rate','Price per units','Unit price','Mass g','Input dissipation W','Duty percent','Average dissipation W','Recorded rating W','Rating utilization percent','Temp_Max C','Temperature headroom C'])
    currencies=list(r['pricing']['currencies'])
    cols=['Group','References','Components','Pricing components','Physical components']+['Cost per board '+c for c in currencies]+['Unpriced components','Known mass g','Mass missing / invalid','Known dissipation W','Power missing / invalid','Minimum Temp_Max C']
    put('groups',cols,[[g['label'],', '.join(g['references']),g['components'],g['pricing_components'],g['physical_components'],*[g['cost_per_board'].get(c) for c in currencies],g['price_missing_or_invalid'],g['mass_per_board'],g['mass_missing_or_invalid'],g['power_per_board'],g['power_missing_or_invalid'],g['min_temp_max_c']] for g in r['groups']],cols[2:])
    cols=['References','Manufacturer','MPN','Component value','Footprint','Supplier','SKU','Currency','Unit price','Quantity per board','Installed quantity','Required quantity','MOQ','Order multiple','Order quantity','Attrition quantity','Overbuy quantity','Installed cost','Required cost','Order cost','Overbuy cost','Identity complete','Order policy valid','Quote date']
    put('procurement',cols,[[', '.join(x['references']),x['manufacturer'],x['mpn'],x['value'],x['footprint'],x['supplier'],x['sku'],x['currency'],x['unit_price'],x['qty_per_board'],x['installed_qty'],x['required_qty'],x['moq'],x['order_multiple'],x['order_qty'],x['attrition_qty'],x['overbuy_qty'],x['installed_cost'],x['required_cost'],x['order_cost'],x['overbuy_cost'],x['identity_complete'],x['policy_valid'],x['quote_date']] for x in r['procurement']],cols[8:21])
    cols=['Boards','Currency','Known installed cost','Known order cost','Known order cost per board','Incomplete order lines','Mass per board g','Known installed batch mass g','Dissipation per board W','Rate assumption']
    put('scenarios',cols,[[x['boards'],x['currency'],x['known_installed_cost'],x['known_order_cost'],x['known_order_cost_per_board'],x['incomplete_order_lines'],x['mass_g_per_board'],x['known_installed_mass_g'],x['power_w_per_board'],x['price_assumption']] for x in r['scenarios']],cols[:1]+cols[2:9])
    cols=['Field','Canonical unit','Scope','Known','Missing','Invalid','Minimum','Maximum','Mean','Median','P95 nearest rank','Minimum references','Maximum references']
    put('statistics',cols,[[field,s['canonical_unit'],s['scope'],s['known'],s['missing'],s['invalid'],s['minimum'],s['maximum'],s['mean'],s['median'],s['p95_nearest_rank'],', '.join(s.get('minimum_references',[])),', '.join(s.get('maximum_references',[]))] for field,s in r['statistics'].items()],cols[3:11])
    put('issues',['Severity','Reference','Field','Code','Message'],[[i['severity'],i['reference'],i['field'],i['code'],i['message']] for i in r['issues']])
    tables['families']=family_table
    return tables


def csv_bytes(table, report, delimiter=','):
    out=io.StringIO(newline='');w=csv.writer(out,delimiter=delimiter,lineterminator='\r\n')
    context=['Project','Variant','Scenario','Generated UTC','Report status']
    values=[report['project'],report['variant'],report['config']['scenario_name'],report['generated_at'],STATUS]
    w.writerow([*context,*table['columns']])
    for row in table['rows']:w.writerow(safe_csv('' if v is None else v) for v in [*values,*row])
    return out.getvalue().encode('utf-8-sig')


def _plain(report, table, ascii_only=False):
    clean=lambda v:str('' if v is None else v).replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')
    data=[[clean(v) for v in row] for row in [table['columns'],*table['rows']]]
    if ascii_only:data=[[ascii_text(v) for v in row] for row in data]
    widths=[max(8,min(32,max(len(row[i]) for row in data))) for i in range(len(table['columns']))]
    border='+'+'+'.join('-'*(x+2) for x in widths)+'+'
    out=[STATUS,report['project']+' | '+report['variant']+' | '+report['config']['scenario_name'],report['generated_at'],'Blank numeric cells = unknown / not applicable, not zero.',border]
    for index,row in enumerate(data):
        wrapped=[textwrap.wrap(v,w,replace_whitespace=False,drop_whitespace=False) or [''] for v,w in zip(row,widths)]
        for line in range(max(map(len,wrapped))):out.append('| '+' | '.join((v[line] if line<len(v) else '').ljust(w) for v,w in zip(wrapped,widths))+' |')
        if index==0:out.append(border)
    out.append(border);text='\n'.join(out)+'\n'
    return ascii_text(text).encode('ascii') if ascii_only else text.encode('utf-8')


def html_bytes(report, all_tables):
    esc=lambda v:html.escape(str('—' if v is None else v),quote=True)
    out=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WayriCAD BOM analytics</title><style>body{font:14px system-ui;color:#18333c;background:#f5f8f9;margin:32px}h1{font-size:30px}h2{margin-top:32px}.status{padding:14px;border:2px solid #a86719;background:#fff7e8}.panel{overflow:auto;background:white;border:1px solid #d7e3e7;border-radius:8px;margin-top:12px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px 12px;vertical-align:top;border-bottom:1px solid #e1e8eb;max-width:350px;overflow-wrap:anywhere}th{background:#173f4b;color:white}td.num{text-align:right;font-variant-numeric:tabular-nums}meter{width:180px}small{color:#526976}a{color:#065a72}@media print{body{margin:0;background:white}.panel{overflow:visible;border:0}table{font-size:9px}tr{break-inside:avoid}h2{break-after:avoid}}</style></head><body>',
         '<h1>'+esc(report['project'])+' — BOM analytics</h1><p>'+esc(report['variant'])+' · '+esc(report['config']['scenario_name'])+' · '+esc(report['generated_at'])+'</p>',
         '<p class="status">'+esc(STATUS)+'<br>Known subtotals only. Blank inputs are not zeros; no live prices, discounts or thermal simulation.</p>',
         '<p>'+str(report['scope']['matched_components'])+' matched components · '+str(report['scope']['pricing_components'])+' pricing eligible · '+str(report['scope']['physical_components'])+' physical eligible.</p>',
         '<nav>'+' · '.join('<a href="#'+name+'">'+name.title()+'</a>' for name in all_tables)+'</nav>']
    for currency,pareto in report['pricing']['pareto'].items():
        out.append('<h2>Known cost contributors — '+esc(currency)+'</h2><div class="panel"><table><tr><th>Group</th><th>Known cost / board</th><th>Share of known subtotal</th><th>ABC</th></tr>')
        for x in pareto[:20]:
            share=x['share_percent'];numeric=float(share) if share is not None else 0
            out.append('<tr><td>'+esc(x['label'])+'</td><td class="num">'+esc(x['known_amount'])+'</td><td><meter min="0" max="100" value="'+str(numeric)+'"></meter> '+esc(share)+'%</td><td>'+esc(x['abc'])+'</td></tr>')
        out.append('</table></div>')
    analysis=report.get('component_analysis',{})
    if analysis:
        out.append('<h2>Component insights and evidence</h2><ul>'+''.join('<li>'+esc(v)+'</li>' for v in analysis['insights']+analysis['limits'])+'</ul>')
        for group in analysis['groups']:
            out.append('<details><summary>'+esc(group['label'])+' — '+esc(group['level'])+'</summary>')
            for label,bins in group['histograms'].items():
                if not bins:continue
                sample_size=sum(bin_['count'] for bin_ in bins)
                if sample_size<8:
                    members=[part for part in report['components'] if part['id'] in group['ids']]
                    if label.startswith('Unit cost '):
                        currency=label[len('Unit cost '):]
                        observations=[(part['reference'],part['cost']['unit_price']) for part in members
                                      if part.get('cost') and part['cost']['currency']==currency
                                      and part['cost']['unit_price'] is not None]
                    elif label=='Mass (g)':
                        observations=[(part['reference'],part['mass']['value']) for part in members
                                      if part.get('mass') and part['mass']['status']=='known']
                    elif label=='Dissipation (W)':
                        observations=[(part['reference'],part['power']['value']) for part in members
                                      if part.get('power') and part['power']['status']=='known']
                    else:
                        continue
                    out.append('<h3>'+esc(label)+'</h3><p>'+str(len(observations))+' of '
                               +str(len(members))+' components with known values; individual observations are shown instead of sparse histogram bins.</p>')
                    out.append('<div class="panel"><table><tr><th>Reference</th><th>Value</th></tr>')
                    for reference,value in sorted(observations,key=lambda item:item[1],reverse=True):
                        out.append('<tr><td>'+esc(reference)+'</td><td class="num">'+esc(value)+'</td></tr>')
                    out.append('</table></div>')
                    continue
                maximum=max(b['count'] for b in bins);width=320/len(bins)
                out.append('<figure><figcaption>'+esc(label)+' — component count</figcaption><svg role="img" aria-label="'+esc(label)+' histogram" viewBox="0 0 360 150" width="360" style="max-width:100%">')
                for i,bin_ in enumerate(bins):
                    h=90*bin_['count']/maximum
                    out.append(f'<rect x="{20+i*width}" y="{115-h}" width="{width-3}" height="{h}" fill="#148078"><title>'+esc(bin_['lower'])+' to '+esc(bin_['upper'])+': '+str(bin_['count'])+' components</title></rect>')
                out.append('<text x="20" y="140" font-size="11">'+esc(bins[0]['lower'])+'</text><text x="340" y="140" text-anchor="end" font-size="11">'+esc(bins[-1]['upper'])+'</text></svg></figure>')
            out.append('</details>')
        out.append('<details><summary>Geometry source and coverage</summary><pre>'+esc(json.dumps(analysis['geometry_source'],indent=2,ensure_ascii=False))+'</pre></details>')
    for name,t in all_tables.items():
        out.append('<h2 id="'+name+'">'+name.title()+'</h2><div class="panel"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in t['columns'])+'</tr></thead><tbody>')
        for row in t['rows']:out.append('<tr>'+''.join('<td'+(' class="num"' if i in t['numeric'] else '')+'>'+esc(v)+'</td>' for i,v in enumerate(row))+'</tr>')
        out.append('</tbody></table></div>')
    out.append('<h2>Calculation provenance</h2><p>Workspace SHA-256: '+esc(report['workspace_sha256'])+'</p><details><summary>Source fields, units, budgets and assumptions</summary><pre>'+esc(json.dumps(report['config'],indent=2,ensure_ascii=False))+'</pre></details></body></html>')
    return ''.join(out).encode('utf-8')


def workbook_bytes(report, all_tables):
    """Multi-sheet OOXML snapshot. Only trusted metric columns become numeric."""
    context={'columns':['Property','Value'],'rows':[['Status',STATUS],['Project',report['project']],['Variant',report['variant']],['Scenario',report['config']['scenario_name']],['Generated UTC',report['generated_at']],['Workspace SHA-256',report['workspace_sha256']],['Calculation contract','Computed snapshots, not recalculating spreadsheet formulas. Re-run analytics after input changes.'],*[[key,json.dumps(value,ensure_ascii=False)] for key,value in report['config'].items()]],'numeric':set()}
    sheets=[(name.title(),table) for name,table in all_tables.items()]+[('Provenance',context)]
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        content='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        for i in range(1,len(sheets)+1):content+=f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        z.writestr('[Content_Types].xml',content+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join('<sheet name='+quoteattr(name)+f' sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF173F4B"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF0F6F8"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" horizontal="right"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" horizontal="right"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for index,(name,t) in enumerate(sheets,1):
            rows=[t['columns'],*t['rows']];count=len(t['columns'])
            if len(rows)>1048576:raise ValueError('Report exceeds the XLSX row limit.')
            widths=[min(38,max(13,len(str(label))+2)) for label in t['columns']]
            if name=='Provenance':widths=[30,100]
            if name=='Summary':widths=[36,25,19,22,19,21,75]
            if name=='Issues':widths=[13,16,22,30,100]
            fragments=[f'<worksheet xmlns="{ns}"><dimension ref="A1:{_col(count)}{len(rows)}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="24"/><cols>']
            fragments += [f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i,w in enumerate(widths,1)]
            fragments.append('</cols><sheetData>')
            for ri,row in enumerate(rows,1):
                height=36 if ri==1 else min(110,max(24,16*max((1+(len(str(v or ''))//max(10,int(widths[ci])))) for ci,v in enumerate(row))))
                fragments.append(f'<row r="{ri}" ht="{height}" customHeight="1">')
                for ci,v in enumerate(row):
                    if v is None:continue
                    numeric=ri>1 and ci in t['numeric'] and not isinstance(v,bool)
                    if numeric:
                        try:n=Decimal(str(v));numeric=n.is_finite()
                        except (InvalidOperation,ValueError):numeric=False
                    address=_col(ci+1)+str(ri);even=ri%2==0
                    if numeric:
                        # More than 15 significant digits are kept as text so Excel
                        # cannot silently rewrite the exact exported decimal snapshot.
                        if len(n.as_tuple().digits)>15:numeric=False
                    if numeric:fragments.append(f'<c r="{address}" s="{4 if even else 2}" t="n"><v>{n}</v></c>')
                    else:
                        text=str(v)
                        if len(text)>32767:raise ValueError('XLSX cell exceeds 32,767 characters. Export JSON/CSV instead; no text was truncated.')
                        text=''.join(c for c in text if ord(c)>=32 or c in '\t\r\n')
                        fragments.append(f'<c r="{address}" s="{1 if ri==1 else 3 if even else 0}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>')
                fragments.append('</row>')
            fragments.append(f'</sheetData><autoFilter ref="A1:{_col(count)}{len(rows)}"/><pageMargins left="0.3" right="0.3" top="0.4" bottom="0.4" header="0.2" footer="0.2"/></worksheet>')
            z.writestr(f'xl/worksheets/sheet{index}.xml',''.join(fragments))
    return out.getvalue()


def render(report, fmt='json', table='summary'):
    if fmt=='asc':fmt='ascii'
    if fmt not in MIME:raise ValueError('Unknown analytics format: '+str(fmt))
    if table not in TABLES:raise ValueError('Unknown analytics table: '+str(table))
    t=tables(report);base=filename(report['project']+'_'+report['variant']+'_'+report['config']['scenario_name']+'_analytics')
    ext='asc' if fmt=='ascii' else fmt
    if fmt=='json':data=json_bytes(report)
    elif fmt in ('csv','tsv'):data=csv_bytes(t[table],report,'\t' if fmt=='tsv' else ',');base+='_'+table
    elif fmt=='html':data=html_bytes(report,t)
    elif fmt=='xlsx':data=workbook_bytes(report,t)
    elif fmt in ('txt','ascii'):data=_plain(report,t[table],fmt=='ascii');base+='_'+table
    elif fmt=='md':
        cell=lambda v:str('' if v is None else v).replace('\\','\\\\').replace('|','\\|').replace('<','&lt;').replace('>','&gt;').replace('\r','').replace('\n','<br>')
        rows=[t[table]['columns'],*t[table]['rows']]
        text=['# '+cell(report['project'])+' — '+cell(report['variant']),'',STATUS,'',report['generated_at'],'','| '+' | '.join(cell(v) for v in rows[0])+' |','| '+' | '.join('---' for _ in rows[0])+' |']
        text+=['| '+' | '.join(cell(v) for v in row)+' |' for row in rows[1:]];data=('\n'.join(text)+'\n').encode();base+='_'+table
    else:
        out=io.BytesIO();files={'analytics.json':json_bytes(report),'analytics.xlsx':workbook_bytes(report,t),'analytics.html':html_bytes(report,t)}
        files.update({name+'.csv':csv_bytes(value,report) for name,value in t.items()})
        manifest={'schema':'wayricad-analytics-bundle-1','report_status':'ADVISORY','files':{name:{'bytes':len(raw),'sha256':sha(raw)} for name,raw in files.items()}}
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for name,raw in files.items():z.writestr(name,raw)
            z.writestr('manifest.json',json_bytes(manifest))
        data=out.getvalue()
    return data,base+'.'+ext,MIME[fmt]
