'use strict';
const {JSDOM, VirtualConsole, ResourceLoader} = require(process.env.BOM_STUDIO_JSDOM_PATH);
const assert = require('node:assert/strict');
const url = process.argv[2];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function page(failAsset = '') {
  const errors = [], requests = [], pending = new Set();
  const console = new VirtualConsole();
  console.on('jsdomError', error => errors.push(error.message));
  class Assets extends ResourceLoader {
    fetch(address, options) {
      if (failAsset && new URL(address).pathname === failAsset)
        return Promise.reject(new Error('Simulated local asset failure'));
      return super.fetch(address, options);
    }
  }
  const dom = await JSDOM.fromURL(url, {
    resources: new Assets(), runScripts: 'dangerously', pretendToBeVisual: true,
    virtualConsole: console,
    beforeParse(w) {
      w.fetch = (path, options) => {
        requests.push({path, body: options?.body && JSON.parse(options.body)});
        const task = fetch(new URL(path, url), options);
        pending.add(task);
        task.finally(() => pending.delete(task));
        return task;
      };
      w.structuredClone = structuredClone;
      w.confirm = () => true;
      w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
      w.HTMLDialogElement.prototype.close = function () { this.open = false; };
    },
  });
  await new Promise(resolve => {
    if (dom.window.document.readyState === 'complete') resolve();
    else dom.window.addEventListener('load', resolve, {once: true});
  });
  return {dom, errors, requests, async close() {
    // Complete in-flight view requests before disposing the simulated document.
    await Promise.allSettled([...pending]);
    await pause(20);
    dom.window.close();
  }};
}

(async () => {
  const p = await page();
  const w = p.dom.window, doc = w.document;
  try {
    for (let n = 0; n < 100 && !w.eval('S.data?.project'); n++) await pause(50);
    assert.ok(w.eval('S.data?.project'), 'Workspace loaded from the real local API');
    assert.deepEqual(p.errors, [], 'Every shipped script must load');
    for (const button of [...doc.querySelectorAll('#navigation [data-view]')]) {
      button.click();
      const expected = w.eval(`titles[${JSON.stringify(button.dataset.view)}][0]`);
      assert.equal(doc.querySelector('h1').textContent, expected, button.dataset.view);
    }
    // Real variant edit: preview and downloaded CSV must describe the same data.
    await w.eval(`api('variant/add',{name:'FrontendTest',parent:BASE,description:'Synthetic test'})`);
    await w.eval(`switchVariant('FrontendTest')`);
    await w.eval(`api('edit',{variant:S.variant,ids:[S.data.rows.find(r=>r.ref==='R1').id],changes:{Value:'variant-only-edit',UnitPrice:'2',Currency:'USD',Mass:'100 mg',Dissipation:'250 mW'}})`);
    await w.eval('refresh()');
    w.eval(`S.view='exports';render()`);
    await w.eval('handlers.quickPreview()');
    assert.ok(doc.querySelector('#quickRows').textContent.includes('variant-only-edit'));
    const preview = p.requests.findLast(r => r.path === '/api/simple-export/preview');
    assert.equal(preview.body.variant, 'FrontendTest');
    const exported = await w.eval(`fetch('/api/simple-export/download',{method:'POST',headers:{'X-Bom-Token':token,'Content-Type':'application/json'},body:JSON.stringify({variant:S.variant,options:quickExport,format:'csv',draft:true})}).then(r=>r.text())`);
    assert.ok(exported.includes('variant-only-edit'));
    w.eval(`S.view='analytics';render()`);
    await w.eval('handlers.analyticsRun()');
    assert.equal(w.eval('S.analytics5.report.variant'), 'FrontendTest');
    const part = w.eval('S.analytics5.report.components.find(p=>p.reference==="R1")');
    assert.equal(Number(part.cost.unit_price), 2);
    assert.equal(part.cost.currency, 'USD');
    assert.equal(Number(part.mass.value), 0.1); // 100 mg in report grams
    assert.equal(Number(part.power.value), 0.25); // 250 mW in report watts
    await w.eval(`api('save',{})`);
    await w.eval(`api('reload',{discard:true,variant:S.variant})`);
    await w.eval('refresh()');
    assert.equal(w.eval(`S.data.rows.find(r=>r.ref==='R1').fields.Value`), 'variant-only-edit');

    // Enter six mass/rate cells through the real inline editor. Calculation
    // must review them instead of quietly using the prior zero server values.
    await w.eval(`api('edit',{variant:S.variant,ids:S.data.rows.map(r=>r.id),changes:{in_bom:false,on_board:false}})`);
    await w.eval(`api('edit',{variant:S.variant,ids:S.data.rows.filter(r=>['R1','R2','R3'].includes(r.ref)).map(r=>r.id),changes:{in_bom:true,on_board:true,dnp:false,MassInput:'0',Rate:'0',PackQty:'100',PayCurrency:'USD',UnitPrice:'999'}})`);
    await w.eval(`api('analytics/settings',{settings:{price_field:'Rate',price_per_field:'PackQty',currency_field:'PayCurrency',mass_field:'MassInput',mass_unit:'g',boards:3,attrition_percent:'10',physical_include_bom_excluded:false,metrics:['pricing','mass']}})`);
    await w.eval(`api('grouping/settings',{fields:[],raw:false})`);
    await w.eval('refresh()');
    w.eval(`S.view='bom';S.columns=['@field:Reference','@field:MassInput','@field:Rate'];render()`);
    for (const [ref, mass, rate] of [['R1','100 mg','200'],['R2','0.1 g','200'],['R3','0.002 kg','500']]) {
      const id = w.eval(`S.data.rows.find(r=>r.ref===${JSON.stringify(ref)}).id`);
      for (const [field, value] of [['MassInput',mass],['Rate',rate]]) {
        const cell = [...doc.querySelectorAll('td.live-cell')].find(c=>c.dataset.id===id && c.dataset.field==='@field:'+field);
        assert.ok(cell, 'Inline edit cell for '+ref+' '+field);
        cell.dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
        const input=cell.querySelector('input');assert.ok(input);
        input.value=value;
        input.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
      }
    }
    assert.equal(w.eval('pendingGridCount()'),6);
    w.eval(`S.view='analytics';render()`);
    const priorRuns=p.requests.filter(r=>r.path==='/api/analytics/run').length;
    await w.eval('handlers.analyticsRun()');
    assert.equal(p.requests.filter(r=>r.path==='/api/analytics/run').length,priorRuns);
    assert.match(doc.querySelector('#dialogForm button[type=submit]').textContent,/Stage edits and calculate/);
    doc.querySelector('#dialogForm [name=confirmation]').value='EDIT';
    doc.querySelector('#dialogForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
    for(let n=0;n<200;n++) {
      if(w.eval('S.gridDraft.size===0 && S.analytics5.report?.pricing?.currencies?.USD?.known_cost_per_board==="9"'))break;
      await pause(25);
    }
    assert.equal(w.eval('S.gridDraft.size'),0);
    assert.equal(w.eval('S.analytics5.report.mass.known_per_board'),'2.2');
    assert.equal(w.eval('S.analytics5.report.mass.known_build_total'),'6.6');
    assert.equal(w.eval('S.analytics5.report.pricing.currencies.USD.known_cost_per_board'),'9');
    assert.equal(w.eval('S.analytics5.report.pricing.currencies.USD.known_build_cost'),'27');
    assert.equal(w.eval('S.data.stats.cost.USD'),'9');
    w.eval(`S.view='exports';render()`);
    await w.eval('handlers.quickPreview()');
    assert.match(doc.querySelector('#quickRows').textContent,/USD.*9/);
    assert.match(doc.querySelector('#quickRows').textContent,/rounded per export line/);
    // Whole-variant sum must ignore a narrow presentation filter and an old
    // analytics query; repeated MPN+value retains quantity and summed mass/cost.
    await w.eval(`api('edit',{variant:S.variant,ids:S.data.rows.filter(r=>['R1','R2'].includes(r.ref)).map(r=>r.id),changes:{MPN:'SYNTH-PAIR',Value:'10k',Manufacturer:'Synthetic',Footprint:'Synthetic:0603'}})`);
    await w.eval(`api('grouping/settings',{fields:['MPN','Value'],raw:false})`);
    await w.eval('refresh()');
    w.eval(`S.view='bom';S.search='R1';config5().query='Reference=R1';S.analytics5.dirty=true;render()`);
    assert.ok(doc.querySelector('[data-act="analyticsAll"]'));
    await w.eval('handlers.analyticsAll()');
    assert.equal(w.eval('S.analytics5.report.config.query'),'');
    assert.equal(w.eval('S.analytics5.report.mass.known_per_board'),'2.2');
    assert.equal(w.eval('S.analytics5.report.pricing.currencies.USD.known_cost_per_board'),'9');
    const pair=w.eval(`S.analytics5.report.consolidated.find(g=>g.references.includes('R1'))`);
    assert.deepEqual(Array.from(pair.references),['R1','R2']);
    assert.equal(pair.components,2);
    assert.equal(Number(pair.mass_per_board),0.2);
    assert.equal(Number(pair.cost_per_board.USD),4);
    assert.match(doc.querySelector('#main').textContent,/Sum across all/);
    assert.match(doc.querySelector('#main').textContent,/whole active variant/);
    const csv=await w.eval(`fetch('/api/analytics/export',{method:'POST',headers:{'X-Bom-Token':token,'Content-Type':'application/json'},body:JSON.stringify({variant:S.variant,config:config5(),format:'csv',table:'consolidated'})}).then(r=>{if(!r.ok)throw Error(r.status);return r.text()})`);
    assert.match(csv,/SYNTH-PAIR/);
    assert.match(csv,/R1, R2/);
    assert.match(csv,/Known mass g/);
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); }

  const failed = await page('/assemblers.js');
  try {
    const doc = failed.dom.window.document;
    assert.match(doc.querySelector('h1').textContent, /could not load its interface/);
    assert.ok(doc.querySelector('#main').textContent.includes('assemblers.js'));
    assert.ok(doc.querySelector('#retryInterface'));
    assert.ok([...doc.querySelectorAll('#navigation button')].every(b => b.disabled));
    assert.equal(failed.requests.length, 0, 'Incomplete UI cannot start project work');
  } finally { await failed.close(); }
  console.log('Frontend acceptance passed: assets, 17 views, variant edit/preview/CSV, analytics, save/reload, failed-asset recovery.');
})().catch(error => { console.error(error); process.exitCode = 1; });
