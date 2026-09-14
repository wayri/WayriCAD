"""Open BOM interchange formats. Not netlists, IPC-2581 or ODB++ board data."""
from __future__ import annotations
import io
import json
import textwrap
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.sax.saxutils import escape, quoteattr

MIME={'txt':'text/plain; charset=utf-8','ascii':'text/plain; charset=us-ascii',
      'md':'text/markdown; charset=utf-8','xml':'application/xml; charset=utf-8',
      'jsonl':'application/x-ndjson','ods':'application/vnd.oasis.opendocument.spreadsheet'}
EXT={'ascii':'asc'}


def ascii_text(text,policy='escape'):
    text=str(text)
    if policy=='error':
        try:return text.encode('ascii').decode('ascii')
        except UnicodeEncodeError as e:raise ValueError('Non-ASCII data found. Choose Unicode text or escaped ASCII; no characters were silently replaced.') from e
    return text.encode('ascii',errors='backslashreplace').decode('ascii')


def render_extra(payload,fmt,draft=False):
    options=payload['template'].get('options',{})
    status='DRAFT - NOT FOR MANUFACTURING' if draft else 'CHECKED BOM DATA - REVIEW BEFORE RELEASE'
    if fmt in ('txt','ascii'):
        convert=(lambda v:ascii_text(v,options.get('ascii_policy','escape'))) if fmt=='ascii' else str
        clean=lambda v:convert(v).replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')
        data=[[clean(v) for v in row] for row in [payload['columns']]+payload['rows']]
        cap=options.get('ascii_width',36)
        widths=[max(8,min(cap,max(len(r[i]) for r in data))) for i in range(len(payload['columns']))]
        border='+'+'+'.join('-'*(w+2) for w in widths)+'+'
        out=[clean(status),clean(payload['project']+' | '+payload['variant']),
             f"Boards: {payload['boards']} | BOM lines: {payload['groups']}",
             'Escaping: non-ASCII uses \\xHH / \\uXXXX / \\UXXXXXXXX; controls are escaped.' if fmt=='ascii' else 'UTF-8 plain text; controls are escaped.',border]
        for index,row in enumerate(data):
            wrapped=[textwrap.wrap(v,w,replace_whitespace=False,drop_whitespace=False) or [''] for v,w in zip(row,widths)]
            for i in range(max(map(len,wrapped))):
                out.append('| '+' | '.join((v[i] if i<len(v) else '').ljust(w) for v,w in zip(wrapped,widths))+' |')
            if index==0:out.append(border)
        out.append(border)
        out.append('Prices/stock are offline inputs. This report is BOM data only.')
        return ('\r\n' if options.get('line_ending','crlf')=='crlf' else '\n').join(out).encode('ascii' if fmt=='ascii' else 'utf-8')
    if fmt=='md':
        cell=lambda v:str(v).replace('\\','\\\\').replace('|','\\|').replace('<','&lt;').replace('>','&gt;').replace('\r','').replace('\n','<br>')
        lines=['# '+cell(payload['project'])+' — '+cell(payload['variant']),'',status,'',
               '| '+' | '.join(cell(c) for c in payload['columns'])+' |',
               '| '+' | '.join('---' for _ in payload['columns'])+' |']
        lines+=['| '+' | '.join(cell(v) for v in r)+' |' for r in payload['rows']]
        return ('\n'.join(lines)+'\n').encode()
    if fmt=='xml':
        root=Element('bom',{'schema':'wayricad-bom-1','status':'draft' if draft else 'checked','project':payload['project'],'variant':payload['variant']})
        cols=SubElement(root,'columns')
        for i,label in enumerate(payload['columns']):SubElement(cols,'column',{'index':str(i),'label':label})
        lines=SubElement(root,'lines')
        for index,row in enumerate(payload['rows'],1):
            item=SubElement(lines,'line',{'number':str(index)})
            for i,v in enumerate(row):SubElement(item,'cell',{'column':str(i),'name':payload['columns'][i]}).text=str(v)
        checks=SubElement(root,'checks')
        for issue in payload['issues']:SubElement(checks,'issue',{'severity':issue['severity'],'reference':issue['reference'],'code':issue['code']}).text=issue['message']
        return tostring(root,encoding='utf-8',xml_declaration=True)
    if fmt=='jsonl':
        lines=[json.dumps({'type':'metadata','schema':'wayricad-bom-1','status':'draft' if draft else 'checked','project':payload['project'],'variant':payload['variant'],'columns':payload['columns']},ensure_ascii=False)]
        lines+=[json.dumps({'type':'bom_line','line':i,'fields':dict(zip(payload['columns'],row))},ensure_ascii=False) for i,row in enumerate(payload['rows'],1)]
        return ('\n'.join(lines)+'\n').encode()
    if fmt=='ods':return ods(payload,status)
    raise ValueError('Unknown text/interchange format: '+fmt)


def ods(payload,status):
    # ODF 1.2 packaging: first entry is uncompressed mimetype. No formulas/macros.
    ns='xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    sheets=[('BOM',[payload['columns']]+payload['rows']),('Release notes',[['Status',status],['Project',payload['project']],['Variant',payload['variant']],['Scope','BOM data only; no live supplier data or board manufacturing package.']])]
    parts=[f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns} office:version="1.2"><office:automatic-styles><style:style style:name="head" style:family="table-cell"><style:text-properties fo:font-weight="bold"/></style:style><style:style style:name="col" style:family="table-column"><style:table-column-properties style:column-width="1.7in"/></style:style></office:automatic-styles><office:body><office:spreadsheet>']
    for name,rows in sheets:
        parts.append('<table:table table:name='+quoteattr(name)+'><table:table-column table:style-name="col" table:number-columns-repeated="'+str(len(rows[0]))+'"/>')
        for i,row in enumerate(rows):
            parts.append('<table:table-row>')
            for v in row:
                content=escape(str(v)).replace('\t','<text:tab/>').replace('\r','').replace('\n','<text:line-break/>')
                parts.append('<table:table-cell office:value-type="string"'+(' table:style-name="head"' if i==0 else '')+'><text:p>'+content+'</text:p></table:table-cell>')
            parts.append('</table:table-row>')
        parts.append('</table:table>')
    parts.append('</office:spreadsheet></office:body></office:document-content>')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('mimetype',MIME['ods'],compress_type=zipfile.ZIP_STORED)
        z.writestr('content.xml',''.join(parts),compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('META-INF/manifest.xml','<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="'+MIME['ods']+'" manifest:version="1.2"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()
