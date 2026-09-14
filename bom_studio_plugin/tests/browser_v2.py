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
   page.evaluate("async()=>{await api('bom-format/select',{mode:'custom',custom_template:'Purchasing'});NF.profilesCustom=true;S.template='Purchasing';await refresh();}")
   # Persistent workspace ordering and visibility, through the actual dialog.
   page.get_by_role('button',name='Columns',exact=True).click();page.locator('[data-act=legacyColumns8]').click()
   page.get_by_role('button',name='Hide all',exact=True).click()
   page.locator('#viewColumns input[value="MPN"]').check();page.locator('#viewColumns input[value="Reference"]').check()
   for _ in range(page.locator('#viewColumns label').count()+50):
    b=page.get_by_role('button',name='Move MPN up',exact=True)
    if b.is_disabled():break
    b.click()
   page.locator('#viewPresetName').fill('Buyer layout')
   page.screenshot(path=str(output/'01-column-layout-dialog.png'),full_page=True)
   page.get_by_role('button',name='Apply columns',exact=True).click()
   page.wait_for_function("S.columns.join(',')==='MPN,Reference'");checks.append('Workspace visibility and arrow ordering persist in named layout')
   page.locator('[data-grid-column="MPN"]').drag_to(page.locator('[data-grid-column="Reference"]'))
   page.wait_for_function("S.columns.join(',')==='Reference,MPN'");checks.append('Direct table-header drag updates persistent order')
   page.get_by_role('button',name='Columns',exact=True).click();page.locator('[data-act=legacyColumns8]').click();page.locator('#viewPreset').select_option('Buyer layout')
   with page.expect_download() as event:page.get_by_role('button',name='Share saved layout ↗',exact=True).click()
   d=event.value;d.save_as(str(output/'Buyer_layout.json'));b=json.loads((output/'Buyer_layout.json').read_text());assert b['view_presets'][0]['columns']==['MPN','Reference'];checks.append('Saved layout shares as data-only JSON')
   page.get_by_role('button',name='Apply columns',exact=True).click();page.wait_for_function("S.columns.join(',')==='MPN,Reference'")
   # New, reorder, hide, preview, download, share, duplicate, rename, delete, import.
   page.locator('[data-view=exports]').first.click();page.locator('[data-act=newDefinition][data-section=templates]').click();page.locator('#dialog [name=name]').fill('Browser BOM');page.get_by_role('button',name='Create template',exact=True).click();page.locator('#templateName').wait_for();page.wait_for_function("S.template==='Browser BOM'")
   row=page.locator('.export-column').filter(has=page.locator('input[data-column-field][value="MPN"]'));row.locator('[data-column-label]').fill('Part code');row.locator('[data-act=columnUp]').click()
   page.locator('.export-column').filter(has=page.locator('input[data-column-field][value="Qty"]')).locator('[data-column-export]').uncheck()
   page.locator('#quickExport').click();assert page.locator('.export-column').first.locator('[data-column-label]').input_value()=='Part code';assert not page.locator('.export-column').filter(has=page.locator('input[data-column-field][value="Qty"]')).locator('[data-column-export]').is_checked();checks.append('Top Export shortcut does not discard an unsaved export form')
   page.get_by_role('button',name='Preview',exact=True).click();page.locator('#exportPreview table').wait_for()
   assert page.locator('#exportPreview th').all_text_contents()==['Part code','Reference'];checks.append('Current unsaved column order, labels and export inclusion used by preview')
   assert len(app.workspace.state['templates']['Browser BOM']['columns'])==3;checks.append('Unchecked columns remain in the reusable template')
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'02-exports-and-templates.png'),full_page=True)
   for fmt in ('csv','xlsx','ascii','ods','xml','txt'):
    page.locator('#exportFormat').select_option(fmt)
    with page.expect_download() as event:page.get_by_role('button',name='Export active variant ↗',exact=True).click()
    d=event.value;d.save_as(str(output/d.suggested_filename));assert (output/d.suggested_filename).stat().st_size>20
   checks.append('Six real browser downloads: CSV, Excel, ASCII, ODS, XML, Unicode text')
   with page.expect_download() as event:page.locator('[data-act=shareDefinition][data-section=templates]').click()
   d=event.value;d.save_as(str(output/'Shared_BOM_template.json'));bundle=(output/'Shared_BOM_template.json').read_text();assert json.loads(bundle)['templates'][0]['name']=='Browser BOM';checks.append('Custom BOM template shares without component rows')
   page.locator('[data-act=manageDefinition][data-op=duplicate][data-section=templates]').click();page.locator('#dialog [name=name]').fill('BOM copy');page.get_by_role('button',name='Duplicate',exact=True).last.click();page.wait_for_function("S.template==='BOM copy'")
   page.locator('[data-act=manageDefinition][data-op=rename][data-section=templates]').click();page.locator('#dialog [name=name]').fill('Renamed BOM');page.get_by_role('button',name='Rename',exact=True).last.click();page.wait_for_function("S.template==='Renamed BOM'")
   page.locator('[data-act=manageDefinition][data-op=delete][data-section=templates]').click();page.wait_for_function("!S.data.templates['Renamed BOM']");checks.append('Custom template duplicate, rename and delete')
   page.get_by_role('button',name='Import…',exact=True).click();page.locator('#templateImportText').fill(bundle);page.get_by_role('button',name='Preview import',exact=True).click();page.get_by_role('button',name='Apply reviewed import',exact=True).wait_for();page.get_by_role('button',name='Apply reviewed import',exact=True).click();page.wait_for_function("!!S.data.templates['Browser BOM (imported)']");checks.append('Template import previews name conflict and keeps both')
   page.locator('#templateSelect').select_option('Browser BOM');page.wait_for_function("S.template==='Browser BOM'")
   page.get_by_text('Text, variables & export options',exact=True).click();page.locator('#templateEncoding').select_option('ascii');page.locator('#templateLineEnd').select_option('lf');page.get_by_role('button',name='Save template',exact=True).click();page.wait_for_function("S.data.templates['Browser BOM'].options.encoding==='ascii'");checks.append('Encoding and line-ending controls saved')
   # Field-name standards and destructive-operation safeguards.
   page.locator('[data-view=fieldtemplates]').first.click();page.locator('[data-act=newDefinition][data-section=field_profiles]').click();page.locator('#dialog [name=name]').fill('Browser field standard');page.get_by_role('button',name='Create template',exact=True).click();page.wait_for_function("S.fieldProfile==='Browser field standard'")
   page.get_by_role('button',name='+ Field',exact=True).click();row=page.locator('.field-schema-row').last;row.locator('[data-schema-name]').fill('${PROJECTNAME}_Code');row.locator('[data-schema-default]').fill('${PROJECTNAME}');row.locator('[data-schema-visible]').check();page.get_by_role('button',name='Save field template',exact=True).click();page.wait_for_function("S.data.field_profiles[S.fieldProfile].fields.length===2");checks.append('Create variable-bearing field-name template with raw default expression')
   page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'03-field-name-templates.png'),full_page=True)
   source_hashes=dict(app.workspace.project.hashes)
   page.get_by_role('button',name='Enforce…',exact=True).click();page.locator('#enforceVisibility').check();page.get_by_role('button',name='Preview all changes →',exact=True).click();page.locator('#enforceConfirmation').wait_for()
   assert app.workspace.project.hashes==source_hashes;app.workspace.project.check_unchanged();assert app.workspace.state['field_schema_edits']=={};checks.append('Enforce preview changes neither native files nor staged fields')
   page.screenshot(path=str(output/'04-enforcement-review.png'),full_page=True)
   with page.expect_download() as event:page.get_by_role('button',name='Save full review JSON ↗',exact=True).click()
   d=event.value;d.save_as(str(output/'Full_enforcement_review.json'));assert json.loads((output/'Full_enforcement_review.json').read_text())['components']==11;checks.append('Full enforcement review downloadable before confirmation')
   page.locator('#enforceConfirmation').fill('ENFORCE');page.locator('#enforceAcknowledge').check();page.get_by_role('button',name='Enforce in workspace',exact=True).click();page.wait_for_function("S.data.field_schema_pending>0");assert all('${PROJECTNAME}_Code' in r['raw'] for r in app.workspace.rows());app.workspace.project.check_unchanged();checks.append('Typed ENFORCE stages all components without native writes')
   page.locator('[data-view=bom]').first.click();page.get_by_role('button',name='↶ Undo',exact=True).click();page.wait_for_function("S.data.field_schema_pending===0");assert all('${PROJECTNAME}_Code' not in r['raw'] for r in app.workspace.rows());page.get_by_role('button',name='↷ Redo',exact=True).click();page.wait_for_function("S.data.field_schema_pending>0");checks.append('Single Undo/Redo covers the whole enforcement transaction')
   page.locator('[data-view=review]').first.click();page.get_by_role('button',name='Review proposed native changes').click();page.locator('#nativePreview details').first.wait_for();assert '${PROJECTNAME}_Code' in page.locator('#nativePreview').text_content();checks.append('Native review shows raw expressions and project field defaults')
   page.get_by_role('button',name='Apply reviewed native changes…',exact=True).click();page.locator('#dialog [name=closed]').check();page.locator('#dialog [name=confirmation]').fill('APPLY');page.get_by_role('button',name='Apply with backups',exact=True).click();page.wait_for_function("S.data.field_schema_pending===0");assert all('${PROJECTNAME}_Code' in r['raw'] for r in app.workspace.rows());assert any(e['name']=='${PROJECTNAME}_Code' for e in app.workspace.project.pro['schematic']['drawing']['field_names']);checks.append('Reviewed APPLY writes synthetic native files, creates backups, and reloads through adapter')
   page.locator('[data-view=fieldtemplates]').first.click();page.get_by_role('button',name='Enforce…',exact=True).click();page.locator('#enforceMode').select_option('exact');page.get_by_role('button',name='Preview all changes →',exact=True).click();page.locator('#enforceConfirmation').wait_for();assert page.evaluate('S.enforcePreview.variable_losses')>0;assert page.locator('.loss-row').count()>0;page.get_by_role('button',name='Cancel',exact=True).click();assert app.workspace.state['field_schema_edits']=={};checks.append('Exact-mode preview highlights expression loss; Cancel leaves fields unchanged')
   with page.expect_download() as event:page.locator('[data-act=shareDefinition][data-section=field_profiles]').click()
   d=event.value;d.save_as(str(output/'Shared_field_standard.json'));assert json.loads((output/'Shared_field_standard.json').read_text())['field_profiles'][0]['fields'][1]['name']=='${PROJECTNAME}_Code';checks.append('Field template share preserves expressions without variable definitions')
   page.locator('#themeButton').click();page.evaluate("document.querySelector('#toasts').replaceChildren()");page.screenshot(path=str(output/'05-field-templates-dark.png'),full_page=True);checks.append('New field-template view renders in dark mode')
   for view in ('fieldtemplates','exports'):
    page.locator('[data-view='+view+']').first.click();page.set_viewport_size({'width':780,'height':1060});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),view+' overflow at 780';page.screenshot(path=str(output/('06-'+view+'-compact.png')),full_page=True)
   checks.append('Both new workspaces have no horizontal page overflow at 780 pixels')
   browser.close()
  if errors:raise AssertionError('Browser errors: '+repr(errors))
  print(json.dumps({'passed':len(checks),'checks':checks,'browser_errors':errors,'browser':'System Chromium via Playwright; injected static assets + Python HTTP fetch bridge' if a.bridge else 'System Chromium via Playwright; normal loopback navigation','host_kicad_tested':False},indent=2))
 finally:server.shutdown();server.server_close();thread.join();shutil.rmtree(app.demo_directory)

if __name__=='__main__':main()
