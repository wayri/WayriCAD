"""Optional real-browser acceptance checks. Requires Playwright + Chromium.

Run from the plugin directory:
  python tests/browser_smoke.py --chromium /path/to/chromium --output /tmp/screens
Not run by unittest discovery; not a runtime dependency.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server

def main():
 from playwright.sync_api import sync_playwright
 args=argparse.ArgumentParser();args.add_argument('--chromium');args.add_argument('--bridge',action='store_true',help='Inject static assets and bridge fetch via Python for managed browsers that prohibit all URL navigation');args.add_argument('--output',default='test-artifacts');a=args.parse_args()
 output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 errors=[];checks=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=a.chromium,args=['--no-sandbox'])
   page=browser.new_page(viewport={'width':1536,'height':1060},device_scale_factor=1)
   page.set_default_timeout(15000)
   page.on('pageerror',lambda error:errors.append(str(error)))
   page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
   if a.bridge:
    import base64,http.client
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
     c.request(req['method'],req['path'],body=req.get('body').encode('utf-8') if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}))
     r=c.getresponse();result={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return result
    page.expose_function('_wayricadLocalTransport',bridge)
    web=Path(__file__).resolve().parents[1]/'web'
    html=(web/'index.html').read_text().replace('<link rel="stylesheet" href="/style.css">','').replace('<script src="/app.js" defer></script>','').replace('<script src="/workbench.js" defer></script>','').replace('<script src="/intelligence.js" defer></script>','').replace('<script src="/automation.js" defer></script>','').replace('<script src="/analytics.js" defer></script>','').replace('<script src="/engineering.js" defer></script>','').replace('<script src="/assets.js" defer></script>','').replace('<script src="/studio8.js" defer></script>','').replace('<script src="/library8.js" defer></script>','').replace('<script src="/nativefirst.js" defer></script>','').replace('<script src="/vendors.js" defer></script>','').replace('<script src="/assemblers.js" defer></script>','')
    page.set_content(html)
    page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='''const testStorage={wayricadToken:'''+json.dumps(app.token)+'''};
    for(const name of ['sessionStorage','localStorage']) Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});
    history.replaceState=()=>{};
    window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    page.add_script_tag(content=(web/'app.js').read_text())
    page.add_script_tag(content=(web/'workbench.js').read_text())
    page.add_script_tag(content=(web/'intelligence.js').read_text())
    page.add_script_tag(content=(web/'automation.js').read_text())
    page.add_script_tag(content=(web/'analytics.js').read_text())
    page.add_script_tag(content=(web/'engineering.js').read_text())
    page.add_script_tag(content=(web/'assets.js').read_text())
    page.add_script_tag(content=(web/'studio8.js').read_text())
    page.add_script_tag(content=(web/'library8.js').read_text())
    page.add_script_tag(content=(web/'nativefirst.js').read_text())
    page.add_script_tag(content=(web/'vendors.js').read_text())
    page.add_script_tag(content=(web/'assemblers.js').read_text())
   else:page.goto(server.url)
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   page.evaluate("async()=>{await api('bom-format/select',{mode:'custom',custom_template:'Purchasing'});NF.profilesCustom=true;S.template='Purchasing';await refresh();}")
   page.get_by_text('11',exact=True).first.wait_for();checks.append('Demo loads 11 physical component instances')
   page.screenshot(path=str(output/'01-bom-workspace.png'),full_page=True)
   page.get_by_label('Select R1',exact=True).check();page.get_by_role('button',name='DNI',exact=True).click()
   page.locator('#dialog [name=confirmation]').fill('EDIT');page.get_by_role('button',name='Stage reviewed bulk changes',exact=True).click();page.wait_for_function("!document.querySelector('#dialog').open")
   page.locator('tr[data-row]').filter(has=page.locator('[data-select]')).count()
   page.wait_for_function("document.querySelector('.selectionbar').textContent.includes('1 selected')")
   page.get_by_role('button',name='↶ Undo',exact=True).click();checks.append('Bulk DNI edit and undo')
   page.locator('[data-view=variants]').first.click();page.get_by_role('button',name='+ New variant').click()
   page.locator('#dialog [name=name]').fill('Browser test');page.locator('#dialog [name=parent]').select_option('Economy')
   page.get_by_role('button',name='Create variant',exact=True).click();page.wait_for_function("document.querySelector('#activeVariant').value==='Browser test'")
   page.get_by_role('button',name='Compare',exact=True).click();page.locator('#variantComparison .data-table').wait_for();checks.append('Derived variant creation and comparison')
   page.get_by_role('button',name='Population matrix',exact=True).click();page.locator('.matrix-cell').first.wait_for();checks.append('Cross-variant population matrix')
   page.locator('[data-view=variables]').first.click();page.get_by_role('button',name='Save variable changes',exact=True).wait_for();checks.append('Variable editor renders')
   page.locator('[data-view=sourcing]').first.click();page.get_by_role('heading',name='Alternate decision register').wait_for();checks.append('Sourcing and alternate register render')
   page.locator('[data-view=exports]').first.click();page.get_by_role('button',name='Preview',exact=True).click();page.locator('#exportPreview table').wait_for()
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'02-export-templates.png'),full_page=True)
   with page.expect_download() as event:page.get_by_role('button',name='Export active variant ↗',exact=True).click()
   download=event.value;download.save_as(str(output/download.suggested_filename));checks.append('Real browser XLSX download')
   page.locator('[data-view=bom]').first.click();page.get_by_role('button',name='Import CSV',exact=True).click();page.locator('#csvText').fill('Reference,Notes\nR1,Browser import\n');page.get_by_role('button',name='Preview changes',exact=True).click();page.get_by_role('button',name='Apply 1 changes').click();checks.append('CSV preview and import')
   page.get_by_role('button',name='Save workspace',exact=True).click();page.wait_for_function("document.querySelector('#saveStatus').textContent==='Workspace up to date'")
   page.locator('[data-view=review]').first.click();page.get_by_role('button',name='Review proposed native changes').click();page.locator('#nativePreview details').first.wait_for();checks.append('Native diff preview')
   page.locator('[data-view=checks]').first.click();page.get_by_role('heading',name='Design checks',exact=True).wait_for();checks.append('Checks render')
   page.locator('[data-view=about]').first.click();page.get_by_text('0 native BOM presets detected.').wait_for();checks.append('Compatibility probe renders')
   page.locator('[data-view=bom]').first.click();page.locator('#activeVariant').select_option('<Default>');page.wait_for_timeout(200)
   page.locator('#search').fill('TERM-2P');page.wait_for_timeout(400);assert page.locator('#main tbody tr').count()==1;checks.append('Search filtering')
   page.locator('#search').fill('');page.wait_for_timeout(400);page.locator('#themeButton').click();page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'03-dark-mode.png'),full_page=True);checks.append('Dark theme')
   page.set_viewport_size({'width':780,'height':1050});page.screenshot(path=str(output/'04-compact-layout.png'),full_page=True)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Page-level horizontal overflow';checks.append('Compact viewport has no page-level horizontal overflow')
   browser.close()
  if errors:raise AssertionError('Browser errors: '+repr(errors))
  print(json.dumps({'passed':len(checks),'checks':checks,'browser_errors':errors,'browser':'System Chromium via Playwright; injected static assets + Python HTTP fetch bridge' if a.bridge else 'System Chromium via Playwright; normal loopback navigation','host_kicad_tested':False},indent=2))
 finally:server.shutdown();server.server_close();thread.join();shutil.rmtree(app.demo_directory)

if __name__=='__main__':main()
