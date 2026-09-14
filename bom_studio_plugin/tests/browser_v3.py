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
 errors=[]
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
   page.evaluate("async()=>{await api('fields/adopt',{all_fields:true});await api('bom-format/select',{mode:'custom',custom_template:'Purchasing'});NF.profilesCustom=true;S.template='Purchasing';await refresh();}")
   # All data below is a synthetic project/fixture, not live supplier evidence.
   from datetime import datetime,timezone
   r1=next(r for r in app.workspace.rows() if r['ref']=='R1');r2=next(r for r in app.workspace.rows() if r['ref']=='R2')
   id1=r1['id'];id2=r2['id'];native_hashes=dict(app.workspace.project.hashes)
   def stage():
    page.locator('#dialog [name=confirmation]').fill('EDIT')
    if page.locator('#dialog [name=loss]').count():page.locator('#dialog [name=loss]').check()
    page.get_by_role('button',name='Stage reviewed edits',exact=True).click();page.wait_for_function("!document.querySelector('#dialog').open")
   def inline(id,field,value):
    page.locator(f'td.live-cell[data-id="{id}"][data-field="@field:{field}"]').dblclick()
    page.locator('.inline-input').fill(value);page.locator('.inline-input').press('Enter')
   inline(id1,'Value','10000Ohm');assert next(r for r in app.workspace.rows() if r['ref']=='R1')['fields']['Value']=='10k'
   assert page.evaluate('pendingGridCount()')==1;page.evaluate('render()');assert page.locator(f'td[data-id="{id1}"][data-field="@field:Value"]').inner_text()=='10000Ohm';checks.append('Inline typing stays draft until reviewed; native/workspace unchanged')
   page.get_by_role('button',name='Review grid edits',exact=True).click();page.locator('#dialog [name=confirmation]').wait_for()
   assert page.locator('#dialog').inner_text().count('R1')>0
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'01-direct-edit-review.png'),full_page=True)
   stage();assert next(r for r in app.workspace.rows() if r['ref']=='R1')['fields']['Value']=='10000Ohm';assert page.evaluate('pendingGridCount()')==0;app.workspace.project.check_unchanged();checks.append('Typed EDIT commits Value with native files untouched')
   page.get_by_role('button',name='↶ Undo',exact=True).click();page.wait_for_function("S.data.rows.find(r=>r.ref==='R1').fields.Value==='10k'")
   page.get_by_role('button',name='↷ Redo',exact=True).click();page.wait_for_function("S.data.rows.find(r=>r.ref==='R1').fields.Value==='10000Ohm'");checks.append('Single undo/redo restores reviewed grid transaction')
   inline(id2,'Value','10000Ohm')
   page.get_by_role('button',name='Paste table…',exact=True).click();page.locator('#gridPasteText').fill('Reference\tMPN\tTolerance\nR1\tDEMO-ALT-10K\t1%')
   page.get_by_role('button',name='Review pasted changes',exact=True).click();stage();assert page.evaluate('pendingGridCount()')==1;checks.append('Pasted multi-field edit keeps unrelated pending grid drafts')
   page.get_by_role('button',name='Review grid edits',exact=True).click();stage();checks.append('Remaining draft can still be reviewed and committed')
   page.locator('[data-act=groupingDialog]').click();page.locator('[data-act=groupPreset][data-fields="Value,Footprint"]').click();page.get_by_role('button',name='Apply grouping',exact=True).click()
   page.wait_for_function("S.data.grouping.fields.length===2");assert page.locator('tr.group-row').count()>0;checks.append('Persisted Value + Footprint grouping with mixed values')
   page.locator('[data-act=expandGroup]').first.click();assert page.locator('.group-child').count()>0
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'02-grouped-bom.png'),full_page=True);checks.append('Grouped rows expand to actual editable components')
   page.locator('[data-view=analyzer]').first.click();page.get_by_role('button',name='Run smart analyzer',exact=True).click();page.wait_for_function('!!S.analysisReport')
   assert page.evaluate('S.analysisReport.summary.candidate_groups')>=1
   assert page.evaluate('S.analysisReport.summary.normalization_groups')>=1
   assert next(r for r in app.workspace.rows() if r['ref']=='R1')['fields']['MPN']=='DEMO-ALT-10K'
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'03-consolidation-assessment.png'),full_page=True);checks.append('Analyzer reports candidates and equivalent passive labels without editing parts')
   page.locator('[data-view=health]').first.click();page.get_by_role('button',name='Run BOM health',exact=True).click();page.wait_for_function('!!S.healthReport')
   assert page.evaluate('S.healthReport.summary.unknowns')>0;assert page.evaluate('S.healthReport.summary.stock_observed_covered')==0;checks.append('No-evidence health is unknown, never fabricated availability')
   # Add a real, read-only temporary footprint file with one deliberately missing pad.
   root=Path(app.demo_directory)/'fixture_libraries';lib=root/'Resistor_SMD.pretty';lib.mkdir(parents=True)
   (lib/'R_0603_1608Metric.kicad_mod').write_text('(footprint "R_0603_1608Metric" (pad "1" smd rect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu" "F.Paste" "F.Mask")))')
   page.get_by_role('button',name='Health settings',exact=True).click();page.locator('#dialog [name=roots]').fill(str(root));page.get_by_role('button',name='Save health settings',exact=True).click();page.wait_for_function("S.data.health_settings.library_roots?.length===1")
   page.get_by_role('button',name='Run BOM health',exact=True).click();page.wait_for_function('S.healthReport.revision===S.data.revision')
   assert page.evaluate('S.healthReport.summary.geometry_read')>=3;assert page.evaluate("S.healthReport.issues.some(i=>i.code==='SYMBOL_PAD_MISSING')")
   checks.append('Health reads real local pad geometry and detects missing symbol pad')
   page.locator('[data-view=evidence]').first.click()
   with page.expect_download() as event:page.get_by_role('button',name='DigiKey CSV',exact=True).click()
   download=event.value;download.save_as(str(output/'DigiKey_request.csv'));assert 'Manufacturer Part Number' in (output/'DigiKey_request.csv').read_text();checks.append('Supplier request CSV downloads through GUI without API credentials')
   page.get_by_role('button',name='Add reviewed part evidence…',exact=True).click()
   record={'manufacturer':'Demo only','mpn':'DEMO-ALT-10K','supplier':'DigiKey','sku':'SYNTHETIC-NOT-ORDERABLE','stock':'1000','observed_at':datetime.now(timezone.utc).isoformat(),'source_url':'https://example.invalid/synthetic-test-only','package':'0603_1608Metric','pin_numbers':'1,2','mounting':'SMD','region':'IN','notes':'Synthetic browser test; not supplier data.'}
   for key,value in record.items():page.locator(f'#dialog [name={key}]').fill(value)
   # Actual fixture manufacturer is authoritative for exact identity matching.
   record['manufacturer']=r1['fields']['Manufacturer'];page.locator('#dialog [name=manufacturer]').fill(record['manufacturer'])
   page.get_by_role('button',name='Review evidence',exact=True).click();page.locator('#evidenceConfirm').wait_for();assert len(app.workspace.state['evidence'])==0
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'04-evidence-review.png'),full_page=True);checks.append('Manual part evidence previews exact identity before import')
   page.locator('#evidenceReviewed').check();page.locator('#evidenceConfirm').fill('IMPORT');page.get_by_role('button',name='Import reviewed evidence',exact=True).click();page.wait_for_function('S.data.evidence.length===1');checks.append('Evidence import requires reviewed acknowledgement and typed IMPORT')
   # CSV mapping: intentionally no numeric stock, undated -> unknown, never zero.
   page.get_by_role('button',name='Import supplier / capture file…',exact=True).click();page.locator('#evidenceText').fill('Manufacturer Part Number,Manufacturer,Stock,Source URL\nDEMO-R0603-10K,'+record['manufacturer']+',,https://example.invalid/undated')
   page.get_by_role('button',name='Read headers / JSON',exact=True).click();page.locator('[data-evidence-map="mpn"]').wait_for();assert page.locator('[data-evidence-map="mpn"]').input_value()=='Manufacturer Part Number'
   page.get_by_role('button',name='Preview evidence',exact=True).click();page.locator('#evidenceConfirm').wait_for();assert page.evaluate('S.evidencePlan.plan.items[0].record.stock') is None
   page.locator('#evidenceReviewed').check();page.locator('#evidenceConfirm').fill('IMPORT');page.get_by_role('button',name='Import reviewed evidence',exact=True).click();page.wait_for_function('S.data.evidence.length===2');checks.append('Supplier CSV header mapping preserves unknown stock and observation date')
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'05-supplier-evidence.png'),full_page=True)
   page.locator('[data-view=health]').first.click();assert 'older workspace' in page.locator('#main').inner_text()
   page.get_by_role('button',name='Run BOM health',exact=True).click();page.wait_for_function('S.healthReport.revision===S.data.revision')
   assert page.evaluate('S.healthReport.summary.stock_observed_covered')==1;assert page.evaluate("S.healthReport.issues.some(i=>i.code==='PART_PAD_SET_MISMATCH')");checks.append('Fresh exact identity stock covers demand but physical mismatch remains an error')
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'06-bom-health.png'),full_page=True)
   page.locator('[data-act=inspectHealthPart]').first.click();assert 'pin_numbers' in page.locator('#dialog').inner_text();page.locator('#dialogClose').click();checks.append('Part inspection exposes pad facts and source hashes')
   with page.expect_download() as event:page.get_by_role('button',name='Export fresh report JSON',exact=True).click()
   download=event.value;download.save_as(str(output/'Health_report.json'));assert json.loads((output/'Health_report.json').read_text())['schema']=='wayricad-health-1';checks.append('Fresh complete health report downloads with findings and provenance')
   page.locator('#themeButton').click()
   for view in ('health','analyzer','evidence','bom'):
    page.locator('[data-view='+view+']').first.click();page.set_viewport_size({'width':780,'height':1060});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),view+' overflow'
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'07-grouped-compact-dark.png'),full_page=True);checks.append('All four new workspaces fit compact viewport in dark mode')
   assert app.workspace.project.hashes==native_hashes;app.workspace.project.check_unchanged();checks.append('All GUI analysis/import/edit tests leave native project files untouched')
   # Pure capture function tested on controlled HTML, NOT real distributor pages.
   capture=(Path(__file__).resolve().parents[1]/'integrations'/'browser_capture_extension'/'capture-core.js').read_text().replace('location.','testLocation.')
   page2=browser.new_page();page2.set_content('<table><tr><td>Quantity Available</td><td>1,234 In Stock</td></tr><tr><td>Package / Case</td><td>SOT-23-5</td></tr><tr style="display:none"><td>Quantity Available</td><td>9999</td></tr></table><script type="application/ld+json">{"@type":"Product","mpn":"SYNTHETIC-TR","manufacturer":{"name":"Fixture Inc"},"offers":{"availability":"InStock"}}</script>')
   page2.add_script_tag(content="const testLocation={hostname:'www.digikey.in',pathname:'/en/products/detail/fixture/part/123',origin:'https://www.digikey.in',search:''};"+capture)
   captured=page2.evaluate('captureWayriCADPage()');assert captured['record']['stock']=='1234';assert captured['record']['mpn']=='SYNTHETIC-TR';assert captured['record']['package']=='SOT-23-5';checks.append('Capture parser: visible exact numeric quantity and single Product identity on synthetic HTML')
   page2.evaluate("document.querySelector('table').remove()");assert page2.evaluate('captureWayriCADPage().record.stock')=='';checks.append('Capture parser never turns InStock structured data into a quantity')
   rejected=page2.evaluate("(()=>{testLocation.hostname='digikey.in.attacker.invalid';try{captureWayriCADPage();return false}catch{return true}})()");assert rejected;checks.append('Capture parser rejects lookalike domains')
   page2.close()
   browser.close()
  if errors:raise AssertionError('Browser errors: '+repr(errors))
  print(json.dumps({'passed':len(checks),'checks':checks,'browser_errors':errors,'browser':'System Chromium via Playwright; injected static assets + Python HTTP fetch bridge' if a.bridge else 'System Chromium via Playwright; normal loopback navigation','host_kicad_tested':False},indent=2))
 finally:server.shutdown();server.server_close();thread.join();shutil.rmtree(app.demo_directory)

if __name__=='__main__':main()
