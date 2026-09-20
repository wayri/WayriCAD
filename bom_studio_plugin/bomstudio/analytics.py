"""Read-only, evidence-explicit BOM cost/mass/power analytics.

One row is one physical component from Workspace.rows(), not one graphical unit.
Unknown measurements are never replaced by zero. All arithmetic is decimal.
This module is shared by the browser, CLI and release/job-set pipeline.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, localcontext
import json
import re
from . import __version__
from . import measures as m
from .native import BASE, natural, sha
from .engine import now

D = Decimal
SCHEMA = 'wayricad-analytics-config-1'
DEFAULT = {
    'pcb': {},
    'schema': SCHEMA, 'metrics': ['pricing', 'mass', 'thermal'], 'scenario_name': 'Nominal',
    'price_field': 'UnitPrice', 'currency_field': 'Currency', 'currency_default': '',
    'price_per': '1', 'price_per_field': '', 'moq_field': 'MOQ', 'multiple_field': 'OrderMultiple',
    'supplier_field': 'Supplier', 'sku_field': 'SKU', 'quote_date_field': 'PriceDate', 'quote_max_age_days': 90,
    'mass_field': 'Mass', 'mass_unit': 'g', 'power_field': 'Dissipation', 'power_unit': 'W',
    'power_basis': 'average', 'duty_field': '', 'duty_percent': '100', 'rating_field': '',
    'temperature_field': 'Temp_Max', 'temperature_unit': 'C', 'temperature_requirement_c': None,
    'type_field': 'ComponentType', 'group_by': ['@type'], 'statistics': {}, 'field_units': {},
    'query': '', 'case_sensitive': False, 'physical_include_bom_excluded': True,
    'boards': None, 'attrition_percent': None, 'scenario_boards': [1, 10, 100],
    'budgets': {'cost_per_board': {}, 'mass_g': None, 'power_w': None},
    'fx': {'base_currency': '', 'rates': {}, 'as_of': '', 'source': ''},
}
TYPES = {'R':'Resistor', 'RN':'Resistor network', 'C':'Capacitor', 'L':'Inductor',
         'U':'Integrated circuit', 'IC':'Integrated circuit', 'Q':'Transistor', 'D':'Diode',
         'J':'Connector', 'P':'Connector', 'F':'Fuse', 'Y':'Crystal / oscillator',
         'X':'Crystal / oscillator', 'SW':'Switch', 'TP':'Test point', 'H':'Mechanical',
         'BT':'Battery', 'BAT':'Battery', 'T':'Transformer', 'RV':'Variable resistor',
         'FB':'Ferrite bead', 'LED':'LED'}
OPTIONAL_FIELDS = {'currency_field', 'price_per_field', 'moq_field', 'multiple_field',
                   'supplier_field', 'sku_field', 'quote_date_field', 'duty_field',
                   'rating_field', 'temperature_field', 'type_field'}


def _number(value, label, lower=0, upper='1e12'):
    n = m.scalar(value)
    if n is None or n < D(str(lower)) or n > D(str(upper)):
        raise ValueError(label + ' must be a finite decimal between ' + str(lower) + ' and ' + str(upper) + '.')
    return n


def _integer(value, label, lower=1, upper=1000000000):
    n = _number(value, label, lower, upper)
    if n != n.to_integral_value():
        raise ValueError(label + ' must be an integer.')
    return int(n)


def _field(value, optional=False):
    if not isinstance(value, str) or (not optional and not value.strip()) or len(value) > 1000 or any(ord(c) < 32 for c in value):
        raise ValueError('Field names must be text without control characters (maximum 1,000 characters).')
    return value


def _currency(value, optional=False):
    if optional and value == '': return ''
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z]{3}', value):
        raise ValueError('Currency must be an explicit three-letter uppercase code, such as INR, USD or EUR.')
    return value


def validate_config(config=None):
    if config is None: config = {}
    if not isinstance(config, dict) or set(config) - set(DEFAULT):
        raise ValueError('Unknown analytics configuration keys.')
    c = deepcopy(DEFAULT); c.update(deepcopy(config))
    from .pcb_estimates import validate as validate_pcb
    c['pcb']=validate_pcb(c['pcb'])
    if c['schema'] != SCHEMA: raise ValueError('Expected ' + SCHEMA + '.')
    if not isinstance(c['metrics'], list) or not c['metrics'] or len(c['metrics']) > 3 or any(not isinstance(x,str) or x not in ('pricing','mass','thermal') for x in c['metrics']) or len(set(c['metrics'])) != len(c['metrics']):
        raise ValueError('Choose unique analytics metrics: pricing, mass, thermal.')
    for key in DEFAULT:
        if key.endswith('_field'):
            _field(c[key], key in OPTIONAL_FIELDS)
    if not isinstance(c['scenario_name'], str) or not c['scenario_name'].strip() or len(c['scenario_name']) > 128 or any(ord(x)<32 for x in c['scenario_name']):
        raise ValueError('Scenario name must contain 1–128 printable characters.')
    _currency(c['currency_default'], True)
    c['price_per'] = str(_integer(c['price_per'], 'Price per units'))
    c['quote_max_age_days'] = _integer(c['quote_max_age_days'], 'Maximum quote age', 0, 36500)
    for key, dim in (('mass_unit','mass'), ('power_unit','power'), ('temperature_unit','temperature')):
        c[key] = m.unit_name(c[key])
        if m.UNITS[c[key]][0] != dim: raise ValueError(key + ' has the wrong dimension.')
    if c['power_basis'] not in ('average', 'active'): raise ValueError('Power basis must be average or active.')
    c['duty_percent'] = m.text(_number(c['duty_percent'], 'Duty percent', 0, 100))
    if c['rating_field'] and c['rating_field'] == c['power_field']:
        raise ValueError('Dissipation and rated-power fields must be different. A rating is not an operating loss.')
    if c['temperature_requirement_c'] is not None:
        c['temperature_requirement_c'] = m.text(_number(c['temperature_requirement_c'], 'Required maximum temperature (C)', '-273.15', '100000'))
    if c['boards'] is not None: c['boards'] = _integer(c['boards'], 'Build quantity')
    if c['attrition_percent'] is not None:
        c['attrition_percent'] = m.text(_number(c['attrition_percent'], 'Attrition percent', 0, 10000))
    if not isinstance(c['scenario_boards'],list) or len(c['scenario_boards']) > 20:
        raise ValueError('Provide at most 20 build-quantity scenarios.')
    c['scenario_boards'] = [_integer(n, 'Scenario quantity') for n in c['scenario_boards']]
    if len(set(c['scenario_boards'])) != len(c['scenario_boards']): raise ValueError('Scenario quantities must be unique.')
    for key in ('case_sensitive','physical_include_bom_excluded'):
        if type(c[key]) is not bool: raise ValueError(key + ' must be a boolean.')
    if not isinstance(c['query'], str): raise ValueError('Analytics query must be text.')
    from .search import Parser
    Parser(c['query']).parse()
    if not isinstance(c['group_by'],list) or not 1 <= len(c['group_by']) <= 8 or any(not isinstance(x,str) for x in c['group_by']) or len(set(c['group_by'])) != len(c['group_by']):
        raise ValueError('Choose 1–8 unique breakdown fields.')
    for field in c['group_by']:
        _field(field)
        if field.startswith('@') and field not in ('@type','@population'): raise ValueError('Unknown synthetic breakdown field: '+field)
    for key in ('statistics','field_units'):
        if not isinstance(c[key],dict) or len(c[key]) > 50: raise ValueError(key+' supports at most 50 field/unit mappings.')
        for field, unit in c[key].items(): _field(field); c[key][field] = m.unit_name(unit)
    budget = c['budgets']
    if not isinstance(budget,dict) or set(budget)-set(DEFAULT['budgets']): raise ValueError('Unknown analytics budget options.')
    c['budgets'] = {**deepcopy(DEFAULT['budgets']), **budget}
    if not isinstance(c['budgets']['cost_per_board'],dict) or len(c['budgets']['cost_per_board']) > 30:
        raise ValueError('Cost budgets must map currency codes to per-board amounts.')
    for currency, amount in c['budgets']['cost_per_board'].items():
        _currency(currency); c['budgets']['cost_per_board'][currency] = m.text(_number(amount, 'Cost budget'))
    for key in ('mass_g','power_w'):
        if c['budgets'][key] is not None: c['budgets'][key] = m.text(_number(c['budgets'][key],key))
    fx = c['fx']
    if not isinstance(fx,dict) or set(fx)-set(DEFAULT['fx']): raise ValueError('Unknown FX configuration options.')
    c['fx'] = {**deepcopy(DEFAULT['fx']), **fx}; fx=c['fx']
    _currency(fx['base_currency'], True)
    if not isinstance(fx['rates'],dict) or len(fx['rates']) > 30: raise ValueError('FX rates must be a currency/rate object (at most 30).')
    for currency, rate in fx['rates'].items():
        _currency(currency); n=_number(rate, 'FX rate', '0.000000001', '1e9'); fx['rates'][currency]=m.text(n)
        if currency == fx['base_currency'] and n != 1: raise ValueError('A base currency has exchange rate 1.')
    for key in ('as_of','source'):
        if not isinstance(fx[key],str) or len(fx[key]) > 1000 or any(ord(x)<32 for x in fx[key]): raise ValueError('FX provenance must be bounded printable text.')
    if fx['rates']:
        if not fx['base_currency'] or not fx['source'].strip(): raise ValueError('Enter FX base currency, source and observation date; rates are user-supplied, not live.')
        try: datetime.fromisoformat(fx['as_of'].replace('Z','+00:00'))
        except (ValueError,TypeError): raise ValueError('FX as_of must be an ISO date or timestamp.')
    units_for_config(c)  # Reject conflicting dimensional declarations.
    return c


def units_for_config(c):
    from .search import split_field
    units={}
    declarations=[(c[key],unit) for key,unit in (
        ('mass_field',c['mass_unit']),('power_field',c['power_unit']),
        ('rating_field',c['power_unit']),('temperature_field',c['temperature_unit']),('duty_field','%')) if c[key]]
    declarations.extend(c['statistics'].items());declarations.extend(c['field_units'].items())
    for field,unit in declarations:
        field=split_field(field)[1].removeprefix('@field:')
        if field in units and units[field]!=unit:
            raise ValueError('Conflicting default units for mapped field '+field+'. Use the same default unit in metrics, statistics and filters.')
        units[field]=unit
    # Exact-property columns refer to the same authored measurements, not new units.
    return {**units,**{'@field:'+field:unit for field,unit in units.items()}}


def units_for(ws):
    return units_for_config(validate_config(ws.state.get('analytics_settings',{})))


def configure(ws, config):
    c=validate_config(config)
    ws.commit('Configure cost, mass and dissipation analytics', lambda:ws.state.update(analytics_settings=c))
    return {'ok':True, 'settings':c, 'native_files_written':False}


def defaults(ws):
    c=validate_config(ws.state.get('analytics_settings',{}))
    return c


def _value(row, field):
    if not field: return ''
    from .search import get_value
    # Workspace supplies a convenience Currency default. Analytics records its
    # own explicit fallback rather than pretending it was authored in a symbol.
    if field == 'Currency' and not any(str(row.get('raw',{}).get(k,'')).strip() for k in ('Currency',row.get('field_name_sources',{}).get('Currency'))):
        return ''
    return get_value(row, field)


def provenance(row, field):
    if not field: return {'field':'','raw_name':'','raw_value':'','resolved_value':''}
    name=field.removeprefix('raw.').removeprefix('resolved.')
    source=row.get('field_name_sources',{}).get(name,name)
    return {'field':field, 'raw_name':source, 'raw_value':row.get('raw',{}).get(source,''), 'resolved_value':_value(row,field)}


def component_type(row, field):
    custom=str(_value(row,field)).strip()
    if custom: return custom, 'field:'+field
    prefix=re.match(r'[A-Za-z]+', row['ref'])
    return TYPES.get(prefix[0].upper() if prefix else '', 'Other / unclassified'), 'reference-prefix heuristic'


_SYMBOLS={'₹':{'INR'}, '€':{'EUR'}, '£':{'GBP'}, '$':{'USD','CAD','AUD','NZD','SGD','HKD','MXN'}, '¥':{'JPY','CNY'}}


def money(raw, currency_raw, fallback):
    """Amount, currency, status, reason, currency provenance. No FX guessing."""
    s=str(raw).strip(); field_currency=str(currency_raw).strip().upper()
    if field_currency and not re.fullmatch(r'[A-Z]{3}',field_currency): return None,'','invalid','Invalid currency field.',''
    embedded=''; symbol=''
    a=re.match(r'^([A-Z]{3})\s+(.+)$',s)
    b=re.match(r'^(.+?)\s+([A-Z]{3})$',s)
    if a: embedded,s=a[1],a[2]
    elif b: s,embedded=b[1],b[2]
    elif s[:1] in _SYMBOLS: symbol,s=s[0],s[1:].strip()
    elif s[-1:] in _SYMBOLS: symbol,s=s[-1],s[:-1].strip()
    if embedded and field_currency and embedded != field_currency:
        return None,field_currency,'invalid','Price currency conflicts with currency field.','field'
    currency=field_currency or embedded
    source='field' if field_currency else 'price' if embedded else 'default'
    if not currency and symbol and len(_SYMBOLS[symbol])==1:
        currency=next(iter(_SYMBOLS[symbol])); source='price symbol'
    currency=currency or fallback
    if symbol and currency not in _SYMBOLS[symbol]:
        return None,currency,'invalid','Ambiguous or contradictory currency symbol; supply a matching currency code.',''
    amount=m.parse(s,'number',nonnegative=True)
    return amount.value,currency,amount.status,amount.reason,source


def _count(row, field, default, label):
    s=str(_value(row,field)).strip() if field else ''
    if not s: return default, False, ''
    try: return _integer(s,label), False, ''
    except ValueError as exc: return None, True, str(exc)


def _ceil(value): return int(value.to_integral_value(rounding=ROUND_CEILING))


def _summary(values, eligible, boards):
    known=[q['value'] for q in values if q['status']=='known']
    counts=Counter(q['status'] for q in values)
    status='not_applicable' if not eligible else 'unknown' if not known else 'complete' if len(known)==eligible else 'partial'
    subtotal=sum(known,D(0)) if known else None
    return {'status':status, 'eligible_components':eligible, 'known_components':len(known),
            'missing_components':counts['missing'], 'invalid_components':counts['invalid'],
            'coverage_percent':D(len(known))*100/eligible if eligible else None,
            'known_per_board':subtotal, 'known_build_total':subtotal*boards if subtotal is not None else None}


def _json(data):
    if isinstance(data,D): return m.text(data)
    if isinstance(data,dict): return {k:_json(v) for k,v in data.items()}
    if isinstance(data,(list,tuple)): return [_json(v) for v in data]
    return data


def _metric(q):
    return {'value':q.value, 'status':q.status, 'input_unit':q.input_unit, 'assumed_unit':q.assumed_unit, 'reason':q.reason}


def run(ws, variant=BASE, config=None):
    with localcontext() as ctx:
        ctx.prec=40
        return _run(ws,variant,config)


def _run(ws, variant, config):
    ws.variant_chain(variant); ws.project.check_unchanged()
    c=validate_config(ws.state.get('analytics_settings',{}) if config is None else config)
    boards=c['boards'] if c['boards'] is not None else _integer(ws.state['settings']['boards'],'Build quantity')
    attrition=D(c['attrition_percent']) if c['attrition_percent'] is not None else _number(ws.state['settings']['attrition'],'Attrition percent',0,10000)
    currency_default=c['currency_default'] or _currency(ws.state['settings']['currency'])
    c=deepcopy(c);c.update(boards=boards,attrition_percent=m.text(attrition),currency_default=currency_default)
    from . import search
    all_rows=ws.rows(variant)
    rows,_=search.select(ws,variant,c['query'],c['case_sensitive'],all_rows,field_units=units_for_config(c))
    known_fields=set().union(*(set(r['fields'])|set(r['raw']) for r in all_rows)) if all_rows else set()
    issues=[]
    def issue(severity, code, message, ref='', field=''):
        issues.append({'severity':severity,'code':code,'message':message,'reference':ref,'field':field})
    if not rows: issue('unknown','EMPTY_ANALYTICS_SCOPE','No components match this analytics scope. Empty totals are not a qualified zero.')
    mapped=[]
    if 'pricing' in c['metrics']: mapped.extend([c['price_field'], c['price_per_field']])
    if 'mass' in c['metrics']: mapped.append(c['mass_field'])
    if 'thermal' in c['metrics']: mapped.extend([c['power_field'], c['rating_field'], c['temperature_field'],c['duty_field'] if c['power_basis']=='active' else ''])
    mapped.extend(c['statistics'])
    for field in dict.fromkeys(x for x in mapped if x):
        if search.split_field(field)[1] not in known_fields:
            issue('warning','MAPPED_FIELD_ABSENT','Mapped field does not exist in this project; its observations remain missing.',field=field)
    for field in c['group_by']:
        if not field.startswith('@') and search.split_field(field)[1] not in known_fields:
            raise ValueError('Unknown analytics breakdown field: '+field)
    parts=[]; lots={}; current=datetime.now(timezone.utc)
    for r in rows:
        typ,type_source=component_type(r,c['type_field'])
        fitted=r['fields']['Assembly']=='FIT'
        price_eligible=fitted and r['flags']['in_bom'] and 'pricing' in c['metrics']
        physical=fitted and r['flags']['on_board'] and (r['flags']['in_bom'] or c['physical_include_bom_excluded'])
        part={'id':r['id'],'reference':r['ref'],'value':r['fields'].get('Value',''), 'footprint':r['fields'].get('Footprint',''),
              'mpn':r['fields'].get('MPN',''), 'manufacturer':r['fields'].get('Manufacturer',''),
              'type':typ,'type_source':type_source, 'assembly':r['fields']['Assembly'], 'in_bom':r['flags']['in_bom'],
              'on_board':r['flags']['on_board'], 'price_eligible':price_eligible, 'physical_eligible':physical,
              'cost':None,'mass':None,'power':None,'temperature':None,'rating':None,
              'source_fields':{k:provenance(r,c[k]) for k in ('price_field','currency_field','mass_field','power_field','rating_field','temperature_field')}}
        if r.get('errors'): issue('warning','SOURCE_EXPRESSION_ERRORS','Component has unresolved/unsupported expressions; review source checks.',r['ref'])
        if price_eligible:
            amount,cur,status,reason,source=money(_value(r,c['price_field']), _value(r,c['currency_field']), currency_default)
            divisor=int(c['price_per'])
            if c['price_per_field']:
                try: divisor=_integer(_value(r,c['price_per_field']),'Price-per units')
                except ValueError as exc: divisor=None;status='invalid';reason=str(exc)
            unit=amount/D(divisor) if amount is not None and divisor and status=='known' else None
            if status!='known': issue('unknown' if status=='missing' else 'warning','PRICE_'+status.upper(),reason or 'Missing selected price.',r['ref'],c['price_field'])
            cost={'status':status,'currency':cur,'currency_source':source,'entered_rate':amount,'price_per':divisor,'unit_price':unit,'reason':reason,'quote_status':'undated'}
            quote=str(_value(r,c['quote_date_field'])).strip()
            if quote:
                try:
                    stamp=datetime.fromisoformat(quote.replace('Z','+00:00'))
                    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
                    age=(current-stamp).total_seconds()/86400
                    cost['quote_status']='future' if age<0 else 'stale' if age>c['quote_max_age_days'] else 'dated_within_window'
                    if cost['quote_status']!='dated_within_window': issue('warning','QUOTE_'+cost['quote_status'].upper(),'User-entered price observation date is '+cost['quote_status']+'; it remains in known arithmetic, not a live quote.',r['ref'],c['quote_date_field'])
                except (ValueError,OverflowError): cost['quote_status']='invalid_date';issue('warning','QUOTE_DATE_INVALID','Price observation date is not an ISO date/time.',r['ref'],c['quote_date_field'])
            cost['quote_date']=quote;part['cost']=cost
            moq,bad1,reason1=_count(r,c['moq_field'],1,'MOQ')
            multiple,bad2,reason2=_count(r,c['multiple_field'],1,'Order multiple')
            if bad1 or bad2: issue('warning','ORDER_POLICY_INVALID',reason1 or reason2,r['ref'])
            identity=(str(part['manufacturer']).strip().casefold(),str(part['mpn']).strip())
            incomplete=not all(identity)
            if incomplete: issue('warning','PROCUREMENT_IDENTITY_INCOMPLETE','Manufacturer/MPN missing; this component is not pooled with other purchasing lines.',r['ref'])
            key=(identity, part['value'],part['footprint'], str(_value(r,c['supplier_field'])), str(_value(r,c['sku_field'])),
                 cur,unit,divisor,amount,moq,multiple,quote,r['id'] if incomplete else '')
            if key not in lots:
                lots[key]={'references':[],'ids':[], 'manufacturer':part['manufacturer'],'mpn':part['mpn'],'value':part['value'],'footprint':part['footprint'],
                           'supplier':str(_value(r,c['supplier_field'])),'sku':str(_value(r,c['sku_field'])),
                           'currency':cur,'unit_price':unit,'moq':moq,'order_multiple':multiple,
                           'qty_per_board':0,'policy_valid':not(bad1 or bad2),'identity_complete':not incomplete,'quote_date':quote}
            lots[key]['references'].append(r['ref']);lots[key]['ids'].append(r['id']);lots[key]['qty_per_board']+=1
        for key,field,unit,enabled in [('mass',c['mass_field'],c['mass_unit'],'mass' in c['metrics']), ('power',c['power_field'],c['power_unit'],'thermal' in c['metrics'])]:
            if not physical or not enabled: continue
            q=m.parse(_value(r,field),unit,nonnegative=True); rec=_metric(q)
            if key=='power':
                rec['input_power_w']=q.value;rec['basis']=c['power_basis'];rec['duty_percent']=D(100)
                if c['power_basis']=='active':
                    duty=m.parse(_value(r,c['duty_field']) if c['duty_field'] else c['duty_percent'],'%',nonnegative=True)
                    if duty.status!='known' or duty.value>100:
                        rec.update(value=None,status='invalid' if duty.status!='missing' else 'missing',reason='Duty cycle must be a known percentage from 0 to 100.',duty_percent=None)
                    else:
                        rec['duty_percent']=duty.value
                        if q.value is not None:rec['value']=q.value*duty.value/100
            if key=='mass' and rec.get('status')=='known':
                rec['basis']=r['fields'].get('Mass_Basis','entered-unspecified');rec['source']=r['fields'].get('Mass_Source','')
                if 'estimated' in rec['basis'].lower():issue('warning','ESTIMATED_MASS','Entered mass is an accepted package proxy, not a measured or qualified component mass.',r['ref'],field)
            part[key]=rec
            if rec['status']!='known':issue('unknown' if rec['status']=='missing' else 'warning',key.upper()+'_'+rec['status'].upper(),rec['reason'],r['ref'],field)
        if physical and 'thermal' in c['metrics']:
            if c['rating_field']:
                rating=m.parse(_value(r,c['rating_field']),c['power_unit'],nonnegative=True)
                part['rating']=_metric(rating)
                p=part['power'].get('input_power_w')
                if p is not None and rating.value is not None:
                    part['power']['rating_utilization_percent']=p*100/rating.value if rating.value else None
                    if p>rating.value: issue('error','DISSIPATION_ABOVE_RECORDED_RATING','Recorded operating dissipation exceeds recorded rated power. Derating/conditions still require engineering review.',r['ref'],c['rating_field'])
                elif rating.status!='known':issue('unknown','RATED_POWER_UNKNOWN','Selected rated-power observation is missing/invalid.',r['ref'],c['rating_field'])
            if c['temperature_field']:
                q=m.parse(_value(r,c['temperature_field']),c['temperature_unit']);part['temperature']=_metric(q)
                if c['temperature_requirement_c'] is not None:
                    required=D(c['temperature_requirement_c'])
                    if q.value is None:issue('unknown','TEMPERATURE_RATING_UNKNOWN','Cannot assess the required temperature against this missing/invalid maximum rating.',r['ref'],c['temperature_field'])
                    else:
                        part['temperature']['headroom_c']=q.value-required
                        if q.value<required:issue('error','TEMPERATURE_RATING_BELOW_REQUIREMENT','Recorded maximum temperature is below the configured '+m.text(required)+' C requirement. Verify the field represents the intended operating rating.',r['ref'],c['temperature_field'])
        parts.append(part)
    price_parts=[p for p in parts if p['price_eligible']]
    physical_parts=[p for p in parts if p['physical_eligible']]
    known_prices=[p for p in price_parts if p['cost']['unit_price'] is not None]
    currencies={}
    for cur in sorted(set(p['cost']['currency'] for p in price_parts)):
        cp=[p for p in price_parts if p['cost']['currency']==cur];known=[p for p in cp if p['cost']['unit_price'] is not None]
        subtotal=sum((p['cost']['unit_price'] for p in known),D(0)) if known else None
        currencies[cur]={'eligible_components':len(cp),'priced_components':len(known),'missing_or_invalid_components':len(cp)-len(known),
                         'known_cost_per_board':subtotal,'known_build_cost':subtotal*boards if subtotal is not None else None}
    procurement=[_lot_amounts(lot,boards,attrition) for lot in lots.values()]
    procurement.sort(key=lambda x:(x['currency'],str(x['manufacturer']),str(x['mpn']),natural(x['references'][0])))
    for cur,summary in currencies.items():
        cl=[x for x in procurement if x['currency']==cur]
        for source,target in [('required_cost','known_required_cost'),('order_cost','known_order_cost'),('overbuy_cost','known_overbuy_cost')]:
            amounts=[x[source] for x in cl if x[source] is not None]
            summary[target]=sum(amounts,D(0)) if amounts else None
        summary['procurement_lines']=len(cl);summary['unpriced_or_invalid_order_lines']=sum(x['order_cost'] is None for x in cl)
    pricing={'eligible_components':len(price_parts),'priced_components':len(known_prices),
             'missing_or_invalid_components':len(price_parts)-len(known_prices),
             'coverage_percent':D(len(known_prices))*100/len(price_parts) if price_parts else None,
             'currency_defaulted_components':sum(p['cost']['currency_source']=='default' for p in price_parts),
             'quote_status_counts':dict(Counter(p['cost']['quote_status'] for p in price_parts)),
             'currencies':currencies,'fx':_fx(c['fx'],currencies,len(price_parts)-len(known_prices))}
    mass=_summary([p['mass'] for p in physical_parts if p['mass'] is not None],len(physical_parts) if 'mass' in c['metrics'] else 0,boards)
    mass['unit']='g'
    thermal=_summary([p['power'] for p in physical_parts if p['power'] is not None],len(physical_parts) if 'thermal' in c['metrics'] else 0,boards)
    thermal.pop('known_build_total',None)  # Never imply that the full order is simultaneously powered.
    thermal['unit']='W';thermal['scenario_name']=c['scenario_name'];thermal['basis']=c['power_basis']
    temps=[p['temperature']['value'] for p in physical_parts if p['temperature'] and p['temperature']['value'] is not None]
    thermal['minimum_known_temp_max_c']=min(temps) if temps else None
    thermal['temperature_ratings_known']=len(temps)
    thermal['temperature_ratings_missing_or_invalid']=len(physical_parts)-len(temps) if c['temperature_field'] else None
    thermal['temperature_requirement_c']=c['temperature_requirement_c']
    groups=_groups(rows,parts,c)
    pareto={cur:_pareto(groups,'cost_per_board',cur) for cur in currencies}
    pricing['pareto']=pareto
    scenarios=[]
    for n in dict.fromkeys([boards,*c['scenario_boards']]):
        sl=[_lot_amounts(lot,n,attrition) for lot in lots.values()]
        for cur,summary in currencies.items():
            lines=[x for x in sl if x['currency']==cur]
            known=[x['order_cost'] for x in lines if x['order_cost'] is not None]
            ordered=sum(known,D(0)) if known else None
            installed=summary['known_cost_per_board']
            scenarios.append({'boards':n,'currency':cur,'known_installed_cost':installed*n if installed is not None else None,
                              'known_order_cost':ordered, 'known_order_cost_per_board':ordered/n if ordered is not None else None,
                              'known_overbuy_cost':sum((x['overbuy_cost'] for x in lines if x['overbuy_cost'] is not None),D(0)) if known else None,
                              'incomplete_order_lines':sum(x['order_cost'] is None for x in lines),
                              'mass_g_per_board':mass['known_per_board'],'known_installed_mass_g':mass['known_per_board']*n if mass['known_per_board'] is not None else None,
                              'power_w_per_board':thermal['known_per_board'],'price_assumption':'Same entered rate at every quantity; no inferred volume discount.'})
        if not currencies:
            scenarios.append({'boards':n,'currency':'','known_installed_cost':None,'known_order_cost':None,'known_order_cost_per_board':None,'known_overbuy_cost':None,
                              'incomplete_order_lines':None,'mass_g_per_board':mass['known_per_board'],
                              'known_installed_mass_g':mass['known_per_board']*n if mass['known_per_board'] is not None else None,
                              'power_w_per_board':thermal['known_per_board'],'price_assumption':'Pricing unavailable/disabled.'})
    stats={field:statistics(rows,field,unit) for field,unit in c['statistics'].items()}
    budgets=[]
    for cur,limit in c['budgets']['cost_per_board'].items():
        cp=currencies.get(cur,{})
        budgets.append(_budget('cost_per_board',cur,D(limit),cp.get('known_cost_per_board'),cp.get('missing_or_invalid_components',1)))
    for name,metric in [('mass_g',mass),('power_w',thermal)]:
        if c['budgets'][name] is not None:
            budgets.append(_budget(name,metric['unit'],D(c['budgets'][name]),metric['known_per_board'],metric['eligible_components']-metric['known_components']))
    for b in budgets:
        if b['status'] in ('exceeded','unknown'):
            issue('error' if b['status']=='exceeded' else 'unknown','BUDGET_'+b['status'].upper(),b['metric']+' ('+b['unit']+') budget '+b['status']+'. Known subtotal is not a complete total when observations are missing.')
    report={'schema':'wayricad-analytics-1','app_version':__version__,'generated_at':now(),'project':ws.project.name,'variant':variant,'revision':ws.revision,
            'config':c,'source_sha256':dict(ws.project.hashes),'workspace_sha256':sha(ws._serialize().encode()),
            'scope':{'query':c['query'],'matched_components':len(rows),'project_components':len(all_rows),'pricing_components':len(price_parts),'physical_components':len(physical_parts),
                     'not_fitted_components':sum(p['assembly']!='FIT' for p in parts),
                     'bom_excluded_physical_components':sum(p['physical_eligible'] and not p['in_bom'] for p in parts),
                     'type_heuristic_components':sum(p['type_source']=='reference-prefix heuristic' for p in parts)},
            'pricing':pricing,'mass':mass,'thermal':thermal,'groups':groups,'procurement':procurement,'scenarios':scenarios,'statistics':stats,
            'components':parts,'budgets':budgets,'issues':issues,'summary':dict(Counter(i['severity'] for i in issues)),
            'limits':[
                'Advisory arithmetic over saved/committed component fields, not engineering or purchasing approval.',
                'Missing/invalid values are never zero; shares and Pareto percentages use known subtotals only.',
                'Pricing counts fitted BOM-included parts. Physical metrics count fitted on-board parts under the selected exclusion policy.',
                'Mass excludes PCB substrate, solder, coatings, wiring and unrepresented hardware unless entered as component records.',
                'Dissipation is user-supplied average or duty-weighted active power. Rated power is not operating heat.',
                'No junction-temperature, airflow, coupling, land-pattern, derating or thermal simulation is performed.',
                'Exact manufacturer/MPN plus value, footprint, supplier/SKU, price, currency and order policy guard procurement pooling.',
                'Scenario rates do not change with volume; taxes, shipping, NRE and labor are not included.',
                'FX rates and price dates are user-entered observations, never live or independently verified.',
                'Native files and component fields are not changed by analytics or threshold highlighting.']}
    from .pcb_estimates import estimate
    report['pcb']=estimate(c['pcb'],boards,mass,pricing)
    for warning in report['pcb']['warnings']:
        issue('warning','PCB_CURRENCY_MISMATCH',warning)
    report['summary']=dict(Counter(i['severity'] for i in issues))
    report['fingerprint']=sha((report['workspace_sha256']+json.dumps(c,sort_keys=True)).encode())
    return _json(report)


def _lot_amounts(lot, boards, attrition):
    r=deepcopy(lot);installed=r['qty_per_board']*boards;required=_ceil(D(installed)*(1+attrition/100))
    ordered=((max(required,r['moq'])+r['order_multiple']-1)//r['order_multiple'])*r['order_multiple'] if r['policy_valid'] else None
    price=r['unit_price'];r.update(installed_qty=installed,required_qty=required,order_qty=ordered,
        attrition_qty=required-installed,overbuy_qty=ordered-required if ordered is not None else None,
        installed_cost=price*installed if price is not None else None,required_cost=price*required if price is not None else None,
        order_cost=price*ordered if price is not None and ordered is not None else None,
        overbuy_cost=price*(ordered-required) if price is not None and ordered is not None else None)
    return r


def _fx(fx, currencies, unknown_prices):
    if not fx['base_currency']:return {'enabled':False}
    base=fx['base_currency'];covered=[];missing=[];total=D(0);observed=False
    for cur,summary in currencies.items():
        rate=D(1) if cur==base else D(fx['rates'][cur]) if cur in fx['rates'] else None
        if rate is None:missing.append(cur);continue
        covered.append(cur)
        if summary['known_cost_per_board'] is not None:
            observed=True;total+=summary['known_cost_per_board']*rate
    return {'enabled':True,'base_currency':base,'known_cost_per_board':total if observed else None,
            'status':'complete' if observed and not missing and not unknown_prices else 'partial' if observed else 'unknown',
            'currencies_converted':covered,'missing_rates':missing,'as_of':fx['as_of'],'source':fx['source'],'direction':'base currency units per 1 source currency unit'}


def _groups(rows, parts, c):
    indexed={p['id']:p for p in parts};buckets={}
    for r in rows:
        p=indexed[r['id']]
        key=tuple(p['type'] if f=='@type' else p['assembly'] if f=='@population' else str(_value(r,f)) for f in c['group_by'])
        buckets.setdefault(key,[]).append(p)
    result=[]
    for key,ps in sorted(buckets.items(),key=lambda item:tuple(natural(x) for x in item[0])):
        physical=[p for p in ps if p['physical_eligible']];eligible=[p for p in ps if p['price_eligible']]
        costs={}
        for cur in sorted(set(p['cost']['currency'] for p in eligible)):
            cp=[p['cost']['unit_price'] for p in eligible if p['cost']['currency']==cur and p['cost']['unit_price'] is not None]
            costs[cur]=sum(cp,D(0)) if cp else None
        rec={'id':sha(json.dumps(key,ensure_ascii=False).encode())[:20],'keys':dict(zip(c['group_by'],key)),
             'label':' / '.join(x or '(blank)' for x in key),'references':[p['reference'] for p in ps],'ids':[p['id'] for p in ps],
             'components':len(ps),'pricing_components':len(eligible),'physical_components':len(physical),
             'cost_per_board':costs,'price_missing_or_invalid':sum(p['cost']['unit_price'] is None for p in eligible)}
        for name in ('mass','power'):
            metric=[p[name] for p in physical if p[name] is not None];known=[x['value'] for x in metric if x['status']=='known']
            rec[name+'_per_board']=sum(known,D(0)) if known else None
            rec[name+'_known']=len(known);rec[name+'_missing_or_invalid']=len(metric)-len(known)
        temp=[p['temperature']['value'] for p in physical if p['temperature'] and p['temperature']['value'] is not None]
        rec['min_temp_max_c']=min(temp) if temp else None
        result.append(rec)
    return result


def _pareto(groups, metric, currency):
    pairs=[(g,g[metric][currency]) for g in groups if g[metric].get(currency) is not None]
    pairs.sort(key=lambda x:(-x[1],x[0]['label']))
    total=sum((amount for _,amount in pairs),D(0));running=D(0);out=[]
    for g,amount in pairs:
        before=running;running+=amount
        out.append({'group_id':g['id'],'label':g['label'],'known_amount':amount,
                    'share_percent':amount*100/total if total else None,
                    'cumulative_percent':running*100/total if total else None,
                    'abc':'A' if total and before<total*D('.8') else 'B' if total and before<total*D('.95') else 'C',
                    'ids':g['ids'],'references':g['references']})
    return out


def _budget(metric, unit, limit, known, unknown):
    status='exceeded' if known is not None and known>limit else 'unknown' if known is None or unknown else 'within_known_budget'
    return {'metric':metric,'unit':unit,'limit':limit,'known_subtotal':known,'unknown_components':unknown,'status':status,
            'remaining_against_known':limit-known if known is not None else None}


def statistics(rows, field, unit):
    observations=[(r,m.parse(_value(r,field),unit)) for r in rows]
    good=sorted((q.value,r['ref']) for r,q in observations if q.value is not None)
    values=[v for v,_ in good];n=len(values);counts=Counter(q.status for _,q in observations)
    out={'field':field,'input_unit':unit,'canonical_unit':m.CANONICAL[m.UNITS[m.unit_name(unit)][0]],'scope':'all query-matched physical component records',
         'known':n,'missing':counts['missing'],'invalid':counts['invalid'],'minimum':None,'maximum':None,'mean':None,'median':None,'p95_nearest_rank':None,'histogram':[]}
    if not n:return out
    out.update(minimum=values[0],maximum=values[-1],mean=sum(values,D(0))/n,median=values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2,
               p95_nearest_rank=values[max(0,_ceil(D(n)*D('.95'))-1)],minimum_references=[r for v,r in good if v==values[0]],maximum_references=[r for v,r in good if v==values[-1]])
    if values[0]==values[-1]:out['histogram']=[{'lower':values[0],'upper':values[-1],'upper_inclusive':True,'count':n}]
    else:
        width=(values[-1]-values[0])/8
        counts=[0]*8
        for v in values:counts[min(7,int((v-values[0])/width))]+=1
        out['histogram']=[{'lower':values[0]+width*i,'upper':values[0]+width*(i+1),'upper_inclusive':i==7,'count':counts[i]} for i in range(8)]
    return out


def threshold(ws, variant, field, condition, unit=None, query='', include_rows=False):
    """A compact, typed numeric filter; unknown/invalid entries never match !=."""
    from . import search
    ws.project.check_unchanged()
    _field(field);op,literal=m.compact_condition(condition)
    rows,_=search.select(ws,variant,query)
    all_rows=ws.rows(variant);known=set().union(*(set(r['fields'])|set(r['raw']) for r in all_rows)) if all_rows else set()
    if search.split_field(field)[1] not in known:raise ValueError('Unknown threshold field: '+field)
    configured=units_for(ws).get(search.split_field(field)[1],'number') if unit is None else m.unit_name(unit)
    rhs=m.literal(literal,configured)
    if rhs.value is None:raise ValueError('Invalid threshold: '+rhs.reason)
    effective=configured if configured!='number' else rhs.input_unit
    matches=[];unknown=[];valid=0
    for r in rows:
        q=m.parse(search.get_value(r,field),effective,dimension=rhs.dimension)
        if q.value is None:unknown.append({'id':r['id'],'reference':r['ref'],'status':q.status,'reason':q.reason});continue
        valid+=1
        if m.compare(q.value,op,rhs.value):matches.append(r)
    report={'schema':'wayricad-threshold-1','variant':variant,'revision':ws.revision,'field':field,'condition':condition,'input_unit':effective,
            'canonical_unit':m.CANONICAL[rhs.dimension],'threshold_value':m.text(rhs.value),'query_scope':query,
            'tested':len(rows),'numeric_components':valid,'unknown_or_invalid':unknown,'matched':len(matches),
            'ids':[r['id'] for r in matches],'references':[r['ref'] for r in matches],
            'note':'Read-only. Unknown/invalid quantities do not match; highlights are not bulk-edit selections.'}
    if include_rows:report['rows']=matches
    return report


def price_overview(ws, rows):
    """Cheap full-variant KPI using saved price mappings, without scenario math."""
    c=defaults(ws); costs={}; unpriced=0
    fallback=c['currency_default'] or ws.state['settings']['currency']
    with localcontext() as ctx:
        ctx.prec=40
        for row in rows:
            if row['fields']['Assembly']!='FIT' or not row['flags']['in_bom']:continue
            amount,cur,status,_,_=money(_value(row,c['price_field']),_value(row,c['currency_field']),fallback)
            try:divisor=_integer(_value(row,c['price_per_field']) if c['price_per_field'] else c['price_per'],'Price per units')
            except ValueError:divisor=None
            if amount is None or status!='known' or divisor is None:unpriced+=1;continue
            costs[cur]=costs.get(cur,D(0))+amount/D(divisor)
    return {k:m.text(v) for k,v in costs.items()},unpriced,c
