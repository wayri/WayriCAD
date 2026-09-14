"""Reviewed mass suggestions. Published typical masses are never universal facts.

Exact catalog data takes precedence. Package proxies are offered only as
explicitly labelled estimates; no automatic field population or overwrite.
"""
from __future__ import annotations
from copy import deepcopy
import re
from . import measures,bulkedit
from .partsdb import digest,record_identity
from .native import BASE

RES_SOURCE='https://www.vishay.com/doc/?20023='
CAP_SOURCE='https://www.murata.com/en-global/support/faqs/capacitor/ceramiccapacitor/conf/0004'
NEX='https://www.nexperia.com/chemical-content/'


def seeds():
    out=[]
    for inch,metric,mg in [('0402','1005','0.65'),('0603','1608','2'),('0805','2012','5.5'),('1206','3216','10'),('1210','3225','16'),('2010','5025','25.5'),('2512','6332','40.5')]:
        out.append({'id':'res-'+inch,'reference_prefix':'R','footprint_prefix':'R_'+inch+'_'+metric+'Metric','mass':mg+' mg','basis':'estimated-package-proxy','source':RES_SOURCE,
                    'assumptions':'Historical Vishay D/CRCW-TR e3 typical chip mass, 08-Aug-2022 p1. That resistor series is EOL; this is a mass proxy, NOT a part/lifecycle recommendation. Other constructions differ.','range':'Not characterized'})
    for inch,metric,mg,thick in [('0201','0603','0.33','0.3 mm TC/HiK'),('0402','1005','1.6','0.5 mm TC/HiK, tight thickness tolerance'),('0603','1608','3.0','0.5 mm TC/HiK'),('0603','1608','6.3','0.8 mm TC/HiK, ±0.1 mm thickness'),('0805','2012','6.4','0.6 mm temperature-compensating dielectric'),('0805','2012','9.6','0.6 mm high-K dielectric'),('1206','3216','15','0.6 mm TC/HiK')]:
        out.append({'id':'cap-'+inch+'-'+mg,'reference_prefix':'C','footprint_prefix':'C_'+inch+'_'+metric+'Metric','mass':mg+' mg','basis':'estimated-package-proxy','source':CAP_SOURCE,
                    'assumptions':'Murata MLCC mass table (2025 linked revision), selected family; '+thick+'. Confirm height and dielectric before accepting. Footprint area alone does not establish these.','range':'Typical, lot variation; no bound supplied'})
    for name,fp,prefix,mg in [('MMBT2222A','SOT-23','Q','7.677338'),('BAS416','SOD-323','D','4.128128'),('NGD31251D','SOIC-8_3.9x4.9mm_P1.27mm','U','79.418953')]:
        out.append({'id':'semi-'+name,'reference_prefix':prefix,'footprint_prefix':fp,'mass':mg+' mg','basis':'estimated-package-proxy','source':NEX+name+'.html',
                    'assumptions':'Nexperia '+name+' chemical-content total (22-May-2026). Indicative proxy for the named package only; die/leadframe/mold and manufacturer can differ. No universal package mass.','range':'Not characterized'})
    return out


def suggest(ws,variant=BASE,lib=None,field=None,default_unit=None):
    config=ws.state.get('analytics_settings',{});field=field or config.get('mass_field') or 'Mass';unit=default_unit or config.get('mass_unit') or 'g'
    rows=ws.rows(variant);suggestions=[];unchanged=0;unknown=[];cache={}
    for row in rows:
        if str(row['fields'].get(field,'')).strip():unchanged+=1;continue
        options=[];pid=record_identity(row['fields'])
        if lib and pid.startswith('P-'):
            if pid not in cache:
                try:cache[pid]=lib.get(pid)
                except ValueError:cache[pid]=None
            part=cache[pid]
            if part:
                value=part['fields'].get(field,part['fields'].get('Mass',''));q=measures.parse(value,unit,dimension='mass',nonnegative=True)
                if q.status=='known':
                    source=part['fields'].get('Mass_Source') or 'Local catalog '+part['id']+' revision '+str(part['revision'])
                    options.append({'id':'catalog-'+part['id']+'-r'+str(part['revision']),'mass':measures.text(q.value)+' g','basis':part['fields'].get('Mass_Basis') or 'catalog-observation-unqualified',
                                    'source':source,'assumptions':'Exact manufacturer/full MPN catalog value. Source quality remains that of the catalog record; not independently measured by this program.','range':part['fields'].get('Mass_Uncertainty','Not characterized')})
        fp=row['fields'].get('Footprint','').rsplit(':',1)[-1]
        for seed in seeds():
            # Prefix must terminate or continue with a footprint option separator, not SOT-23-5.
            prefix=seed['footprint_prefix']
            if re.match(r'^'+re.escape(seed['reference_prefix'])+r'\d',row['ref'],re.I) and (fp==prefix or fp.startswith(prefix+'_')):
                options.append(deepcopy(seed))
        if options:suggestions.append({'id':row['id'],'reference':row['ref'],'value':row['fields'].get('Value',''),'footprint':row['fields'].get('Footprint',''),'options':options})
        else:unknown.append({'id':row['id'],'reference':row['ref'],'reason':'No exact catalog mass or supported, source-linked package proxy.'})
    return {'schema':'wayricad-mass-suggestions-1','variant':variant,'field':field,'default_unit':unit,'items':suggestions,'unknown':unknown,'existing_untouched':unchanged,
            'fingerprint':digest([ws._serialize(),ws.project.hashes,lib.meta('epoch') if lib else None,field,unit]),
            'notice':'Every proxy requires review of its assumptions. No known uncertainty bound is fabricated. Selecting a proxy preserves its estimate label in the component fields.'}


def preview(ws,variant,choices,lib=None,field=None,default_unit=None):
    report=suggest(ws,variant,lib,field,default_unit)
    if not isinstance(choices,list) or not choices or len(choices)>20000:raise ValueError('Choose 1..20,000 missing component masses.')
    seen=set();entries=[]
    for ch in choices:
        cid=ch.get('id');oid=ch.get('option')
        if cid in seen:raise ValueError('Choose one mass source per component.');
        seen.add(cid)
        row=next((r for r in report['items'] if r['id']==cid),None)
        option=next((o for o in row['options'] if o['id']==oid),None) if row else None
        if not option:raise ValueError('Suggestion is absent/stale or this component already has mass.')
        entries.append({'ids':[cid],'changes':{report['field']:option['mass'],'Mass_Basis':option['basis'],'Mass_Source':option['source'],
                                             'Mass_Assumptions':option['assumptions'],'Mass_Uncertainty':option['range']}})
    edit=bulkedit.preview(ws,variant,entries)
    return {'schema':'wayricad-mass-plan-1','choices':choices,'field':report['field'],'default_unit':report['default_unit'],'suggestion_fingerprint':report['fingerprint'],'edit':edit,'entries':entries,
            'warning':'Estimated masses will contribute to entered-value analytics and are explicitly flagged as estimates, not measured/qualified values.'}


def apply(ws,variant,plan,confirmation,acknowledge,lib=None):
    if acknowledge is not True:raise ValueError('Acknowledge that estimated/catalog masses are not independently measured.')
    fresh=preview(ws,variant,plan['choices'],lib,plan['field'],plan.get('default_unit'))
    if fresh['suggestion_fingerprint']!=plan.get('suggestion_fingerprint') or fresh['edit']['fingerprint']!=plan['edit']['fingerprint']:raise ValueError('Mass review is stale; preview again.')
    return bulkedit.apply(ws,variant,fresh['entries'],fresh['edit']['fingerprint'],confirmation,True)
