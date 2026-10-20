"""Offline report review controls and recoverable publication of paired evidence."""
from __future__ import annotations

from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


REPORT_CSS = '''
.report-summary{display:block!important;padding:18px;border:1px solid #bacdd5;border-left:5px solid #267c86;background:#f2f8fa;border-radius:8px;margin:18px 0}.report-summary dl{display:grid;grid-template-columns:minmax(110px,1fr) minmax(180px,3fr);gap:7px 18px}.report-summary dt{font-weight:600}.report-summary dd{margin:0;overflow-wrap:anywhere}.report-nav{display:flex;flex-wrap:wrap;gap:8px;padding:12px;border:1px solid #cbd8df;margin:16px 0}.report-nav a{padding:4px 8px;color:#155c85}.report-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0}.report-tools input{font:inherit;padding:8px;min-width:200px;flex:1;max-width:500px}.report-tools button,.report-sort{font:inherit;cursor:pointer;border:1px solid #b9cbd4;background:#fff;padding:6px 10px;border-radius:4px;color:#203744}.report-sort{border:0;background:transparent;font-weight:600;padding:0;text-align:left}.report-table{max-width:100%;overflow:auto;border:1px solid #d4e0e5;border-radius:6px;margin:10px 0 22px}.report-table table{width:100%;border-collapse:collapse}.report-table th,.report-table td{padding:9px 11px;border-bottom:1px solid #d4e0e5;text-align:left;vertical-align:top;overflow-wrap:anywhere}.report-table th{background:#eef4f7;position:sticky;top:0}.report-table td{max-width:40rem}.report-print{font:inherit;padding:8px 13px;cursor:pointer}.report-note{color:#536976}.report-evidence pre{max-height:26rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}body{box-sizing:border-box;width:auto;max-width:1500px;margin:30px auto;padding:0 20px;font:15px/1.6 system-ui,sans-serif;color:#203744;background:#fff}body>section{min-width:0}img,svg{max-width:100%}h2,h3{scroll-margin-top:15px}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid #42aab5;outline-offset:2px}@media(max-width:650px){.report-summary dl{grid-template-columns:1fr}.report-summary dd{margin-bottom:10px}body>section{grid-template-columns:minmax(0,1fr)!important}}@media print{body{max-width:none;margin:0;padding:0;color:#000}.report-tools,.report-nav,.report-print{display:none!important}.report-table,.report-evidence pre{overflow:visible;max-height:none;border:0}.report-table tr[hidden]{display:table-row!important}.report-table th{position:static}details>*{display:block!important}details>summary{font-weight:bold}figure,.report-summary,tr{break-inside:avoid}.report-sort{padding:0;border:0}a{color:#000}img{max-height:230mm;object-fit:contain}}
'''

REPORT_JS = r'''
(()=>{
 const headings=[...document.querySelectorAll('h2')];
 const nav=document.querySelector('.report-nav');
 headings.forEach((heading,index)=>{if(!heading.id)heading.id='report-section-'+index;if(nav){const link=document.createElement('a');link.href='#'+heading.id;link.textContent=heading.textContent;link.addEventListener('click',()=>{let parent=heading.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}});nav.append(link);}});
 document.querySelector('.report-print')?.addEventListener('click',()=>window.print());
 let printedDetails=[];window.addEventListener('beforeprint',()=>{printedDetails=[...document.querySelectorAll('details:not([open])')];printedDetails.forEach(item=>item.open=true);});window.addEventListener('afterprint',()=>{printedDetails.forEach(item=>item.open=false);printedDetails=[];});
 document.querySelectorAll('table').forEach((table,index)=>{
   // Interactive board tables keep their own cross-selection, sorting and filters.
   if(table.closest('#thermal-context,.thermal-interactive,.interactive-plot,.interactive-analysis')||table.dataset.reportReview==='skip')return;
   const rows=[...table.rows];if(rows.length<2)return;
   const header=rows[0];if(![...header.cells].every(cell=>cell.tagName==='TH'))return;
   const wrapper=document.createElement('div');wrapper.className='report-table';table.before(wrapper);wrapper.append(table);
   const tools=document.createElement('div');tools.className='report-tools';
   const label=document.createElement('label');label.textContent='Find in table '+(index+1)+' ';const input=document.createElement('input');input.type='search';input.placeholder='Reference, net, value or status';input.setAttribute('aria-label','Search table '+(index+1));label.append(input);
   const count=document.createElement('span');count.className='report-note';count.setAttribute('aria-live','polite');
   tools.append(label,count);wrapper.before(tools);
   const dataRows=rows.slice(1);const original=new Map(dataRows.map((row,i)=>[row,i]));
   function filter(){let shown=0;const term=input.value.toLocaleLowerCase();dataRows.forEach(row=>{row.hidden=!row.textContent.toLocaleLowerCase().includes(term);if(!row.hidden)shown++;});count.textContent=shown+' / '+dataRows.length+' rows';}
   input.addEventListener('input',filter);filter();
   [...header.cells].forEach((cell,column)=>{const button=document.createElement('button');button.type='button';button.className='report-sort';button.textContent=cell.textContent;button.title='Sort by '+cell.textContent;cell.textContent='';cell.append(button);let ascending=true;
     button.addEventListener('click',()=>{const direction=ascending?1:-1;const ordered=[...dataRows].sort((a,b)=>{const x=a.cells[column]?.textContent.trim()||'',y=b.cells[column]?.textContent.trim()||'';const number=text=>{const match=/^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+[^\d]*)?$/.exec(text);return match?Number(match[1]):NaN;};const nx=number(x),ny=number(y);const difference=Number.isFinite(nx)&&Number.isFinite(ny)?nx-ny:x.localeCompare(y,undefined,{numeric:true,sensitivity:'base'});return direction*difference||original.get(a)-original.get(b);});ordered.forEach(row=>row.parentElement.append(row));[...header.cells].forEach(other=>other.removeAttribute('aria-sort'));cell.setAttribute('aria-sort',ascending?'ascending':'descending');ascending=!ascending;});
   });
 });
})();
'''


def enhance_report(document, *, status='UNKNOWN', summary=(), notice='', provenance=None):
    """Add offline review controls without replacing existing plot/probe scripts."""
    rows=''.join('<dt>'+escape(str(label))+'</dt><dd>'+escape(str(value if value is not None else 'Unknown'))+'</dd>' for label,value in summary)
    panel=('<section class="report-summary" aria-label="Analysis summary"><h2>Analysis summary</h2>'
           '<p><strong>Status: '+escape(str(status))+'</strong></p><p>'+escape(notice)+'</p><dl>'+rows+'</dl></section>'
           '<button class="report-print" type="button">Print / save as PDF</button>'
           '<nav class="report-nav" aria-label="Report sections"></nav>')
    if provenance:
        panel+='<details class="report-evidence"><summary>Source fingerprints and model provenance</summary><pre>'+escape(json.dumps(provenance,indent=2,ensure_ascii=False,allow_nan=False))+'</pre></details>'
    marker=re.search(r'</h1\s*>',document,re.I)
    if marker:document=document[:marker.end()]+panel+document[marker.end():]
    else:document=panel+document
    style='<style>'+REPORT_CSS+'</style>'
    if '<meta name="viewport"' not in document:style='<meta name="viewport" content="width=device-width,initial-scale=1">'+style
    marker=re.search(r'</head\s*>',document,re.I)
    if marker:document=document[:marker.start()]+style+document[marker.start():]
    else:
        marker=re.search(r'<h1\b',document,re.I)
        document=document[:marker.start()]+style+document[marker.start():] if marker else style+document
    script='<script>'+REPORT_JS+'</script>'
    marker=re.search(r'</(?:body|html)\s*>',document,re.I)
    return document[:marker.start()]+script+document[marker.start():] if marker else document+script


def provenance(bundle):
    """Retain declared hashes and model sources; never infer missing coverage."""
    return {key:bundle[key] for key in ('source_sha256','source_fingerprints','source_hash','board_path','study_sha256','study_file_sha256','study_input_path','geometry_origin','board_binding','schema') if key in bundle}


def report_paths(path):
    path=Path(path)
    design={'.kicad_pcb','.kicad_sch','.kicad_pro','.kicad_dru','.kicad_mod','.kicad_sym'}
    if path.suffix.lower() in design:raise ValueError('Choose an HTML report destination, not a KiCad design file.')
    output=path.with_suffix('.html')
    return output,output.with_suffix('.json')


def publish_documents(documents, *, sources=()):
    """Atomically replace each rendered file and roll back the set on failure.

    This is recoverable process-level publication, not power-loss atomicity of
    several files. Existing approved report replacements remain supported.
    """
    targets=[Path(path) for path in documents]
    if len({p.resolve() for p in targets})!=len(targets):raise ValueError('Report outputs must be distinct files.')
    protected=[Path(path).resolve() for path in sources if path]
    for target in targets:
        if target.is_symlink():raise ValueError('Report destinations must not be symbolic links.')
        for source in protected:
            if target.resolve()==source or (target.exists() and source.exists() and os.path.samefile(target,source)):
                raise ValueError('Reports must not overwrite the saved board or input study.')
    staged=[];backups={};published=[];retained=set()
    try:
        for target,content in ((Path(path),content) for path,content in documents.items()):
            target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='wb',dir=target.parent,delete=False) as handle:
                temporary=Path(handle.name);staged.append((temporary,target))
                handle.write(content.encode('utf-8') if isinstance(content,str) else content);handle.flush();os.fsync(handle.fileno())
        for _,target in staged:
            backup=None
            if target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as handle:
                    backup=Path(handle.name);backups[target]=backup
                    with target.open('rb') as original:shutil.copyfileobj(original,handle)
            backups[target]=backup
        try:
            for temporary,target in staged:os.replace(temporary,target);published.append(target)
        except BaseException as failure:
            errors=[]
            for target in reversed(published):
                try:
                    if backups[target] is None:target.unlink(missing_ok=True)
                    else:os.replace(backups[target],target)
                except OSError as rollback:
                    if backups[target] is not None:retained.add(backups[target])
                    errors.append(str(target)+': '+str(rollback))
            if errors:raise OSError('Report rollback needs inspection. Recovery files: '+', '.join(map(str,retained))+'. '+'; '.join(errors)) from failure
            raise
    finally:
        for temporary,_ in staged:temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None and backup not in retained:backup.unlink(missing_ok=True)


def publish_report(path, document, bundle):
    """Serialize exact evidence first, then publish its HTML/JSON pair together."""
    output,evidence=report_paths(path)
    payload=json.dumps(bundle,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    sources=checked_sources(bundle)
    publish_documents({evidence:payload,output:document},sources=sources)
    return {'html':str(output),'json':str(evidence)}


def checked_sources(bundle):
    """Check declared source hashes and return files protected from publication."""
    sources=[]
    for scope in (bundle,bundle.get('request',{})):
        sources.extend(scope[key] for key in ('board_path','source_path','study_input_path') if scope.get(key))
        for key,digest in (('board_path','source_sha256'),('study_input_path','study_file_sha256')):
            expected=scope.get(digest) or bundle.get(digest)
            if scope.get(key) and expected:
                if hashlib.sha256(Path(scope[key]).read_bytes()).hexdigest()!=expected:raise ValueError('Source or input study changed; rerun before exporting.')
    return sources
