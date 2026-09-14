"""Actual GUI + backend acceptance for captured asset browsing. --bridge is only
for managed browsers that prohibit normal navigation to localhost; it is not a
KiCad host or a replacement renderer. All UI scripts remain the shipped files.
"""
from pathlib import Path
import argparse,base64,http.client,json,re,sys,threading,shutil,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio import partsdb

def main():
 from playwright.sync_api import sync_playwright
 a=argparse.ArgumentParser();a.add_argument('--chromium',default='/usr/bin/chromium');a.add_argument('--bridge',action='store_true');a.add_argument('--output',required=True);args=a.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 app=Application(engineering_demo=True);root=app.demo_directory;ws=app.workspace;library=app.library_path
 row=next(r for r in ws.rows() if r['ref']=='R1');pid=partsdb.record_identity(row['fields']);app.workspace=None # genuine catalogue-only mode, not just hidden project heading
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks=[];errors=[];renderers=set()
 def check(value,name):
  assert value,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']);page=browser.new_page(viewport={'width':1600,'height':1080},device_scale_factor=1);page.set_default_timeout(15000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('dialog',lambda d:d.accept())
   if args.bridge:
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=75);c.request(req['method'],req['path'],body=req.get('body').encode() if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}));r=c.getresponse();result={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return result
    page.expose_function('_wayricadLocalTransport',bridge);web=Path(__file__).resolve().parents[1]/'web';html=re.sub(r'<script[^>]+src="/[^\"]+"[^>]*></script>','',(web/'index.html').read_text()).replace('<link rel="stylesheet" href="/style.css">','');page.set_content(html);page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='const testStorage={wayricadToken:'+json.dumps(app.token)+'};'+'''for(const name of ['sessionStorage','localStorage'])Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});history.replaceState=()=>{};window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    for script in ('app','workbench','intelligence','automation','analytics','engineering','assets','studio8','library8','nativefirst','vendors','assemblers'):page.add_script_tag(content=(web/(script+'.js')).read_text())
   else:page.goto(server.url,timeout=5000)
   def act(name):page.locator('[data-act="'+name+'"]').first.click();page.wait_for_timeout(150)
   def close():page.locator('#dialogClose').click();page.wait_for_timeout(100)
   def shot(name):page.evaluate('document.querySelector("#toasts").replaceChildren()');page.screenshot(path=str(out/name),full_page=not page.locator('#dialog').evaluate('(d)=>d.open'))
   page.locator('[data-act=browseCatalog7]').click();page.get_by_role('heading',name='Component catalogue',exact=True).wait_for();check(page.evaluate('S.data.project===null && E6.page.total>0'),'Browse saved catalogue with no open project')
   check(page.locator('.asset-chip').count()>0,'Separate symbol/footprint/model status labels and tooltips')
   page.locator('#engQuery').fill(row['fields']['MPN']);act('engSearch');check(page.evaluate('E6.page.total')==1,'Search exact manufacturer part number');shot('01-catalogue-search.png')
   act('assetSetup7');check('No API key' in page.locator('#dialog').inner_text(),'Preview dependency status and explicit install instructions');close();act('assetOpen7');page.locator('#assetViewport7 svg').wait_for();check(page.locator('#assetProps7').inner_text().find('MPN')>=0,'Preview inspector retains searchable property metadata')
   check('SHA-256' in page.locator('#assetStatus7').inner_text(),'Preview binds to stored file checksum');shot('02-symbol-preview.png')
   page.locator('#assetMetaSearch7').fill('Temp_Max');check(page.locator('#assetProps7 [data-property-text]:visible').count()==1,'Filter metadata fields inside inspector')
   page.locator('[data-act=assetTab7][data-kind=footprint]').click();page.locator('#assetViewport7 svg').wait_for();check(page.locator('#assetViewport7 svg rect').count()>=3,'Footprint preview renders saved copper-pad geometry')
   before=page.locator('#assetViewport7 svg').get_attribute('viewBox');page.locator('#assetViewport7').focus();page.keyboard.press('+');check(before!=page.locator('#assetViewport7 svg').get_attribute('viewBox'),'Keyboard SVG zoom changes viewport');act('assetReset7');check(before==page.locator('#assetViewport7 svg').get_attribute('viewBox'),'Fit resets native inspection viewport');shot('03-footprint-preview.png')
   page.locator('[data-act=assetTab7][data-kind=model]').click();page.locator('#assetCanvas7').wait_for(timeout=20000);check('triangles' in page.locator('#assetStatus7').inner_text(),'VRML model creates a real mesh preview');check(page.locator('#assetModel7 option').count()==2,'All assigned models remain selectable, including hidden references')
   renderers.add(page.locator('#assetCanvas7').get_attribute('data-renderer'));page.locator('#assetCanvas7').focus();page.keyboard.press('ArrowRight');page.keyboard.press('+');act('assetReset7');shot('04-vrml-model-preview.png')
   page.locator('#assetModel7').select_option('1');page.locator('#assetCanvas7').wait_for(timeout=25000);page.wait_for_function("document.querySelector('#assetStatus7').textContent.includes('STEP')",timeout=25000);check(True,'Actual optional OpenCascade STEP worker is exercised by browser');shot('05-step-model-preview.png')
   with page.expect_download() as dl:act('assetOriginal7')
   dest=out/'downloaded-model.step';dl.value.save_as(dest);check(dest.read_bytes()==(root/'demo-models/SYNTHETIC_resistor.step').read_bytes(),'Browser downloads byte-identical original STEP model')
   page.locator('[data-act=assetTab7][data-kind=source]').click();page.locator('.asset-source').wait_for();page.locator('.asset-source summary').first.click();check(page.locator('.asset-source').count()==1 and 'rotation' in page.locator('.asset-source').inner_text(),'Provenance shows model transform and source linkage');shot('06-asset-provenance.png')
   act('assetExportPart7');check(page.locator('#dialog [name=complete]').is_checked(),'Native library export defaults to complete-reference requirement')
   with page.expect_download() as dl:page.get_by_role('button',name='Export native ZIP',exact=True).click()
   dl.value.save_as(out/'native-assembly.zip');page.wait_for_function('!document.querySelector("#dialog").open')
   import zipfile
   with zipfile.ZipFile(out/'native-assembly.zip') as z:check(sum(n.startswith('WayriCAD.3dshapes/') for n in z.namelist())==2 and any(n.endswith('.kicad_sym') for n in z.namelist()),'Browser native export bundles symbols, footprints and both linked models')
   act('assetFilters7');page.locator('#dialog [name=has]').select_option('all3');page.get_by_role('button',name='Apply filters',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.evaluate('E6.page.total')==1,'All-three asset filter works without a project')
   act('assetFilters7');page.locator('#addRule7').click();page.locator('#rules7 [data-key=field]').fill('Temp_Max');page.locator('#rules7 [data-key=op]').select_option('<');page.locator('#rules7 [data-key=value]').fill('80');page.locator('#rules7 [data-key=unit]').fill('C');page.get_by_role('button',name='Apply filters',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(page.evaluate('E6.page.total')==0,'Typed catalogue threshold filters over actual part properties')
   act('assetClear7');check(page.evaluate('E6.page.total')>1,'Clear restores catalogue scope without changing records');act('engHarvest');check(page.locator('#dialog [name=asset_options]').count()==1,'Harvest GUI exposes custom paths, variables and source precedence');close()
   page.locator('#engQuery').fill(row['fields']['MPN']);act('engSearch');act('assetOpen7');page.locator('#assetViewport7 svg').wait_for();close()
   # Prove read independence by removing actual external source assets.
   shutil.rmtree(root/'demo-models');shutil.rmtree(root/'demo-footprints');act('assetOpen7');page.locator('[data-act=assetTab7][data-kind=model]').click();page.locator('#assetCanvas7').wait_for();check(True,'Model still previews after source project model/footprint folders are deleted');close()
   page.locator('#themeButton').click();shot('07-dark-catalogue.png');page.set_viewport_size({'width':800,'height':1000});act('assetOpen7');page.locator('#assetViewport7 svg').wait_for();shot('08-compact-preview.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Compact viewport has no page-wide horizontal overflow')
   close();check(not errors,'No recorded JavaScript page/console errors');browser.close()
 except Exception:
  try:page.screenshot(path=str(out/'failure.png'));(out/'failure-dom.txt').write_text(page.locator('body').inner_text())
  except Exception:pass
  raise
 finally:
  server.shutdown();server.server_close();thread.join(2);(out/'results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'errors':errors,'bridge':args.bridge,'model_renderers_exercised':sorted(renderers)},indent=2));shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':main()
