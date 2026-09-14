'use strict';
// Keep everyday work visible while retaining every advanced workflow.
const essentials = new Set(['bom','variants','exports','review','about']);
const moreTools = document.createElement('details');
moreTools.className = 'more-tools';
const moreSummary = document.createElement('summary');
moreSummary.textContent = 'More tools';
moreTools.append(moreSummary);
const navigation = document.querySelector('#navigation');
for (const button of [...navigation.querySelectorAll('[data-view]')]) {
  if (!essentials.has(button.dataset.view)) moreTools.append(button);
}
navigation.append(moreTools);
document.querySelector('.brandmark').textContent = 'W';
const originalAuthority = authorityBarNF;
authorityBarNF = function () {
  const workspaceSettings=ctxNF().preferences.preset==='@workspace';
  const authority=workspaceSettings ? originalAuthority().replace('Following KiCad','Workspace BOM settings').replace('Saved columns, labels and format; no native files changed.','Workspace columns, labels and format; native files unchanged.') : originalAuthority();
  return authority + `<div class="toolbar compact-settings">${b8('editNativeSettings','BOM settings…')}<span class="fine">Columns, grouping, sorting, DNP and CSV formatting</span></div>`;
};
let nativeDraft;
function nativeFieldsTable() {
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Order</th><th>Field</th><th>Heading</th><th>Show</th><th>Group</th></tr></thead><tbody>${nativeDraft.bom_settings.fields_ordered.map((c,i)=>`<tr data-native-column="${i}"><td><button type="button" data-native-move="${i}" data-direction="-1" aria-label="Move ${esc(c.name)} up">↑</button><button type="button" data-native-move="${i}" data-direction="1" aria-label="Move ${esc(c.name)} down">↓</button></td><td>${esc(c.name)}</td><td><input data-native-label="${i}" aria-label="Heading for ${esc(c.name)}" value="${esc(c.label)}"></td><td><input type="checkbox" data-native-show="${i}" aria-label="Show ${esc(c.name)}" ${c.show?'checked':''}></td><td><input type="checkbox" data-native-group="${i}" aria-label="Group by ${esc(c.name)}" ${c.group_by?'checked':''}></td></tr>`).join('')}</tbody></table></div>`;
}
handlers.editNativeSettings = () => {
  const c=ctxNF();nativeDraft=structuredClone({bom_settings:c.preset,bom_fmt_settings:c.format});
  const p=nativeDraft.bom_settings,f=nativeDraft.bom_fmt_settings;
  showDialog('BOM settings',`<p>Saved in this workspace. Native KiCad project settings change only through Review & native sync.</p><div id="nativeColumnEditor">${nativeFieldsTable()}</div><div class="row"><input id="nativeNewField" placeholder="Additional field name" aria-label="Additional field name"><button type="button" id="nativeAddField">Add field</button></div><div class="columns2"><section><label class="check-label"><input type="checkbox" name="group_symbols" ${p.group_symbols?'checked':''}>Group matching components</label><label class="check-label"><input type="checkbox" name="exclude_dnp" ${p.exclude_dnp?'checked':''}>Exclude DNP components</label><label class="check-label"><input type="checkbox" name="sort_asc" ${p.sort_asc?'checked':''}>Sort ascending</label><div class="field"><label>Sort field</label><input name="sort_field" value="${esc(p.sort_field||'Reference')}"></div><div class="field"><label>Reference filter</label><input name="filter_string" value="${esc(p.filter_string||'')}" placeholder="R*, C*, U?"></div></section><section>${['field_delimiter','string_delimiter','ref_delimiter','ref_range_delimiter'].map(k=>`<div class="field"><label>${esc(k.replaceAll('_',' '))}</label><input name="${k}" value="${esc(f[k]||'')}"></div>`).join('')}<label class="check-label"><input type="checkbox" name="keep_tabs" ${f.keep_tabs?'checked':''}>Keep tabs</label><label class="check-label"><input type="checkbox" name="keep_line_breaks" ${f.keep_line_breaks?'checked':''}>Keep line breaks</label></section></div>${formActions('Use these settings')}`,async form=>{
    for(const k of ['group_symbols','exclude_dnp','sort_asc'])nativeDraft.bom_settings[k]=form.has(k);
    for(const k of ['sort_field','filter_string'])nativeDraft.bom_settings[k]=form.get(k);
    for(const k of ['field_delimiter','string_delimiter','ref_delimiter','ref_range_delimiter'])nativeDraft.bom_fmt_settings[k]=form.get(k);
    for(const k of ['keep_tabs','keep_line_breaks'])nativeDraft.bom_fmt_settings[k]=form.has(k);
    await api('bom-format/configure',{settings:nativeDraft});await refresh();toast('BOM settings updated.');
  });
};
document.addEventListener('change',event=>{
  const e=event.target;if(!nativeDraft)return;
  for(const [key,property] of [['nativeLabel','label'],['nativeShow','show'],['nativeGroup','group_by']]){
    if(e.dataset[key]!==undefined)nativeDraft.bom_settings.fields_ordered[Number(e.dataset[key])][property]=property==='label'?e.value:e.checked;
  }
});
document.addEventListener('click',event=>{
  const e=event.target.closest('[data-native-move],#nativeAddField');if(!e||!nativeDraft)return;
  const fields=nativeDraft.bom_settings.fields_ordered;
  if(e.id==='nativeAddField'){
    const name=document.querySelector('#nativeNewField').value.trim();
    if(!name||fields.some(f=>f.name===name))return toast('Enter a new, unique field name.',true);
    fields.push({name,label:name,show:true,group_by:false});document.querySelector('#nativeNewField').value='';
  }else{
    const i=Number(e.dataset.nativeMove),j=i+Number(e.dataset.direction);
    if(j<0||j>=fields.length)return;[fields[i],fields[j]]=[fields[j],fields[i]];
  }
  document.querySelector('#nativeColumnEditor').innerHTML=nativeFieldsTable();
});
if(S.data?.project)render();
