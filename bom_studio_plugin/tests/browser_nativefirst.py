"""Native-first full GUI acceptance using the shipped code and localhost API.

--bridge is only for browser-policy-restricted environments. Native KiCad's
subprocess contract is injected; this does not claim a KiCad-host export/window.
"""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace
import argparse,base64,csv,hashlib,http.client,io,json,os,re,shutil,sys,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.server import Application,Server
from bomstudio.engine import Workspace
from bomstudio.native import Project
from bomstudio import nativebom


def main():
 from playwright.sync_api import sync_playwright
 parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--bridge',action='store_true');parser.add_argument('--output',required=True);args=parser.parse_args()
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);root=app.demo_directory;project=app.workspace.project.pro_path
 # Configure a saved native format independent of WayriCAD's sample custom layouts.
 j=json.loads(project.read_text());s=j['schematic'];s['drawing']={'field_names':[{'name':'Approver','visible':False,'url':False},{'name':'ProjectOnly','visible':True,'url':False}]}
 p={'name':'Native custom','fields_ordered':[{'name':'Reference','label':'Designators','show':True,'group_by':False},{'name':'Value','label':'Actual value','show':True,'group_by':False},{'name':'MPN','label':'Hidden ordering code','show':False,'group_by':False},{'name':'Approver','label':'Approval record','show':True,'group_by':False}], 'sort_field':'Reference','sort_asc':False,'filter_string':'','group_symbols':False,'exclude_dnp':False,'include_excluded_from_bom':True}
 s['bom_settings']=p;s['bom_presets']=[dict(deepcopy(p),name='Resistors only',filter_string='R*',exclude_dnp=True)]
 s['bom_fmt_settings']={'name':'Team text','field_delimiter':';','string_delimiter':"'",'ref_delimiter':' / ','ref_range_delimiter':'~','keep_tabs':True,'keep_line_breaks':True}
 s['bom_fmt_presets']=[{'name':'Tabs','field_delimiter':'\t','string_delimiter':'','ref_delimiter':',','ref_range_delimiter':'','keep_tabs':False,'keep_line_breaks':False}]
 project.write_text(json.dumps(j,indent=2));app.workspace=Workspace(Project(project))
 cfg=root/'cfg';cfg.mkdir();(cfg/'eeschema.json').write_text(json.dumps({'drawing':{'field_names':'(templatefields (field (name "GlobalOnly") visible url) (field (name "Approver") visible))'}}))
 original={str(f):f.read_bytes() for f in app.workspace.project.documents};original[str(project)]=project.read_bytes();calls=[];checks=[];errors=[]
 def fake_run(cmd,timeout=20):
  if cmd[1:]==['version']:return SimpleNamespace(returncode=0,stdout='10.0-contract-fixture',stderr='')
  if '--help' in cmd:return SimpleNamespace(returncode=0,stdout='\n'.join('--'+k.replace('_','-')+(' VAR' if k=='sort_asc' else '') for k in nativebom.OPTIONS),stderr='')
  calls.append(cmd);target=Path(cmd[cmd.index('--output')+1]);target.write_bytes(b"'Designators';'Actual value';'Approval record'\r\n'R1';'10k';''\r\n")
  return SimpleNamespace(returncode=0,stdout='',stderr='')
 def check(condition,name):
  assert condition,name
  checks.append(name);print('PASS',name,flush=True)
 server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  with patch.dict(os.environ,{'WAYRICAD_KICAD_CONFIG_DIR':str(cfg)}),patch.object(nativebom,'cli_path',return_value='/injected/kicad-cli'),patch.object(nativebom,'_run',side_effect=fake_run),sync_playwright() as play:
   browser=play.chromium.launch(headless=True,executable_path=args.chromium,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1620,'height':1080},device_scale_factor=1);page.set_default_timeout(18000)
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
   def view(name):page.locator('[data-view="'+name+'"]').first.click();page.wait_for_timeout(200)
   def shot(name):page.evaluate('document.querySelector("#toasts").replaceChildren()');page.screenshot(path=str(out/name),full_page=not page.locator('#dialog').evaluate('(d)=>d.open'))
   page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   check(page.evaluate('followingNative()'),'Fresh migrated workspace follows KiCad by default')
   check(page.evaluate("JSON.stringify(S.columns)===JSON.stringify(['@field:Reference','@field:Value','@field:Approver'])"),'Native visible membership is exact; hidden and omitted fields are not appended')
   check(page.locator('th[data-grid-column="@field:Reference"]').inner_text().startswith('Designators'),'Native BOM labels are inherited')
   check(page.evaluate('!S.asc'),'Native descending sort is inherited')
   check(page.evaluate("!S.data.rows[0].raw.hasOwnProperty('Approver')"),'Native field definition does not create properties on components')
   check(page.locator('#runtimeBadgeNF').inner_text().startswith('v'+json.loads((Path(__file__).resolve().parents[1]/'metadata.json').read_text(encoding='utf-8'))['versions'][0]['version']),'Running version and presentation mode visible')
   shot('01-following-kicad-bom.png')
   act('projectFields8');check(page.locator('[data-field-choice8="@field:MPN"]').count()==1,'Hidden physical field remains discoverable')
   check(page.locator('[data-field-choice8="@field:GlobalOnly"]').count()==1,'Unpopulated global template field remains discoverable');close()
   view('fieldtemplates');page.locator('#nativeFieldsNF').wait_for()
   check(page.locator('#nativeFieldsNF tr').filter(has=page.get_by_text('Approver',exact=True)).inner_text().endswith('No\tNo'),'Project template overrides matching global visibility')
   check(page.locator('#nativeFieldsNF').get_by_text('GlobalOnly',exact=True).count()==1,'Global native templates are included')
   check(page.locator('#fieldProfileForm').count()==0,'Custom engineering profile editor is not active by default')
   shot('02-native-field-templates.png')
   page.locator('#saveButton').click();page.wait_for_timeout(300);check(page.evaluate('!NF.profilesCustom'),'Saving read-only templates does not activate enforcement')
   view('exports');check(page.locator('#nativePresetNF').count()==1,'Export starts with inherited native format, not Purchasing')
   check(page.locator('#templateSelect').count()==0,'Custom exporter is absent until explicitly selected')
   check(page.locator('#main details pre').text_content().find('"field_delimiter": ";"')>=0,'Saved delimiter is displayed without substitution')
   act('previewNativeNF');check(len(calls)==0,'Native export requires saved-source acknowledgement')
   page.locator('#nativeSavedNF').check();act('previewNativeNF');page.locator('#nativePreviewNF pre').wait_for()
   check(len(calls)==1,'Native export delegates through capability-probed CLI contract')
   cmd=calls[-1];check(cmd[cmd.index('--fields')+1]=='Reference,Value,Approver','Native request retains saved visible fields only')
   check(cmd[cmd.index('--labels')+1]=='Designators,Actual value,Approval record','Native request uses exact headings')
   check(cmd[cmd.index('--field-delimiter')+1]==';' and cmd[cmd.index('--sort-asc')+1]=='false','Native request retains saved delimiter and descending sort')
   check('--keep-tabs' in cmd and '--keep-line-breaks' in cmd,'Native keep-tabs and multiline flags preserved')
   shot('03-inherited-native-export.png')
   with page.expect_download() as download:act('exportNativeNF')
   saved=out/'native-contract-output.csv';download.value.save_as(str(saved));check(saved.read_bytes()==b"'Designators';'Actual value';'Approval record'\r\n'R1';'10k';''\r\n",'Downloaded native contract bytes are not reserialized')
   page.locator('#nativePresetNF').select_option('0');page.wait_for_function("ctxNF().preferences.preset==='0'")
   view('bom');check(page.evaluate("filteredRows().every(r=>r.ref.startsWith('R')&&!r.flags.dnp)"),'Native reference pattern and DNP filter precede grouping')
   view('exports');page.locator('#nativeFormatNF').select_option('0');page.wait_for_function("ctxNF().preferences.format_preset==='0'")
   page.locator('#nativeSavedNF').check();act('previewNativeNF');check('--preset' in calls[-1] and '--format-preset' in calls[-1] and '--fields' not in calls[-1],'Named native presets are forwarded by name')
   page.locator('#nativePresetNF').select_option('@current');page.wait_for_function("ctxNF().preferences.preset==='@current'");page.locator('#nativeFormatNF').select_option('@current');page.wait_for_function("ctxNF().preferences.format_preset==='@current'")
   act('customizeNF');page.locator('#dialog [name=name]').fill('Reviewed custom');page.get_by_role('button',name='Create custom copy',exact=True).click()
   page.get_by_role('heading',name='Custom-copy differences',exact=True).wait_for();check(True,'Replacement dialog survives completion of the previous form submit')
   check(page.locator('#dialog').evaluate('(d)=>d.open'),'Custom-copy differences are actually visible, not immediately auto-closed');close()
   check(page.evaluate("!followingNative() && S.template==='Reviewed custom'"),'Custom export activates only after deliberate copying')
   check(page.locator('#templateSelect').count()==1,'Existing enhanced export controls remain available')
   act('mergeNativeNF');page.get_by_role('button',name='Merge native columns',exact=True).click();page.get_by_role('heading',name='Merge result',exact=True).wait_for();check(True,'Merge result replacement dialog stays open');close()
   act('reverseFormatNF');page.get_by_role('heading',name='Review custom BOM format → KiCad',exact=True).wait_for()
   check(page.locator('#formatDiffNF').inner_text().find('bom_fmt_settings')>=0,'Reverse-format dialog opens and contains the complete before/after diff')
   shot('04-reviewed-format-to-kicad.png')
   page.locator('#dialog [name=acknowledge]').check();page.locator('#dialog [name=confirmation]').fill('WRONG');page.get_by_role('button',name='Stage reviewed format',exact=True).click();page.wait_for_timeout(300)
   check(page.locator('#dialog').evaluate('(d)=>d.open') and 'FORMAT' in page.locator('#dialogError').inner_text(),'Wrong confirmation keeps the review dialog open with an error')
   page.locator('#dialog [name=confirmation]').fill('FORMAT');page.get_by_role('button',name='Stage reviewed format',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open')
   check(app.workspace.state.get('native_bom_settings') is not None,'FORMAT stages the reviewed settings')
   check(all(Path(k).read_bytes()==v for k,v in original.items()),'Staging, viewing and exporting never mutate native project files')
   view('bom');act('undo');view('exports');check(app.workspace.state.get('native_bom_settings') is None,'Undo restores the pre-staging native-settings state')
   act('followNativeNF');check(page.evaluate("followingNative() && Boolean(S.data.templates['Reviewed custom'])"),'Returning to KiCad retains custom copies without activating them')
   page.locator('#saveButton').click();page.wait_for_timeout(300);check(all(Path(k).read_bytes()==v for k,v in original.items()),'Saving native-first workspace keeps all source bytes unchanged')
   act('runtimeNF');check(page.locator('#dialog').inner_text().find('installation')>=0,'Runtime diagnostic identifies actual installation and interpreter');close()
   # Deliberate field-profile copy preserves read-only defaults and does not enforce.
   view('fieldtemplates');act('copyProfileNF');page.locator('#dialog [name=name]').fill('Native names copy');page.get_by_role('button',name='Create field-profile copy',exact=True).click();page.wait_for_function('!document.querySelector("#dialog").open')
   check(page.evaluate('NF.profilesCustom'),'Explicit field-template copy opens custom management')
   check(all(Path(k).read_bytes()==v for k,v in original.items()),'Copying field definitions does not enforce or remove native properties')
   act('nativeProfilesNF');check(page.locator('#nativeFieldsNF').count()==1,'Native field definitions can be restored as read-only view')
   view('exports');page.locator('#themeButton').click();shot('05-dark-native-format.png');page.set_viewport_size({'width':800,'height':1050});shot('06-compact-native-format.png');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Compact native-format page has no page-wide overflow')
   page.evaluate("NF.projectKey='different previous project';NF.profilesCustom=true;renderFieldTemplates();");check(page.evaluate('!NF.profilesCustom'),'Changing project context resets custom field-profile presentation to native definitions')
   check(not errors,'All ten shipped UI scripts run without recorded page/console errors')
   browser.close()
 except Exception:
  try:page.screenshot(path=str(out/'failure.png'));(out/'failure-dom.txt').write_text(page.locator('body').inner_text())
  except Exception:pass
  raise
 finally:
  server.shutdown();server.server_close();thread.join(3);(out/'results.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'errors':errors,'bridge':args.bridge,'native_cli_contract_injected':True,'native_host_tested':False},indent=2));shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':main()
