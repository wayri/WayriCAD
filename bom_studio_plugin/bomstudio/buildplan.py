"""Deterministic multi-build allocation: simulation, not ordering/reservation.

Consumes each entered stock lot/offer pool once. Exact identities only, explicit
split permission, typed lead days, separate currencies and known/unknown costs.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timezone,timedelta,date
from decimal import Decimal,ROUND_CEILING,InvalidOperation
from pathlib import Path
import json
import re
from .native import BASE,Project
from .engine import Workspace,now
from .partsdb import digest,encoded,text,number,record_identity,normalized,catalog_health
from . import evidence

D=Decimal


def decimal(v,name,low='0',high='1e12'):
    if isinstance(v,bool):raise ValueError(name+' cannot be boolean.')
    try:n=D(str(v))
    except (InvalidOperation,TypeError):raise ValueError(name+' needs a decimal number.')
    if not n.is_finite() or not D(low)<=n<=D(high):raise ValueError('Invalid '+name)
    return n


def datevalue(v,name):
    if not isinstance(v,str):raise ValueError(name+' needs YYYY-MM-DD.')
    try:return date.fromisoformat(v)
    except ValueError as exc:raise ValueError(name+' needs YYYY-MM-DD.') from exc


def timestamp(v):
    try:d=datetime.fromisoformat(v.replace('Z','+00:00'))
    except (ValueError,AttributeError):raise ValueError('Observation time needs timezone-aware ISO format.')
    if d.tzinfo is None:raise ValueError('Observation time requires a timezone.')
    return d


def inventory_validate(lib,rows):
    if not isinstance(rows,list) or len(rows)>100000:raise ValueError('Inventory must contain at most 100,000 lots.')
    seen=set();result=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'id','part_id','quantity','reserved','location','expires','status','source','observed_at','notes'}:raise ValueError('Unknown inventory keys.')
        r={'reserved':0,'expires':'','status':'available','location':'','notes':'',**row}
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',r.get('id','')) or r['id'] in seen:raise ValueError('Inventory lot IDs must be unique, 1..80 safe characters.')
        seen.add(r['id']);part=lib.get(r['part_id'])
        if part['kind']!='orderable':raise ValueError('Inventory requires an exact manufacturer and MPN catalog identity.')
        number(r.get('quantity'),'quantity');number(r['reserved'],'reserved')
        if r['reserved']>r['quantity']:raise ValueError('Reserved stock cannot exceed lot quantity.')
        if r['status'] not in ('available','quarantine','scrapped'):raise ValueError('Lot state: available, quarantine or scrapped.')
        for k in ('location','source','notes'):text(r.get(k,''),k,4000)
        if not r.get('source'):raise ValueError('Record the inventory observation source.')
        timestamp(r.get('observed_at'))
        if r['expires']:datevalue(r['expires'],'Lot expiration')
        result.append(r)
    return result


def inventory_preview(lib,rows):
    records=inventory_validate(lib,rows);old={r['id']:json.loads(r['payload']) for r in lib.db.execute('SELECT * FROM inventory')}
    changes=[{'id':r['id'],'before':old.get(r['id']),'after':r} for r in records if old.get(r['id'])!=r]
    return {'schema':'wayricad-inventory-plan-1','records':records,'changes':changes,'fingerprint':digest([lib.meta('id'),lib.meta('epoch'),records,old]),
            'notice':'Upsert these lot observations; omitted lots remain. Set quantity=0 or status=scrapped to retire a lot. Planning never silently reserves stock.'}


def inventory_apply(lib,plan,confirmation,actor):
    if confirmation!='INVENTORY':raise ValueError('Type INVENTORY after reviewing the lot changes.')
    text(actor,'actor',128)
    if not actor.strip():raise ValueError('Inventory actor required.')
    with lib.transaction():
        fresh=inventory_preview(lib,plan['records'])
        if fresh['fingerprint']!=plan.get('fingerprint'):raise ValueError('Inventory review is stale.')
        for c in fresh['changes']:lib.db.execute('INSERT INTO inventory VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(c['id'],encoded(c['after'])))
        if fresh['changes']:lib.touch();lib.audit('inventory-upsert',{'actor':actor,'changes':fresh['changes']})
    return {'updated':len(fresh['changes'])}


def validate_config(config):
    if not isinstance(config,dict) or config.get('schema')!='wayricad-build-plan-1':raise ValueError('Expected wayricad-build-plan-1.')
    allowed={'schema','name','builds','offers','market','stock_age_hours','inventory_age_days','allow_split','independent_pools_reviewed','supplier_priority'}
    if set(config)-allowed:raise ValueError('Unknown build-plan keys.')
    c={'name':'Multi-build scenario','market':'IN','stock_age_hours':24,'inventory_age_days':30,'allow_split':False,'independent_pools_reviewed':False,'supplier_priority':[], 'offers':[],**deepcopy(config)}
    text(c['name'],'name',128)
    if not re.fullmatch('[A-Z]{2}',c['market']):raise ValueError('Market needs a two-letter uppercase code.')
    for k,max_ in [('stock_age_hours',8760),('inventory_age_days',3650)]:number(c[k],k,1,max_)
    for k in ('allow_split','independent_pools_reviewed'):
        if type(c[k]) is not bool:raise ValueError(k+' must be boolean.')
    if c['allow_split'] and not c['independent_pools_reviewed']:raise ValueError('Split sourcing requires explicit independent inventory-pool review.')
    if not isinstance(c['supplier_priority'],list) or len(c['supplier_priority'])>100 or any(not isinstance(s,str) for s in c['supplier_priority']):raise ValueError('Invalid supplier priority list.')
    if not isinstance(c.get('builds'),list) or not 1<=len(c['builds'])<=100:raise ValueError('Choose 1..100 builds.')
    ids=set()
    for b in c['builds']:
        if not isinstance(b,dict) or set(b)-{'id','project','variant','boards','priority','due_date','attrition_percent'}:raise ValueError('Invalid build keys.')
        b.setdefault('variant',BASE);b.setdefault('priority',100);b.setdefault('attrition_percent','0');b.setdefault('due_date','')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}',b.get('id','')) or b['id'] in ids:raise ValueError('Build IDs must be unique safe names.')
        ids.add(b['id']);number(b.get('boards'),'boards',1,1000000);number(b['priority'],'priority',0,100000)
        decimal(b['attrition_percent'],'attrition percent','0','1000')
        if b['due_date']:datevalue(b['due_date'],'Build due date')
    if not isinstance(c['offers'],list) or len(c['offers'])>100000:raise ValueError('Offers: at most 100,000.')
    ids=set()
    for o in c['offers']:
        allowed_offer={'id','part_id','supplier','sku','available','observed_at','source_url','region','reviewed','lead_days','currency','unit_price','moq','multiple','pool_id','tiers'}
        if not isinstance(o,dict) or set(o)-allowed_offer:raise ValueError('Unknown offer keys.')
        if not o.get('id') or o['id'] in ids:raise ValueError('Unique offer IDs required.')
        ids.add(o['id'])
        for k in ('id','part_id','supplier','sku','pool_id'):text(o.get(k,''),k,256)
        if not o.get('pool_id') or not o.get('supplier') or not o.get('sku'):raise ValueError('Offer requires supplier, SKU and explicit inventory pool ID.')
        number(o.get('available'),'available');number(o.get('moq',1),'MOQ',1);number(o.get('multiple',1),'multiple',1)
        if o.get('lead_days') is not None:number(o['lead_days'],'lead days',0,10000)
        timestamp(o.get('observed_at'));evidence.safe_url(o.get('source_url',''))
        if not o.get('source_url'):raise ValueError('Offer requires a source URL.')
        if not re.fullmatch('[A-Z]{2}',o.get('region','')):raise ValueError('Offer region required.')
        if type(o.get('reviewed')) is not bool:raise ValueError('Offer reviewed flag required.')
        if o.get('unit_price') not in ('',None):decimal(o['unit_price'],'unit price')
        if o.get('currency') and not re.fullmatch('[A-Z]{3}',o['currency']):raise ValueError('Offer currency: uppercase 3-letter code.')
        tiers=o.get('tiers',[])
        if not isinstance(tiers,list) or len(tiers)>100:raise ValueError('At most 100 price tiers.')
        thresholds=set()
        for t in tiers:
            if not isinstance(t,dict) or set(t)!={'min_qty','unit_price'}:raise ValueError('Price tier needs min_qty and unit_price.')
            number(t['min_qty'],'tier quantity',1);decimal(t['unit_price'],'tier rate')
            if t['min_qty'] in thresholds:raise ValueError('Duplicate price-break threshold.')
            thresholds.add(t['min_qty'])
    return c


def _offer_price(offer,qty):
    base=offer.get('unit_price');rate=decimal(base,'unit price') if base not in ('',None) else None
    for tier in sorted(offer.get('tiers',[]),key=lambda t:t['min_qty']):
        if qty>=tier['min_qty']:rate=decimal(tier['unit_price'],'tier price')
    return rate if offer.get('currency') else None


def catalog_offers(lib,market='IN'):
    """Convert dated numeric evidence. Lead-time prose is deliberately NOT parsed."""
    out=[]
    for r in lib.db.execute('SELECT payload FROM parts'):
        part=json.loads(r[0])
        for e in part.get('evidence',[]):
            if e.get('stock') is None or not e.get('observed_at') or not e.get('source_url') or not e.get('supplier') or not e.get('sku') or not e.get('region'):continue
            out.append({'id':part['id']+'-'+e['id'],'part_id':part['id'],'supplier':e['supplier'],'sku':e['sku'],'available':e['stock'],
                        'observed_at':e['observed_at'],'source_url':e['source_url'],'region':e['region'],'reviewed':e.get('reviewed') is True,
                        'lead_days':None,'currency':e.get('currency',''),'unit_price':e.get('unit_price'),'moq':e.get('moq') or 1,'multiple':e.get('order_multiple') or 1,
                        'pool_id':e['supplier']+'|'+e['sku'],'tiers':[]})
    return out


def run(ws,lib,config,clock=None):
    c=validate_config(config);clock=clock or datetime.now(timezone.utc);issues=[];sources={};workspace_hashes={};loaded={};demands=[];canonical={};bad_ids=set()
    initial_epoch=lib.meta('epoch');initial_inventory=[json.loads(r[0]) for r in lib.db.execute('SELECT payload FROM inventory ORDER BY id')]
    def issue(code,message,scope='',severity='warning'):issues.append({'code':code,'severity':severity,'scope':scope,'message':message})
    for b in sorted(c['builds'],key=lambda b:(b['priority'],b['due_date'] or '9999-12-31',b['id'])):
        if b.get('project'):
            path=str(Path(b['project']).expanduser().resolve())
            if path not in loaded:loaded[path]=Workspace(Project(path))
            work=loaded[path]
        else:work=ws
        work.project.check_unchanged();work.variant_chain(b['variant']);sources.update(work.project.hashes)
        workspace_hashes[b['id']]=digest(work.state)
        rows=work.rows(b['variant']);lines={}
        if work.project.blockers or any(r.get('errors') for r in rows):
            raise ValueError('Cannot allocate a build with unsupported source constructs or unresolved field expressions.')
        for r in rows:
            if r['flags']['dnp'] or not r['flags']['in_bom']:continue
            pid=record_identity(r['fields']);orderable=pid.startswith('P-')
            if not orderable:pid='UNRESOLVED-'+digest([str(work.project.root),b['id'],r['id']])[:24];issue('MISSING_IDENTITY','Exact manufacturer/MPN missing; inventory/offers cannot be matched.',r['ref'],'unknown')
            else:
                try:p=lib.get(pid)
                except ValueError:p=None
                if p:
                    h=catalog_health(p,c['market'],c['stock_age_hours'],clock)
                    if h['state']=='blocked' or h['lifecycle']=='AT RISK':issue('CATALOG_RISK','Blocked/conflicting/NRND/EOL identity requires independent review.',pid,'error');bad_ids.add(pid)
            sig=(normalized(r['fields'],r['ref']),r['fields'].get('Footprint',''))
            if pid in canonical and canonical[pid]!=sig:issue('IDENTITY_CONFLICT','Same full MPN has differing value/footprint descriptions; allocation withheld.',pid,'error');bad_ids.add(pid)
            canonical[pid]=sig
            line=lines.setdefault(pid,{'part_id':pid,'manufacturer':r['fields'].get('Manufacturer',''),'mpn':r['fields'].get('MPN',''),'references':[],'installed':0})
            line['references'].append(r['ref']);line['installed']+=b['boards']
        for l in lines.values():
            l.update(build=b['id'],variant=b['variant'],due_date=b['due_date'],required=int((D(l['installed'])*(1+decimal(b['attrition_percent'],'attrition')/100)).to_integral_value(rounding=ROUND_CEILING)))
            demands.append(l)
    lots=[]
    for lot in inventory_validate(lib,initial_inventory):
        age=(clock-timestamp(lot['observed_at'])).total_seconds()/86400
        eligible=lot['status']=='available' and 0<=age<=c['inventory_age_days'] and (not lot['expires'] or datevalue(lot['expires'],'expires')>=clock.date())
        lots.append({**lot,'remaining':lot['quantity']-lot['reserved'] if eligible else 0})
        if not eligible and lot['quantity']:issue('INVENTORY_INELIGIBLE','Quarantined/scrapped/expired/stale/future lot excluded.',lot['id'],'unknown')
    # Only the latest dated observation per supplier/SKU/region is eligible.
    latest={}
    for o in c['offers']:
        key=(o['part_id'],o['supplier'],o['sku'],o['region'])
        if key not in latest or timestamp(o['observed_at'])>timestamp(latest[key]['observed_at']):latest[key]=o
        elif timestamp(o['observed_at'])==timestamp(latest[key]['observed_at']) and o!=latest[key]:raise ValueError('Conflicting simultaneous offer observations for the same supplier/SKU.')
    offers=[];pool_stock={};pool_identity={}
    for o in latest.values():
        age=(clock-timestamp(o['observed_at'])).total_seconds()/3600
        if not o['reviewed'] or o['region']!=c['market'] or not 0<=age<=c['stock_age_hours']:
            issue('OFFER_INELIGIBLE','Unreviewed, stale, future-dated or other-market offer excluded.',o['id'],'unknown');continue
        pool=o['pool_id']
        if pool in pool_identity and pool_identity[pool]!=o['part_id']:raise ValueError('One stock pool cannot represent two different exact part identities.')
        pool_identity[pool]=o['part_id']
        if pool in pool_stock and pool_stock[pool]!=o['available']:issue('POOL_QUANTITY_DISAGREEMENT','Same-pool quantities differ; conservative minimum used.',pool)
        pool_stock[pool]=min(pool_stock.get(pool,o['available']),o['available']);offers.append(o)
    allocations=[];orders=[];surplus={};costs=defaultdict(D)
    priority={s:i for i,s in enumerate(c['supplier_priority'])}
    for line in demands:
        pid=line['part_id'];remaining=line['required'];line['inventory_used']=0;line['purchased_allocated']=0
        if pid in bad_ids:line.update(shortfall=remaining,status='BLOCKED');continue
        due=datevalue(line['due_date'],'due') if line['due_date'] else None
        for lot in sorted(lots,key=lambda l:(l['expires'] or '9999-12-31',l['id'])):
            if lot['part_id']!=pid or lot['remaining']<=0 or (due and lot['expires'] and datevalue(lot['expires'],'expires')<due):continue
            take=min(remaining,lot['remaining']);lot['remaining']-=take;remaining-=take;line['inventory_used']+=take
            if take:allocations.append({'build':line['build'],'part_id':pid,'source':'inventory','lot':lot['id'],'quantity':take})
        # Leftovers from a preceding simulated purchase retain arrival dates.
        for pool in surplus.get(pid,[]):
            if due and (pool['arrival'] is None or date.fromisoformat(pool['arrival'])>due):continue
            take=min(remaining,pool['remaining']);remaining-=take;pool['remaining']-=take;line['purchased_allocated']+=take
            if take:allocations.append({'build':line['build'],'part_id':pid,'source':'planned-surplus','order':pool['order'],'quantity':take})
        compatible=[]
        for o in offers:
            if o['part_id']!=pid:continue
            arrival=(clock.date()+timedelta(days=o['lead_days'])).isoformat() if o.get('lead_days') is not None else None
            if due and (arrival is None or date.fromisoformat(arrival)>due):issue('LEAD_TIME_INELIGIBLE','Unknown/late lead time cannot cover the dated build.',o['id'],'unknown');continue
            compatible.append((o,arrival))
        while remaining>0 and compatible:
            candidates=[]
            for o,arrival in compatible:
                available=pool_stock[o['pool_id']];multiple=o.get('multiple',1);moq=o.get('moq',1)
                rounded=((max(remaining,moq)+multiple-1)//multiple)*multiple
                qty=rounded if rounded<=available else (available//multiple)*multiple if c['allow_split'] else 0
                if qty<moq or qty<=0:continue
                rate=_offer_price(o,qty)
                # Explicit supplier priority dominates. Across currencies no numeric comparison is fabricated.
                candidates.append((priority.get(o['supplier'],len(priority)),o.get('currency') or '~',rate*qty if rate is not None else D('Infinity'),o['id'],o,arrival,qty,rate))
            if not candidates:break
            currencies={x[1] for x in candidates}
            if len(currencies)>1:issue('CURRENCY_ORDERING','Different currencies are not economically compared; supplier priority then currency-code ordering is used.',pid)
            *_,o,arrival,qty,rate=min(candidates,key=lambda t:t[:4]);pool_stock[o['pool_id']]-=qty
            take=min(remaining,qty);remaining-=take;line['purchased_allocated']+=take;oid='PO-SIM-'+str(len(orders)+1)
            order={'id':oid,'part_id':pid,'supplier':o['supplier'],'sku':o['sku'],'pool_id':o['pool_id'],'quantity':qty,'allocated':take,'overbuy':qty-take,'currency':o.get('currency'),
                   'unit_price':str(rate) if rate is not None else None,'cost':str(rate*qty) if rate is not None else None,'arrival_date':arrival,'evidence':o['id'],'source_url':o['source_url']}
            orders.append(order);allocations.append({'build':line['build'],'part_id':pid,'source':'planned-purchase','order':oid,'quantity':take})
            if rate is not None:costs[o['currency']]+=rate*qty
            else:issue('PRICE_UNKNOWN','A planned purchase has no numeric price/currency.',oid,'unknown')
            if qty>take:surplus.setdefault(pid,[]).append({'order':oid,'remaining':qty-take,'arrival':arrival})
            if not c['allow_split']:break
            compatible=[x for x in compatible if x[0]['pool_id']!=o['pool_id']]
        line['shortfall']=remaining;line['status']='OBSERVED_COVERED' if remaining==0 else 'SHORTFALL_OR_UNKNOWN'
        if remaining:issue('BUILD_SHORTFALL','No eligible observed allocation covers '+str(remaining)+' required parts.',line['build']+':'+pid,'unknown')
    for order in orders:
        order['initial_allocation']=order['allocated']
        order['allocated']=sum(a['quantity'] for a in allocations if a.get('order')==order['id'])
        order['overbuy']=order['quantity']-order['allocated']
    for work in [ws,*loaded.values()]:
        work.project.check_unchanged()
        if work.sidecar.exists() and __import__('hashlib').sha256(work.sidecar.read_bytes()).hexdigest()!=work.sidecar_hash:raise ValueError('Saved workspace changed during planning.')
    if lib.meta('epoch')!=initial_epoch:raise ValueError('Catalog/inventory changed during planning; rerun.')
    return {'schema':'wayricad-build-result-1','name':c['name'],'generated_at':now(),'config':c,'source_hashes':sources,'workspace_hashes_by_build':workspace_hashes,'catalog_epoch':int(initial_epoch),'demands':demands,'allocations':allocations,
            'orders':orders,'known_cost_by_currency':{k:str(v) for k,v in costs.items()},'remaining_inventory':[{k:v for k,v in l.items() if k in ('id','part_id','remaining')} for l in lots],
            'remaining_purchased_surplus':surplus,'issues':issues,'status':'GAPS_OR_REVIEW' if issues else 'OBSERVED_PLAN',
            'notice':'Simulation only: no orders, reservations or inventory mutations. Greedy priority allocation is not a global cost optimum. Stock is observed, not guaranteed. Unknown lead time cannot satisfy a dated build.'}
