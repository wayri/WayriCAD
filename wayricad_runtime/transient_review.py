"""Offline review of exact lumped transient samples, without interpolation."""
from __future__ import annotations

from html import escape
import json


def review_rows(result):
    """Summarize each simulated unit; unspecified limits remain unevaluated."""
    is_pi = 'loads' in result
    rows = []
    for index, unit in enumerate(result['loads' if is_pi else 'components']):
        values = unit['voltage_V' if is_pi else 'temperature_c']
        limits = unit.get('limits', {}) if is_pi else {'maximum': unit.get('limit_c')}
        evaluated = any(value is not None for value in limits.values())
        failed = bool(unit.get('violations')) if is_pi else unit.get('limit_exceeded', False)
        rows.append(dict(index=index, label=str(unit.get('label') or unit.get('reference') or unit['id']),
                         minimum=min(values), maximum=max(values), final=values[-1],
                         status='FAIL' if failed else 'PASS' if evaluated else 'NOT EVALUATED',
                         limit_text=json.dumps(limits, ensure_ascii=False, allow_nan=False)))
    return rows


def review_html(bundle):
    """Render a selectable summary and one bounded exact-sample trace at a time."""
    result = bundle['transient']; is_pi = 'loads' in result
    units = result['loads' if is_pi else 'components']; rows = review_rows(result)
    unit_name = 'V' if is_pi else '°C'
    table = '<h2>Unit summary</h2><p>Select a row to inspect its raw samples. PASS applies only to specified limits; it is not model qualification.</p><table id="transient-units"><thead><tr>'
    table += ''.join('<th>'+label+'</th>' for label in ('Unit', 'Minimum · '+unit_name, 'Maximum · '+unit_name, 'Final · '+unit_name, 'Limits', 'Result'))
    table += '</tr></thead><tbody>'
    for row in rows:
        table += '<tr data-unit="'+str(row['index'])+'"><td><button type="button" data-unit="'+str(row['index'])+'">'+escape(row['label'])+'</button></td>'
        table += ''.join('<td>'+escape(f'{row[key]:.8g}')+'</td>' for key in ('minimum', 'maximum', 'final'))
        table += '<td>'+escape(row['limit_text'])+'</td><td>'+row['status']+'</td></tr>'
    table += '</tbody></table>'
    data = dict(times=result['times_s'], phases=result.get('sample_phase'), unit=unit_name,
                secondary='Requested current · A' if is_pi else 'Applied power · W',
                rows=[dict(label=row['label'], values=unit['voltage_V' if is_pi else 'temperature_c'],
                           secondary=unit['requested_current_A' if is_pi else 'power_W'])
                      for row, unit in zip(rows, units)])
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c')
    controls = '<h2>Exact time samples</h2><p>Choose a unit, hover the trace or move the sample slider. Click the trace to retain a probe. Duplicate event timestamps retain their before/after phase. Lines connect computed samples for display only.</p>'
    controls += '<label>Unit <select id="transient-unit">'+''.join('<option value="'+str(row['index'])+'">'+escape(row['label'])+'</option>' for row in rows)+'</select></label> '
    controls += '<label>Sample <input id="transient-sample" type="range" min="0" max="'+str(len(data['times'])-1)+'" value="0"></label> '
    controls += '<button id="transient-pin" type="button">Pin sample</button> <button id="transient-clear" type="button">Clear probes</button><output id="transient-value" aria-live="polite"></output>'
    controls += '<canvas id="transient-trace" aria-label="Selected unit computed time samples" style="width:100%;height:300px;display:block;touch-action:none"></canvas><ol id="transient-probes"></ol>'
    return table+controls+'<script>(()=>{const data='+payload+';'+_SCRIPT+'})();</script>'


_SCRIPT = r'''
const select=document.getElementById('transient-unit'),slider=document.getElementById('transient-sample'),canvas=document.getElementById('transient-trace'),ctx=canvas.getContext('2d'),output=document.getElementById('transient-value'),probes=document.getElementById('transient-probes');
let selected=0,index=0;
const format=v=>Number(v).toPrecision(8);
function description(){const r=data.rows[selected];return r.label+' | sample '+index+' | t '+format(data.times[index])+' s'+(data.phases?' | '+data.phases[index]:'')+' | '+format(r.values[index])+' '+data.unit+' | '+data.secondary+' '+format(r.secondary[index]);}
function draw(){const r=data.rows[selected],values=r.values,w=canvas.width=Math.max(280,Math.round(canvas.clientWidth)),h=canvas.height=300;
 let lo=Infinity,hi=-Infinity;for(const v of values){lo=Math.min(lo,v);hi=Math.max(hi,v);}const t0=data.times[0],span=data.times[data.times.length-1]-t0||1,scale=hi-lo||1;
 const x=i=>55+(data.times[i]-t0)/span*(w-75),y=v=>260-(v-lo)/scale*225;
 ctx.clearRect(0,0,w,h);ctx.fillStyle='#203744';ctx.font='12px sans-serif';ctx.fillText(format(hi)+' '+data.unit,4,20);ctx.fillText(format(lo)+' '+data.unit,4,276);ctx.fillText('Time (s) · '+format(t0)+' to '+format(t0+span),55,294);
 ctx.strokeStyle='#147f94';ctx.lineWidth=1.5;ctx.beginPath();values.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v)));ctx.stroke();ctx.strokeStyle='#ae5b23';ctx.beginPath();ctx.moveTo(x(index),25);ctx.lineTo(x(index),265);ctx.stroke();ctx.fillStyle='#ae5b23';ctx.beginPath();ctx.arc(x(index),y(values[index]),4,0,Math.PI*2);ctx.fill();output.textContent=description();
}
function choose(value){selected=Number(value);select.value=String(selected);document.querySelectorAll('#transient-units tr[data-unit]').forEach(row=>{row.style.background=Number(row.dataset.unit)===selected?'#dff1f3':'';row.setAttribute('aria-selected',String(Number(row.dataset.unit)===selected));});draw();}
function sample(value){index=Math.max(0,Math.min(data.times.length-1,Number(value)));slider.value=String(index);draw();}
select.onchange=()=>choose(select.value);slider.oninput=()=>sample(slider.value);
document.querySelectorAll('#transient-units button[data-unit]').forEach(button=>button.onclick=()=>choose(button.dataset.unit));
function pin(){if(probes.children.length>=100){output.textContent='100 probes retained; clear probes before adding more.';return;}const li=document.createElement('li');li.textContent=description();probes.append(li);}
document.getElementById('transient-pin').onclick=pin;document.getElementById('transient-clear').onclick=()=>probes.replaceChildren();
canvas.onpointermove=event=>{const rect=canvas.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,((event.clientX-rect.left)*canvas.width/rect.width-55)/(canvas.width-75))),target=data.times[0]+fraction*(data.times[data.times.length-1]-data.times[0]);let low=0,high=data.times.length-1;while(low<high){let mid=(low+high)>>1;if(data.times[mid]<target)low=mid+1;else high=mid;}if(low>0&&target-data.times[low-1]<data.times[low]-target)low--;sample(low);};
canvas.onclick=pin;new ResizeObserver(draw).observe(canvas);choose(0);
'''
