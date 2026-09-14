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
 args=argparse.ArgumentParser();args.add_argument('--chromium');args.add_argument('--bridge',action='store_true',help='Inject static assets and bridge fetch via Python for managed browsers that prohibit all URL navigation');args.add_argument('--output',default='test-artifacts-v4');a=args.parse_args()
 output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 errors=[]
 from bomstudio.bridge import SelectionService
 from test_v4 import FakeBoard,FakeClient
 board=FakeBoard(app.workspace.project);client=FakeClient(board)
 app.link.close();app.link=SelectionService(lambda **kwargs:client)
 class Checks(list):
  def append(self,message):super().append(message);print('PASS: '+message,flush=True)
 checks=Checks()
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
   page.on('dialog',lambda d:d.accept())
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   page.evaluate("async()=>{await api('bom-format/select',{mode:'custom',custom_template:'Purchasing'});NF.profilesCustom=true;S.template='Purchasing';await refresh();}")
   # Synthetic project + injected selection transport. No native KiCad is running.
   native_hashes=dict(app.workspace.project.hashes)
   def ready():page.wait_for_function("!document.querySelector('#dialog').open")
   def stage_bulk():
    page.locator('#dialog [name=confirmation]').fill('EDIT');page.get_by_role('button',name='Stage reviewed bulk changes',exact=True).click();ready()
   def shot(name):
    page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/name),full_page=not page.locator('#dialog').evaluate('(x)=>x.open'))
   page.get_by_role('button',name='Advanced search & saved filters',exact=True).click();page.locator('#advancedQuery').fill('Reference~"R*" AND Value=10k');page.get_by_role('button',name='Test count & facets').click();page.wait_for_function("document.querySelector('#queryResult').innerText.includes('3 / 11')");checks.append('Advanced boolean query gives exact count and facets through shared backend')
   page.locator('[data-act=queryFacet]').first.click();assert 'AND' in page.locator('#advancedQuery').input_value() and 'Assembly' in page.locator('#advancedQuery').input_value();page.get_by_role('button',name='Test count & facets').click();page.wait_for_function("document.querySelector('#queryResult').innerText.includes('3 / 11')");page.locator('#advancedQuery').fill('Reference~"R*" AND Value=10k');checks.append('Facet chips append executable narrowing predicates without losing the original query')
   page.locator('#filterName').fill('10k resistors');page.locator('#filterDescription').fill('Demo shared query');page.get_by_role('button',name='Save query as filter').click();page.wait_for_function("Object.hasOwn(S.data.saved_filters,'10k resistors')");page.locator('#savedFilter').select_option('10k resistors');page.get_by_role('button',name='Load',exact=True).click();assert page.locator('#advancedQuery').input_value()=='Reference~"R*" AND Value=10k';checks.append('Named filter stores query/description and reloads correctly')
   with page.expect_download() as d:page.get_by_role('button',name='Share filter library JSON').click()
   dest=output/'shared_filters.json';d.value.save_as(dest);payload=json.loads(dest.read_text());assert payload['schema']=='wayricad-filters-1';assert '10k resistors' in payload['filters'];checks.append('Portable saved-filter JSON is a real browser download')
   page.get_by_role('button',name='Test count & facets').click();page.locator('.facet-card').first.wait_for();shot('01-advanced-search.png');page.get_by_role('button',name='Apply search',exact=True).click();ready();assert page.evaluate('filteredRows().length')==3;assert page.locator('tr[data-row]').count()==3;checks.append('Applied advanced filter limits the grid before grouping')
   page.get_by_role('button',name='Select all 3 results',exact=True).click();assert page.evaluate('S.selected.size')==3
   page.locator('#search').fill('R1');page.wait_for_function('filteredRows().length===1');assert page.evaluate('S.selected.size')==3;checks.append('Selection remains explicit when filters hide selected components')
   page.get_by_role('button',name='Bulk actions…',exact=True).click();assert '3 parts' in page.locator('#bulkScope option[value=selected]').inner_text();assert '1 parts' in page.locator('#bulkScope option[value=filtered]').inner_text();page.locator('[data-bulk-field]').fill('ReviewNote');page.locator('[data-value]').fill('  staged  ');page.get_by_role('button',name='+ Add operation',exact=True).click();page.locator('[data-op]').nth(1).select_option('trim');page.locator('[data-bulk-field]').nth(1).fill('ReviewNote');page.get_by_role('button',name='+ Add operation',exact=True).click();page.locator('[data-op]').nth(2).select_option('upper');page.locator('[data-bulk-field]').nth(2).fill('ReviewNote');shot('02-bulk-recipe.png')
   page.get_by_role('button',name='Preview complete changes',exact=True).click();page.locator('#dialog [name=confirmation]').wait_for();assert page.evaluate('S.bulkPlan.matched')==3;assert all('ReviewNote' not in r['raw'] for r in app.workspace.rows());checks.append('Multistep bulk preview includes hidden explicit targets without changing data');shot('03-bulk-review.png');stage_bulk();assert all(next(r for r in app.workspace.rows() if r['ref']==ref)['raw']['ReviewNote']=='STAGED' for ref in ('R1','R2','R3'));checks.append('Ordered set/trim/uppercase stages one reviewed transaction')
   page.get_by_role('button',name='↶ Undo',exact=True).click();page.wait_for_function("!S.data.rows.find(r=>r.ref==='R1').raw.ReviewNote");checks.append('One Undo reverts every operation/member of the bulk transaction')
   # FIT/DNP shortcuts now require the same review, not an immediate state change.
   page.locator('[data-act=reviewPopulation][data-population=DNI]').click();page.locator('#dialog [name=confirmation]').wait_for();assert next(r for r in app.workspace.rows() if r['ref']=='R1')['fields']['Assembly']=='FIT';stage_bulk();assert all(next(r for r in app.workspace.rows() if r['ref']==ref)['fields']['Assembly']=='DNI' for ref in ('R1','R2','R3'));checks.append('Population shortcuts require reviewed EDIT before changing selected parts')
   page.get_by_role('button',name='↶ Undo',exact=True).click();page.wait_for_function("S.data.rows.find(r=>r.ref==='R1').fields.Assembly==='FIT'")
   page.get_by_role('button',name='Clear query',exact=True).click();page.locator('#search').fill('');page.locator('[data-act=clearSelection]').first.click();page.locator('[data-act=groupingDialog]').click();page.locator('[data-act=groupPreset][data-fields="Value,Footprint"]').click();page.get_by_role('button',name='Apply grouping',exact=True).click();ready();page.locator('[data-select-group]').first.check();assert page.evaluate('S.selected.size')>=1;checks.append('Grouped BOM rows have explicit group-edit selection checkboxes')
   page.locator('[data-act=expandGroup]').first.click();assert page.locator('.group-child [data-select]').count()>0;checks.append('Expanded groups expose individual selection controls')
   # Live linking through the actual bridge + fake driver only.
   page.locator('[data-act=liveLink]').first.click();page.locator('#dialog [name=focus]').check();page.get_by_role('button',name='Connect / reconnect',exact=True).click();ready();page.wait_for_function('S.link.connected');assert page.evaluate('S.link.mapped_components')==11;checks.append('Connection UI negotiates optional IPC settings and shows UUID mapping coverage (injected driver)')
   first=page.locator('tr.group-row').first;gid=first.get_attribute('data-link-group');ids=page.evaluate('(g)=>groupById(g).ids',gid);first.locator('td[data-field="@field:Reference"]').click();page.wait_for_function('(n)=>S.link.ids.length===n',arg=len(ids));assert len(board.selection)==len(ids);assert client.actions==['common.Control.zoomFitSelection'];checks.append('Single grouped-row click sends all UUID-linked footprints and only the opt-in zoom action')
   before_selection=page.evaluate('[...S.selected]');target=next(r for r in app.workspace.rows() if r['ref']=='J1');fp=app.link.bridge.mapping[target['id']];board.selection=[fp.definition.items[0]];page.wait_for_function("S.link.references?.includes('J1')");page.wait_for_function("document.querySelector('tr[data-row=\"'+S.data.rows.find(r=>r.ref==='J1').id+'\"]')?.classList.contains('linked-row')");assert page.evaluate('[...S.selected]')==before_selection;checks.append('Editor pad selection expands/focuses the BOM member without changing edit selection')
   shot('04-live-link-fixture.png')
   # Incoming selection does not steal focus during a form edit.
   page.locator('[data-act=advancedSearch]').click();page.locator('#advancedQuery').fill('Reference=R1');board.selection=[app.link.bridge.mapping[next(r for r in app.workspace.rows() if r['ref']=='C1')['id']]];page.wait_for_function("S.link.references?.includes('C1')");assert page.locator('#dialog').evaluate('(x)=>x.open');assert page.locator('#advancedQuery').input_value()=='Reference=R1';assert page.evaluate('S.linkPending');checks.append('Incoming editor changes defer navigation while a dialog/input is active')
   page.get_by_role('button',name='Apply search',exact=True).click();ready();assert page.evaluate('filteredRows().length')==1;page.get_by_role('button',name='Reveal in BOM',exact=True).click();assert page.evaluate('S.filterBypass');assert page.locator('.linked-row').count()>0;page.get_by_role('button',name='Restore filters',exact=True).click();assert page.evaluate('filteredRows().length')==1;checks.append('Hidden linked parts can be revealed with reversible filter bypass')
   page.get_by_role('button',name='Use linked parts as edit selection',exact=True).click();assert page.evaluate('[...S.selected]')==[next(r for r in app.workspace.rows() if r['ref']=='C1')['id']];checks.append('An explicit action is required to make linked parts the bulk-edit selection')
   # Disconnect when host moves to another document.
   board.document.board_filename='other.kicad_pcb';page.wait_for_function('!S.link.connected');assert 'changed' in page.evaluate('S.link.error');checks.append('Changing the live board disconnects rather than selecting another design')
   page.locator('[data-view=automation]').first.click();page.locator('#pipelineConfig').wait_for();assert json.loads(page.locator('#pipelineConfig').input_value())['policy']['checks']=='error';shot('05-automation-pipeline.png')
   with page.expect_download() as d:page.get_by_role('button',name='Download pipeline JSON',exact=True).click()
   dest=output/'pipeline.json';d.value.save_as(dest);assert json.loads(dest.read_text())['schema']=='wayricad-pipeline-1';checks.append('Pipeline policy configuration downloads as non-executable JSON')
   page.get_by_role('button',name='Generate job-set bundle…',exact=True).click();page.locator('#jobDirectory').fill(str(Path(app.demo_directory)/'generated-jobs'));page.locator('#jobPlatform').select_option('posix')
   with page.expect_download() as d:page.get_by_role('button',name='Download job-set ZIP',exact=True).click()
   dest=output/'jobset.zip';d.value.save_as(dest)
   import zipfile
   with zipfile.ZipFile(dest) as z:
    job=json.loads(z.read('WayriCAD_BOM.kicad_jobset'));assert job['jobs'][0]['type']=='special_execute';assert not job['jobs'][0]['settings']['ignore_exit_code']
   assert not (Path(app.demo_directory)/'generated-jobs').exists();checks.append('GUI job-set generation creates a valid bundle without executing or writing its destination')
   page.locator('#dialogClose').click();page.set_viewport_size({'width':860,'height':800});page.locator('#themeButton').click();page.locator('[data-view=bom]').first.click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.locator('[data-view=automation]').first.click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');shot('06-compact-automation.png');checks.append('New panels fit compact viewport in dark mode without page overflow')
   app.workspace.project.check_unchanged();assert app.workspace.project.hashes==native_hashes;checks.append('All new GUI workflows preserve native schematic/project bytes')
   assert not errors,errors
   report={'passed':len(checks),'checks':checks,'browser_errors':errors,'browser':'System Chromium via Playwright; '+('injected static assets + Python HTTP fetch bridge' if a.bridge else 'direct HTTP navigation'),'host_kicad_tested':False,'live_link_transport':'Injected fake PCB driver; actual bridge and GUI exercised, no actual KiCad'}
   (output/'browser-workflows.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));browser.close()
 finally:
  server.shutdown();server.server_close()
  if app.demo_directory:shutil.rmtree(app.demo_directory,ignore_errors=True)
if __name__=='__main__':main()
