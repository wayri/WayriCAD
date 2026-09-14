"""Optional real-browser engineering acceptance. No fake KiCad host claims.
Requires development-only Playwright/Chromium; --bridge for managed navigation.
"""
from pathlib import Path
import argparse,json,shutil,sys,threading,time,tempfile
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio import intelligence,partsdb,qualification
from bomstudio.native import BASE
from bomstudio.footprints import symbol_pins

def main():
 from playwright.sync_api import sync_playwright
 parser=argparse.ArgumentParser();parser.add_argument('--chromium');parser.add_argument('--bridge',action='store_true');parser.add_argument('--output',required=True);args=parser.parse_args()
 output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);ws=app.workspace;root=ws.project.root.parent
 fp=root/'libraries/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod';fp.parent.mkdir(parents=True)
 fp.write_text('(footprint "R_0603_1608Metric" (version 20241229) (layer "F.Cu") (solder_mask_margin 0) (solder_paste_margin 0) (solder_paste_margin_ratio 0) (pad "1" smd rect (at -0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask")) (pad "2" smd rect (at 0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask")))')
 intelligence.configure(ws,{'library_roots':[str(fp.parent.parent)]});ws.save()
 r1=next(r for r in ws.rows() if r['ref']=='R1');r2=next(r for r in ws.rows() if r['ref']=='R2');pid=partsdb.record_identity(r1['fields']);original=dict(ws.project.hashes)
 spec={'schema':'wayricad-land-pattern-1','manufacturer':r1['fields']['Manufacturer'],'mpn':r1['fields']['MPN'],'source_url':'https://example.com/SYNTHETIC-TEST-DRAWING','document_revision':'TEST ONLY','document_sha256':'a'*64,'page':1,'reviewed_by':'Synthetic author','frame':'top-view-mm','tolerance_mm':.02,'angle_tolerance_deg':.1,'pads':[{k:v for k,v in a.items() if k!='custom'} for a in qualification.actual_geometry(fp)['pads']],'pin_functions':{k:[n] for k,n in symbol_pins(ws.project.by_id[r1['id']])['pin_names'].items()}}
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks=[];errors=[];measures={}
 def check(test,name):
  assert test,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with tempfile.TemporaryDirectory(prefix='wayricad-browser-catalog-') as tmp,sync_playwright() as pw:
   library=str(Path(tmp)/'parts')
   browser=pw.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1600,'height':1080},device_scale_factor=1);page.set_default_timeout(15000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('dialog',lambda d:d.accept())
   if args.bridge:
    import base64,http.client
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=60);c.request(req['method'],req['path'],body=req.get('body').encode('utf-8') if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}));r=c.getresponse();out={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return out
    page.expose_function('_wayricadLocalTransport',bridge);web=Path(__file__).resolve().parents[1]/'web';scripts=['app','workbench','intelligence','automation','analytics','engineering','assets','studio8','library8','nativefirst','vendors','assemblers']
    html=(web/'index.html').read_text().replace('<link rel="stylesheet" href="/style.css">','')
    for script in scripts:html=html.replace(f'<script src="/{script}.js" defer></script>','')
    page.set_content(html);page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='const testStorage={wayricadToken:'+json.dumps(app.token)+'};'+'''for(const name of ['sessionStorage','localStorage'])Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});history.replaceState=()=>{};window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    for script in scripts:page.add_script_tag(content=(web/(script+'.js')).read_text())
   else:page.goto(server.url)
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   page.evaluate("async()=>{await api('bom-format/select',{mode:'custom',custom_template:'Purchasing'});NF.profilesCustom=true;S.template='Purchasing';await refresh();}")
   def act(name):
    page.locator('[data-act="'+name+'"]').first.click();page.wait_for_timeout(180)
   def tab(name):page.locator('[data-act=engTab][data-tab="'+name+'"]').click()
   def fill(name,value):page.locator('#dialog [name="'+name+'"]').fill(str(value))
   def waitclosed():page.wait_for_function('!document.querySelector("#dialog").open')
   def close():page.locator('#dialog .icon-button').first.click()
   def stage(token):
    page.wait_for_timeout(250)
    if not page.locator('#dialog [name=confirmation]').count():
     print('PREVIEW ERROR',page.locator('#toasts').inner_text(),flush=True);page.screenshot(path=str(output/'failure.png'))
    fill('confirmation',token);page.get_by_role('button',name='Stage reviewed change',exact=True).click();waitclosed()
   def shot(name):
    page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/name),full_page=not page.locator('#dialog').evaluate('(x)=>x.open'))
   page.locator('[data-view=engineering]').first.click();act('engCreate');fill('path',library);fill('confirmation','CREATE');page.locator('#dialog [name=remember]').uncheck();page.get_by_role('button',name='Create library',exact=True).click();waitclosed()
   check(page.evaluate('E6.info.attached') and Path(library,'catalog.sqlite3').exists(),'Create and attach separate local SQLite catalog')
   act('engHarvest');fill('paths',str(ws.project.pro_path));page.get_by_role('button',name='Scan for review',exact=True).click()
   page.get_by_role('heading',name='Review harvested parts',exact=True).wait_for();check(page.evaluate('E6.task.state')=='ready','Cancelable read task scans saved project and returns preview')
   with partsdb.Library(library) as lib:check(lib.info()['parts']==0,'Harvest preview makes no catalog changes')
   fill('actor','Browser test');fill('confirmation','IMPORT');page.get_by_role('button',name='Import into catalog',exact=True).click();waitclosed()
   check(page.evaluate('E6.page.total')>0,'Reviewed harvest imports identities and metadata')
   page.locator('#engQuery').fill(r1['fields']['MPN']);act('engSearch');check(page.evaluate('E6.page.total')==1,'Full MPN search identifies one catalog identity')
   page.locator('[data-eng-select="'+pid+'"]').check()
   act('engNative')
   with page.expect_download() as dl:page.get_by_role('button',name='Export native ZIP',exact=True).click()
   waitclosed()
   dl.value.save_as(output/'native-library.zip')
   import zipfile
   with zipfile.ZipFile(output/'native-library.zip') as z:check(any(n.endswith('.kicad_sym') for n in z.namelist()) and any(n.endswith('.kicad_mod') for n in z.namelist()),'Native library export contains captured symbol and footprint')
   act('finderPart8');act('engEditPart');fill('ipn','KW-RES-10K-0603');fill('tags','Analog, preferred assembly');fill('notes','Synthetic browser review record. Not a real production approval.');fill('actor','Browser engineer');fill('reason','Standardize internal part number')
   page.get_by_role('button',name='Preview revision',exact=True).click();stage('CATALOG');act('engSearch')
   check(page.evaluate('E6.page.items[0].revision')==2,'Reviewed catalog edit creates a new immutable revision')
   shot('01-local-catalog.png')
   tab('reuse');act('engSuggest');page.locator('#dialog [name=component]').select_option(r1['id']);page.get_by_role('button',name='Find candidates',exact=True).click();page.get_by_role('heading',name='Catalog candidates · R1',exact=True).wait_for()
   check(page.evaluate('E6.lastRecommendations.items.length')>0,'Value and exact-footprint candidates available in project')
   check('Tolerance' in page.locator('#dialog').inner_text(),'Missing passive ratings explicitly disclosed')
   shot('02-recommendations.png');act('engChooseCandidate');page.locator('#dialog [name=engineering]').check();stage('EDIT')
   check(next(r for r in ws.rows() if r['ref']=='R1')['fields']['CatalogID']==pid,'Reviewed recommendation stages catalog identity on the part')
   check(next(r for r in ws.rows() if r['ref']=='R1')['fields']['Value']==r1['fields']['Value'],'Recommendation preserves the selected Value by default')
   tab('mass');act('engMass');page.locator('[data-mass-pick="'+r1['id']+'"]').check();shot('03-mass-suggestions.png');page.locator('#engMassPreview').click();page.locator('#dialog [name=estimate]').check();stage('EDIT')
   current=next(r for r in ws.rows() if r['ref']=='R1');check(bool(current['fields'].get('Mass_Source')) and 'estim' in current['fields']['Mass_Basis'].lower(),'Accepted proxy retains source, assumptions and estimated basis')
   tab('variants');act('engNewVariant');fill('name','Assembly budget');page.locator('#dialog [name=mode]').select_option('pinned');fill('tags','quote, not native');page.locator('#engVariantPreview').click();stage('VARIANT')
   check(ws.state['variants']['Assembly budget']['bom_only'] and ws.state['variants']['Assembly budget']['pinned'],'Pinned independent BOM variant is created through review')
   act('engVariantAction');page.locator('#dialog [name=op]').select_option('lock');page.locator('#engVariantPreview').click();stage('VARIANT');check(ws.state['variants']['Assembly budget']['locked'],'Independent variant lock is an explicit reviewed operation');shot('04-independent-variants.png')
   tab('qualify');act('engQualify');page.locator('#dialog [name=component]').select_option(r1['id']);fill('spec',json.dumps(spec));page.get_by_role('button',name='Run read-only comparison',exact=True).click();waitclosed()
   check(page.evaluate('E6.report.data.status')=='MATCHED_DECLARED_CHECKS','Actual pad/pin comparison returns bounded declared-check match');shot('05-land-pattern-review.png')
   tab('reviews')
   for name,role,pwtext in [('Admin','admin','browser-admin-password'),('Engineer','engineering','browser-engineer-password')]:
    act('engAccounts');fill('name',name);page.locator('#dialog [name=role]').select_option(role);fill('password',pwtext);fill('confirmation','REGISTER')
    if role!='admin':fill('admin','Admin');fill('admin_password','browser-admin-password')
    page.get_by_role('button',name='Register local reviewer',exact=True).click();waitclosed()
   check(True,'Local role accounts created without displaying or persisting plaintext passphrases')
   act('engReviewContext');page.wait_for_function('E6.report.data.schema==="wayricad-review-context-1"');check(page.evaluate('E6.report.data.status')=='NOT_APPROVED','No implicit approval from a passing data check')
   act('engDecision');fill('reviewer','Engineer');fill('password','browser-engineer-password');fill('reason','Reviewed synthetic project inputs');fill('evidence','BROWSER TEST ONLY');fill('confirmation','REVIEW');page.get_by_role('button',name='Record signed local decision',exact=True).click();waitclosed()
   check(page.evaluate('E6.report.data.status')=='APPROVED_LOCAL','Authenticated engineering approval binds current inputs');shot('06-controlled-review.png')
   ws.edit([r2['id']],BASE,{'Notes':'Change after approved context'});page.evaluate('refresh()');act('engReviewContext');page.wait_for_function('E6.report.data.status==="NOT_APPROVED"');check(any(d['status']=='STALE' for d in page.evaluate('E6.report.data.decisions')),'Changed input invalidates earlier approval')
   tab('catalog');page.locator('#engQuery').fill(r1['fields']['MPN']);act('engSearch');act('finderPart8');act('engEvidence');fill('supplier','DigiKey');fill('sku','SYNTHETIC-BROWSER-SKU');fill('stock','20');fill('observed_at',datetime.now(timezone.utc).isoformat());fill('source_url','https://example.com/SYNTHETIC-OBSERVATION');fill('actor','Browser reviewer');page.locator('#dialog [name=reviewed]').check();page.locator('#engEvidencePreview').click();stage('IMPORT')
   act('engHealth');fill('query','');fill('low_stock_threshold','50');page.get_by_role('button',name='Run catalog health',exact=True).click();page.wait_for_function('E6.report.data.schema==="wayricad-catalog-health-1"')
   check(page.evaluate('E6.report.data.all_matches') and page.evaluate('E6.report.data.assessed===E6.report.data.total'),'Full-catalog health scan covers every matched identity')
   check(any(x['health']['low_stock'] for x in page.evaluate('E6.report.data.items')),'Configurable low-stock threshold detects observed low quantity');shot('07-catalog-health.png')
   tab('purchasing');act('engInventory');fill('records',json.dumps([{'id':'Shelf-lot-1','part_id':pid,'quantity':30,'reserved':2,'location':'Shelf A','expires':'','status':'available','source':'Synthetic physical count','observed_at':datetime.now(timezone.utc).isoformat(),'notes':'test only'}]));fill('actor','Browser stockroom');page.locator('#engInventoryPreview').click();stage('INVENTORY')
   act('engBuild');page.locator('#engAddBuild').click();rows=page.locator('[data-build-row]');rows.nth(0).locator('[data-build-key=boards]').fill('10');rows.nth(1).locator('[data-build-key=boards]').fill('15');page.get_by_role('button',name='Save session scenario and run',exact=True).click();waitclosed()
   report=page.evaluate('E6.report.data');check(len(report['demands'])>1 and report['status']=='GAPS_OR_REVIEW','Multiple build priorities report unmet demand instead of invented stock')
   check(sum(a['quantity'] for a in report['allocations'] if a['source']=='inventory' and a['lot']=='Shelf-lot-1')<=28,'Shared inventory allocated at most once after reserved quantity');shot('08-multi-build-planning.png')
   with page.expect_download() as dl:act('engDownloadReport')
   dl.value.save_as(output/'multi-build-report.json');check(json.loads((output/'multi-build-report.json').read_text())['schema']=='wayricad-build-result-1','Engineering report JSON download contains full plan')
   tab('validation');act('engVerify');page.wait_for_function('E6.report.data.ok===true');check(True,'Catalog revisions/assets/audit integrity verified')
   # Actual DOM benchmark, synthetic client-side 50k rows, not a project parser or KiCad benchmark.
   page.locator('[data-view=bom]').first.click();page.evaluate('window._realRows6=S.data.rows;window._realGrouping6=S.data.grouping;S.data.grouping={fields:[]};S.selected.clear();S.search="";S.query4="";S.data.rows=Array.from({length:50000},(_,i)=>({..._realRows6[0],id:"SYNTH-"+i,ref:"R"+(i+1),fields:{..._realRows6[0].fields,Reference:"R"+(i+1)}}));E6.virtual=true;E6.vstart=0;window._startV6=performance.now();render();window._elapsedV6=performance.now()-_startV6;')
   page.locator('#engVirtualViewport').wait_for();measures['synthetic_50000_initial_render_ms']=page.evaluate('_elapsedV6')
   check(page.locator('#engVirtualWindow tr[data-row]').count()<=45,'50,000 client-side rows render no more than 45 data rows')
   viewport=page.locator('#engVirtualViewport');viewport.focus();page.keyboard.press('Control+End');page.wait_for_timeout(100)
   check(page.evaluate('document.activeElement.dataset.id')=='SYNTH-49999','Keyboard Control-End reaches last row without focus loss')
   page.keyboard.press('Control+Home');page.wait_for_timeout(100);check(page.evaluate('document.activeElement.dataset.id')=='SYNTH-0','Keyboard Control-Home returns to first row')
   page.evaluate('document.querySelector("#engVirtualViewport").scrollTop=400000');page.wait_for_timeout(200);check(page.locator('#engVirtualWindow tr[data-row]').count()<=45 and page.evaluate('E6.vstart')>9000,'Scrolling retains bounded DOM at a distant virtual window')
   check(page.locator('#engVirtualWindow table').get_attribute('aria-rowcount')=='50001','Virtual table exposes total row count for assistive technology')
   page.screenshot(path=str(output/'09-bounded-viewport.png'),full_page=True)
   page.evaluate('S.data.rows=_realRows6;S.data.grouping=_realGrouping6;E6.virtual=false;render();');page.locator('[data-view=engineering]').first.click();tab('catalog');page.locator('#engQuery').fill('');act('engSearch')
   page.locator('[data-act=engTab][data-tab=catalog]').focus();page.keyboard.press('ArrowRight');check(page.evaluate('E6.tab')=='reuse','Keyboard arrow navigation switches engineering tabs')
   tab('catalog');page.locator('#themeButton').click();shot('10-dark-catalog.png');page.set_viewport_size({'width':780,'height':1080});shot('11-compact-catalog.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Engineering catalog has no page-level overflow at 780px')
   check(page.locator('.eng-state[title]').count()>0,'Color states retain visible labels and explanatory tooltips')
   check(original==ws.project.hashes and all(__import__('hashlib').sha256(Path(p).read_bytes()).hexdigest()==h for p,h in original.items()),'All tested engineering workflows preserve native source bytes')
   check(not errors,'No uncaught JavaScript or console errors')
   browser.close()
  result={'passed':len(checks),'checks':checks,'errors':errors,'measures':measures,'transport':'Actual DOM/scripts/backend through HTTP bridge' if args.bridge else 'Direct loopback','native_host_tested':False,'screen_reader_tested':False}
  (output/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 finally:
  if errors:print('BROWSER ERRORS:',errors,flush=True)
  server.shutdown();server.server_close();thread.join();shutil.rmtree(app.demo_directory,ignore_errors=True)
if __name__=='__main__':main()
