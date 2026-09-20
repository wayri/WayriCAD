'use strict';
// Plugin-only alternate selections never become native schematic fields.
const SP={context:null,task:null,candidates:[],component:null};
const sharedAPI=(op,data={})=>api('shared-parts/'+op,{variant:S.variant,...data});
function sharedControl(r){
 const old=Object.values(S.data.engineering?.shared_alternates||{}).find(x=>x.component===r.id&&x.variant===S.variant);
 return `<select data-shared-alt="${esc(r.id)}" aria-label="Alternative for ${esc(r.ref)}"><option value="">${esc(old?.fields?.MPN||'Not selected')}</option><option value="search">Search shared library…</option>${old?'<option value="clear">Clear candidate</option>':''}</select>`;
}
const sharedGrid=gridTable;
gridTable=function(rows,columns,selectable=true){
 const html=sharedGrid(rows,columns,selectable);
 if(S.view!=='bom')return html;
 const t=document.createElement('template');t.innerHTML=html;
 const head=document.createElement('th');head.textContent='Alt (plugin only)';const hr=t.content.querySelector('thead tr');hr?.insertBefore(head,hr.children[2]||null);
 for(const tr of t.content.querySelectorAll('tbody tr[data-row]')){
  const id=tr.dataset.row,r=rows.find(x=>x.id===id);if(!r)continue;
  const td=document.createElement('td');td.innerHTML=sharedControl(r);tr.insertBefore(td,tr.children[2]||null);
 }
 return t.innerHTML;
};
const sharedBOM=renderBOM;
renderBOM=function(){
 const t=document.createElement('template');t.innerHTML=sharedBOM();
 const groups=t.content.querySelectorAll('tr.group-row');
 if(groups.length){
  const hr=groups[0].closest('table').querySelector('thead tr'),th=document.createElement('th');th.textContent='Alt (plugin only)';hr.insertBefore(th,hr.children[2]||null);
  for(const tr of groups){
   const group=groupById(tr.querySelector('[data-group]').dataset.group),td=document.createElement('td');
   const selected=Object.values(S.data.engineering?.shared_alternates||{}).filter(x=>x.variant===S.variant&&group.rows.some(r=>r.id===x.component));
   td.innerHTML=`<select data-shared-group aria-label="Alternatives for ${esc(group.rows.map(r=>r.ref).join(', '))}"><option value="">${selected.length?selected.length+' candidate(s) recorded':'Choose a part…'}</option>${group.rows.map(r=>`<option value="${esc(r.id)}">${esc(r.ref)} — ${esc(selected.find(x=>x.component===r.id)?.fields.MPN||'find alternatives')}</option>`).join('')}</select>`;tr.insertBefore(td,tr.children[2]||null);
  }
  for(const tr of t.content.querySelectorAll('tr.group-child')){
   const id=tr.querySelector('[data-id]')?.dataset.id,r=S.data.rows.find(x=>x.id===id);if(!r)continue;
   const td=document.createElement('td');td.innerHTML=sharedControl(r);tr.insertBefore(td,tr.children[2]||null);
  }
 }
 return `<div class="toolbar"><button data-act="sharedLibrary" class="small">Shared parts library</button><span class="fine">Reuse parts, native assets and templates across projects.</span></div>`+t.innerHTML;
};
document.addEventListener('change',e=>{
 if(e.target.dataset.sharedAlt&&e.target.value==='clear'){const component=e.target.dataset.sharedAlt;sharedAPI('clear',{component}).then(refresh).catch(x=>toast(x.message,true));}
 if(e.target.hasAttribute('data-shared-group')&&e.target.value){const id=e.target.value;e.target.value='';sharedAlternates(id).catch(x=>toast(x.message,true));}
 if(e.target.dataset.sharedAlt&&e.target.value==='search'){
  const id=e.target.dataset.sharedAlt;e.target.value='';sharedAlternates(id).catch(x=>toast(x.message,true));
 }
 if(e.target.id==='sharedCandidate')sharedCandidateDetails();
});
handlers.sharedLibrary=async()=>{
 SP.context=await sharedAPI('context');const c=SP.context;
 showDialog('Shared parts library',`<p>Parts and captured assets live outside projects and plugin updates. The chosen library is remembered for future projects.</p>${field6('Library folder','sharedPath',c.library||c.default_destination)}<div class="toolbar">${button6('sharedAttach','Use existing library')}${button6('sharedCreate','Create this library')}</div><hr><p><b>1. Save reusable information</b></p><div class="toolbar">${button6('sharedCapture','Review project parts + assets')}${button6('sharedTemplatesSave','Save templates')}${button6('sharedTemplatesLoad','Load saved templates')}</div><p class="fine">Save the workspace before capturing. Existing identities are merged with provenance; conflicting observations remain visible in Library & control.</p><p><b>2. Use assets in KiCad</b></p><p class="fine">Publish a native snapshot and register it globally. Missing or ambiguous assets must be resolved first. Symbols and footprints use manufacturer/MPN names; identical model bytes share one stored asset.</p>${field6('KiCad configuration folder','sharedConfig',c.config)}${field6('Global library nickname','sharedNickname','WayriCADParts')}${button6('sharedNativePreview','Review global registration')}<div id="sharedProgress" role="status"></div>`);
};
const sharedPath=()=>document.querySelector('[name="sharedPath"]').value.trim();
handlers.sharedAttach=async()=>{await sharedAPI('open',{path:sharedPath()});await refresh();toast('Shared library remembered.');await handlers.sharedLibrary();};
handlers.sharedCreate=async()=>{const path=sharedPath();showDialog('Create shared library',`<p>Create a new catalogue at <code>${esc(path)}</code>. Existing libraries are never overwritten.</p>${field6('Type CREATE','confirmation')}${formActions('Create library')}`,async f=>{await sharedAPI('open',{path,create:true,confirmation:f.get('confirmation')});await refresh();toast('Shared catalogue created. Save project parts next.');});};
handlers.sharedCapture=async()=>{
 const task=await sharedAPI('harvest-start');SP.task=task.id;
 const poll=async()=>{try{
  const t=await api('engineering/task-status',{id:task.id});
  const box=$('#sharedProgress');if(box)box.textContent=t.message;
  if(t.state==='running'){setTimeout(poll,600);return;}
  if(t.state!=='ready')throw Error(t.message);
  showDialog('Review captured project parts',`<p>The following captures are observations, not approved substitutes. Missing geometry remains explicit.</p>${json6(t.summary)}${field6('Type IMPORT to merge into the shared catalogue','confirmation')}${formActions('Save parts and assets')}`,async f=>{
   await api('engineering/harvest-import',{task_id:task.id,confirmation:f.get('confirmation'),actor:'Local user'});toast('Parts and assets saved without duplicate identities.');
  });
 }catch(e){toast(e.message,true);}};await poll();
};
handlers.sharedTemplatesSave=async()=>{await sharedAPI('templates-save');toast('Reusable template bundle saved in the shared catalogue.');};
handlers.sharedTemplatesLoad=async()=>{
 const r=await sharedAPI('templates-list');if(!r.items.length)throw Error('No templates saved in this library yet.');
 showDialog('Load shared templates',`<p>Conflicting local names are retained; imported definitions receive a separate name.</p><label class="field">Bundle<select name="key">${r.items.map(x=>`<option value="${esc(x.key)}">${esc(x.templates.join(', '))} · ${esc(x.key.slice(-8))}</option>`).join('')}</select></label>${formActions('Load templates')}`,async f=>{await sharedAPI('templates-load',{key:f.get('key')});await refresh();});
};
handlers.sharedNativePreview=async()=>{
 const config=document.querySelector('[name="sharedConfig"]').value,name=document.querySelector('[name="sharedNickname"]').value;
 const p=await sharedAPI('native-preview',{config,name});
 showDialog('Review global KiCad registration',`<p>${esc(p.notice)}</p><p>${p.parts} parts → <code>${esc(p.destination)}</code></p>${json6({tables:p.tables,metadata_observations:p.observations})}${field6('Close library managers, then type REGISTER','confirmation')}${formActions('Register symbols and footprints')}`,async f=>{const r=await sharedAPI('native-apply',{confirmation:f.get('confirmation')});toast(r.restart);});
};
async function sharedAlternates(component){
 SP.component=component;const r=S.data.rows.find(x=>x.id===component);SP.candidates=[];
 showDialog('Alternatives for '+r.ref,`<p>${esc(r.fields.Value)} · ${esc(r.fields.Footprint)}. Text matches do not establish electrical or pin compatibility.</p><div class="toolbar"><input id="sharedQuery" type="search" aria-label="Search shared parts" placeholder="STM32, resistor, capacitor X7R…"><label><input id="sharedRegex" type="checkbox"> Bounded regex</label>${button6('sharedSearch','Search')}</div><p class="fine">Regex: anchors, character classes, | and one quantifier per alternative. Example ^STM32.*</p><label class="field">Candidate<select id="sharedCandidate"><option>No search yet</option></select></label><div id="sharedDifferences" aria-live="polite"></div>${field6('Engineering review note','sharedNote')}${button6('sharedChoose','Record candidate (plugin only)')}`);
 await handlers.sharedSearch();
}
handlers.sharedSearch=async()=>{
 const component=SP.component, query=$('#sharedQuery').value,regex=$('#sharedRegex').checked;
 const r=await sharedAPI('suggest',{component,query,regex});
 if(component!==SP.component||!$('#sharedCandidate')||query!==$('#sharedQuery').value||regex!==$('#sharedRegex').checked)return;
 SP.candidates=r.items;$('#sharedCandidate').innerHTML=r.items.length?r.items.map((x,i)=>`<option value="${i}">${esc(x.fields.Manufacturer)} ${esc(x.fields.MPN||x.fields.Value)} · ${esc(x.fields.Footprint)}</option>`).join(''):'<option value="">No matches</option>';
 sharedCandidateDetails();if(r.scan_limited)toast('Only the first 5,000 catalogue records were scanned; use the full catalogue finder for larger libraries.',true);
};
function sharedCandidateDetails(){const x=SP.candidates[Number($('#sharedCandidate').value)];$('#sharedDifferences').innerHTML=x?`<p><b>Matching:</b> ${esc(x.matches.join(', ')||'None')}<br><b>Unknown:</b> ${esc(x.unknown.join(', ')||'None')}</p>${table6(['Field','Project','Candidate'],x.differences.map(d=>`<tr><td>${esc(d.field)}</td><td>${esc(d.project)}</td><td>${esc(d.candidate)}</td></tr>`))}<p>${esc(x.qualification)}</p>`:'<p>No candidates. Save parts to the shared library or broaden the search.</p>';}
handlers.sharedChoose=async()=>{const x=SP.candidates[Number($('#sharedCandidate').value)];if(!x)throw Error('Choose a candidate first.');await sharedAPI('choose',{component:SP.component,id:x.id,revision:x.revision,note:document.querySelector('[name="sharedNote"]').value});$('#dialog').close();await refresh();toast('Candidate recorded. Native part and BOM export remain unchanged. Save workspace to retain it.');};
if(S.data?.project)render();
