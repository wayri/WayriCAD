"""Declared bare-board mass and quote arithmetic; no inferred market prices."""
from decimal import Decimal, InvalidOperation
import re

D = Decimal
DEFAULT = dict(mass_g=None, area_mm2=None, dielectric_mm=None, dielectric_density_g_cm3=None,
               copper_total_mm=None, copper_coverage_percent=None, copper_density_g_cm3=None,
               unit_cost=None, setup_cost=None, quote_quantity=None, currency='', source='')


def validate(value):
    if not isinstance(value, dict) or set(value)-set(DEFAULT):
        raise ValueError('Unknown PCB estimate settings.')
    result={**DEFAULT, **value}
    for key in DEFAULT:
        v=result[key]
        if key in ('currency','source'):
            if not isinstance(v,str) or len(v)>1000 or any(ord(c)<32 for c in v):
                raise ValueError('PCB '+key+' must be printable text.')
            continue
        if v is None or v == '':
            result[key]=None;continue
        try:
            if isinstance(v,bool):raise ValueError()
            n=D(str(v))
            if not n.is_finite() or n<0 or n>D('1e12'):raise ValueError()
            if key=='copper_coverage_percent' and n>100:raise ValueError()
            if key=='quote_quantity' and (n<1 or n!=n.to_integral_value()):raise ValueError()
            if key.endswith('density_g_cm3') and n<=0:raise ValueError()
        except (ValueError,InvalidOperation):
            raise ValueError('Invalid PCB '+key+'. Use a finite nonnegative value in the displayed unit.') from None
        result[key]=str(n)
    if result['currency'] and not re.fullmatch('[A-Z]{3}',result['currency']):
        raise ValueError('PCB currency must be an explicit three-letter uppercase code.')
    return result


def estimate(config, boards, mass, pricing):
    c=validate(config)
    n=lambda k: D(c[k]) if c[k] is not None else None
    result=dict(assumptions=c, mass_g=None, mass_basis='unknown', expected_unit_cost=None,
                expected_batch_cost=None, currency=c['currency'], assembly_mass_g=None,
                assembly_cost_per_board=None, mass_status='unknown', cost_status='unknown', warnings=[])
    required=('area_mm2','dielectric_mm','dielectric_density_g_cm3','copper_total_mm','copper_coverage_percent','copper_density_g_cm3')
    if n('mass_g') is not None:
        result.update(mass_g=n('mass_g'),mass_basis='User-declared bare-board mass')
    elif all(n(k) is not None for k in required):
        # mm³ / 1000 converts to cm³; dielectric thickness excludes copper.
        result.update(mass_g=n('area_mm2')/1000*(n('dielectric_mm')*n('dielectric_density_g_cm3')+
                      n('copper_total_mm')*n('copper_coverage_percent')/100*n('copper_density_g_cm3')),
                      mass_basis='Declared material-volume estimate; no automatic STEP/stackup inference')
    if result['mass_g'] is not None:
        result['mass_status']='declared' if n('mass_g') is not None else 'estimated'
        if mass['status']=='complete':result['assembly_mass_g']=mass['known_per_board']+result['mass_g']
    if n('unit_cost') is not None and n('setup_cost') is not None and c['currency']:
        quantity=n('quote_quantity') or D(boards)
        result.update(expected_unit_cost=n('unit_cost')+n('setup_cost')/quantity,
                      expected_batch_cost=n('unit_cost')*quantity+n('setup_cost'),
                      quote_quantity=int(quantity),cost_status='declared quote')
        currencies=pricing['currencies']
        if currencies and set(currencies)!={c['currency']}:
            result['warnings'].append('Currency mismatch: component subtotals use '+', '.join(sorted(currencies))+
                                      '; PCB quote uses '+c['currency']+'. No combined cost or implicit FX conversion.')
        if pricing['eligible_components'] and not pricing['missing_or_invalid_components'] and set(currencies)=={c['currency']}:
            result['assembly_cost_per_board']=currencies[c['currency']]['known_cost_per_board']+result['expected_unit_cost']
    result['limitations']=['PCB cost uses the entered quote and setup allocation; no live price prediction.',
                          'Mass excludes solder, coatings, plating, wiring and hardware not represented in the declared board or component values.',
                          'Assembly totals remain unknown when component coverage is incomplete or currencies differ.',
                          'Do not count the bare PCB again as a BOM component. Quote quantity may differ from build quantity.']
    return result
