/* Optional UI smoke: NODE_PATH=<Playwright modules> node tests/browser_component_analytics.cjs
 * Set BROWSER_EXECUTABLE if Playwright Chromium is not installed; SCREENSHOT is optional.
 * All project data lives in the application's disposable demo directory. */
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {createInterface}=require('node:readline');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const python=spawn(process.env.PYTHON||'python',['-B','-u','-c',`
from bomstudio.server import Application, Server
from bomstudio.native import BASE
import threading, sys, shutil
app=Application(demo=True)
for row in app.workspace.rows():
    ref=row['ref'];kind='Resistor' if ref.startswith('R') else 'Capacitor' if ref.startswith('C') else 'IC' if ref.startswith('U') else 'Other'
    app.workspace.edit([row['id']],BASE,{'UnitPrice':'2','Mass':'100mg','Dissipation':'250mW','ComponentType':kind})
server=Server(app)
threading.Thread(target=server.serve_forever,daemon=True).start()
print(server.url,flush=True)
try:sys.stdin.readline()
finally:
    server.shutdown();server.server_close();app.link.close()
    if app.demo_directory:shutil.rmtree(app.demo_directory)
`],{cwd:require('node:path').resolve(__dirname,'..'),stdio:['pipe','pipe','inherit']});
const exited=once(python,'exit');
(async()=>{
 let browser;
 try {
  const lines=createInterface({input:python.stdout});
  const [url]=await Promise.race([once(lines,'line'),exited.then(()=>{throw Error('Demo server exited before URL')})]);
  browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(url);await page.getByRole('heading',{name:'BOM workspace',exact:true}).waitFor();
  await page.locator('[data-view=analytics]:visible').first().click();
  await page.locator('[data-act=analyticsRun]').click();
  await page.waitForFunction(()=>S.analytics5.report!==null);
  await page.locator('[data-tab=families]').click();
  assert(await page.getByRole('heading',{name:'Passive, active and other parts'}).isVisible());
  assert(await page.locator('svg[aria-label*=histogram]').count()>0);
  assert(!(await page.locator('#main').innerText()).includes('undefined'));
  const report=await page.evaluate(()=>S.analytics5.report);
  assert(report.component_analysis.groups.some(g=>g.label==='RLC combined'));
  assert.equal(report.component_analysis.geometry_source.status,'unavailable');
  await page.locator('#analyticsFormat').selectOption('csv');
  await page.locator('#analyticsTable').selectOption('families');
  const downloaded=page.waitForEvent('download');await page.locator('[data-act=analyticsExport]').click();
  const download=await downloaded;assert.equal(await download.failure(),null);
  if(process.env.SCREENSHOT){
   await page.evaluate(()=>document.querySelector('#toasts').replaceChildren());
   await page.getByRole('heading',{name:'Passive, active and other parts'}).scrollIntoViewIfNeeded();
   await page.screenshot({path:process.env.SCREENSHOT});
  }
  await page.locator('#themeButton').click();
  await page.setViewportSize({width:780,height:1000});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.deepEqual(errors,[]);
  console.log('PASS: family UI, histogram rendering, unknown geometry, CSV download, dark/compact layout, no JS errors');
 } finally {
  if(browser)await browser.close();python.stdin.end('\n');await exited;
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
