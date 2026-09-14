'use strict';
/* Native configuration is read-only by default. Customization and reverse sync
   are deliberate operations; rendering and exporting never enforce fields. */
const NF={profilesCustom:false,copyWarnings:[],preview:null,nativeBusy:false,projectKey:null};
const followingNative=()=>S.data?.bom_authority?.preferences.mode!=='custom';
const ctxNF=()=>S.data.bom_authority;
function syncProjectNF(){const key=S.data?.project?.path||'';if(key!==NF.projectKey){NF.projectKey=key;NF.profilesCustom=false;NF.preview=null;NF.nativeBusy=false;S.template=S.data?.bom_authority?.preferences.custom_template||'';}}
function authorityBarNF(){return `<section class="panel native-authority"><div class="toolbar"><strong>${followingNative()?'Following KiCad':'Custom workspace format'}</strong><span class="fine">${followingNative()?'Saved columns, labels and format; no native files changed.':'Explicit workspace customization; no automatic reverse sync.'}</span><span class="grow"></span>${!followingNative()?b8('followNativeNF','Follow KiCad'):''}${b8('customizeNF','Customize a copy…')}${b8('selectCustomNF','Use existing custom…')}${b8('runtimeNF','Runtime diagnostics')}</div></section>`;}
const renderBOMBeforeNF=renderBOM;
renderBOM=function(){syncProjectNF();return authorityBarNF()+renderBOMBeforeNF();};
const filterBeforeNF=filteredRows;
function nativeWildcardNF(text,pattern){const escaped=pattern.replace(/[.+^${}()|[\]\\]/g,'\\$&').replace(/\*/g,'.*').replace(/\?/g,'.');return new RegExp('^'+escaped+'$','i').test(text);}
filteredRows=function(){let rows=filterBeforeNF();if(!followingNative()||S.filterBypass)return rows;const p=ctxNF().preset;return rows.filter(r=>(!p.exclude_dnp||!r.flags.dnp)&&(p.include_excluded_from_bom!==false||r.flags.in_bom)&&(!p.filter_string||nativeWildcardNF(r.ref,p.filter_string)));};
const renderExportsBeforeNF=renderExportsV2;
renderExportsV2=function(){
 syncProjectNF();
 if(!followingNative()){
  if(!S.data.templates[S.template])S.template=ctxNF().preferences.custom_template||Object.keys(S.data.templates)[0]||'';
  return authorityBarNF()+`<div class="toolbar">${b8('mergeNativeNF','Merge missing KiCad columns…')}${b8('reverseFormatNF','Review custom format → KiCad…')}<span class="fine">Custom export uses WayriCAD rules. Native export remains available without writing edits.</span></div>`+renderExportsBeforeNF();
 }
 const c=ctxNF(),p=c.preset,f=c.format;
 return authorityBarNF()+`<div class="columns2"><section class="panel"><div class="panel-title"><h2>KiCad BOM format — inherited</h2><span class="chip">Read only</span></div><div class="panel-body">
 <div class="field"><label for="nativePresetNF">Native BOM preset</label><select id="nativePresetNF">${c.presets.map(x=>`<option value="${esc(x.id)}" ${c.preferences.preset===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
 <div class="field"><label for="nativeFormatNF">Native formatting preset</label><select id="nativeFormatNF">${c.formats.map(x=>`<option value="${esc(x.id)}" ${c.preferences.format_preset===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
 <div class="table-wrap tall"><table class="data-table"><thead><tr><th>Source field</th><th>BOM heading</th><th>Export</th><th>Group by</th></tr></thead><tbody>${p.fields_ordered.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.label)}</td><td>${x.show?'Yes':'No'}</td><td>${p.group_symbols&&x.group_by?'Yes':'No'}</td></tr>`).join('')}</tbody></table></div>
 <p class="fine">Sort: ${esc(p.sort_field)} · ${p.sort_asc?'ascending':'descending'} · Reference filter: ${esc(p.filter_string||'(none)')} · Exclude DNP: ${p.exclude_dnp?'yes':'no'}</p>
 <details><summary>Inherited format settings</summary><pre>${esc(JSON.stringify(f,null,2))}</pre></details>
 <p class="fine">Hidden and omitted fields are not added to this BOM. Project fields remain discoverable in Columns. Field-name templates are independent of these BOM settings.</p>${c.warnings.map(w=>`<div class="notice warning">${esc(w)}</div>`).join('')}</div></section>
 <section class="stack"><article class="panel"><div class="panel-title"><h2>Native output</h2></div><div class="panel-body"><p>Exports through the installed KiCad BOM engine using the inherited settings. The delimited output is not rewritten by WayriCAD.</p>
 <label class="check-label"><input type="checkbox" id="nativeSavedNF">I saved in KiCad. Export saved native data only, excluding pending WayriCAD edits and BOM-only variants.</label>
 <div class="toolbar">${b8('previewNativeNF','Preview native output')}${b8('exportNativeNF','Export native BOM')}</div>
 <div class="notice warning">Native output retains KiCad's expression, rule-area and exclusion decisions. It does not validate WayriCAD's independent attribute/health checks. Native text is not spreadsheet-formula-sanitized.</div>
 <p class="fine">Excel, analytics, additional formats and custom BOM-only variants remain available after explicitly choosing a custom copy. Nothing is silently synchronized to make native export work.</p></div></article>
 <article class="panel"><div class="panel-title"><h2>Native preview</h2></div><div class="panel-body" id="nativePreviewNF"><p class="muted">Preview/export never applies component or format changes.</p></div></article></section></div>`;
};
const renderProfilesBeforeNF=renderFieldTemplates;
renderFieldTemplates=function(){
 syncProjectNF();
 if(NF.profilesCustom)return `<div class="toolbar">${b8('nativeProfilesNF','Return to native field-name templates')}<strong>Custom profile — enforcement is explicit</strong></div>`+renderProfilesBeforeNF();
 const t=ctxNF().field_templates;
 return `<section class="panel"><div class="panel-title"><h2>KiCad field-name templates</h2><span class="chip">Inherited · read only</span></div><div class="panel-body"><p>Project definitions take precedence over identical global names. These are field definitions—not an instruction to rename, remove or fill component properties.</p>
 <div class="toolbar">${b8('copyProfileNF','Customize native field template…')}${b8('customProfilesNF','Manage custom profiles…')}${b8('fieldAudit8','Download field audit')}</div>
 <div class="table-wrap"><table class="data-table" id="nativeFieldsNF"><thead><tr><th>Exact field name</th><th>Source</th><th>Visible on schematic</th><th>URL field</th></tr></thead><tbody>${t.effective.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.source)}</td><td>${x.visible?'Yes':'No'}</td><td>${x.url?'Yes':'No'}</td></tr>`).join('')}</tbody></table></div>
 ${!t.effective.length?'<p class="notice">No custom native field-name templates found. Actual component fields remain available; no WayriCAD engineering standard has been activated.</p>':''}
 <p class="fine">Global preferences read: ${esc(t.global_path||'No eeschema.json found in the configured KiCad 10 location. Set WAYRICAD_KICAD_CONFIG_DIR for a nonstandard config directory.')}</p>
 ${t.warnings.map(w=>`<p class="notice warning">${esc(w)}</p>`).join('')}<p class="fine">Visibility here is schematic visibility, not BOM inclusion. Raw variable expressions stay intact. Default values and required-field policies are not invented from field names.</p></div></section>`;
};
const ensureTemplateBeforeNF=ensureTemplateSaved;
ensureTemplateSaved=async function(){if(followingNative())return;return ensureTemplateBeforeNF();};
const saveProfileBeforeNF=saveFieldProfile;
saveFieldProfile=async function(refreshView=true){if(!NF.profilesCustom)return;return saveProfileBeforeNF(refreshView);};
const headerBeforeNF=header;
header=function(){headerBeforeNF();const r=S.data?.runtime;let badge=$('#runtimeBadgeNF');if(!badge){badge=document.createElement('button');badge.id='runtimeBadgeNF';badge.className='quiet small';badge.dataset.act='runtimeNF';$('.sidebar-bottom').append(badge);}if(r){badge.textContent=`v${r.version} · ${r.ui_mode==='desktop'?'Desktop window':r.ui_mode==='browser'?'External browser':'Headless/test'}`;badge.title=`Installation: ${r.installation}\nPython: ${r.interpreter}\nPID: ${r.pid}`;}};
async function chooseNativeNF(){await api('bom-format/select',{mode:'native',preset:$('#nativePresetNF').value,format_preset:$('#nativeFormatNF').value});await refresh();}
async function nativeOutputNF(downloadIt=false){
 if(!$('#nativeSavedNF')?.checked)throw Error('Acknowledge saved native data only before exporting.');
 if(NF.nativeBusy)return;NF.nativeBusy=true;
 try{if(downloadIt)await download('bom-format/export',{acknowledge_saved:true});else{const p=await api('bom-format/preview',{variant:S.variant,acknowledge_saved:true});$('#nativePreviewNF').innerHTML=`<p class="fine">${esc(p.notice)}</p><pre class="native-output">${esc(p.text)}</pre>${p.truncated?'<p>Preview truncated; export contains complete native output.</p>':''}`;}}finally{NF.nativeBusy=false;}
}
Object.assign(handlers,{
 followNativeNF:async()=>{if(S.formDirty&&!confirm('Return to KiCad format? Unsaved custom form edits will be discarded.'))return;await api('bom-format/select',{mode:'native',preset:'@current',format_preset:'@current'});S.formDirty=false;await refresh();},
 customizeNF:()=>showDialog('Customize a native BOM copy',`<div class="notice">Copies inherited columns into a new WayriCAD template. Native settings and component properties remain unchanged. Unsupported differences will be listed.</div>${field6('New custom-template name','name','My BOM')} ${formActions('Create custom copy')}`,async f=>{const r=await api('bom-format/customize',{name:f.get('name')});S.template=r.template.name;S.formDirty=false;S.view='exports';await refresh();if(r.warnings.length)showDialog('Custom-copy differences',`<div class="notice warning">${r.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}</div>${b8('closeDialog','Understood')}`);}),
 selectCustomNF:()=>showDialog('Choose an existing custom BOM',`<p>This explicitly departs from native export defaults. No native data will be written.</p><select name="template">${Object.keys(S.data.templates).map(n=>`<option>${esc(n)}</option>`).join('')}</select>${formActions('Use custom format')}`,async f=>{S.template=f.get('template');await api('bom-format/select',{mode:'custom',custom_template:S.template});S.formDirty=false;await refresh();}),
 mergeNativeNF:async()=>{await ensureTemplateSaved();showDialog('Merge missing native BOM columns',`<p>Append absent KiCad columns to <b>${esc(S.template)}</b>. Existing custom order, labels and options win. Native files remain untouched.</p>${formActions('Merge native columns')}`,async()=>{const r=await api('bom-format/customize',{name:S.template,merge:true});await refresh();showDialog('Merge result',`<p>${esc(r.notice)}</p>${r.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}${b8('closeDialog','Close')}`);});},
 reverseFormatNF:async()=>{
  await ensureTemplateSaved();const p=await api('bom-format/reverse-preview',{template:S.template});NF.preview=p;
  showDialog('Review custom BOM format → KiCad',`${p.warnings.map(w=>`<p class="notice warning">${esc(w)}</p>`).join('')}<pre class="native-output" id="formatDiffNF">${esc(p.diff||'No settings differences.')}</pre><p>${esc(p.notice)}</p><label class="check-label"><input type="checkbox" name="acknowledge" required>I reviewed replacement of the project BOM settings.</label>${field6('Type FORMAT to stage only','confirmation','')}${formActions('Stage reviewed format')}`,async f=>{await api('bom-format/reverse-apply',{template:p.template,fingerprint:p.fingerprint,confirmation:f.get('confirmation'),acknowledge:f.has('acknowledge')});await refresh();toast('Format staged. Native files unchanged until separate Review & native sync → APPLY.');});
 },
 previewNativeNF:()=>nativeOutputNF(false),exportNativeNF:()=>nativeOutputNF(true),
 nativeProfilesNF:()=>{if(S.formDirty&&!confirm('Discard unsaved custom-profile form edits?'))return;NF.profilesCustom=false;S.formDirty=false;render();},
 customProfilesNF:()=>{NF.profilesCustom=true;render();},
 copyProfileNF:()=>showDialog('Copy native field-name templates',`${field6('Custom profile name','name','My field names')}<p>Copies names/visibility/URL metadata only. Does not enforce, invent defaults or alter variables.</p>${formActions('Create field-profile copy')}`,async f=>{const name=f.get('name');if(S.data.field_profiles[name])throw Error('Name already exists.');const fields=ctxNF().field_templates.effective.map(x=>({name:x.name,visible:x.visible,url:x.url,aliases:[],default:'',required:false}));if(!fields.length)throw Error('There are no native custom names to copy. Use Manage custom profiles to create a standard.');await api('field/profile',{profile:{name,fields}});S.fieldProfile=name;NF.profilesCustom=true;await refresh();}),
 runtimeNF:async()=>{const d=await api('runtime/diagnostic',{});showDialog('WayriCAD runtime and installation diagnostics',`<p class="notice">Desktop mode is a separate modeless window with an embedded webview—not a docked native KiCad table. This read-only report identifies the code actually running.</p><pre>${esc(JSON.stringify(d,null,2))}</pre>${b8('saveRuntimeNF','Save diagnostic JSON')}`);NF.runtime=d;},
 saveRuntimeNF:()=>jsonSave8(NF.runtime,'WayriCAD_runtime_diagnostics.json'),
 nativeBOM8:()=>{S.view='exports';render();if(!followingNative())toast('Use Follow KiCad to export its saved format; your custom template is retained.');}
});
document.addEventListener('change',e=>{if(['nativePresetNF','nativeFormatNF'].includes(e.target.id))chooseNativeNF().catch(x=>toast(x.message,true));});
document.addEventListener('change',e=>{if(e.target.id==='templateSelect'&&!followingNative())api('bom-format/select',{mode:'custom',custom_template:e.target.value}).catch(x=>toast(x.message,true));});
const previewHandlerBeforeNF=handlers.previewExport,downloadHandlerBeforeNF=handlers.downloadExport;
handlers.previewExport=()=>followingNative()?nativeOutputNF(false):previewHandlerBeforeNF();
handlers.downloadExport=()=>followingNative()?nativeOutputNF(true):downloadHandlerBeforeNF();
// Initial async state can arrive before the final extension script in an
// embedded engine/test bridge. Apply final presentation once, whichever wins.
if(S.data){header();if(S.data.project)render();}
