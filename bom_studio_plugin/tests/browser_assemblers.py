"""Real DOM/export acceptance, optional explicit bridge. No portal or KiCad host."""
from pathlib import Path
import argparse,base64,http.client,json,re,sys,threading,shutil,io,zipfile,csv
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio.native import BASE

def main():
 from playwright.sync_api import sync_playwright
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--bridge',action='store_true');args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);ws=app.workspace;root=app.demo_directory
 ws.state['settings'].update(boards=100,attrition=50)
 for index,row in enumerate(ws.rows(),1):ws.edit([row['id']],BASE,{'Description':'Synthetic component '+row['ref'],'LCSC Part #':'C'+str(1000+index),'MOQ':'1000','OrderMultiple':'100','Supplier':'Mouser'})
 row=next(r for r in ws.rows() if r['ref']=='R1');ws.edit([row['id']],BASE,{'MPN':'0000123-DEMO-CT'})
 ws.save();native_before={str(p):p.read_bytes() for p in ws.project.documents};props_before=[r['raw'] for r in ws.rows()];vendors_before=ws.state['vendor_export_settings'].copy()
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks=[];errors=[]
 def check(value,name):
  assert value,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1600,'height':1100},device_scale_factor=1);page.set_default_timeout(20000)
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('dialog',lambda d:d.accept())
   if args.bridge:
    def bridge(req):
     c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=120);c.request(req['method'],req['path'],body=req.get('body').encode() if isinstance(req.get('body'),str) else req.get('body'),headers=req.get('headers',{}));r=c.getresponse();result={'status':r.status,'headers':dict(r.getheaders()),'data':base64.b64encode(r.read()).decode()};c.close();return result
    page.expose_function('_wayricadLocalTransport',bridge);web=Path(__file__).resolve().parents[1]/'web';html=(web/'index.html').read_text();scripts=re.findall(r'<script[^>]+src="/([^"]+)"[^>]*></script>',html);html=re.sub(r'<script[^>]+src="/[^"]+"[^>]*></script>','',html).replace('<link rel="stylesheet" href="/style.css">','');page.set_content(html);page.add_style_tag(content=(web/'style.css').read_text())
    page.add_script_tag(content='const testStorage={wayricadToken:'+json.dumps(app.token)+'};'+'''for(const name of ['sessionStorage','localStorage'])Object.defineProperty(window,name,{value:{getItem:k=>testStorage[k]||null,setItem:(k,v)=>testStorage[k]=v}});history.replaceState=()=>{};window.fetch=async(path,options={})=>{const r=await window._wayricadLocalTransport({path,method:options.method||'GET',headers:options.headers||{},body:options.body});return new Response(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});};''')
    for script in scripts:page.add_script_tag(content=(web/script).read_text())
   else:page.goto(server.url,timeout=10000)
   def act(name):page.locator('[data-act="'+name+'"]').first.click();page.wait_for_timeout(120)
   def preview():act('asmPreview');page.wait_for_function('ASM.report && !ASM.busy')
   def shot(name):page.evaluate('document.querySelector("#toasts").replaceChildren()');page.screenshot(path=str(out/name),full_page=False)
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for();check(page.evaluate('followingNative()'),'Native-first authority unchanged on launch')
   page.locator('[data-view=assemblers]').click();page.wait_for_function('ASM.defs && Object.keys(ASM.defs).length===11');check(page.locator('[data-asm-profile]').count()==11,'All eleven assembler cards included')
   check(page.locator('[data-asm-profile=jlcpcb]').is_checked(),'JLCPCB default without manual profile import');check(page.locator('[data-asm-profile=hqpcb]').count()==1 and page.locator('[data-asm-profile=nextpcb]').count()==1,'HQPCB and NextPCB separate profiles');check(page.locator('[data-vs-map=boards]').count()==0,'No purchasing build multiplier in assembly form')
   shot('01-assembler-profiles.png');preview();check(page.evaluate('ASM.report.status')=='READY_FOR_REVIEW','Documented JLCPCB mapping previews');check(page.evaluate('ASM.report.profiles[0].quantity_per_board')==10,'100-board/50-percent purchasing settings do not multiply assembly demand');check(page.locator('#assemblerOutputTable th').all_text_contents()==['Comment','Designator','Footprint','LCSC Part #'],'Exact JLCPCB four-column headings');check('R4' not in page.locator('#assemblerOutputTable').inner_text(),'DNP not in assembly upload')
   with page.expect_download() as info:page.locator('[data-act=asmExportOne][data-format=csv]').click()
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);rows=list(csv.reader(io.StringIO(dest.read_text(encoding='utf-8-sig'))));check(len(rows[0])==4 and all(len(r)==4 for r in rows),'Actual JLCPCB CSV download has four columns')
   act('asmAll');preview();check(page.evaluate('ASM.report.status')=='REVIEW_REQUIRED','Unverified provider mappings require acknowledgement');check(page.locator('[data-act=asmExportAll]').is_disabled(),'No unreviewed upload ZIP');page.locator('#assemblerReviewAck').check();preview();check(page.evaluate('ASM.report.status')=='READY_FOR_REVIEW','Explicit mapping acknowledgement permits complete handoff');check(page.evaluate('ASM.report.profiles.every(p=>p.quantity_per_board===10 && p.complete)'),'Every alternative reconciles to same one-board quantity')
   page.locator('[data-act=asmTab][data-profile=nextpcb]').click();check('Quantity' in page.locator('#assemblerOutputTable th').all_text_contents(),'NextPCB has explicit per-board quantity column');shot('02-nextpcb-per-board.png')
   with page.expect_download() as info:page.locator('[data-act=asmExportOne][data-format=xlsx]').click()
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);z=zipfile.ZipFile(dest);check('xl/worksheets/sheet2.xml' not in z.namelist(),'Excel upload has one BOM worksheet only');s=z.read('xl/worksheets/sheet1.xml');check(b'0000123-DEMO-CT' in s and b'<f>' not in s,'Full leading-zero MPN retained without formulas')
   with page.expect_download() as info:act('asmExportAll')
   d=info.value;dest=out/d.suggested_filename;d.save_as(dest);z=zipfile.ZipFile(dest);check(len([n for n in z.namelist() if n.startswith('uploads/')])==22,'ZIP has all eleven CSV/Excel alternatives');check('reports/EXCLUDED.csv' in z.namelist(),'DNP/excluded audit accompanies ZIP');check(b'PER BOARD' in z.read('README_UPLOAD.txt'),'Upload instructions protect quantity interpretation')
   page.locator('[data-view=bom]').click();page.locator('[data-view=assemblers]').click();check(page.evaluate('ASM.config.profiles.length')==11,'Unsaved selections survive navigation');page.locator('#saveButton').click();page.wait_for_function('!ASM.draft && !S.data.dirty');check(ws.state['assembler_export_settings']['profiles']==list(__import__('bomstudio.assembler_export',fromlist=['PROFILES']).PROFILES),'Top Save persists assembly profile selections');check(page.evaluate('followingNative()'),'Assembly settings do not switch native BOM authority');check(ws.state['vendor_export_settings']==vendors_before,'Distributor settings remain unchanged')
   preview();page.locator('[data-act=asmTab][data-profile=nextpcb]').click();act('asmColumns');first=page.locator('#assemblerColumnRows [data-asm-header]').first;first.fill('Component comment');page.get_by_role('button',name='Use assembly columns',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open');check(not page.locator('#assemblerReviewAck').is_checked(),'Customizing output resets acknowledgement');page.locator('#assemblerReviewAck').check();preview();page.locator('[data-act=asmTab][data-profile=nextpcb]').click();check(page.locator('#assemblerOutputTable th').first.inner_text()=='Component comment','Edited heading applied without native property rename');check(props_before==[r['raw'] for r in ws.rows()],'All component properties unchanged')
   page.locator('.assembler-mappings summary').click();page.locator('[data-asm-map=description]').fill('Description');page.locator('[data-asm-option=footprint_mode]').select_option('name');preview();check(page.evaluate('ASM.report.profiles[0].lines.every(l=>!l.footprint.includes(":"))'),'Optional nickname removal only in output');check(page.evaluate('ASM.report.profiles[0].lines.some(l=>l.description.startsWith("Synthetic component"))'),'Actual Description property used rather than forced Value')
   with page.expect_download() as info:act('asmShare')
   d=info.value;d.save_as(out/'shared-settings.json');check(json.loads((out/'shared-settings.json').read_text())['schema']=='wayricad-assembler-config-1','Share settings uses dedicated schema')
   page.locator('#themeButton').click();shot('03-assembler-dark.png');page.set_viewport_size({'width':820,'height':1000});shot('04-assembler-compact.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Compact page has no outer horizontal overflow');check(all(Path(p).read_bytes()==b for p,b in native_before.items()),'Native source bytes unchanged');check(not errors,'No page/console errors');browser.close()
 except Exception:
  try:page.screenshot(path=str(out/'failure.png'));(out/'failure-dom.txt').write_text(page.locator('body').inner_text());print(errors)
  except Exception:pass
  raise
 finally:
  server.shutdown();server.server_close();thread.join(2);(out/'results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'errors':errors,'bridge':args.bridge,'host_tested':False},indent=2));shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':main()
