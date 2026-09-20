'use strict';
/* v0.4: shared query DSL, reviewed bulk recipes and opt-in selection-only IPC.
   Live highlights NEVER implicitly become the bulk-edit selection. */
Object.assign(titles,{automation:['Automation & live linking','Repeatable releases, reviewable changes and explicit host capabilities.']});
Object.assign(S,{advanced:{query:'',case_sensitive:false,ids:null,context:'',error:''},filterBypass:false,
 link:{connected:false,ids:[]},linkPreferences:{send:true,follow:true,focus:false},linkBusy:false,linkSequence:null,linkPending:false,
 bulkOperations:[{op:'set',field:'Value',value:''}],bulkScope:'selected',pipeline:null});
const context4=()=>JSON.stringify([S.data?.project?.path||S.data?.project?.root,S.data?.project?.name,S.variant,S.data?.revision]);
const quoteQuery4=v=>JSON.stringify(String(v));
const beforeFiltered4=filteredRows;
filteredRows=function(){
 if(S.filterBypass)return [...S.data.rows].sort((a,b)=>String(a.fields[S.sort]??'').localeCompare(String(b.fields[S.sort]??''),undefined,{numeric:true})*(S.asc?1:-1));
 let rows=beforeFiltered4();
 if(S.advanced.query){if(S.advanced.context!==context4()||S.advanced.error||!S.advanced.ids)return [];rows=rows.filter(r=>S.advanced.ids.has(r.id));}
 return rows;
};
async function evaluateAdvanced4(){
 if(!S.advanced.query||!S.data?.project){S.advanced.ids=null;S.advanced.context=context4();return;}
 const context=context4(),request={variant:S.variant,query:S.advanced.query,case_sensitive:S.advanced.case_sensitive};
 try{const result=await api('query',request);if(context===context4()&&request.query===S.advanced.query){S.advanced.ids=new Set(result.ids);S.advanced.context=context;S.advanced.error='';S.advanced.result=result;}}
 catch(e){S.advanced.ids=null;S.advanced.error=e.message;S.advanced.context=context;}
}
const beforeRefresh4=refresh;
refresh=async function(){const previous=S.data?.project?.path;await beforeRefresh4();if(previous&&previous!==S.data?.project?.path){S.link={connected:false,ids:[]};S.linkSequence=null;S.linkPending=false;S.filterBypass=false;S.queuedLinkIds=null;}if(S.data?.project&&S.advanced.query){await evaluateAdvanced4();render();}};
const beforeBOM4=renderBOM;
renderBOM=function(){
 const currentIds=new Set(filteredRows().map(r=>r.id)),count=currentIds.size,hiddenSelected=[...S.selected].filter(id=>!currentIds.has(id)).length;
 const a=S.advanced;
 return `<section class="panel search-tools"><div class="toolbar"><button class="${a.query?'primary':'secondary'} small" data-act="advancedSearch">Advanced search & saved filters</button><button class="small" data-act="selectResults">Select all ${count} results</button><button class="small" data-act="invertResults">Invert results selection</button><button class="small" data-act="clearSelection">Clear selection</button><span class="grow"></span><button class="primary small" data-act="bulkActions">Bulk actions…</button><button class="small" data-act="liveLink">${S.link.connected?'● Live link':'○ Connect KiCad'}</button></div>${a.query?`<div class="query-chip"><code>${esc(a.query)}</code><span>${count} results${hiddenSelected?' · '+hiddenSelected+' selected outside filter':''}</span><button class="quiet small" data-act="clearAdvanced">Clear query</button></div>`:''}${a.error?`<div class="notice error">Search could not be evaluated: ${esc(a.error)}. No results are targeted. <button class="linkbutton" data-act="advancedSearch">Edit query</button></div>`:''}${S.filterBypass?'<div class="notice warning">Filters temporarily bypassed to reveal linked components. <button class="linkbutton" data-act="restoreFilters">Restore filters</button></div>':''}<div id="linkNotice" class="link-notice" role="status"></div></section>`+beforeBOM4();
};
const beforeRender4=render;
render=function(){beforeRender4();if(S.data?.project&&S.view==='bom'){decorateGroups4();paintLink4();
 // Replace legacy one-click population with the same reviewed transaction as other bulk actions.
 for(const b of $$('[data-pop]')){b.dataset.act='reviewPopulation';b.dataset.population=b.dataset.pop;delete b.dataset.pop;}
}};
function decorateGroups4(){
 for(const row of $$('#main tr.group-row')){const g=groupById(row.querySelector('[data-group]')?.dataset.group);if(!g)continue;row.dataset.linkGroup=g.key;
 const td=row.cells[0],box=document.createElement('input');box.type='checkbox';box.dataset.selectGroup=g.key;box.setAttribute('aria-label','Select group '+g.label);box.checked=g.ids.every(id=>S.selected.has(id));box.indeterminate=!box.checked&&g.ids.some(id=>S.selected.has(id));td.prepend(box);}
 for(const row of $$('#main tr.group-child')){const id=row.querySelector('[data-id]')?.dataset.id;if(!id)continue;row.dataset.row=id;
 const box=document.createElement('input');box.type='checkbox';box.dataset.select=id;box.checked=S.selected.has(id);box.setAttribute('aria-label','Select component '+S.data.rows.find(r=>r.id===id)?.ref);row.cells[0].prepend(box);}
}
function searchDialog4(){
 const fields=[...new Set(S.data.rows.flatMap(r=>Object.keys(r.fields)))].sort();
 showDialog('Advanced search & saved filters',`<p>Combine fields with <b>AND</b>, <b>OR</b>, <b>NOT</b> and parentheses. The same query works in the CLI and bulk recipes. Values ignore case by default; field names are exact.</p>
 <div class="rule-builder"><select id="queryField" aria-label="Search field">${fields.map(f=>`<option>${esc(f)}</option>`).join('')}<option>has</option><option>missing</option><option>is</option></select><select id="queryOperator" aria-label="Search operator"><option value=":">contains</option><option value="=">equals</option><option value="!=">not equal</option><option value="~">wildcard * ?</option><option value=">=">at least</option><option value="<=">at most</option></select><input id="queryValue" placeholder="Value, field name or state" aria-label="Search value"><button data-act="appendQuery">+ AND rule</button><button data-act="appendQueryOr">+ OR rule</button></div>
 <label for="advancedQuery">Query</label><textarea id="advancedQuery" rows="3" spellcheck="false">${esc(S.advanced.query)}</textarea><label class="check-label"><input id="queryCase" type="checkbox" ${S.advanced.case_sensitive?'checked':''}>Case-sensitive values</label>
 <p class="fine">Examples: <code>Reference~"R*" AND Value="10k"</code> · <code>is:fitted AND missing:MPN</code> · <code>(Footprint:"0603" OR Footprint:"0805") AND NOT is:dnp</code> · <code>raw.Value:"&#36;{"</code> · <code>UnitPrice &gt;= 1</code>. No regex execution or implicit SI-unit comparisons.</p>
 <div class="toolbar"><button class="primary" data-act="applyQuery">Apply search</button><button data-act="tryQuery">Test count & facets</button></div><div id="queryResult" aria-live="polite"></div><hr>
 <h3>Saved filters</h3><div class="rule-builder"><select id="savedFilter" aria-label="Saved filter"><option value="">Choose saved filter…</option>${Object.keys(S.data.saved_filters||{}).map(n=>`<option>${esc(n)}</option>`).join('')}</select><button data-act="loadFilter">Load</button><button data-act="deleteFilter">Delete</button></div><div class="rule-builder"><input id="filterName" placeholder="Filter name" aria-label="New filter name"><input id="filterDescription" placeholder="Description" aria-label="Filter description"><button data-act="saveFilter">Save query as filter</button></div><div class="toolbar"><button data-act="shareFilters">Share filter library JSON</button><label class="button-file">Import filter library<input type="file" id="filterImport" accept=".json,application/json"></label><label class="check-label"><input type="checkbox" id="replaceFilters">Replace name conflicts</label></div><p class="fine">Definitions are saved with the workspace. Sharing includes literal query text; review confidential terms before sharing. Import stores definitions only; it does not edit components.</p>`);
}
function queryInput4(){return {query:$('#advancedQuery').value,case_sensitive:$('#queryCase').checked};}
async function testQuery4(apply=false){
 const request=queryInput4(),r=await api('query',{variant:S.variant,...request});
 if(apply){S.advanced={...request,ids:new Set(r.ids),context:context4(),error:'',result:r};S.filterBypass=false;S.page=0;$('#dialog').close();render();toast(r.matched+' matched before quick population/text filters.');}
 else $('#queryResult').innerHTML=`<div class="notice">${r.matched} / ${r.total} components match. Click a facet to append a rule.</div><div class="query-facets">${Object.entries(r.facets).map(([name,f])=>`<section class="facet-card"><h4>${esc(name)}</h4>${f.values.slice(0,12).map(x=>`<button class="small" data-act="queryFacet" data-facet-field="${esc(name)}" data-facet-value="${esc(x.value)}" title="${esc(x.value)}">${esc(x.value||'(blank)')}<span>${x.count}</span></button>`).join('')}${f.distinct>12?`<p class="fine">${f.distinct} distinct values; showing 12</p>`:''}</section>`).join('')}</div>`;
}
function appendQuery4(or=false){const field=$('#queryField').value,op=['has','missing','is'].includes(field)?':':$('#queryOperator').value,predicate=quoteQuery4(field)+op+quoteQuery4($('#queryValue').value),q=$('#advancedQuery');q.value=q.value.trim()?'('+q.value.trim()+') '+(or?'OR':'AND')+' '+predicate:predicate;}

const bulkOps4={set:'Set value',fill_empty:'Fill only blanks',clear:'Clear value (keep field)',trim:'Trim whitespace',upper:'UPPERCASE',lower:'lowercase',prefix:'Add prefix',suffix:'Add suffix',replace:'Replace literal text',copy:'Copy raw field',reset_to_base:'Reset workspace override'};
function collectBulk4(){S.bulkOperations=$$('#bulkRows .bulk-operation').map(row=>{const op=row.querySelector('[data-op]').value,r={op,field:row.querySelector('[data-bulk-field]').value};if(['set','fill_empty','prefix','suffix','replace'].includes(op))r.value=row.querySelector('[data-value]').value;if(op==='replace')r.find=row.querySelector('[data-find]').value;if(op==='copy')r.source=row.querySelector('[data-source]').value;return r;});S.bulkScope=$('#bulkScope')?.value||S.bulkScope;}
function drawBulkRows4(){
 $('#bulkRows').innerHTML=S.bulkOperations.map((r,i)=>`<div class="bulk-operation" data-index="${i}"><span>${i+1}.</span><select data-op aria-label="Operation ${i+1}">${Object.entries(bulkOps4).map(([k,v])=>`<option value="${k}" ${r.op===k?'selected':''}>${v}</option>`).join('')}</select><input data-bulk-field list="bulkFieldNames" placeholder="Target field" aria-label="Target field ${i+1}" value="${esc(r.field||'')}">${r.op==='replace'?`<input data-find placeholder="Find literal" aria-label="Find text" value="${esc(r.find||'')}">`:''}${['set','fill_empty','prefix','suffix','replace'].includes(r.op)?`<input data-value placeholder="Raw value or expression" aria-label="Operation value ${i+1}" value="${esc(r.value??'')}">`:''}${r.op==='copy'?`<input data-source list="bulkFieldNames" placeholder="Source field" aria-label="Source field" value="${esc(r.source||'')}">`:''}<button class="quiet small" data-act="bulkMoveUp" data-index="${i}" aria-label="Move operation up">↑</button><button class="quiet small" data-act="bulkRemoveOp" data-index="${i}" aria-label="Remove operation">×</button></div>`).join('');
}
function bulkDialog4(){
 if(S.gridDraft.size)throw Error('Review or discard unstaged grid edits before starting a bulk recipe.');
 showDialog('Bulk actions — review before changing',`<div class="notice">Operations run in order on raw fields. Changing Value/MPN does not replace the library symbol or qualify a part. Clear blanks a property; it does not remove it.</div><div class="field"><label for="bulkScope">Target scope</label><select id="bulkScope"><option value="selected" ${S.bulkScope==='selected'?'selected':''}>Explicit selection — ${S.selected.size} parts (including hidden selected parts)</option><option value="filtered" ${S.bulkScope==='filtered'?'selected':''}>All current results — ${filteredRows().length} parts across every page</option></select></div><datalist id="bulkFieldNames">${allFields().map(f=>`<option value="${esc(f)}">`).join('')}</datalist><div id="bulkRows"></div><div class="toolbar"><button data-act="bulkAddOp">+ Add operation</button><button data-act="bulkShareRecipe">Save recipe JSON</button><label class="button-file">Load operations<input id="bulkRecipeImport" type="file" accept=".json,application/json"></label><span class="grow"></span><button class="primary" data-act="bulkPreview">Preview complete changes</button></div><p class="fine">Loading a recipe imports its operations only: choose the scope explicitly here. CLI recipes can instead target a query. Native files change only through separate APPLY.</p>`);drawBulkRows4();
}
function currentBulkRecipe4(){collectBulk4();const ids=S.bulkScope==='filtered'?filteredRows().map(r=>r.id):[...S.selected];if(!ids.length)throw Error('The chosen scope has no components.');return {schema:'wayricad-bulk-recipe-1',ids,operations:S.bulkOperations};}
async function reviewBulk4(recipe){
 if(S.gridDraft.size)throw Error('Stage/discard grid drafts before bulk changes.');
 const variant=S.variant,plan=await api('bulk/preview',{variant,recipe});S.bulkPlan=plan;
 showDialog('Review bulk transaction',`<div class="notice"><b>${plan.matched} explicitly targeted</b> · ${plan.affected} affected components · ${plan.events.length} field changes, including shared-sheet/inherited-variant effects.</div>${(plan.warnings||[]).map(w=>`<div class="notice warning">${esc(w)}</div>`).join('')}<div class="table-wrap tall"><table class="data-table"><thead><tr><th>Variant</th><th>Reference</th><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>${plan.events.slice(0,500).map(e=>`<tr class="${e.variable_loss?'loss-row':''}"><td>${esc(e.variant)}</td><td>${esc(e.reference)}</td><td>${esc(e.field)}</td><td>${esc(e.before)}</td><td>${esc(e.after)}</td></tr>`).join('')}</tbody></table></div><button type="button" class="linkbutton" data-act="bulkSaveReview">Save all review events JSON</button>${plan.variable_losses?'<label class="check-label"><input name="loss" type="checkbox" required>I acknowledge replacement/loss of raw variable expressions.</label>':''}<div class="field"><label>Type EDIT to stage one undoable transaction</label><input name="confirmation" required autocomplete="off"></div>${formActions('Stage reviewed bulk changes')}`,async f=>{const result=await api('bulk/apply',{variant,recipe,fingerprint:plan.fingerprint,confirmation:f.get('confirmation'),acknowledge_loss:!!f.get('loss')});await refresh();toast(result.affected+' components changed in workspace. Save workspace; native APPLY is separate.');});
}

// Selection-only live link. One in-flight poll; incoming highlights never echo back.
function paintLink4(){
 const ids=new Set(S.link.ids||[]);
 for(const tr of $$('#main tr[data-row],#main tr[data-link-group]')){
  const group=tr.dataset.linkGroup?groupById(tr.dataset.linkGroup):null;
  const linked=group?group.ids.some(id=>ids.has(id)):ids.has(tr.dataset.row);tr.classList.toggle('linked-row',linked);if(linked)tr.setAttribute('aria-current','true');else tr.removeAttribute('aria-current');
 }
 const notice=$('#linkNotice');if(!notice)return;
 if(!S.link.connected){notice.innerHTML=S.link.error?`<span class="error-text">Link disconnected: ${esc(S.link.error)}</span>`:'';return;}
 const visible=new Set(filteredRows().map(r=>r.id)),hidden=[...ids].filter(id=>!visible.has(id)).length;
 notice.innerHTML=`<span class="link-dot">●</span> KiCad ${esc(S.link.version)} · ${S.link.mapped_components}/${S.link.total_components} mapped · ${ids.size} linked${S.link.unmapped_selected?' · '+S.link.unmapped_selected+' unlinked editor items':''}${hidden?' · '+hidden+' hidden by filters':''} <button class="quiet small" data-act="revealLinked">Reveal in BOM</button><button class="quiet small" data-act="selectLinked">Use linked parts as edit selection</button>${S.linkPending?'<b>Selection waiting—finish editing, then Reveal.</b>':''}<span class="fine">Schematic uses native relay; not host-validated. Variant is not switched.</span>`;
}
function busyEditing4(){return $('#dialog').open||S.formDirty||S.gridDraft.size||!!document.activeElement?.closest('input,textarea,select,[contenteditable="true"]');}
function revealLinked4(explicit=false){
 const ids=new Set(S.link.ids||[]);if(!ids.size)return;
 if(!explicit&&busyEditing4()){S.linkPending=true;paintLink4();return;}
 const rows=filteredRows(),visible=rows.filter(r=>ids.has(r.id));
 if(!visible.length){if(!explicit){S.linkPending=true;paintLink4();return;}S.filterBypass=true;}
 S.view='bom';S.linkPending=false;
 if(S.data.grouping?.fields?.length){const groups=groupingRows(),i=groups.findIndex(g=>g.ids.some(id=>ids.has(id)));if(i>=0){S.expandedGroups.add(groups[i].label);S.page=Math.floor(i/50);}}
 else{const i=filteredRows().findIndex(r=>ids.has(r.id));if(i>=0)S.page=Math.floor(i/S.pageSize);}
 render();requestAnimationFrame(()=>$('#main .linked-row')?.scrollIntoView({block:'nearest',inline:'nearest'}));
}
function adoptLink4(result){
 const changed=S.linkSequence!==result.sequence||S.link.board!==result.board;
 S.link=result;S.linkSequence=result.sequence;
 if(changed&&result.connected&&result.origin==='editor'&&S.linkPreferences.follow)revealLinked4(false);else paintLink4();
}
async function pollLink4(){
 if(!S.link.connected||S.linkBusy)return;S.linkBusy=true;
 try{adoptLink4(await api('link/poll',{}));}catch(e){S.link={connected:false,ids:[],error:e.message};paintLink4();}finally{S.linkBusy=false;}
}
async function sendLink4(ids){
 if(!S.link.connected||!S.linkPreferences.send||!ids.length)return;
 if(S.linkBusy){S.queuedLinkIds=ids;return;}
 S.linkBusy=true;
 try{adoptLink4(await api('link/select',{ids,focus:S.linkPreferences.focus,allow_partial:S.linkPreferences.partial===true}));}
 catch(e){toast(e.message,true);}
 finally{S.linkBusy=false;const queued=S.queuedLinkIds;S.queuedLinkIds=null;if(queued)setTimeout(()=>sendLink4(queued),0);}
}
async function linkDialog4(){
 const d=await api('link/diagnostic',{});S.linkDiagnostic=d;
 showDialog('Live KiCad link — experimental host integration',`<div class="notice warning">Selection-only IPC. The PCB must belong to this saved project. Keep both editors open from KiCad Project Manager; enable native cross-selection, centering and zoom. Schematic-only parts cannot relay through a footprint. Actual KiCad-host behavior still needs validation.</div><p>Core BOM functions work without IPC. Live linking uses the optional official <code>kicad-python==0.8.0</code> client, installed in the launcher’s Python environment. KiCad managed plugin launch can provide it from requirements.txt.</p><div class="field"><label>Local IPC socket (usually leave blank for KiCad launch environment)</label><input name="socket" placeholder="Automatically use KICAD_API_SOCKET"></div><label class="check-label"><input type="checkbox" name="reference_fallback">Allow weak reference-only matches when UUID paths are absent (never mismatching UUIDs)</label><label class="check-label"><input type="checkbox" name="focus" ${S.linkPreferences.focus?'checked':''}>Experimental PCB Zoom to Selection action (unstable host API; submission is not viewport confirmation)</label><label class="check-label"><input type="checkbox" name="partial" ${S.linkPreferences.partial?'checked':''}>Permit partial group linking; leave unmatched members unselected and report them</label><label class="check-label"><input type="checkbox" name="future">Explicitly allow an untested non-KiCad-10 host</label><label class="check-label"><input type="checkbox" name="send" ${S.linkPreferences.send?'checked':''}>BOM row clicks select linked footprints</label><label class="check-label"><input type="checkbox" name="follow" ${S.linkPreferences.follow?'checked':''}>Follow native editor selection in the BOM (without interrupting edits)</label><details><summary>Dependency diagnostics and mapping status</summary><pre class="code-sample">${esc(JSON.stringify({diagnostics:d,status:S.link},null,2))}</pre></details><button type="button" data-act="disconnectLink">Disconnect</button>${formActions('Connect / reconnect')}`,async f=>{const options={socket:f.get('socket').trim(),reference_fallback:!!f.get('reference_fallback'),experimental_focus:!!f.get('focus'),allow_untested:!!f.get('future')};const status=await api('link/connect',{options});S.linkPreferences={send:!!f.get('send'),follow:!!f.get('follow'),focus:!!f.get('focus'),partial:!!f.get('partial')};adoptLink4(status);render();toast('Linked '+status.mapped_components+' components. Schematic relay and focus require target-host validation.');});
}
let linkClickTimer4=null;
document.addEventListener('click',e=>{
 if(S.view!=='bom'||!S.link.connected||!S.linkPreferences.send||e.target.closest('button,input,select,textarea,a,label'))return;
 const tr=e.target.closest('#main tr[data-row],#main tr[data-link-group]');if(!tr)return;
 const ids=tr.dataset.linkGroup?(groupById(tr.dataset.linkGroup)?.ids||[]):[tr.dataset.row];clearTimeout(linkClickTimer4);linkClickTimer4=setTimeout(()=>sendLink4(ids),260);
});
document.addEventListener('dblclick',()=>clearTimeout(linkClickTimer4));
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&S.view==='bom'&&e.target.matches('td[data-field="Reference"]')){const id=e.target.dataset.id;if(id)sendLink4([id]);}});
setInterval(()=>{if(S.queuedLinkIds&&!S.linkBusy){const ids=S.queuedLinkIds;S.queuedLinkIds=null;sendLink4(ids);}else pollLink4();},1000);

function defaultPipeline4(){return {schema:'wayricad-pipeline-1',name:'WayriCAD_BOM',variants:'all',template:'Purchasing',formats:['csv','xlsx','json','txt'],reports:['checks','health','analysis'],policy:{checks:'error',health:'none',require_stock:false}};}
function renderAutomation(){
 S.pipeline=S.pipeline||defaultPipeline4();
 return `<div class="notice">Headless commands use saved files plus the saved workspace—not unsaved editor memory. Live selection is independent and does not alter design data. Native writes always require their separate reviewed APPLY.</div><section class="panel panel-body"><h2>Release pipeline & KiCad job set</h2><p>Generate a native <code>.kicad_jobset</code> containing Special → Execute Command. Its runner writes to KiCad’s <code>JOBSET_OUTPUT_WORK_PATH</code>, records stdout and propagates nonzero exits. A failed policy produces reports and a FAILED manifest, not BOM files.</p><label for="pipelineConfig">Data-only pipeline JSON</label><textarea id="pipelineConfig" rows="14" spellcheck="false">${esc(JSON.stringify(S.pipeline,null,2))}</textarea><div class="toolbar"><button data-act="savePipeline">Download pipeline JSON</button><button class="primary" data-act="jobsetDialog">Generate job-set bundle…</button><button data-act="liveLink">Connect live selection…</button></div><p class="fine">Policy: checks = error/warning; health = none/error/warning/unknown. require_stock requires fresh reviewed numeric coverage for every fitted purchasing identity. Health screening is not component qualification.</p></section><section class="panel panel-body"><h2>A real CLI, not GUI automation</h2><pre class="code-sample">python cli.py doctor
python cli.py query Board.kicad_pro --query 'Reference~"R*" AND Value="10k"' --rows
python cli.py check Board.kicad_pro --fail-on warning
python cli.py health Board.kicad_pro --fail-on error
python cli.py export Board.kicad_pro --format xlsx --output new-BOM.xlsx
python cli.py bulk preview Board.kicad_pro --recipe changes.json --output review.json
python cli.py bulk apply Board.kicad_pro --plan review.json --confirm EDIT
python cli.py run Board.kicad_pro --config pipeline.json --output-dir new-release
python cli.py verify new-release</pre><p class="fine">Examples use POSIX/PowerShell quoting; Windows cmd needs its own escaping. cli.py is in the plugin directory. Every output path must be new. Preview plans bind to source/workspace hashes. Bulk apply saves the sidecar, not native schematic files.</p><p>Also: info, list, compare, analyze, release, templates, config, enforce, evidence, native, jobset, schema and gui. Use <code>python cli.py COMMAND --help</code>. Machine JSON on stdout; errors on stderr; documented exit codes distinguish invalid input, failed policies, I/O and stale reviews.</p></section><section class="panel panel-body"><h2>What “world class” should mean next</h2><p><b>Qualification:</b> independently measured package/pin-function checks and versioned manufacturer evidence, never an opaque green score. <b>Release governance:</b> authenticated approval roles, signed manifests, expiring waivers and reproducible change control. <b>Usability:</b> measured large-BOM performance, virtualized grids, accessibility and integration tests on every supported KiCad/OS combination.</p><p><b>Planned—not in this build:</b> native KiCad 11 schematic adapter once its interfaces are stable; managed part-library/catalog synchronization; optional inventory/ERP connectors; supplier-PCN tracking; signed multi-user approvals. The core should remain useful offline without paid services.</p></section>`;
}
function readPipeline4(){if($('#pipelineConfig'))S.pipeline=JSON.parse($('#pipelineConfig').value);return S.pipeline||defaultPipeline4();}
function jobsetDialog4(){readPipeline4();showDialog('Generate native KiCad job-set bundle',`<p>Choose the exact directory where you will extract this bundle on this machine. The generated command references that location. It does not modify an existing job set or execute a shell command now.</p><div class="field"><label>Intended extraction directory (absolute, new location)</label><input id="jobDirectory" placeholder="C:\\Projects\\Board-release-jobs"></div><div class="field"><label>Python interpreter (absolute path recommended; blank = running server interpreter)</label><input id="jobPython" placeholder="C:\\Path\\to\\python.exe"></div><div class="field"><label>Target shell</label><select id="jobPlatform"><option value="windows">Windows cmd</option><option value="posix">POSIX shell</option></select></div><div class="notice warning">Includes local project, plugin and interpreter paths. Review before sharing. Regenerate after moving files. Do not use GUI launch for unattended releases.</div><button class="primary" data-act="downloadJobset">Download job-set ZIP</button><p class="fine">Open WayriCAD_BOM.kicad_jobset in KiCad, review its Execute Command, then run it. The runner is also directly executable. Native KiCad job-set execution remains host-untested; runner behavior is tested separately.</p>`);}
Object.assign(handlers,{
 queryFacet:el=>{const q=$('#advancedQuery'),rule=quoteQuery4(el.dataset.facetField)+'='+quoteQuery4(el.dataset.facetValue);q.value=q.value.trim()?'('+q.value.trim()+') AND '+rule:rule;},
 advancedSearch:searchDialog4,appendQuery:()=>appendQuery4(),appendQueryOr:()=>appendQuery4(true),tryQuery:()=>testQuery4(),applyQuery:()=>testQuery4(true),
 clearAdvanced:()=>{S.advanced={query:'',case_sensitive:false,ids:null,context:'',error:''};S.filterBypass=false;S.page=0;render();},
 restoreFilters:()=>{S.filterBypass=false;S.page=0;render();},
 selectResults:()=>{for(const r of filteredRows())S.selected.add(r.id);render();},invertResults:()=>{for(const r of filteredRows())S.selected.has(r.id)?S.selected.delete(r.id):S.selected.add(r.id);render();},
 loadFilter:()=>{const name=$('#savedFilter').value,r=S.data.saved_filters?.[name];if(!r)throw Error('Choose a saved filter.');$('#advancedQuery').value=r.query;$('#queryCase').checked=r.case_sensitive;$('#filterName').value=name;$('#filterDescription').value=r.description||'';},
 saveFilter:async()=>{const name=$('#filterName').value.trim();if(!name)throw Error('Enter a filter name.');if(S.data.saved_filters?.[name]&&!confirm('Replace the saved filter '+name+'?'))return;await api('filter/save',{name,record:{...queryInput4(),description:$('#filterDescription').value}});await refresh();searchDialog4();toast('Filter stored in workspace; Save workspace to persist.');},
 deleteFilter:async()=>{const name=$('#savedFilter').value;if(!name)throw Error('Choose a filter.');if(!confirm('Delete filter '+name+'?'))return;await api('filter/save',{name,remove:true});await refresh();searchDialog4();},
 shareFilters:()=>download('filter/export',{}),
 bulkActions:bulkDialog4,bulkPreview:()=>reviewBulk4(currentBulkRecipe4()),bulkAddOp:()=>{collectBulk4();if(S.bulkOperations.length>=30)throw Error('At most 30 operations per recipe.');S.bulkOperations.push({op:'set',field:'Value',value:''});drawBulkRows4();},
 bulkRemoveOp:el=>{collectBulk4();S.bulkOperations.splice(Number(el.dataset.index),1);drawBulkRows4();},bulkMoveUp:el=>{collectBulk4();const i=Number(el.dataset.index);if(i>0)[S.bulkOperations[i-1],S.bulkOperations[i]]=[S.bulkOperations[i],S.bulkOperations[i-1]];drawBulkRows4();},
 bulkShareRecipe:()=>{const recipe=currentBulkRecipe4();saveJSON(recipe,'WayriCAD_bulk_recipe.json');toast('Recipe includes explicit component IDs; review before sharing.');},
 bulkSaveReview:()=>saveJSON(S.bulkPlan,'WayriCAD_bulk_review.json'),
 reviewPopulation:el=>reviewBulk4({schema:'wayricad-bulk-recipe-1',ids:[...S.selected],operations:[{op:'set',field:'Assembly',value:el.dataset.population}]}),
 liveLink:linkDialog4,disconnectLink:async()=>{await api('link/disconnect',{});S.link={connected:false,ids:[]};S.linkSequence=null;S.queuedLinkIds=null;$('#dialog').close();render();},revealLinked:()=>revealLinked4(true),
 selectLinked:()=>{S.selected=new Set(S.link.ids||[]);S.view='bom';render();toast('Linked components explicitly selected for editing.');},
 savePipeline:()=>saveJSON(readPipeline4(),'pipeline.json'),jobsetDialog:jobsetDialog4,
 downloadJobset:()=>download('jobset/bundle',{directory:$('#jobDirectory').value,python:$('#jobPython').value||null,platform:$('#jobPlatform').value,config:S.pipeline})
});
document.addEventListener('change',async e=>{try{
 if(e.target.dataset.selectGroup){const g=groupById(e.target.dataset.selectGroup);if(g)for(const id of g.ids)e.target.checked?S.selected.add(id):S.selected.delete(id);render();}
 if(e.target.hasAttribute('data-op')){collectBulk4();drawBulkRows4();}
 if(e.target.id==='filterImport'&&e.target.files[0]){const file=e.target.files[0];if(file.size>2*1024*1024)throw Error('Filter bundle exceeds 2 MiB.');const payload=JSON.parse(await file.text());await api('filter/import',{payload,replace:$('#replaceFilters').checked});await refresh();searchDialog4();toast('Filter definitions imported; no component data changed.');}
 if(e.target.id==='bulkRecipeImport'&&e.target.files[0]){if(e.target.files[0].size>2*1024*1024)throw Error('Recipe exceeds 2 MiB.');const payload=JSON.parse(await e.target.files[0].text());if(payload.schema!=='wayricad-bulk-recipe-1'||!Array.isArray(payload.operations)||payload.operations.length>30)throw Error('Expected a WayriCAD bulk recipe with at most 30 operations.');if(payload.operations.some(o=>!Object.hasOwn(bulkOps4,o.op)||typeof o.field!=='string'))throw Error('Unsupported operation.');S.bulkOperations=payload.operations;drawBulkRows4();toast('Operations loaded. Choose the target scope explicitly.');}
 }catch(error){toast(error.message,true);}});
// Query context is revalidated after variant refresh. Reopening a project must not
// retain a stale editor link or action scope, even when references happen to match.
const beforeSwitch4=switchVariant;
switchVariant=async function(value){await beforeSwitch4(value);S.filterBypass=false;if(S.advanced.query){await evaluateAdvanced4();render();}};
// Initial refresh runs after the analytics module is registered.
