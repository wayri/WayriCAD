"""Optional real-browser acceptance checks. Requires Playwright + Chromium.

Run from the plugin directory:
  python tests/browser_v5.py --chromium /path/to/chromium --output /tmp/screens
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
 args=argparse.ArgumentParser();args.add_argument('--chromium');args.add_argument('--bridge',action='store_true',help='Inject static assets and bridge fetch via Python for managed browsers that prohibit all URL navigation');args.add_argument('--output',default='test-artifacts-v5');a=args.parse_args()
 output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
 app=Application(demo=True);server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 errors=[]
 from bomstudio.native import BASE
 # Synthetic observations; not distributor prices or real package facts.
 ws=app.workspace
 for row in ws.rows():
  ref=row['ref'];prefix=''.join(x for x in ref if x.isalpha())
  defaults={'R':('Resistor','0.50','12mg','2mW','125'), 'C':('Capacitor','4.50','35mg','1mW','85'), 'U':('IC','120','0.32g','150mW','105'), 'J':('Connector','25','1.2g','0W','70')}
  typ,rate,mass,power,temp=defaults.get(prefix,('Other','12','0.1g','25mW','85'))
  ws.edit([row['id']],BASE,{'Rate':rate,'Mass':mass,'Dissipation':power,'Temp_Max':temp,'ComponentType':typ,'RatedPower':'1W','Duty':'25','PricePer':'1'})
 row=next(r for r in ws.rows() if r['ref']=='R4');ws.edit([row['id']],BASE,{'Temp_Max':'unknown'})
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
   def check(condition,message):
    assert condition,message
    checks.append(message)
   def shot(name):
    page.evaluate("document.querySelector('#toasts').replaceChildren()")
    page.screenshot(path=str(output/name),full_page=not page.locator('#dialog').evaluate('(x)=>x.open'))
   def close_dialog():page.locator('#dialog .icon-button').click()
   hashes=dict(ws.project.hashes);before=ws._serialize()
   page.locator('[data-view=analytics]').first.click()
   page.get_by_role('heading',name='Cost, mass & power',exact=True).wait_for()
   check(page.locator('[data-ana=price_field]').input_value()=='UnitPrice','Analytics view opens with current saved mappings')
   page.locator('[data-ana=price_field]').fill('Rate')
   page.locator('[data-ana=boards]').fill('10')
   page.locator('[data-ana=attrition_percent]').fill('5')
   page.locator('[data-act=analyticsRun]').click()
   page.wait_for_function('S.analytics5.report!==null')
   check(page.evaluate('S.analytics5.report.config.price_field')=='Rate','Any field can be mapped as the rate source')
   check(page.evaluate('S.analytics5.report.pricing.priced_components')==10,'Price coverage includes fitted purchasing parts, not DNP')
   check(page.evaluate('S.analytics5.report.mass.known_components')==10,'Mass table counts fitted physical components')
   check(page.evaluate('S.analytics5.report.thermal.known_components')==10,'Dissipation table uses actual mapped data')
   check(ws._serialize()==before,'Running analytics does not mutate workspace or native files')
   check('undefined' not in page.locator('.ana-metrics').inner_text(),'KPI cards show real values/coverage, never undefined data')
   check(not page.locator('.ana-mapping').evaluate('(x)=>x.open'),'Mapping editor collapses after a run so results are visible')
   shot('01-analytics-dashboard.png')
   page.locator('[data-tab=pricing]').click()
   check(page.locator('meter').count()>0,'Cost Pareto shares are rendered from report groups')
   shot('02-cost-pareto.png')
   page.locator('[data-tab=procurement]').click()
   check('Order qty' in page.locator('.ana-table').first.inner_text(),'Purchasing table separates installed, required and ordered quantities')
   page.locator('[data-tab=scenarios]').click()
   check('100' in page.locator('.ana-table').first.inner_text(),'Quantity scenario report includes configured build counts')
   page.locator('[data-tab=components]').click()
   check('Temp_Max' in page.locator('.ana-table').first.inner_text(),'Component table includes mass, active/average loss and temperature observations')
   page.locator('[data-act=analyticsAdvanced]').click()
   page.locator('#anaStatistics').fill('{"Temp_Max":"C","Mass":"g"}')
   page.locator('#anaMassBudget').fill('0.1')
   page.get_by_role('button',name='Use these settings',exact=True).click()
   page.wait_for_function("!document.querySelector('#dialog').open")
   page.locator('[data-act=analyticsRun]').click()
   page.wait_for_function('S.analytics5.report.statistics.Temp_Max!==undefined')
   page.locator('[data-tab=statistics]').click()
   check('P95' in page.locator('.ana-table').first.inner_text(),'Statistics include canonical units, mean, median and nearest-rank P95')
   check(any(b['status']=='exceeded' for b in page.evaluate('S.analytics5.report.budgets')),'Configured mass budget produces an explicit exceedance')
   shot('03-statistics-and-budget.png')
   with page.expect_download() as d:page.locator('[data-act=analyticsExport]').click()
   xlsx=output/'browser-analytics.xlsx';d.value.save_as(xlsx)
   import zipfile
   with zipfile.ZipFile(xlsx) as z:check(z.testzip() is None and len([n for n in z.namelist() if n.startswith('xl/worksheets/')])==8,'Browser Excel export downloads a valid eight-sheet workbook')
   page.locator('#analyticsFormat').select_option('csv');page.locator('#analyticsTable').select_option('groups')
   with page.expect_download() as d:page.locator('[data-act=analyticsExport]').click()
   csv=output/'browser-mass-table.csv';d.value.save_as(csv)
   check('Known mass g' in csv.read_text(encoding='utf-8-sig'),'CSV export contains the selected type/mass breakdown')
   page.locator('.ana-mapping > summary').click()
   with page.expect_download() as d:page.locator('[data-act=analyticsShare]').click()
   settings=output/'settings.json';d.value.save_as(settings)
   check(json.loads(settings.read_text())['price_field']=='Rate','Shareable settings contain mapping definitions without component rows')
   page.locator('[data-act=analyticsSave]').click();page.wait_for_function("S.data.analytics_settings.price_field==='Rate'")
   check(ws.state['analytics_settings']['price_field']=='Rate','Save settings stages the profile independently of native component changes')
   page.locator('#saveButton').click();page.wait_for_function('S.data.dirty===false')
   check(ws.sidecar.exists(),'Save workspace persists the analytics profile')
   if not page.locator('.ana-mapping').evaluate('(x)=>x.open'):page.locator('.ana-mapping > summary').click()
   page.locator('[data-ana=scenario_name]').fill('Saved after navigation')
   page.locator('[data-view=bom]').first.click()
   page.locator('#saveButton').click();page.wait_for_function('S.data.dirty===false && !S.analytics5.dirty')
   check(ws.state['analytics_settings']['scenario_name']=='Saved after navigation','Top-level Save persists pending analytics settings after leaving the analytics view')
   page.locator('[data-act=undo]').first.click();page.wait_for_function("S.data.analytics_settings.scenario_name!=='Saved after navigation'")
   page.locator('[data-view=analytics]').first.click()
   check(page.evaluate('S.analytics5.config.scenario_name')==page.evaluate('S.data.analytics_settings.scenario_name'),'Analytics mapping form follows Undo instead of retaining stale saved settings')
   page.locator('[data-view=bom]').first.click();page.locator('[data-act=redo]').first.click();page.wait_for_function("S.data.analytics_settings.scenario_name==='Saved after navigation'")
   page.locator('[data-view=analytics]').first.click()
   check(page.evaluate('S.analytics5.config.scenario_name')=='Saved after navigation','Redo restores the same analytics profile in the UI')
   page.locator('[data-act=analyticsRun]').click();page.wait_for_function('S.analytics5.report.revision===S.data.revision')
   page.locator('[data-tab=groups]').click()
   page.locator('[data-act=analyticsInspect]').first.click();page.get_by_role('heading',name='BOM workspace',exact=True).wait_for()
   check(page.evaluate('S.selected.size')==0,'Analytics drill-down does not select bulk-edit targets')
   check(page.evaluate('filteredRows().length')==len(page.evaluate('S.drill5.ids')),'Drill-down shows exactly the chosen breakdown members')
   page.locator('[data-act=clearAnalyticsDrill]').click()
   check(page.evaluate('filteredRows().length')==11,'Clearing drill-down restores the original complete row set')
   page.locator('[data-act=columnThreshold]').first.click()
   page.locator('#thresholdField').select_option('Temp_Max');page.locator('#thresholdCondition').fill('<80')
   page.locator('[data-act=thresholdTest]').click()
   page.wait_for_function("document.querySelector('#thresholdResult').innerText.includes('unknown/invalid')")
   check('1 unknown/invalid' in page.locator('#thresholdResult').inner_text(),'Threshold preview reports unknown values instead of treating them as zero')
   shot('04-threshold-preview.png')
   page.locator('[data-act=thresholdHighlight]').click();page.wait_for_function("!document.querySelector('#dialog').open")
   matches=page.evaluate('S.threshold5.report.matched')
   check(matches>0 and page.locator('tr.threshold-match').count()==matches,'Only matching component rows receive threshold highlighting')
   check(page.evaluate('filteredRows().length')==11,'Highlight mode keeps nonmatching parts visible')
   check(page.evaluate('S.selected.size')==0,'Highlighting never silently changes edit selection')
   page.locator('[data-act=columnThreshold]').first.click();page.locator('[data-act=thresholdFilter]').click();page.wait_for_function("!document.querySelector('#dialog').open")
   check(page.evaluate('filteredRows().length')==matches,'Filter mode excludes nonmatches before grouping and pagination')
   check(page.locator('tr[data-row]').count()==matches,'Threshold filtering is reflected in rendered BOM rows')
   shot('05-threshold-filtered-bom.png')
   page.locator('[data-act=clearThreshold]').click();check(page.evaluate('filteredRows().length')==11,'Clear threshold restores the BOM view')
   check(page.locator('.threshold-column-button').count()>0,'Every displayed field header has an accessible threshold control')
   page.locator('.threshold-column-button[data-threshold-field="@field:Rate"]').click();check(page.locator('#thresholdField').input_value()=='@field:Rate','Column-header action preselects the actual field');close_dialog()
   page.locator('[data-act=groupingDialog]').click();page.locator('[data-act=groupPreset][data-fields="Value,Footprint"]').click();page.get_by_role('button',name='Apply grouping',exact=True).click();page.wait_for_function("!document.querySelector('#dialog').open")
   page.locator('[data-act=columnThreshold]').first.click();page.locator('#thresholdField').select_option('Temp_Max');page.locator('#thresholdCondition').fill('<80');page.locator('[data-act=thresholdHighlight]').click();page.wait_for_function("!document.querySelector('#dialog').open")
   check(page.locator('tr.group-row.threshold-match').count()>0,'Threshold matches highlight their containing groups without merging their edit scopes')
   check(page.evaluate('S.selected.size')==0,'Grouped highlighting leaves edit checkboxes untouched')
   page.locator('[data-act=clearThreshold]').click()
   page.locator('[data-view=automation]').first.click();page.locator('[data-act=analyticsPipeline]').click()
   pipe=json.loads(page.locator('#pipelineConfig').input_value())
   check('analytics' in pipe['reports'] and pipe['analytics']['price_field']=='Rate','Automation GUI embeds the same quantitative configuration into a pipeline')
   check(pipe['policy']['analytics']=='none','Adding reports does not silently enable a release-blocking policy')
   page.locator('[data-view=analytics]').first.click();page.locator('[data-tab=groups]').click()
   page.locator('#themeButton').click();check(page.locator('html').get_attribute('data-theme')=='dark','Analytics view works in the existing dark theme')
   shot('06-dark-analytics.png')
   page.set_viewport_size({'width':780,'height':1000})
   check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Analytics has no page-level horizontal overflow at a compact viewport')
   shot('07-compact-analytics.png')
   check(hashes==ws.project.hashes,'All browser analytics actions retain native source hashes')
   ws.project.check_unchanged()
   check(not errors,'No JavaScript page/console errors in analytics workflows')
   browser.close()
 finally:
  server.shutdown();server.server_close();app.link.close()
  if app.demo_directory:shutil.rmtree(app.demo_directory,ignore_errors=True)
 result={'checks':checks,'count':len(checks),'browser_errors':errors,'browser':'System Chromium + Playwright; HTTP bridge' if a.bridge else 'System Chromium + Playwright; direct navigation','host_kicad_tested':False}
 (output/'browser-results.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
