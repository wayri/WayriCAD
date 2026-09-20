"""Bounded known-answer DC verification; no measured board validation."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

RHO = 1.724e-8
REFERENCES = [
    'https://ocw.mit.edu/courses/res-6-002-electromagnetic-field-theory-a-problem-solving-approach-spring-2008/2cccce322d387cccbc78c3ed65843f49_MITRES_6_002S08_chp03_text.pdf',
    'https://github.com/ElmerCSC/elmerfem/tree/b461e4be77d0ca13bada61f04819fccb20a524ab/fem/tests/ConstantUnknownPotStatCurrent',
    'https://www.grc.nasa.gov/www/wind/valid/tutorial/overview.html',
    'https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html',
]


def _mesh(polygons, edge, thickness=.035, z=0):
    from .mesh import triangulate
    p, t, report = triangulate(polygons, edge, max_cells=80000)
    p[:, 2] = z
    return {'points_mm': p.tolist(), 'triangles': t.tolist(),
            'triangle_thickness_mm': [thickness]*len(t),
            'triangle_layer': [z]*len(t), 'vias': []}, report


def _strip(width=1., z=0):
    import numpy as np
    mesh, _ = _mesh([{'outer': [[0,0],[10,0],[10,width],[0,width]], 'holes': []}], .5, z=z)
    x = np.asarray(mesh['points_mm'])[:,0]
    return mesh, np.flatnonzero(abs(x)<1e-9).tolist(), np.flatnonzero(abs(x-10)<1e-9).tolist()


def _combine(a, b):
    n = len(a['points_mm'])
    return {**a, 'points_mm': a['points_mm']+b['points_mm'],
            'triangles': a['triangles']+[[v+n for v in t] for t in b['triangles']],
            'triangle_thickness_mm': a['triangle_thickness_mm']+b['triangle_thickness_mm'],
            'triangle_layer': a['triangle_layer']+b['triangle_layer']}, n


def _metric(actual, reference, tolerance=1e-7):
    error = abs(float(actual)-reference)/abs(reference)
    return {'computed': float(actual), 'reference': reference, 'relative_error': error,
            'relative_tolerance': tolerance, 'pass': math.isfinite(error) and error<=tolerance}


def _error(error, tolerance):
    return {'relative_error': float(error), 'relative_tolerance': tolerance,
            'pass': math.isfinite(error) and error<=tolerance}


def _case(name, mesh, source, sink, resistance, current=1., rho=RHO):
    from .solver import solve
    result = solve(mesh, source, sink, source_voltage=3., sink_current=current,
                   options={'resistivity_ohm_m': rho, 'temperature_c': 20.})
    checks = {'resistance_ohm': _metric(result['drop_over_current_ohm'], resistance),
              'voltage_drop_V': _metric(result['voltage_drop_V'], current*resistance),
              'power_W': _metric(result['total_power_W'], current*current*resistance),
              'energy_balance': _error(result['energy_relative_error'],1e-6),
              'current_balance': _error(result['current_balance_error_A']/current,1e-6)}
    return {'name': name, 'triangles': len(mesh['triangles']), 'checks': checks}, result


def run_benchmarks():
    """Return JSON-safe evidence; dependency/meshing failures propagate to caller."""
    import numpy as np
    cases = []
    strip_r = RHO*.01/(.001*.000035)
    a, sa, ta = _strip()
    case, result = _case('uniform_copper_strip', a, sa, ta, strip_r, 2.)
    j = np.asarray(result['cell_J_A_mm2'])
    case['checks']['J_vector_relative_L2'] = _error(float(np.linalg.norm(j-[2/.035,0])/np.linalg.norm(np.tile([2/.035,0], (len(j),1)))),1e-7)
    cases.append(case)
    b, sb, tb = _strip(width=2., z=1.)
    mesh, n = _combine(a,b)
    case, result = _case('parallel_layers', mesh, sa+[i+n for i in sb], ta+[i+n for i in tb], strip_r/3, 3.)
    for layer,width in ((0,1.),(1.,2.)):
        selected = np.asarray(mesh['triangle_layer'])==layer
        current = float(np.mean(np.asarray(result['cell_J_A_mm2'])[selected,0]))*width*.035
        case['checks']['layer_%s_current_A'%layer] = _metric(current, width)
    cases.append(case)
    b, sb, tb = _strip(z=1.6)
    mesh,n = _combine(a,b)
    mesh['vias'] = [{'id':'barrel','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                    'length_mm':1.6,'drill_mm':.3,'plating_mm':.025}]
    via_r = RHO*.0016/(math.pi*.025*(.3+.025)*1e-6)
    case,result = _case('two_layers_series_via',mesh,sa,[i+n for i in tb],2*strip_r+via_r,2.)
    case['checks']['via_current_A'] = _metric(result['vias'][0]['current_A'],2.)
    case['checks']['via_loss_W'] = _metric(result['vias'][0]['power_W'],4*via_r)
    cases.append(case)
    # Scale an already production-meshed rectangle: avoid millions of contour
    # subdivisions for metre-scale reference geometry (mesher uses mm).
    beam,source,sink = _strip(width=2.)
    beam['points_mm'] = [[100*x,100*y,z] for x,y,z in beam['points_mm']]
    beam['triangle_thickness_mm'] = [1000.]*len(beam['triangles'])
    case,_ = _case('elmer_published_beam_resistance',beam,source,sink,1.,rho=.2)
    case['scope'] = 'Published beam subproblem: 1 m x 0.2 m x 1 m, sigma=5 S/m. Elmer not executed.'
    cases.append(case)
    terminal=len(beam['points_mm'])
    beam['points_mm'].append([1100.,100.,0.])
    beam['lumped_branches']=[{'id':'external_2ohm','top_nodes':[terminal],
                             'bottom_nodes':sink,'resistance_ohm':2.,'inductance_h':0.}]
    case,result=_case('elmer_published_beam_and_circuit',beam,[terminal],source,3.,rho=.2)
    case['checks']['beam_right_voltage_V']=_metric(result['potential_V'][sink[0]],1.)
    case['checks']['ground_voltage_V']={'computed':result['sink_voltage_V'],'reference':0.,
        'absolute_tolerance_V':1e-7,'pass':abs(result['sink_voltage_V'])<=1e-7}
    case['checks']['resistor_drop_V']=_metric(result['components'][0]['voltage_drop_V'],2.)
    case['checks']['resistor_current_A']=_metric(result['components'][0]['current_A'],1.)
    case['scope']='Published 3 V / 1 A operating point reproduced with current-sink boundary; grounded sink verified. Elmer not executed.'
    cases.append(case)
    radial = []
    for count,edge,r_tol,j_tol in ((24,.8,.02,.10),(48,.4,.006,.05),(96,.2,.002,.025)):
        ring = lambda radius: [[radius*math.cos(2*math.pi*i/count),radius*math.sin(2*math.pi*i/count)] for i in range(count)]
        mesh,report = _mesh([{'outer':ring(4.), 'holes':[ring(1.)]}],edge)
        points = np.asarray(mesh['points_mm']); tri=np.asarray(mesh['triangles'])
        edges=np.sort(np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]),axis=1)
        unique,counts=np.unique(edges,axis=0,return_counts=True)
        boundary=np.unique(unique[counts==1]); radii=np.linalg.norm(points[boundary,:2],axis=1)
        case,result=_case('annulus_%d'%count,mesh,boundary[radii<2.5].tolist(),boundary[radii>2.5].tolist(),RHO*math.log(4)/(2*math.pi*.000035))
        for key in ('resistance_ohm','voltage_drop_V','power_W'):
            metric=case['checks'][key]
            metric['relative_tolerance']=r_tol
            metric['pass']=metric['relative_error']<=r_tol
        centroid=points[tri,:2].mean(axis=1); r2=(centroid**2).sum(axis=1)
        expected=centroid/(2*math.pi*.035*r2[:,None])
        xy=points[tri,:2]; u=xy[:,1]-xy[:,0]; v=xy[:,2]-xy[:,0]
        area=abs(u[:,0]*v[:,1]-u[:,1]*v[:,0])/2
        error=float(np.sqrt(np.sum(area*np.sum((np.asarray(result['cell_J_A_mm2'])-expected)**2,axis=1))/np.sum(area*np.sum(expected**2,axis=1))))
        case['checks']['J_vector_L2']=_error(error,j_tol)
        case.update(edge_mm=edge,contour_segments=count,outer_sagitta_mm=4*(1-math.cos(math.pi/count)),mesh_area_mm2=report['area_mm2'])
        radial.append(case)
    cases.extend(radial)
    refinement={'resistance_error_decreases': all(a['checks']['resistance_ohm']['relative_error']>b['checks']['resistance_ohm']['relative_error'] for a,b in zip(radial,radial[1:])),
                'J_error_decreases': all(a['checks']['J_vector_L2']['relative_error']>b['checks']['J_vector_L2']['relative_error'] for a,b in zip(radial,radial[1:]))}
    for case in cases: case['pass']=all(m['pass'] for m in case['checks'].values())
    return {'schema_version':1,'scope':'Numerical verification against analytic DC answers; not measured validation or peak-current certification.',
            'references':REFERENCES,'resistivity_ohm_m':RHO,'temperature_c':20.,'cases':cases,'annulus_refinement':refinement,
            'pass':all(c['pass'] for c in cases) and all(refinement.values())}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='Write JSON report to this file instead of stdout.')
    args=parser.parse_args(argv)
    try:
        if args.output and args.output.suffix.lower()!='.json':
            raise ValueError('Output filename must end in .json.')
        report=run_benchmarks()
        text=json.dumps(report,indent=2,allow_nan=False)+'\n'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(text,encoding='utf-8')
        else: print(text,end='')
    except Exception as exc:
        report={'pass':False,'error':str(exc),'error_type':type(exc).__name__}
        print(json.dumps(report,indent=2,allow_nan=False))
        status=2
    else: status=0 if report['pass'] else 1
    return status


if __name__=='__main__':
    raise SystemExit(main())

