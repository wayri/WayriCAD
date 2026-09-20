"""Frequency-dependent conductor estimates from the reviewed path sections."""
import math
from . import rlc_model as model


def sweep(path,minimum_mhz=.001,maximum_mhz=1000.,points=41):
    if not all(math.isfinite(v) for v in (minimum_mhz,maximum_mhz)) or not 0<minimum_mhz<maximum_mhz<=1e6:
        raise ValueError('Use 0 < minimum < maximum <= 1,000,000 MHz.')
    if isinstance(points,bool) or not isinstance(points,int) or not 2<=points<=201:raise ValueError('Use 2–201 sweep points.')
    sections=path['segments'];rows=[];notes=[]
    if not sections:raise ValueError('Analyze a connected copper path before sweeping.')
    if len(sections)>20000:raise ValueError('Narrow the path to at most 20,000 sections.')
    for section in sections:
        if section['kind']!='via' and section.get('width_mm',0)<3*section.get('copper_thickness_mm',.035):
            notes.append('Some sections are not wide relative to thickness; the sheet approximation needs a field-solver check.')
    complete_l=all(section.get('inductance_nh') is not None for section in sections)
    inductance=sum(section.get('inductance_nh') or 0 for section in sections)
    for i in range(points):
        frequency=minimum_mhz*(maximum_mhz/minimum_mhz)**(i/(points-1))
        resistance=[0.,0.]
        for section in sections:
            for faces in (1,2):
                if section['kind']=='via':
                    # Thin annular plating approximation. The two-face case
                    # assumes both barrel surfaces participate equally.
                    value=section['resistance_ohm']*model.slab_skin_factor(frequency,section['plating_mm'],faces)
                else:
                    value=model.ac_resistance_per_m(frequency,section['width_mm'],section['copper_thickness_mm'],excited_faces=faces)*section['length_mm']/1000
                resistance[faces-1]+=value
        x=2*math.pi*frequency*1e6*inductance*1e-9 if complete_l else None
        rows.append(dict(frequency_mhz=frequency,skin_depth_um=model.skin_depth_m(frequency*1e6)*1e6,
            resistance_one_face_ohm=resistance[0],resistance_two_faces_ohm=resistance[1],
            series_reactance_ohm=x,series_magnitude_ohm=math.hypot(resistance[0],x) if x is not None else None))
    return dict(schema='wayricad.rlc-frequency/v1',status='ESTIMATE',rows=rows,
        resistance_dc_ohm=sum(s['resistance_ohm'] for s in sections),
        notes=list(dict.fromkeys(notes))+[
            'One/two-face curves compare imposed sheet-current excitation assumptions, not rigorous proximity bounds.',
            'Skin diffusion is included. Actual neighboring trace/plane proximity, edge crowding, roughness and dielectric loss are not extracted.',
            'Via plating is assumed 25 um unless recorded otherwise; its thin-annulus approximation ignores return placement.',
            'Series R+jωL uses the available lumped section inductances; it is not Z0, terminated input impedance or a high-frequency channel solution.',
            'Missing section inductance keeps series reactance and magnitude unknown. Zone R uses an assumed terminal corridor, not a full plane current solve.'])
