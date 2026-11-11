"""Offline plot document shared by original-sample antenna exporters."""
import html
import json


def write_viewer(path, figures, title, summary, digest, initial='radiation3d'):
    from plotly.offline import get_plotlyjs
    blocks=[]; scripts=[]
    for identifier, heading, figure, caption in figures:
        figure.update_layout(template='plotly_white',margin=dict(l=65,r=45,t=35,b=65),
                             font=dict(size=14),hoverlabel=dict(font_size=14))
        blocks.append(f'<section id="{identifier}" hidden><h2>{html.escape(heading)}</h2>'+
                      f'<p>{html.escape(caption)}</p><div id="plot-{identifier}" class="plot"></div></section>')
        scripts.append('figures['+json.dumps(identifier)+']='+figure.to_json().replace('</','<\\/')+';')
    nav=' '.join(f'<a href="#{i}">{html.escape(t)}</a>' for i,t,_,_ in figures)
    document='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+\
        '<title>'+html.escape(title)+'</title><style>'+\
        'body{margin:0;font:15px system-ui;color:#202b30;background:#fff}header,main{max-width:1400px;margin:auto;padding:20px}'+\
        'h1{font-size:26px}h2{font-size:20px}p{line-height:1.5}nav{display:flex;gap:14px;flex-wrap:wrap}'+\
        'a{color:#126b83}code{overflow-wrap:anywhere}section{border-top:1px solid #ccd6da;padding:18px 0}.plot{height:620px}'+\
        '@media(max-width:650px){header,main{padding:12px}.plot{height:500px}}'+\
        '</style><header><h1>'+html.escape(title)+'</h1><p>'+html.escape(summary)+'</p>'+\
        '<p>Numerical source SHA-256: <code>'+html.escape(digest)+'</code></p><nav>'+nav+'</nav></header><main>'+\
        ''.join(blocks)+'</main><footer>Offline Plotly.js (MIT), bundled once. No network requests required.</footer>'+\
        '<script>'+get_plotlyjs().replace('</script','<\\/script')+'</script><script>const figures={};'+''.join(scripts)+\
        'async function activate(id){if(!figures[id])return;document.querySelectorAll("main section").forEach(s=>s.hidden=s.id!==id);'+\
        'const node=document.getElementById("plot-"+id);if(!node._fullLayout){const f=figures[id];await Plotly.newPlot(node,f.data,f.layout,'+\
        '{responsive:true,displaylogo:false,scrollZoom:true,plotGlPixelRatio:1,toImageButtonOptions:{scale:2}});}else await Plotly.Plots.resize(node);}'+\
        'document.querySelectorAll("nav a").forEach(a=>a.addEventListener("click",e=>{e.preventDefault();activate(a.hash.slice(1));}));'+\
        'activate('+json.dumps(initial)+');</script></html>'
    path.write_text(document,encoding='utf-8',newline='\n')
