'use strict';let record=null;
const fields=['manufacturer','mpn','supplier','sku','stock','region','observed_at','source_url','package','pin_count','mounting','lifecycle','moq','order_multiple','currency','unit_price','notes'];
document.querySelector('#capture').addEventListener('click',async()=>{const error=document.querySelector('#error');error.textContent='';try{
 const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(!tab?.id)throw Error('No active tab.');
 const result=await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureWayriCADPage});
 if(result[0]?.error)throw Error(result[0].error.message||'Page capture failed.');const data=result[0]?.result;if(!data)throw Error('No readable evidence returned.');record=data.record;
 document.querySelector('#fields').replaceChildren();for(const name of fields){const label=document.createElement('label');label.textContent=name;const input=document.createElement('input');input.name=name;input.value=record[name]??'';if(['mpn','manufacturer','source_url'].includes(name))input.required=true;label.append(input);document.querySelector('#fields').append(label);}
 document.querySelector('#warnings').replaceChildren();for(const w of data.warnings){const p=document.createElement('p');p.textContent=w;document.querySelector('#warnings').append(p);}document.querySelector('#result').hidden=false;
 }catch(e){error.textContent=e.message;}});
document.querySelector('#form').addEventListener('submit',e=>{e.preventDefault();try{
 const r={...record,...Object.fromEntries(new FormData(e.target)),reviewed:true};if(!document.querySelector('#review').checked)throw Error('Review the values first.');
 for(const key of ['stock','pin_count','moq','order_multiple'])if(r[key]&&!/^\d+$/.test(r[key]))throw Error(key+' must be a plain integer, or blank when unknown.');
 const data={schema:'wayricad-evidence-1',records:[r]},url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='WayriCAD_'+r.supplier+'_'+r.mpn.replace(/[^a-zA-Z0-9._-]/g,'_')+'_evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
 }catch(error){document.querySelector('#error').textContent=error.message;}});
