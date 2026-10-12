/* Browser regression for the shipped Constraint Studio UI.
 * Generate SNAPSHOT_JSON with studio_model.snapshot/inspect_scope on the public
 * workflow_demo fixture. Requires Playwright; BROWSER_EXECUTABLE is optional.
 * The bridge is simulated here; native model/transaction tests run separately. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require('playwright');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(process.env.SNAPSHOT_JSON,'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
 try {
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(data=>{
   window.bridgeCalls=[];
   window.wayricad={postMessage(raw){const m=JSON.parse(raw);window.bridgeCalls.push(m);
     const value=m.method==='snapshot'?data.snapshot:m.method==='inspect'?data.inspection[String(m.args.rule)]:m.method==='review'?{diff:'',rules:''}:null;
     setTimeout(()=>window.studio.receive(m.id,{ok:true,value}),0);
   }};
 },fixture);
 await page.goto(pathToFileURL(path.resolve(__dirname,'../web/index.html')).href);
 await page.evaluate(()=>window.studio.connect());
 for(const panel of ['filters','board','details'])assert.equal(await page.locator('#workspace-'+panel).isVisible(),false);
 assert.equal(await page.evaluate(()=>window.bridgeCalls.filter(c=>c.method==='inspect').length),0);
 const initialWidth=await page.locator('.worksheet-main').evaluate(el=>el.clientWidth);
 await page.locator('[data-panel="board"]').click();
 await page.waitForFunction(()=>pending.size===0);
 assert(await page.locator('#board-map').isVisible());
 assert(await page.locator('#board-map .item').count()>0);
 await page.locator('[data-panel="details"]').click();
 await page.locator('tr[data-rule="0"]').first().click();
 await page.waitForFunction(()=>pending.size===0);
 assert(await page.locator('.constraint-visual svg').isVisible());
 await page.locator('[data-detail="priority"] summary').click();
 await page.locator('#object-a').selectOption('0');
 await page.waitForFunction(()=>pending.size===0);
 assert.equal(await page.locator('[data-detail="priority"]').getAttribute('open'),'');
 await page.locator('[data-panel="filters"]').click();
 assert(await page.locator('#workspace-filters').isVisible());
 assert(await page.locator('.worksheet-main').evaluate(el=>el.clientWidth)<initialWidth);
 await page.locator('#workspace-filters summary').filter({hasText:'Netclasses'}).click();
 await page.locator('[data-scope="netclass"]').first().click();
 await page.locator('[data-panel="filters"]').click();
 assert(await page.getByRole('button',{name:/Clear filter:/}).isVisible());
 await page.getByRole('button',{name:/Clear filter:/}).click();
 for(const panel of ['board','details'])await page.locator('[data-panel="'+panel+'"]').click();
 await page.locator('[data-action="edit-rule"]').first().click();
 assert(await page.locator('#dialog[open]').isVisible());
 await page.locator('#cancel-dialog').click();
 await page.locator('#search').fill('no_such_rule');
 assert.equal(await page.locator('tr[data-rule]').count(),0);
 await page.locator('#search').fill('');
 if(process.env.SCREENSHOT_DIR){fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'constraint-clean.png')});}
 await page.locator('[data-panel="board"]').click();await page.locator('[data-panel="details"]').click();
 await page.waitForFunction(()=>pending.size===0);
 if(process.env.SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'constraint-panels.png'),fullPage:true});
 await page.locator('[data-action="theme"]').click();
 if(process.env.SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'constraint-dark.png'),fullPage:true});
 for(const width of [1100,900,650]){
   await page.setViewportSize({width,height:1000});
   assert(await page.locator('[data-panel="board"]').isVisible());
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'Horizontal overflow at '+width);
 }
 await page.setViewportSize({width:1600,height:1100});
 await page.locator('.nav[data-view="routing"]').click();
 const geometry=await page.evaluate(()=>({small:routingPreviewGeometry({signal_layer:'F.Cu',width:'.01',gap:'.02'},'differential','pair',60),missing:routingPreviewGeometry({signal_layer:'B.Cu',width:'.3',gap:''},'differential','pair',60)}));
 assert(geometry.small.includes('height="0.60"'));assert(geometry.small.includes('gap .02 mm'));
 assert(geometry.missing.includes('Enter a positive pair gap'));

 assert.equal(await page.locator('#routing-comparison').getAttribute('open'),null);
 assert.equal(await page.locator('#routing-saved').getAttribute('open'),null);
 await page.locator('#routing-comparison>summary').click();
 assert(await page.locator('.routing-preview-panel').isVisible());
 await page.locator('[data-routing="type"]').selectOption('single');
 assert.equal(await page.locator('#routing-comparison').getAttribute('open'),'');
 await page.locator('.nav[data-view="workspace"]').click();
 assert(await page.locator('#workspace-board').isVisible());
 assert.deepEqual(errors,[]);
 console.log('Panels, hidden inspection, filter clearing, edit dialog, search, geometry, themes, responsive layouts and routing folds passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

