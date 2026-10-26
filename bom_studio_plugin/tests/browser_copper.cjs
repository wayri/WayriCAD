// Read-only board-only copper UI, actual local HTTP worker and report exports.
const {spawn}=require('node:child_process');const {once}=require('node:events');const {createInterface}=require('node:readline');const assert=require('node:assert/strict');const {chromium}=require('playwright');const path=require('node:path');
(async()=>{
const python=spawn(process.env.PYTHON||'python',['-B','-u','-c',`
from pathlib import Path
import tempfile,threading,sys,time
from bomstudio.server import Application,Server
from bomstudio import copper_jobs
folder=tempfile.TemporaryDirectory();board=Path(folder.name)/'board-only.kicad_pcb'
board.write_text('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 1 "GND") (gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts")) (segment (start 1 1) (end 9 1) (width 1) (layer "F.Cu") (net 1)))')
original=copper_jobs.run
def delayed(path,progress,cancel):
 for i in range(20):
  if cancel():raise InterruptedError()
  time.sleep(.05)
 return original(path,progress,cancel)
copper_jobs.run=delayed
app=Application(board,auto_link=False);server=Server(app);threading.Thread(target=server.serve_forever,daemon=True).start();print(server.url,flush=True)
try:sys.stdin.readline()
finally:server.shutdown();server.server_close();folder.cleanup()
`],{cwd:path.resolve(__dirname,'..'),stdio:['pipe','pipe','inherit']});
let browser;try{
 const url=await new Promise((resolve,reject)=>{const lines=createInterface({input:python.stdout});lines.on('line',line=>{if(line.startsWith('http://'))resolve(line)});python.once('exit',code=>reject(Error('Server exited '+code)));setTimeout(()=>reject(Error('Server readiness timeout')),15000).unref()});
 browser=await chromium.launch({headless:true,channel:process.env.BROWSER_EXECUTABLE?undefined:'msedge',executablePath:process.env.BROWSER_EXECUTABLE});
 const page=await browser.newPage({viewport:{width:1450,height:1000},acceptDownloads:true});const errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto(url);
 await page.getByRole('heading',{name:'Copper & routing',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Analyze copper',exact:true}).isEnabled(),true);
 await page.getByRole('button',{name:'Analyze copper',exact:true}).click();await page.getByText('Saved copper analysis complete; no board changes.',{exact:true}).waitFor({timeout:20000});
 await page.getByRole('heading',{name:'Copper and routing by layer',exact:true}).waitFor();await page.getByRole('heading',{name:'Net copper by layer',exact:true}).waitFor();assert.equal(await page.locator('#saveButton').isDisabled(),true);
 await page.locator('#boardAnalyticsNetSearch').fill('GND');await page.locator('#copperFormat').selectOption('csv');await page.locator('#copperTable').selectOption('net_layers');
 const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'Export report',exact:true}).click();const file=await downloaded;assert.match(file.suggestedFilename(),/-net_layers\.csv$/);
 if(process.env.SCREENSHOT){await page.setViewportSize({width:1450,height:1500});const savedPath=await page.locator('#copperBoardPath').inputValue();await page.evaluate(()=>{for(const toast of document.querySelectorAll('.toast'))toast.style.display='none';document.querySelector('#projectPath').textContent='[local PCB path redacted]';document.querySelector('#copperBoardPath').value='C:/Projects/Example/board-only.kicad_pcb';for(const p of document.querySelectorAll('#main p'))if(p.textContent.includes('source hash'))p.textContent=p.textContent.replace(/^.*? · source hash/,'[local PCB path redacted] · source hash');});await page.getByRole('heading',{name:'Copper & routing',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:process.env.SCREENSHOT,fullPage:false});await page.locator('#copperBoardPath').fill(savedPath);}
 await page.getByRole('button',{name:'Analyze copper',exact:true}).click();await page.getByRole('button',{name:'Cancel',exact:true}).click();await page.getByText('Analysis canceled; no partial result accepted.',{exact:true}).waitFor({timeout:10000});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,board_only:true,actual_geometry:true,exports:true,cancel:true,page_errors:errors}));
}finally{if(browser)await browser.close();python.stdin.end();await once(python,'exit');}
})().catch(error=>{console.error(error);process.exitCode=1;});
