"""Explainable BOM screening, demand assessment, consolidation candidates.

This is a deterministic local rules engine, not an LLM or a component
qualification service. Missing evidence never counts as a health pass.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import csv
import io
import json
import math
import re
from .native import BASE, natural
from .engine import now
from .evidence import identity, supplier_links
from .footprints import Inspector, package_hint

DEFAULTS={'stock_age_hours':24,'region':'IN','library_roots':[],'board_path':'','dimension_tolerance_mm':0.05}
CRITICAL=['Tolerance','Voltage','Voltage Rating','Power','Power Rating','Dielectric','Temperature Coefficient','Tempco','Temperature Range','Qualification','AEC-Q','Technology','Current Rating']


def validated_settings(settings,current=None):
    if not isinstance(settings,dict) or set(settings)-set(DEFAULTS):raise ValueError('Unknown health setting.')
    merged={**DEFAULTS,**(current or {}),**settings}
    for key,lo,hi in [('stock_age_hours',0.01,8760),('dimension_tolerance_mm',0,1)]:
        v=merged[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+key)
    if not isinstance(merged['region'],str) or len(merged['region'])>50:raise ValueError('Invalid region.')
    if not isinstance(merged['library_roots'],list) or len(merged['library_roots'])>50 or any(not isinstance(p,str) or len(p)>4096 for p in merged['library_roots']):raise ValueError('Use a list of up to 50 footprint-library directories.')
    if not isinstance(merged['board_path'],str) or len(merged['board_path'])>4096:raise ValueError('Invalid board path.')
    return merged


def configure(ws,settings):
    merged=validated_settings(settings,ws.state.get('health_settings',{}))
    ws.commit('Configure local BOM health checks',lambda:ws.state.update(health_settings=merged))
    return merged


def normalized_value(value,reference='',lib_id=''):
    """R/C/L only; case-sensitive SI units, no MPN suffix decoding."""
    match=re.match(r'^(R|C|L)\d',reference)
    if not match:return None
    kind=match[1]
    s=str(value).strip().replace('µ','u').replace('μ','u').replace('Ω','Ohm')
    s=re.sub(r'\s+','',s)
    # 4k7, 4R7, R47 (resistance); 2u2 (capacitance/inductance).
    m=re.fullmatch(r'(\d*)([RrKkMmGgunp])([0-9]+)',s)
    if m:
        scale={'R':0,'r':0,'K':3,'k':3,'M':6,'m':-3,'G':9,'g':9,'u':-6,'n':-9,'p':-12}[m[2]]
        if kind!='R' and m[2] in ('R','r'):return None
        number=(m[1] or '0')+'.'+m[3]
    else:
        m=re.fullmatch(r'(\d+(?:\.\d*)?|\.\d+)([RrKkMmGgunp]?)(Ohms?|ohms?|F|H|f|h)?',s)
        if not m:return None
        unit=m[3]
        if unit and (kind=='R' and unit.lower() not in ('ohm','ohms') or kind=='C' and unit.lower()!='f' or kind=='L' and unit.lower()!='h'):return None
        scale={'':0,'R':0,'r':0,'K':3,'k':3,'M':6,'m':-3,'G':9,'g':9,'u':-6,'n':-9,'p':-12}[m[2]]
        number=m[1]
    try:
        result=Decimal(number)*(Decimal(10)**scale)
        if not result.is_finite() or len(s)>100:return None
        return kind+':'+str(result.normalize())
    except InvalidOperation:return None


def material_rows(rows):return [r for r in rows if r['fields']['Assembly']=='FIT' and r['flags']['in_bom']]


def demand(ws,rows):
    grouped=defaultdict(list)
    for r in material_rows(rows):
        f=r['fields'];key=identity(f.get('Manufacturer',''),f.get('MPN',''))
        if not key[1]:key=('',':missing:'+r['id'])
        grouped[key].append(r)
    result=[]
    factor=Decimal(ws.state['settings']['boards'])*(1+Decimal(str(ws.state['settings']['attrition']))/100)
    for key,items in grouped.items():
        f=items[0]['fields'];qty=int((len(items)*factor).to_integral_value(rounding=ROUND_CEILING))
        result.append({'identity':list(key),'manufacturer':f.get('Manufacturer',''),'mpn':f.get('MPN',''),
            'ids':[r['id'] for r in items],'references':[r['ref'] for r in items],
            'per_board':len(items),'required':qty,'links':supplier_links(f.get('MPN',''))})
    return result


def age_hours(record,clock):
    try:
        d=datetime.fromisoformat(record.get('observed_at','').replace('Z','+00:00'))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return (clock-d).total_seconds()/3600
    except (ValueError,TypeError):return None


def stock_status(req,records,settings,clock):
    offers={}
    for record in records:
        key=(str(record.get('supplier','')).casefold(),record.get('sku',''),str(record.get('region','')).casefold())
        # Same supplier/SKU/market observations replace each other; never add.
        old=offers.get(key)
        def order(r):
            age=age_hours(r,clock)
            return (float('-inf') if age is None else -age, r.get('imported_at',''))
        if old is None or order(record)>order(old):offers[key]=record
    result=[]
    for record in offers.values():
        age=age_hours(record,clock);reasons=[]
        if not record.get('reviewed'):reasons.append('not reviewed')
        if not record.get('source_url'):reasons.append('no source URL')
        if age is None:reasons.append('undated')
        elif age<0:reasons.append('future observation time')
        elif age>settings['stock_age_hours']:reasons.append('stale')
        if settings['region'] and str(record.get('region','')).casefold()!=settings['region'].casefold():reasons.append('market missing/different')
        if type(record.get('stock')) is not int:reasons.append('numeric stock unknown')
        qty=req['required'];moq=record.get('moq') or 1;multiple=record.get('order_multiple') or 1
        order=((max(qty,moq)+multiple-1)//multiple)*multiple
        eligible=not reasons
        result.append({'id':record['id'],'supplier':record['supplier'],'sku':record.get('sku',''),'region':record.get('region',''),
            'stock':record.get('stock'),'age_hours':None if age is None else round(age,2),'source_url':record.get('source_url',''),
            'observed_at':record.get('observed_at',''),'order_quantity':order,'eligible':eligible,'reasons':reasons,
            'covers':eligible and record['stock']>=order,'shortage':max(0,order-record['stock']) if eligible else None})
    usable=[r for r in result if r['eligible']]
    state='observed_covered' if any(r['covers'] for r in usable) else 'observed_shortage' if usable else 'unknown'
    return {'status':state,'offers':result,'note':'Timestamped observations only. Stocks are not reserved, never summed across supplier SKUs, and must be rechecked before ordering.'}


def run(ws,variant=BASE,clock=None):
    clock=clock or datetime.now(timezone.utc);settings=dict(DEFAULTS,**ws.state.get('health_settings',{}))
    rows=ws.rows(variant);issues=[];parts=[];inspector=Inspector(ws)
    records=ws.state.get('evidence',[]);bykey=defaultdict(list)
    for record in records:
        if record.get('manufacturer'):bykey[identity(record['manufacturer'],record['mpn'])].append(record)
    def add(severity,ref,code,message,evidence_ids=None):
        issues.append({'severity':severity,'reference':ref,'code':code,'message':message,'evidence_ids':evidence_ids or []})
    for old in ws.checks(variant,rows):issues.append(dict(old,evidence_ids=[]))
    for note in inspector.issues:add('warning','Project','LOCAL_INSPECTION',note)
    for row in rows:
        f=row['fields'];ref=row['ref'];start=len(issues)
        key=identity(f.get('Manufacturer',''),f.get('MPN',''))
        matched=bykey.get(key,[]) if all(key) else []
        package_records=[r for r in matched if r.get('reviewed') and r.get('source_url') and any(r.get(k) not in ('',None,[],{}) for k in ('package','pin_count','pin_numbers','pitch_mm','body_x_mm','mounting','pin_names','value'))]
        info=inspector.inspect(row);actual=info['selected'];hint=info['library']['hint'];symbol=info['symbol']
        if row['flags']['on_board']:
            if not f.get('Footprint'):add('error',ref,'FOOTPRINT_MISSING','No footprint selected for an on-board part.')
            elif not actual:add('unknown',ref,'FOOTPRINT_FILE_UNKNOWN','Selected footprint geometry could not be read. Configure footprint-library roots or provide a saved PCB. Name-only hints are not physical validation.')
            if info['board_ambiguous']:add('error',ref,'BOARD_REF_AMBIGUOUS','Multiple board footprints share this reference; cannot choose safely.')
            if info['board'] and info['board']['name']!=f.get('Footprint'):
                add('error',ref,'BOARD_ASSIGNMENT_MISMATCH','Saved PCB uses '+info['board']['name']+' but active schematic/variant selects '+str(f.get('Footprint'))+'. Update/review in KiCad.')
            if actual and symbol['pin_numbers'] and not symbol['issues']:
                missing=set(symbol['pin_numbers'])-set(actual['pin_numbers'])
                extra=set(actual['pin_numbers'])-set(symbol['pin_numbers'])
                if missing:add('error',ref,'SYMBOL_PAD_MISSING','Symbol pins missing corresponding numbered footprint pads: '+', '.join(sorted(missing,key=natural)))
                if extra:add('warning',ref,'EXTRA_NUMBERED_PADS','Footprint has additional numbered pads: '+', '.join(sorted(extra,key=natural))+'. Review exposed/mechanical/NC pads; counts alone do not establish electrical compatibility.')
            if symbol['issues']:add('unknown',ref,'SYMBOL_PIN_UNKNOWN','; '.join(symbol['issues']))
            if not package_records:add('unknown',ref,'PART_PACKAGE_UNKNOWN','No reviewed package/pin evidence with source link for this exact manufacturer + complete MPN. Matching footprint text alone is not enough.')
        if f.get('MPN') and not f.get('Manufacturer'):add('warning',ref,'MANUFACTURER_MISSING','Manufacturer is needed for an unambiguous supplier/package match.')
        comparisons=0
        if info.get('board_path_mismatch'):add('error',ref,'BOARD_INSTANCE_MISMATCH','PCB footprint reference matches, but its saved schematic UUID path differs. Board fallback geometry was not used.')
        if info['board'] and info['library'].get('data') and info['board']['name']==f.get('Footprint'):
            if set(info['board']['data']['pin_numbers'])!=set(info['library']['data']['pin_numbers']):
                add('error',ref,'BOARD_LIBRARY_PAD_DIFFERENCE','Saved PCB and selected library footprint have different numbered pad sets despite sharing the same footprint name.')
        # Contradictory records are surfaced, not averaged or silently overwritten.
        for field in ('package','pin_count','pitch_mm','mounting','pin_numbers','pin_names'):
            vals={json.dumps(r.get(field),sort_keys=True) for r in package_records if r.get(field) not in ('',None,[],{})}
            if len(vals)>1:add('warning',ref,'EVIDENCE_CONFLICT','Exact-MPN evidence differs for '+field+'. Review source/package suffix; screening is incomplete.',[r['id'] for r in package_records])
        for record in package_records:
            source=[record['id']];expected=package_hint(record.get('package',''))
            if record.get('value'):
                a=normalized_value(f.get('Value',''),ref,row['lib_id']);b=normalized_value(record['value'],ref,row['lib_id'])
                if a and b and a!=b:add('error',ref,'PART_VALUE_MISMATCH','BOM nominal value '+str(f.get('Value',''))+' differs from exact-MPN evidence '+record['value']+'. Review the selected MPN/value.',source)
            for key,names in [('tolerance',['Tolerance']),('voltage_rating',['Voltage Rating','Voltage']),('power_rating',['Power Rating','Power']),('dielectric',['Dielectric'])]:
                displayed=next((str(f[n]) for n in names if f.get(n)), '')
                if record.get(key) and displayed and re.sub(r'\s+','',displayed).casefold()!=re.sub(r'\s+','',str(record[key])).casefold():
                    add('warning',ref,'RATING_METADATA_REVIEW','BOM '+names[0]+' '+displayed+' differs from part evidence '+str(record[key])+'. This is a metadata discrepancy, not an assumed derating requirement.',source)
            if expected['family'] and hint['family']:
                comparisons+=1
                if expected['family']!=hint['family']:add('warning',ref,'PACKAGE_FAMILY_MISMATCH','Package label suggests '+expected['family']+'; footprint name suggests '+hint['family']+'. Verify the manufacturer land pattern; aliases are not guessed.',source)
            pitch=record.get('pitch_mm') or expected['pitch_mm']
            if pitch and hint['pitch_mm']:
                comparisons+=1
                if abs(pitch-hint['pitch_mm'])>settings['dimension_tolerance_mm']:add('warning',ref,'PITCH_NAME_MISMATCH',f'Expected pitch {pitch:g} mm vs footprint-name pitch {hint["pitch_mm"]:g} mm. Compare the actual drawing and pad centres.',source)
            dims=[record.get('body_x_mm'),record.get('body_y_mm')]
            if all(dims) and hint['body_mm']:
                comparisons+=1
                if any(abs(a-b)>settings['dimension_tolerance_mm'] for a,b in zip(sorted(dims),sorted(hint['body_mm']))):add('warning',ref,'BODY_NAME_MISMATCH','Evidence body dimensions differ from footprint-name body dimensions; not a full land-pattern comparison.',source)
            if actual:
                if record.get('mounting') and actual.get('mounting'):
                    comparisons+=1
                    if record['mounting']!=actual['mounting']:add('error',ref,'MOUNTING_MISMATCH','Part evidence mounting '+record['mounting']+' differs from read footprint pad types '+actual['mounting']+'.',source)
                if record.get('pin_numbers'):
                    comparisons+=1
                    if set(record['pin_numbers'])!=set(actual['pin_numbers']):add('error',ref,'PART_PAD_SET_MISMATCH','Exact expected pin-number set differs from the selected footprint’s unique electrical pad numbers.',source)
                elif record.get('pin_count'):
                    comparisons+=1
                    if record['pin_count']!=actual['unique_electrical_pads']:add('warning',ref,'PART_PAD_COUNT_MISMATCH',f'Part lists {record["pin_count"]} pins; footprint has {actual["unique_electrical_pads"]} unique numbered pads. Exposed pads/count conventions require review.',source)
            if record.get('exposed_pad') is False and hint['exposed_pad'] is True:add('warning',ref,'EXPOSED_PAD_MISMATCH','Part evidence says no exposed pad; footprint name indicates an exposed pad.',source)
            if record.get('pin_names') and symbol['pin_names'] and not symbol['issues']:
                comparisons+=1
                for number,name in record['pin_names'].items():
                    if number not in symbol['pin_names']:add('warning',ref,'PART_SYMBOL_PIN_MISSING','Evidence pin '+number+' is missing from embedded symbol pins.',source)
                    elif name.strip().casefold()!=symbol['pin_names'][number].strip().casefold():add('warning',ref,'PIN_FUNCTION_REVIEW',f'Pin {number}: evidence name {name} vs symbol name {symbol["pin_names"][number]}. Alias/function mapping needs review.',source)
        recent_codes=[i['code'] for i in issues[start:]]
        parts.append({'id':row['id'],'reference':ref,'mpn':f.get('MPN',''),'manufacturer':f.get('Manufacturer',''),'footprint':f.get('Footprint',''),
            'inspection':info,'matched_evidence':[r['id'] for r in matched],'comparisons':comparisons,
            'package_status':'not_on_board' if not row['flags']['on_board'] else 'review_required' if any(i['severity'] in ('warning','error') for i in issues[start:]) else 'unknown' if not actual or not comparisons else 'screened_only',
            'issue_codes':recent_codes,'links':supplier_links(f.get('MPN',''))})
    demands=demand(ws,rows)
    for req in demands:
        matched=bykey.get(tuple(req['identity']),[]) if all(req['identity']) else []
        req['stock']=stock_status(req,matched,settings,clock)
        ref=', '.join(req['references'])
        if req['stock']['status']=='observed_shortage':add('warning',ref,'STOCK_SHORTAGE',f'No single eligible observed offer covers demand {req["required"]} including its MOQ/order multiple. Check other sources; this is not proof of a global shortage.',[r['id'] for r in matched])
        elif req['stock']['status']=='unknown':add('unknown',ref,'STOCK_UNKNOWN','No recent, dated, reviewed exact-MPN numeric stock for the configured market. Unknown is not zero stock.',[r['id'] for r in matched])
        risky=[r for r in matched if str(r.get('lifecycle','')).strip().lower() in ('obsolete','eol','end of life','nrnd','not recommended for new designs','discontinued')]
        if risky:add('warning',ref,'PART_LIFECYCLE','Evidence includes an adverse lifecycle state. Review its date and manufacturer PCN.',[r['id'] for r in risky])
    counts=Counter(i['severity'] for i in issues)
    on_board=sum(r['flags']['on_board'] for r in rows)
    return {'schema':'wayricad-health-1','generated_at':clock.isoformat(),'variant':variant,'revision':ws.revision,
        'settings':settings,'summary':{'components':len(rows),'errors':counts['error'],'warnings':counts['warning'],'unknowns':counts['unknown'],
        'on_board_parts':on_board,'geometry_read':sum(bool(p['inspection']['selected']) for p in parts),
        'with_exact_evidence':sum(bool(p['matched_evidence']) for p in parts),'purchasing_identities':len(demands),
        'stock_observed_covered':sum(d['stock']['status']=='observed_covered' for d in demands),'evidence_records':len(records)},
        'status':'review_required' if counts['error'] or counts['warning'] else 'incomplete' if counts['unknown'] else 'screened_not_qualified',
        'issues':issues,'parts':parts,'demand':demands,
        'limits':['No electrical equivalence, thermal/voltage derating, pad dimensions/solder-mask/courtyard qualification, or complete pinout certification.',
                  'Package-name geometry is heuristic. Read pad sets are stronger evidence, but even equal pin counts do not imply a fit.',
                  'No automatic network stock refresh. Observations are human-reviewed inputs, not authenticated supplier responses or reservations.',
                  'Only active-variant demand is counted. DNP/DNI and BOM-excluded components do not consume purchasing stock.',
                  'Health is an advisory report; existing export data checks remain separate. A checked BOM is not a health qualification.']}


def analyze(ws,variant=BASE):
    rows=ws.rows(variant);buckets=defaultdict(list);items=[];normalizations=[]
    for r in material_rows(rows):
        f=r['fields'];norm=normalized_value(f.get('Value',''),r['ref'],r['lib_id'])
        key=(norm or ('raw:'+str(f.get('Value',''))),str(f.get('Footprint','')),r['lib_id'] if not norm else norm.split(':')[0])
        buckets[key].append(r)
    for (value,footprint,kind),members in buckets.items():
        raw_values=sorted({r['fields'].get('Value','') for r in members})
        identities={identity(r['fields'].get('Manufacturer',''),r['fields'].get('MPN','')) for r in members}
        if len(members)<2:continue
        if len(raw_values)>1 and not value.startswith('raw:'):
            normalizations.append({'references':[r['ref'] for r in members],'ids':[r['id'] for r in members],'values':raw_values,'normalized':value,
                'note':'Numerically equivalent passive labels; raw variables are preserved unless an edit is explicitly reviewed.'})
        differing=[];missing=[]
        for field in CRITICAL:
            vals=[str(r['fields'].get(field,'')).strip() for r in members]
            if len(set(v for v in vals if v))>1:differing.append(field)
            if any(not v for v in vals):missing.append(field)
        if len(identities)>1:
            status='blocked_by_recorded_differences' if differing else 'candidate_needs_qualification'
            items.append({'references':[r['ref'] for r in members],'ids':[r['id'] for r in members],'normalized_value':value,'footprint':footprint,
                'identities':[{'manufacturer':m,'mpn':p} for m,p in sorted(identities)],'potential_line_reduction':len(identities)-1,
                'status':status,'differing_constraints':differing,'missing_constraints':missing,
                'reason':'Same normalized nominal value and exact selected footprint, but different order identities. Do not substitute until all ratings, technology, tolerance, pinout and qualification are reviewed.'})
    exact=[]
    for req in demand(ws,rows):
        if req['per_board']>1 and all(req['identity']):exact.append(req)
    return {'schema':'wayricad-analysis-1','generated_at':now(),'variant':variant,'revision':ws.revision,'normalization_opportunities':normalizations,
        'consolidation_candidates':items,'exact_identity_aggregation':exact,
        'summary':{'candidate_groups':len(items),'normalization_groups':len(normalizations),'exact_repeat_identities':len(exact),
            'potential_line_reduction_upper_bound':sum(i['potential_line_reduction'] for i in items if i['status']!='blocked_by_recorded_differences')},
        'warning':'Candidate counts are not approved substitutions, guaranteed savings or distinct globally deduplicated SKU savings. No nearest-E-series substitution or automatic MPN suffix stripping.'}


def supplier_request(ws,variant=BASE,supplier='DigiKey'):
    if supplier not in ('DigiKey','Mouser'):raise ValueError('Choose DigiKey or Mouser.')
    from .exporters import safe_csv
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['Manufacturer Part Number','Manufacturer','Quantity','Customer Reference'])
    for item in demand(ws,ws.rows(variant)):
        writer.writerow([safe_csv(item['mpn']),safe_csv(item['manufacturer']),item['required'],safe_csv(', '.join(item['references']))])
    return out.getvalue().encode('utf-8-sig'),'WayriCAD_'+supplier+'_BOM_request.csv','text/csv; charset=utf-8'
