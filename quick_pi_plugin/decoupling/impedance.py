"""Explicit source-R/L and parallel capacitor-bank impedance screening.

Zsource = R + jωL; Zcap = ESR + jωESL + 1/(jωC).
Zrail = 1/(1/Zsource + Σ quantity/Zcap), with the ideal source AC-grounded.
These are reviewed lumped values, not extracted PCB/package parameters.
"""
from __future__ import annotations

import math


def initial_model():
    """An illustrative example, never an inferred board configuration."""
    return dict(source_resistance_ohm=.02,source_inductance_H=5e-9,
                allowed_ripple_V=.05,current_step_A=1.,start_Hz=10.,stop_Hz=100e6,points=201,
                capacitors=[dict(name='Illustrative effective capacitor',capacitance_F=100e-6,
                                 esr_ohm=.01,esl_H=1e-9,quantity=1)])


def validate(model):
    if not isinstance(model,dict):raise ValueError('PDN model must be an object.')
    expected={'source_resistance_ohm','source_inductance_H','allowed_ripple_V','current_step_A','start_Hz','stop_Hz','points','capacitors'}
    if set(model)!=expected:raise ValueError('PDN model needs only the documented source, target, band and capacitor fields.')
    def number(value,name,positive=False):
        if isinstance(value,bool):raise ValueError(name+' must be a finite number.')
        try:value=float(value)
        except (TypeError,ValueError) as exc:raise ValueError(name+' must be a finite number.') from exc
        if not math.isfinite(value) or value<0 or positive and value==0:raise ValueError(name+' is outside its valid range.')
        return value
    result={key:number(model[key],key,key not in ('source_inductance_H',)) for key in expected-{'points','capacitors'}}
    if not result['start_Hz']<result['stop_Hz']:raise ValueError('Stop frequency must exceed start frequency.')
    if result['start_Hz']<1e-3 or result['stop_Hz']>1e12:raise ValueError('Frequency band must lie between 1 mHz and 1 THz.')
    points=model['points']
    if isinstance(points,bool) or not isinstance(points,int) or not 21<=points<=2001:raise ValueError('Choose 21 to 2,001 logarithmic sample points.')
    result['points']=points;result['capacitors']=[]
    if not isinstance(model['capacitors'],list) or not 1<=len(model['capacitors'])<=32:raise ValueError('Enter 1 to 32 capacitor types.')
    names=set()
    for row in model['capacitors']:
        if not isinstance(row,dict) or set(row)!={'name','capacitance_F','esr_ohm','esl_H','quantity'}:raise ValueError('Each capacitor needs name, effective C, ESR, ESL and quantity.')
        name=row['name']
        if not isinstance(name,str) or not name.strip() or len(name)>128 or name in names:raise ValueError('Capacitor names must be unique, nonempty and at most 128 characters.')
        names.add(name);quantity=row['quantity']
        if isinstance(quantity,bool) or not isinstance(quantity,int) or not 1<=quantity<=10000:raise ValueError('Capacitor quantity must be an integer from 1 to 10,000.')
        result['capacitors'].append(dict(name=name,quantity=quantity,
            capacitance_F=number(row['capacitance_F'],name+' effective C',True),
            esr_ohm=number(row['esr_ohm'],name+' ESR'),esl_H=number(row['esl_H'],name+' ESL')))
    try:capacity=math.fsum(row['quantity']*row['capacitance_F'] for row in result['capacitors'])
    except OverflowError as exc:raise ValueError('Effective bank capacitance exceeds finite model limits.') from exc
    if not math.isfinite(capacity):raise ValueError('Effective bank capacitance exceeds finite model limits.')
    return result


def impedance_at(model,frequency_hz):
    """Return finite complex Z, or None for a lossless singular pole."""
    try:
        omega=2*math.pi*frequency_hz
        source=complex(model['source_resistance_ohm'],omega*model['source_inductance_H'])
        admittance=1/source
        for capacitor in model['capacitors']:
            branch=complex(capacitor['esr_ohm'],omega*capacitor['esl_H']-1/(omega*capacitor['capacitance_F']))
            if branch==0:return 0j
            admittance+=capacitor['quantity']/branch
        if admittance==0:return None
        value=1/admittance
    except (ZeroDivisionError,OverflowError):return None
    return value if math.isfinite(value.real) and math.isfinite(value.imag) else None


def analyze(model):
    """Evaluate the reviewed network on coarse and doubled log grids.

    Self-resonances are sampled explicitly. The refinement comparison detects
    some missed narrow peaks but is not a guarantee between sampled frequencies.
    No regulator dynamics, bias-dependent material model or PCB field is added.
    """
    model=validate(model);target=model['allowed_ripple_V']/model['current_step_A']
    start,stop=model['start_Hz'],model['stop_Hz'];span=math.log(stop/start)
    resonances=[]
    def candidate(numerator,denominator):
        if denominator<=0:return
        try:frequency=math.sqrt(numerator/denominator)/(2*math.pi)
        except (ZeroDivisionError,OverflowError):return
        if math.isfinite(frequency) and start<=frequency<=stop:resonances.append(frequency)
    for index,row in enumerate(model['capacitors']):
        # Lossless series SRF and source/branch parallel resonance candidates.
        # Resistance and other branches can shift peaks; these seed the sampled
        # grids rather than claiming an exact full-network peak solution.
        candidate(1/row['capacitance_F'],row['esl_H'])
        candidate(1/row['capacitance_F'],row['esl_H']+row['quantity']*model['source_inductance_H'])
        for other in model['capacitors'][index+1:]:
            # n1/X1+n2/X2=0 => ω²=(n1/C2+n2/C1)/(n1 L2+n2 L1).
            candidate(row['quantity']/other['capacitance_F']+other['quantity']/row['capacitance_F'],
                      row['quantity']*other['esl_H']+other['quantity']*row['esl_H'])
    def evaluate(count):
        frequencies={start*math.exp(span*index/(count-1)) for index in range(count)}
        frequencies.update(value for value in resonances if start<=value<=stop)
        rows=[]
        for frequency in sorted(frequencies):
            value=impedance_at(model,frequency)
            rows.append(dict(frequency_Hz=frequency,impedance_ohm=None if value is None else abs(value),
                             phase_deg=None if value is None else math.degrees(math.atan2(value.imag,value.real))))
        return rows
    coarse=evaluate(model['points']);rows=evaluate(2*model['points']-1)
    def peak(values):
        finite=[row for row in values if row['impedance_ohm'] is not None]
        if not finite:raise ValueError('No finite impedance samples; revise the R/L/C scales.')
        return max(finite,key=lambda row:row['impedance_ohm'])
    coarse_peak=peak(coarse);worst=peak(rows)
    difference=abs(worst['impedance_ohm']-coarse_peak['impedance_ohm'])/max(worst['impedance_ohm'],1e-30)
    singular=any(row['impedance_ohm'] is None for row in rows)
    exceeds=worst['impedance_ohm']>target
    status='SINGULAR' if singular else 'SAMPLED_TARGET_EXCEEDED' if exceeds else 'REFINE_REQUIRED' if difference>.05 else 'SAMPLED_TARGET_MET'
    return dict(schema='wayricad.pdn-lumped/v1',model=model,status=status,target_ohm=target,
                peak=worst,rows=rows,refinement_relative_change=difference,
                sample_count=len(rows),effective_capacitance_F=sum(row['quantity']*row['capacitance_F'] for row in model['capacitors']),
                limitations=['Explicit lumped network; PCB/return/package L, regulator dynamics and capacitor bias/temperature behavior are not inferred.',
                             'Enter effective C after bias/temperature/tolerance derating and mounting-plus-part ESL yourself.',
                             'Target applies only to the specified current step and ripple allowance.',
                             'SRF and lossless pair/source LC candidates seed both grids; damping and additional branches can shift peaks.',
                             'Sampled/refined grid is a screening result, not proof of impedance between samples or transient regulation.'])
