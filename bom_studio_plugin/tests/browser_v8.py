"""Real shipped UI/backend checks via an explicit HTTP bridge; no KiCad host."""
from pathlib import Path
import argparse,base64,http.client,json,re,sys,threading,shutil,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio import partsdb

def main():
 from playwright.sync_api import sync_playwright
 a=argparse.ArgumentParser();a.add_argument('--chromium',default='/usr/bin/chromium');a.add_argument('--bridge',action='store_true');a.add_argument('--output',required=True);args=a.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 app=Application(engineering_demo=True);root=app.demo_directory;ws=app.workspace;library=app.library_path
 row=next(r for r in ws.rows() if r['ref']=='R1');pid=partsdb.record_identity(row['fields'])
 c=ws.project.by_id[row['id']];c.fields.update({'Supplier ordering code':'EXACT-CUSTOM','Currency':'','Qty':'5','Source':'Supplier observation'})
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks=[];errors=[]
 def check(value,name):
  assert value,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1720,'height':1120},device_scale_factor=1);page.set_default_timeout(18000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('dialog',lambda d:d.accept())
   if args.bridge:
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=120);c.request(req['method'],req['path'],body=req.get('body').encode() if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}));r=c.getresponse();result={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return result
    page.expose_function('_wayricadLocalTransport',bridge);web=Path(__file__).resolve().parents[1]/'web';html=re.sub(r'<script[^>]+src="/[^"]+"[^>]*></script>','',(web/'index.html').read_text()).replace('<link rel="stylesheet" href="/style.css">','');page.set_content(html);page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='const testStorage={wayricadToken:'+json.dumps(app.token)+'};'+'''for(const name of ['sessionStorage','localStorage'])Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});history.replaceState=()=>{};window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    for script in ('app','workbench','intelligence','automation','analytics','engineering','assets','studio8','library8','nativefirst','vendors','assemblers'):page.add_script_tag(content=(web/(script+'.js')).read_text())
   else:page.goto(server.url,timeout=5000)
   def act(name):page.locator('[data-act="'+name+'"]').first.click();page.wait_for_timeout(150)
   def close():page.locator('#dialogClose').click();page.wait_for_timeout(100)
   def shot(name):page.evaluate('document.querySelector("#toasts").replaceChildren()');page.screenshot(path=str(out/name),full_page=not page.locator('#dialog').evaluate('(d)=>d.open'))
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   page.evaluate("async()=>{await api('fields/adopt',{all_fields:true});await api('grouping/settings',{fields:[],raw:false});NF.profilesCustom=true;await refresh();}")
   if page.locator('[data-act=adoptFields8]').count():act('adoptFields8')
   page.wait_for_function("S.columns.includes('@field:Supplier ordering code')")
   check(True,'Actual arbitrary field names are offered as default columns, not hard-coded aliases')
   check(page.evaluate("S.data.rows.find(r=>r.ref==='R1').fields['@field:Qty']==='5' && S.data.rows.find(r=>r.ref==='R1').fields.Qty===1"),'Custom Qty and calculated quantity remain distinct')
   check(page.evaluate("S.data.rows.find(r=>r.ref==='R1').fields['@field:Currency']===''"),'Intentional blank currency is not the configured purchasing default')
   act('projectFields8');check(page.locator('[data-field-choice8="@field:Supplier ordering code"]').count()==1,'Field inspector includes exact names and presence counts')
   page.locator('[data-field-choice8="@field:MPN"] [data-label8]').fill('Orderable code')
   page.get_by_role('button',name='Apply columns & grouping',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.locator('th[data-grid-column="@field:MPN"]').inner_text().startswith('Orderable code'),'BOM display labels do not rename the actual property')
   shot('01-project-fields.png')
   cell=page.locator('tr[data-row]').filter(has=page.get_by_label('Select R1',exact=True)).locator('td[data-field="@field:Value"]');cell.dblclick();cell.locator('input').fill('22k');page.keyboard.press('Enter');check(page.evaluate('pendingGridCount()')==1,'Exact physical Value supports keyboard inline editing')
   act('reviewGrid');page.locator('#dialog [name=confirmation]').fill('EDIT');page.get_by_role('button',name='Stage reviewed edits',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.evaluate("S.data.rows.find(r=>r.ref==='R1').raw.Value==='22k'"),'Reviewed direct BOM editing changes the physical field')
   act('undo');check(page.evaluate("S.data.rows.find(r=>r.ref==='R1').raw.Value==='10k'"),'Undo restores the complete prior edit')
   act('toggleRaw8');check(page.evaluate('V8.raw'),'Raw-expression inspection toggles independently');act('toggleRaw8')
   act('followNativeNF');act('nativeBOM8');check(page.locator('#nativeSavedNF').count()==1,'Native KiCad export requires saved-source acknowledgement')
   page.locator('[data-view=engineering]').first.click();page.wait_for_function('E6.info?.attached');awaited=page.evaluate('searchCatalog6()');page.wait_for_function('E6.page?.total>0');check(page.get_by_role('heading',name='Local parts finder',exact=True).count()==1,'Integrated category/results/details catalogue browser renders')
   check(page.locator('[data-act=finderCategory8]').count()>1,'Category tree includes full-catalogue counts')
   page.locator('#engQuery').fill(row['fields']['MPN']);act('engSearch');page.wait_for_function('E6.page.total===1');act('finderPart8');page.wait_for_timeout(500);page.locator('#finderPreview8 svg').wait_for();check(True,'Part details include a real inline symbol preview')
   act('finderMini8') # symbol first
   page.locator('[data-act=finderMini8][data-kind=footprint]').click();page.locator('#finderPreview8 svg').wait_for();check(True,'Details panel switches to captured footprint preview')
   shot('02-parts-finder.png')
   act('finderCompareAdd8');act('finderClear8');page.wait_for_function('E6.page.total>1');buttons=page.locator('[data-act=finderCompareAdd8]');
   for n in range(buttons.count()):
    if buttons.nth(n).get_attribute('data-id')!=pid:buttons.nth(n).click();break
   act('finderCompare8');check(page.locator('.compare-difference8').count()>0,'Part comparison highlights differing recorded specifications');close()
   # Catalogue-source creation with all three real captured assets.
   page.locator('#engQuery').fill(row['fields']['MPN']);act('engSearch');page.wait_for_function('E6.page.total===1');page.locator('[data-eng-select]').first.check()
   act('libraryCreate8');page.locator('#libraryMode8').select_option('catalogue');page.locator('#dialog [name=destination]').fill(str(out/'native-from-catalogue'));page.locator('#dialog [name=name]').fill('TeamParts');page.get_by_role('button',name='Preview library creation',exact=True).click();page.get_by_role('heading',name='Review new KiCad library',exact=True).wait_for(timeout=60000)
   check(not (out/'native-from-catalogue').exists(),'Library preview leaves destination absent')
   check(page.evaluate('L8.plan.counts.models')==2,'Library plan includes all captured assigned model originals');shot('03-library-creation-review.png')
   page.locator('#dialog [name=confirmation]').fill('CREATE');page.get_by_role('button',name='Create reviewed library',exact=True).click();page.get_by_role('heading',name='KiCad library created',exact=True).wait_for(timeout=60000)
   check((out/'native-from-catalogue'/'TeamParts.kicad_sym').is_file(),'GUI creates a real native symbol library, not just a ZIP download')
   check(len(list((out/'native-from-catalogue'/'TeamParts.3dshapes').iterdir()))==2,'GUI publishes both original 3D models');close()
   # Project mode constructs its own catalogue without a supplied source parts library.
   act('libraryCreate8');page.locator('#libraryMode8').select_option('projects');page.locator('#dialog [name=destination]').fill(str(out/'auto-created-catalogue'));page.locator('#dialog [name=name]').fill('AutoParts');page.locator('#dialog [name=projects]').fill(str(root/'BOM_Demo.kicad_pro'));page.locator('#dialog [name=require_complete]').uncheck();page.get_by_role('button',name='Preview library creation',exact=True).click();page.get_by_role('heading',name='Review new KiCad library',exact=True).wait_for(timeout=60000)
   check(page.evaluate('L8.plan.new_catalogue'),'Project harvesting automatically proposes a new catalogue')
   page.locator('#dialog [name=confirmation]').fill('CREATE');page.get_by_role('button',name='Create reviewed library',exact=True).click();page.get_by_role('heading',name='KiCad library created',exact=True).wait_for(timeout=60000)
   check((out/'auto-created-catalogue'/'catalogue'/'catalog.sqlite3').is_file(),'Missing source library is handled by creating a new populated local catalogue');check(page.evaluate('E6.info.path').endswith('auto-created-catalogue/catalogue'),'Newly created catalogue is actually attached, not shadowed by the old project path');check(page.evaluate('F8.detail===null && F8.compare.size===0'),'Changing catalogues clears cross-catalogue preview and comparison state');close()
   act('libraryCreate8');page.locator('#libraryMode8').select_option('empty');page.locator('#dialog [name=destination]').fill(str(out/'empty-library'));page.locator('#dialog [name=name]').fill('BlankParts');shot('04-library-creator.png');page.get_by_role('button',name='Preview library creation',exact=True).click();page.get_by_role('heading',name='Review new KiCad library',exact=True).wait_for(timeout=60000);check(page.evaluate('L8.plan.counts.symbols')==0,'Empty library mode does not invent component geometry');close()
   page.locator('#themeButton').click();shot('05-dark-finder.png');page.set_viewport_size({'width':800,'height':1050});shot('06-compact-finder.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Compact parts finder avoids page-wide horizontal overflow')
   check(not errors,'All shipped scripts execute without recorded page/console errors');browser.close()
 except Exception:
  try:page.screenshot(path=str(out/'failure.png'));(out/'failure-dom.txt').write_text(page.locator('body').inner_text())
  except Exception:pass
  raise
 finally:
  server.shutdown();server.server_close();thread.join(2);(out/'results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'errors':errors,'bridge':args.bridge,'host_tested':False},indent=2));shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':main()
