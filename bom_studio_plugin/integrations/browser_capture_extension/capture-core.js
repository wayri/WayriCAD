/* Self-contained for activeTab injection. No requests, cookies or page scripts run. */
function captureWayriCADPage(){
 const host=location.hostname.toLowerCase().replace(/^www\./,''),suffixes=['com','in','co.uk','de','fr','it','es','nl','se','fi','dk','no','at','ch','be','ie','pl','cz','pt','sg','jp','ca','com.au','co.nz','co.za','hk','com.hk','kr','co.kr','tw','cn','com.cn','mx','com.mx'];
 const supplier=suffixes.some(t=>host==='digikey.'+t)?'DigiKey':suffixes.some(t=>host==='mouser.'+t)?'Mouser':null;
 if(!supplier)throw Error('Open an actual DigiKey or Mouser product page first. This tool has no access to other sites.');
 if(!(/\/products\/detail\//i.test(location.pathname)||/\/productdetail\//i.test(location.pathname)))throw Error('Use a single product-detail page, not a search page, cart, BOM list or login page.');
 const r={mpn:'',manufacturer:'',supplier,sku:'',stock:'',observed_at:new Date().toISOString(),source_url:location.origin+location.pathname+location.search,package:'',pin_count:'',mounting:'',lifecycle:'',moq:'',order_multiple:'',region:'',currency:'',unit_price:'',origin:'user-initiated-browser-capture',notes:''};
 const warnings=['Review every field against the visible product page. Page markup and regional layouts can change. Numeric stock is required; an InStock label alone is not inventory.'];
 const products=[];
 function walk(obj,depth=0){if(!obj||depth>12)return;if(Array.isArray(obj)){obj.forEach(x=>walk(x,depth+1));return;}if(typeof obj!=='object')return;const t=obj['@type'];if(t==='Product'||Array.isArray(t)&&t.includes('Product'))products.push(obj);if(obj['@graph'])walk(obj['@graph'],depth+1);}
 for(const script of document.querySelectorAll('script[type="application/ld+json"]')){if(script.textContent.length>1000000)continue;try{walk(JSON.parse(script.textContent));}catch{}}
 if(products.length===1){const p=products[0];r.mpn=typeof p.mpn==='string'?p.mpn:'';r.sku=typeof p.sku==='string'?p.sku:'';const m=p.manufacturer||p.brand;r.manufacturer=typeof m==='string'?m:typeof m?.name==='string'?m.name:'';}
 else if(products.length>1)warnings.push('Multiple Product records found. Identity was not selected automatically.');
 const fields={
 'manufacturerpartnumber':'mpn','mfrpartnumber':'mpn','mfrpart':'mpn','mfrno':'mpn',
 'manufacturer':'manufacturer','digikeypartnumber':'sku','mouserpartnumber':'sku','mouserno':'sku',
 'packagecase':'package','supplierdevicepackage':'package','numberofpins':'pin_count','pincount':'pin_count',
 'mountingtype':'mounting','mountingstyle':'mounting','productstatus':'lifecycle','lifecycle':'lifecycle',
 'quantityavailable':'stock','availablequantity':'stock','instock':'stock','minimumorderquantity':'moq','ordermultiple':'order_multiple'
 };
 const candidates={};
 for(const row of document.querySelectorAll('tr')){
  if(row.getClientRects().length===0)continue; // never extract hidden tables
  const cells=[...row.querySelectorAll(':scope > th, :scope > td')];if(cells.length!==2)continue;
  const key=cells[0].innerText.trim().replace(/[^a-z0-9]/gi,'').toLowerCase(),value=cells[1].innerText.trim();const target=fields[key];
  if(target&&value&&value.length<1000){(candidates[target]??=[]).push(value);}
 }
 for(const [key,values] of Object.entries(candidates)){
  const v=[...new Set(values)];if(v.length!==1){warnings.push('Conflicting visible values for '+key+'; enter the correct product value manually.');continue;}
  let value=v[0];
  if(['stock','moq','order_multiple','pin_count'].includes(key)){const m=value.match(/^(\d+|\d{1,3}(?:,\d{3})+)(?:\s+(?:In Stock|Available))?$/i);if(!m){warnings.push(key+' contains non-numeric/ambiguous text; left blank.');continue;}value=m[1].replaceAll(',','');}
  if(key==='mounting'){value={'Surface Mount':'SMD','SMD/SMT':'SMD','Through Hole':'THT'}[value]||'';}
  if(r[key]&&r[key]!==value){warnings.push('Structured and visible '+key+' differ. Review identity; existing value retained.');continue;}
  r[key]=value;
 }
 if(!r.stock)warnings.push('No unambiguous numeric inventory detected. Copy an exact quantity from the page, or leave it unknown.');
 if(!r.mpn)warnings.push('Exact manufacturer MPN was not detected. Enter it manually, including its full suffix.');
 return {record:r,warnings};
}
