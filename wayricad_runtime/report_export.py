"""Export saved tool JSON as consistent HTML and optional static PDF evidence."""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import sys

from .report_ui import checked_sources, enhance_report, publish_documents


def html_report(bundle, *, title='WayriCAD analysis report', source_digest=''):
    """Render every JSON value in bounded semantic tables, without executing code.

    This is an evidence reader, not a new analysis. Native report exporters retain
    their richer board views; large sampled datasets should use those exporters.
    """
    count=0
    def label(value):return str(value).replace('_',' ')
    def scalar(value):
        if value is None:return 'Unknown / not supplied'
        if isinstance(value,bool):return 'Yes' if value else 'No'
        return str(value)
    def cell(value):return escape(scalar(value))
    def visit(value, heading, depth=0):
        nonlocal count
        count+=1
        if depth>20 or count>20000:
            raise ValueError('Report exceeds 20 nesting levels or 20,000 values; use the tool-specific report for large sampled data.')
        tag='h2' if depth==0 else 'h3'
        out=['<'+tag+'>'+escape(heading)+'</'+tag+'>']
        if isinstance(value,dict):
            simple={key:item for key,item in value.items() if not isinstance(item,(dict,list))}
            if simple:
                count+=len(simple)
                out.append('<table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>')
                out.extend('<tr><td>'+escape(label(key))+'</td><td>'+cell(item)+'</td></tr>' for key,item in simple.items())
                out.append('</tbody></table>')
            for key,item in value.items():
                if isinstance(item,(dict,list)):out.append(visit(item,label(key),depth+1))
            if not value:out.append('<p>No entries.</p>')
        elif isinstance(value,list):
            if value and all(isinstance(row,dict) and all(not isinstance(v,(list,dict)) for v in row.values()) for row in value):
                columns=list(dict.fromkeys(key for row in value for key in row))
                if len(columns)>128:raise ValueError('Report table exceeds 128 columns.')
                out.append('<table><thead><tr><th>Entry</th>'+''.join('<th>'+escape(label(key))+'</th>' for key in columns)+'</tr></thead><tbody>')
                for index,row in enumerate(value):
                    count+=len(row)+1
                    out.append('<tr><td>'+str(index+1)+'</td>'+''.join('<td>'+cell(row[key])+'</td>' if key in row else '<td>Not supplied</td>' for key in columns)+'</tr>')
                out.append('</tbody></table>')
            elif all(not isinstance(item,(list,dict)) for item in value):
                count+=len(value)
                out.append('<table><tr><th>Entry</th><th>Value</th></tr>'+''.join('<tr><td>'+str(i+1)+'</td><td>'+cell(item)+'</td></tr>' for i,item in enumerate(value))+'</table>')
            else:
                for index,item in enumerate(value):out.append(visit(item,heading+' / '+str(index+1),depth+1))
        else:out.append('<p>'+cell(value)+'</p>')
        if count>20000:raise ValueError('Report exceeds 20,000 values; use the tool-specific report for large sampled data.')
        return ''.join(out)
    # Reject non-finite values even when called directly rather than via JSON intake.
    json.dumps(bundle,allow_nan=False)
    body=visit(bundle,'Results and evidence')
    title=escape(title)
    document='<!doctype html><html lang="en"><head><meta charset="utf-8"><title>'+title+'</title></head><body><h1>'+title+'</h1>'+body+'</body></html>'
    status=bundle.get('status','AS RECORDED') if isinstance(bundle,dict) else 'AS RECORDED'
    return enhance_report(document,status=status,summary=[('Input JSON SHA-256',source_digest or 'Not supplied')],
        notice='Saved values are reproduced without recomputation. Missing fields and unknown results remain unevaluated. Units are those declared by the originating tool.')


def export(source, *, html=None, pdf=None, title='WayriCAD analysis report'):
    """Publish requested formats together after verifying the saved input again."""
    source=Path(source)
    if not html and not pdf:raise ValueError('Choose --html and/or --pdf.')
    if source.stat().st_size>16*1024*1024:raise ValueError('Report input exceeds 16 MiB.')
    raw=source.read_bytes()
    def invalid(value):raise ValueError('Non-finite JSON value: '+value)
    bundle=json.loads(raw.decode('utf-8-sig'),parse_constant=invalid)
    protected=[source]
    if isinstance(bundle,dict):protected+=checked_sources(bundle)
    document=html_report(bundle,title=title,source_digest=hashlib.sha256(raw).hexdigest())
    outputs={}
    for path,suffix in ((html,'.html'),(pdf,'.pdf')):
        if path and Path(path).suffix.lower()!=suffix:raise ValueError('Choose a '+suffix+' output file.')
    if html:outputs[Path(html)]=document
    if pdf:
        from .pdf_report import pdf_bytes
        outputs[Path(pdf)]=pdf_bytes(document,title=title)
    if len(outputs)!=int(bool(html))+int(bool(pdf)):raise ValueError('Report output paths must differ.')
    if source.read_bytes()!=raw:raise ValueError('Report input changed during export; retry from the saved result.')
    if isinstance(bundle,dict):checked_sources(bundle)
    publish_documents(outputs,sources=protected)
    return {key:str(value) for key,value in (('html',html),('pdf',pdf)) if value}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Saved JSON result from any tool; never a board file.')
    parser.add_argument('--html',type=Path)
    parser.add_argument('--pdf',type=Path)
    parser.add_argument('--title',default='WayriCAD analysis report')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(export(args.source,html=args.html,pdf=args.pdf,title=args.title),indent=2));return 0
    except (ValueError,OSError,RuntimeError,ImportError) as error:
        print('WayriCAD report: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
