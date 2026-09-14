"""Actual shipped DOM/backend; bridge mode is explicit, no KiCad/retailer host."""
from pathlib import Path
import argparse,base64,http.client,json,re,sys,threading,shutil,io,zipfile,csv
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio.native import BASE

def main():
 from playwright.sync_api import sync_playwright
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--bridge',action='store_true');args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);ws=app.workspace;root=app.demo_directory
 for row in ws.rows():
  supplier='Mouser' if row['ref'].startswith('C') else 'DigiKey'
  ws.edit([row['id']],BASE,{'Supplier':supplier,'Purchasing vendor':supplier,'MOQ':'1','OrderMultiple':'1','InternalPN':''})
 row=next(r for r in ws.rows() if r['ref']=='J1');ws.edit([row['id']],BASE,{'Purchasing vendor':''})
 ws.save();native_before={str(p):p.read_bytes() for p in ws.project.documents};props_before=[r['raw'] for r in ws.rows()]
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks=[];errors=[]
 def check(value,name):
  assert value,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1700,'height':1120},device_scale_factor=1);page.set_default_timeout(18000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('dialog',lambda d:d.accept())
   if args.bridge:
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=120);c.request(req['method'],req['path'],body=req.get('body').encode() if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}));r=c.getresponse();result={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return result
    page.expose_function('_wayricadLocalTransport',bridge);web=Path(__file__).resolve().parents[1]/'web';html=re.sub(r'<script[^>]+src="/[^"]+"[^>]*></script>','',(web/'index.html').read_text()).replace('<link rel="stylesheet" href="/style.css">','');page.set_content(html);page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='const testStorage={wayricadToken:'+json.dumps(app.token)+'};'+'''for(const name of ['sessionStorage','localStorage'])Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});history.replaceState=()=>{};window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    for script in ('app','workbench','intelligence','automation','analytics','engineering','assets','studio8','library8','nativefirst','vendors','assemblers'):page.add_script_tag(content=(web/(script+'.js')).read_text())
   else:page.goto(server.url,timeout=5000)
   def act(name):page.locator('[data-act="'+name+'"]').first.click();page.wait_for_timeout(150)
   def shot(name):page.evaluate('document.querySelector("#toasts").replaceChildren()');page.screenshot(path=str(out/name),full_page=False)
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for();check(page.evaluate('followingNative()'),'Native BOM authority stays the default')
   page.locator('[data-view=vendors]').click();page.get_by_role('heading',name='Vendor split & upload',exact=True).wait_for();check(True,'Dedicated vendor workspace in navigation')
   page.locator('[data-vs-map=vendor_field]').fill('Purchasing vendor');page.locator('[data-vs-map=boards]').fill('10');page.locator('[data-vs-map=attrition_percent]').fill('5');act('vendorPreview');page.wait_for_function('VS.report && !VS.busy');check(page.evaluate('VS.report.summary.vendors')==2,'Separate DigiKey and Mouser groups');check(page.evaluate('VS.report.summary.unassigned_components')==1,'Missing routing retained as unassigned')
   check(page.evaluate("VS.config.vendor_field==='Purchasing vendor' && VS.config.boards===10"),'Unsaved mappings survive preview rerender');check(page.evaluate('!vendorStale()'),'Fresh preview exportable despite unsaved mapping draft');check(page.evaluate('VS.report.summary.reconciled'),'Demand reconciles')
   shot('01-vendor-routing.png');act('vendorExportAll');check(page.locator('#toasts').inner_text().find('PARTIAL')>=0,'Incomplete export requires explicit acknowledgement')
   page.locator('#vendorPartial').check()
   with page.expect_download() as info:act('vendorExportAll')
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);z=zipfile.ZipFile(dest);check('PARTIAL' in d.suggested_filename,'Partial archive clearly named');check('reports/UNASSIGNED.csv' in z.namelist(),'Unassigned report included');check(len([n for n in z.namelist() if n.startswith('uploads/')])==4,'One CSV and one XLSX alternative per vendor')
   act('vendorSelectResults');check(page.evaluate('S.selected.size')==0,'Routing selection is not bulk-edit selection');act('vendorAssign');page.locator('#dialog [name=vendor]').fill('Mouser');page.locator('#dialog [name=sku]').fill('000-DEMO-MOUSER');page.get_by_role('button',name='Apply routing only',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.evaluate('VS.report.summary.unassigned_components')==0,'Assignment resolves missing vendor');check(page.evaluate("VS.report.components.find(x=>x.reference==='J1').sku")=='000-DEMO-MOUSER','Reviewed SKU override applied')
   check(props_before==[r['raw'] for r in ws.rows()],'Routing never changes native component properties');check(page.evaluate('!vendorStale()'),'Assignment preview remains fresh')
   page.locator('[data-act=vendorTab][data-vendor=mouser]').click();shot('02-mouser-upload.png')
   with page.expect_download() as info:page.locator('[data-act=vendorExportOne][data-format=xlsx]').click()
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);z=zipfile.ZipFile(dest);check('xl/worksheets/sheet1.xml' in z.namelist() and 'xl/worksheets/sheet2.xml' not in z.namelist(),'Downloaded workbook is one clean upload worksheet');check('000-DEMO-MOUSER' in z.read('xl/worksheets/sheet1.xml').decode(),'Leading-zero SKU remains literal text in Excel')
   page.locator('[data-view=bom]').click();page.locator('[data-view=vendors]').click();check(page.evaluate("VS.config.vendor_field==='Purchasing vendor' && VS.config.assignments[BASE]"),'Mappings and routing drafts survive navigation')
   page.locator('#saveButton').click();page.wait_for_function('!VS.draft && !S.data.dirty');check(ws.state['vendor_export_settings']['boards']==10,'Top-level Save persists vendor draft');act('vendorPreview');page.wait_for_function('VS.report && !VS.busy');check(page.evaluate('VS.report.summary.unassigned_components')==0,'Saved override survives refreshed preview');check(page.evaluate('followingNative()'),'Saving vendor maps does not switch BOM authority')
   page.locator('[data-vs-map=boards]').fill('20');check(page.evaluate('VS.report===null'),'Input changes invalidate old report');act('vendorPreview');page.wait_for_function('VS.report && !VS.busy');check(page.evaluate('VS.report.boards')==20,'Updated build quantity recomputed')
   act('vendorProfiles');page.locator('#dialog textarea[name=profiles]').fill('{"mouser":{"max_lines":1}}');page.get_by_role('button',name='Use profiles',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.evaluate('vendorStale()'),'Profile edits invalidate older preview');act('vendorPreview');page.wait_for_function('VS.report && !VS.busy');check(page.evaluate("VS.report.vendors.find(v=>v.id==='mouser').file_parts")>1,'Configurable chunking is exposed in preview')
   with page.expect_download() as info:act('vendorExportAll')
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);z=zipfile.ZipFile(dest);check(any('of-' in n for n in z.namelist() if n.startswith('uploads/Mouser')),'All required chunks are included in complete vendor archive')
   with page.expect_download() as info:act('vendorShareConfig')
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);check(json.loads(dest.read_text())['assignments']=={},'Sharing settings excludes project instance routing')
   page.locator('#themeButton').click();shot('03-vendor-dark.png');page.set_viewport_size({'width':820,'height':1000});shot('04-vendor-compact.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Compact view has no page-wide horizontal overflow')
   check(all(Path(p).read_bytes()==b for p,b in native_before.items()),'All native source bytes remain unchanged');check(not errors,'No recorded page/console errors');browser.close()
 except Exception:
  try:page.screenshot(path=str(out/'failure.png'));(out/'failure-dom.txt').write_text(page.locator('body').inner_text());print(errors)
  except Exception:pass
  raise
 finally:
  server.shutdown();server.server_close();thread.join(2);(out/'results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'errors':errors,'bridge':args.bridge,'host_tested':False},indent=2));shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':main()
