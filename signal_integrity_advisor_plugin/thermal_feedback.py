"""Explicit temperature-field to routed DC-resistance feedback, not HF signoff."""
import hashlib
import json
import math
from wayricad_runtime.thermoelectric_study import _sample_temperature_validated,validate_report


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def mapping_template(path_report,thermal_report):
    validate_report(thermal_report)
    path=path_report.get('path',path_report)
    sections=path.get('segments')
    if not isinstance(sections,list) or not sections:raise ValueError('A resolved route report with original sections is required.')
    return dict(schema='wayricad.si-thermal-map/v1',reviewed=False,
                path_report_sha256=fingerprint(path_report),thermal_request_sha256=thermal_report['request_sha256'],
                reference_c=20.,tcr_per_k=.00393,material_temperature_range_c=[-100.,200.],
                sections=[dict(section_index=i,samples_mm=[],note='Enter physical XYZ samples in the thermal study frame.') for i in range(len(sections))])


def apply_temperature(path_report,thermal_report,mapping,current_a=None):
    validate_report(thermal_report)
    if mapping.get('schema')!='wayricad.si-thermal-map/v1' or mapping.get('reviewed') is not True:
        raise ValueError('Explicitly review the XYZ mapping and conductor temperature coefficient.')
    if mapping.get('path_report_sha256')!=fingerprint(path_report) or mapping.get('thermal_request_sha256')!=thermal_report.get('request_sha256'):
        raise ValueError('Path or thermal study identity changed; regenerate and review the mapping.')
    reference=float(mapping['reference_c']);alpha=float(mapping['tcr_per_k'])
    if not all(math.isfinite(v) for v in (reference,alpha)) or reference<=-273.15:
        raise ValueError('Temperature reference and TCR must be finite with a physical temperature reference.')
    bounds=mapping.get('material_temperature_range_c')
    if not isinstance(bounds,list) or len(bounds)!=2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in bounds) or not -273.15<bounds[0]<=reference<=bounds[1] or bounds[0]>=bounds[1]:
        raise ValueError('Declare a valid material temperature range containing the reference.')
    if current_a is not None and (isinstance(current_a,bool) or not math.isfinite(current_a) or current_a<0):raise ValueError('Declared current must be finite and nonnegative.')
    path=path_report.get('path',path_report);sections=path.get('segments',[])
    entries=mapping.get('sections',[])
    if not sections or len(entries)!=len(sections):raise ValueError('Map every original route section exactly once.')
    indexed={}
    for entry in entries:
        index=entry.get('section_index')
        if isinstance(index,bool) or not isinstance(index,int) or index<0 or index>=len(sections) or index in indexed:
            raise ValueError('Unknown or duplicate route section identity.')
        samples=entry.get('samples_mm')
        if not isinstance(samples,list) or not samples or len(samples)>10000:raise ValueError('Each section needs bounded explicit XYZ samples.')
        values=[]
        for sample in samples:
            if not isinstance(sample,list) or len(sample)!=3:raise ValueError('A sample requires [x,y,z] millimetres.')
            values.append(_sample_temperature_validated(thermal_report,*sample,request_sha256=mapping['thermal_request_sha256'])['temperature_c'])
        if any(value<bounds[0] or value>bounds[1] for value in values):raise ValueError('Thermal samples exceed the reviewed conductor correction range.')
        resistance=sections[index].get('resistance_ohm')
        if resistance is None or not math.isfinite(resistance) or resistance<0:raise ValueError('Every mapped section requires a known baseline DC resistance.')
        temperature=math.fsum(values)/len(values);factor=1+alpha*(temperature-reference)
        if not math.isfinite(factor) or factor<=0:raise ValueError('Temperature correction produces invalid resistivity.')
        indexed[index]=dict(section_index=index,temperature_c=temperature,sample_count=len(values),
                            baseline_resistance_ohm=resistance,resistance_dc_ohm=resistance*factor,
                            joule_power_w=None if current_a is None else current_a*current_a*resistance*factor)
    result=[indexed[i] for i in range(len(sections))]
    return dict(schema='wayricad.si-thermal-feedback/v1',status='SCREENED',
                path_report_sha256=mapping['path_report_sha256'],thermal_request_sha256=mapping['thermal_request_sha256'],
                resistance_dc_ohm=math.fsum(row['resistance_dc_ohm'] for row in result),sections=result,
                current_a=current_a,joule_power_w=None if current_a is None else math.fsum(row['joule_power_w'] for row in result),
                reference_c=reference,tcr_per_k=alpha,
                limits=['Explicit equal-weight samples approximate each section temperature; refine spatial sampling.',
                        'Baseline resistance must refer to the declared reference temperature and material.',
                        'DC resistance feedback only: no dielectric-temperature drift, skin/proximity/crosstalk or impedance re-solve.',
                        'I squared R is a DC/low-frequency loss screen, not an RF conductor-loss extraction.',
                        'Imported reports carry source identities, not authenticated measurement or fabrication approval.'])
