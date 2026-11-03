/* Offline Chromium check of compressed PI fields and differential probes. */
'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require('playwright');
(async()=>{
 const file=path.resolve(process.argv[2]);
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const page=await browser.newPage({viewport:{width:1200,height:850}});
 const errors=[],network=[];
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
 try {
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(()=>[...document.querySelectorAll('figure.interactive-analysis canvas')].length===3 &&
   [...document.querySelectorAll('figure.interactive-analysis canvas')].every(c=>typeof c.onpointermove==='function'),{timeout:30000});
  await page.waitForFunction(()=>document.querySelector('.diff-readout').textContent.includes('A:'),{timeout:30000});
  assert.equal(await page.locator('img[src^="data:image/png"]').count(),8);
  const field=page.locator('figure.interactive-analysis').first();
  const canvas=field.locator('canvas');await canvas.scrollIntoViewIfNeeded();
  await field.getByRole('button',{name:'Fit',exact:true}).click();
  assert.equal(errors.length,0,errors.join('\n'));assert.deepEqual(network,[]);
  await page.screenshot({path:path.join(path.dirname(file),'compact-browser.png')});
  console.log('Offline gzip decoding, 3 interactive fields, differential probe, 8 images, Fit and no external requests passed');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
