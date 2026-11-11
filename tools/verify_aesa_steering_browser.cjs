const fs=require('fs');
const path=require('path');
const crypto=require('crypto');
const {pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright',{paths:[process.argv[2]]}));
(async()=>{
  const root=path.resolve(__dirname,'..');
  const out=path.join(root,'.validation','aesa-browser');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[],remote=[];page.on('pageerror',e=>errors.push(String(e)));
    page.on('request',r=>{if(/^https?:/.test(r.url()))remote.push(r.url());});
    await page.goto(pathToFileURL(path.join(root,'examples/quick_emerge/research_antennas/images/aesa-vnext/interactive-steering.html')).href);
    await page.waitForFunction(()=>window.currentAesaState==='uniform-30');
    const states=[];
    for(const taper of ['uniform','binomial'])for(const theta of ['0','30','60']){
      await page.selectOption('#taper',taper);await page.selectOption('#steering',theta);
      await page.waitForFunction(key=>window.currentAesaState===key,taper+'-'+theta);
      const state=await page.locator('#lobes').evaluate(n=>({samples:n.data[1].x.length,axes:n._fullLayout.scene.xaxis.title.text,sum:n.data[0].x.flat().reduce((a,v)=>a+v,0)}));
      if(state.samples!==16471||!state.axes.includes('relative'))throw Error('Missing original sphere or scales: '+JSON.stringify(state));
      states.push({taper,theta,...state});
      await page.evaluate(()=>scrollTo(0,0));
      await page.screenshot({path:path.join(out,taper+'-'+theta+'.png'),fullPage:true});
    }
    if(states[0].sum===states[1].sum||states[1].sum===states[4].sum)throw Error('Beam states did not change');
    await page.selectOption('#taper','uniform');await page.selectOption('#steering','30');
    await page.waitForFunction(()=>window.currentAesaState==='uniform-30');
    await page.locator('#lobes').evaluate(n=>n.on('plotly_hover',e=>{window.aesaProbe=e.points[0].customdata;}));
    await page.locator('#lobes').scrollIntoViewIfNeeded();
    const bounds=await page.locator('#lobes').boundingBox();
    for(const x of [.5,.45,.55,.4,.6,.35,.65]){for(const y of [.5,.4,.6,.3,.7]){
      await page.mouse.move(bounds.x+bounds.width*x,bounds.y+bounds.height*y);await page.waitForTimeout(350);
      if(await page.evaluate(()=>!!window.aesaProbe))break;
    }if(await page.evaluate(()=>!!window.aesaProbe))break;}
    const probe=await page.evaluate(()=>window.aesaProbe);
    if(!probe||probe.length!==4)throw Error('No actual pointer probe of original angular samples');
    await page.click('#animate');await page.waitForFunction(()=>window.currentAesaState!=='uniform-30');
    await page.click('#animate');
    if(await page.locator('#animate').textContent()!=='Play steering')throw Error('Playback did not stop');
    await page.setViewportSize({width:390,height:844});await page.waitForTimeout(700);
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
    if(overflow||errors.length||remote.length)throw Error(JSON.stringify({overflow,errors,remote}));
    const result={states,probe,mobileOverflow:overflow,errors,remote};
    fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
    const gallery=path.join(root,'examples/quick_emerge/research_antennas/images/aesa-vnext');
    const captures=[];
    for(const taper of ['uniform','binomial']){
      const file='viewer-'+taper+'-30.png';const source=path.join(out,taper+'-30.png');
      fs.copyFileSync(source,path.join(gallery,file));
      captures.push({file,sha256:crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex'),steeringThetaDeg:30,taper});
    }
    fs.writeFileSync(path.join(gallery,'screenshot-provenance.json'),JSON.stringify({
      capturedAtUtc:new Date().toISOString(),browser:browser.version(),method:'Actual full-page Edge captures; not mockups',
      htmlSha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(gallery,'interactive-steering.html'))).digest('hex'),
      scope:'Closed-form ideal array factor, not full-wave FEM; no private paths in captures',captures,verification:result},null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
