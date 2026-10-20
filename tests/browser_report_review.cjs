/* Real Chromium acceptance for generated offline PI/SI/Therm reports.
 * Run after generating fixtures; REPORT_REVIEW_DIR points to that directory.
 * Uses an existing Playwright/Chrome installation; installs nothing.
 */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require('playwright');
(async()=>{
 const directory=path.resolve(process.env.REPORT_REVIEW_DIR||'.validation/report-review');
 const browser=await chromium.launch({headless:true,channel:process.env.REPORT_BROWSER_CHANNEL||'chrome'});
 const page=await browser.newPage({viewport:{width:1024,height:720}});
 const errors=[];page.on('pageerror',error=>errors.push(String(error)));
 try {
  for(const name of ['pi','thermal','si','si-study','pi-batch']) {
   await page.goto(pathToFileURL(path.join(directory,name+'.html')).href);
   await page.locator('.report-nav a').first().waitFor();
   assert.equal(await page.locator('.report-summary').count(),1,name);
   assert(await page.locator('.report-summary').innerText(),name);
   const width=await page.evaluate(()=>document.documentElement.scrollWidth);
   assert(width<=1026,name+': page overflow '+width);
   await page.screenshot({path:path.join(directory,name+'-review.png'),fullPage:false});
   assert.equal(errors.length,0,errors.join('\n'));
  }
  await page.goto(pathToFileURL(path.join(directory,'si.html')).href);
  const table=page.locator('.report-table').filter({has:page.getByRole('button',{name:'Length mm',exact:true})});
  const search=table.locator('xpath=preceding-sibling::div[1]').locator('input[type=search]');
  await search.fill('via');assert.equal(await table.locator('tr:visible').count(),2);
  await search.fill('no such section');assert.equal(await table.locator('tr:visible').count(),1);
  await search.fill('');await table.getByRole('button',{name:'Length mm',exact:true}).click();
  assert.equal(await table.locator('tr').nth(1).locator('td').nth(1).textContent(),'1.6');
  await table.getByRole('button',{name:'Length mm',exact:true}).click();
  assert.equal(await table.locator('tr').nth(1).locator('td').nth(1).textContent(),'20');
  await search.fill('via');
  await page.emulateMedia({media:'print'});
  assert.equal(await table.locator('tr:visible').count(),4,'print retains filtered rows');
  await page.emulateMedia({media:'screen'});
  await page.goto(pathToFileURL(path.join(directory,'thermal.html')).href);
  assert.equal(await page.locator('#thermal-part-table .report-sort').count(),0,'existing board sorter is preserved');
  await page.locator('#thermal-part-table tbody tr').filter({hasText:'U1'}).click();
  assert.equal(await page.locator('#thermal-part-table tbody tr.selected').count(),1,'cross-selection survives wrapper');
  await page.goto(pathToFileURL(path.join(directory,'pi-batch.html')).href);
  const relative=await page.locator('a[href$="electrical.html"]').getAttribute('href');
  assert(fs.existsSync(path.resolve(directory,decodeURIComponent(relative))));
  await page.locator('a[href$="electrical.html"]').click();
  assert.equal(await page.locator('.report-summary').count(),1,'linked case report opens');
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('5 reports rendered at1024x720; table filtering/numeric sorting/printing, thermal cross-selection and case links passed.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
