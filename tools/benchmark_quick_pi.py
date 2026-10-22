"""Compare saved-board Quick PI contour code and cold/warm owned-worker requests.

Run with KiCad's scientific Python. The optional baseline is a frozen mesh.py
from the source revision under comparison; only its contour routine is swapped.
The request must be a read-only inspect/geometry/mesh/solve JSON without exports.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--baseline-mesh',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    import pcbnew
    from quick_pi_plugin import service,mesh,board_geometry,solver
    request=json.loads(args.request.read_text(encoding='utf-8-sig'))
    if request.get('action') not in ('inspect','geometry','mesh','solve') or request.get('html_output'):
        raise ValueError('Benchmark requires a read-only board request without HTML publication.')
    if args.output.exists():raise ValueError('Choose a new benchmark output file.')
    source=Path(request['board_path']);before=hashlib.sha256(source.read_bytes()).hexdigest()
    def digest(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    stages={};originals={}
    for module,name in ((board_geometry,'extract'),(mesh,'build_mesh'),(solver,'solve')):
        function=getattr(module,name);originals[(module,name)]=function
        def measured(*a,_function=function,_name=name,**kw):
            start=time.perf_counter()
            try:return _function(*a,**kw)
            finally:stages[_name]=stages.get(_name,0.)+time.perf_counter()-start
        setattr(module,name,measured)
    optimized=mesh._conforming_contours
    variants=[('optimized',optimized)]
    if args.baseline_mesh:
        spec=importlib.util.spec_from_file_location('quick_pi_plugin._benchmark_baseline',args.baseline_mesh)
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        variants=[('baseline',baseline._conforming_contours),*variants]
    rows=[];expected=None;reference=None;contours_equal=None
    def electrical(value):
        # VTK may change equal-quality triangulations of zero-current lands.
        # Retain every potential, current, loss, terminal and conservation value.
        return {key:item for key,item in value.items() if key not in ('cell_centroid_mm','cell_thermal','analytics')}
    def compare(result):
        import numpy as np
        identities={key:digest(result[key]) for key in ('geometry','mesh','result') if key in result}
        if reference is not None:
            if identities.get('geometry')!=expected.get('geometry'):raise AssertionError('Extracted geometry differs.')
            if result.get('result'):
                if electrical(result['result'])!=electrical(reference['result']):raise AssertionError('Electrical fields differ.')
                active=np.any(np.asarray(reference['result']['cell_J_A_mm2'])!=0,axis=1)
                np.testing.assert_array_equal(np.asarray(result['result']['cell_centroid_mm'])[active],
                                              np.asarray(reference['result']['cell_centroid_mm'])[active])
                for i in np.flatnonzero(active):
                    if result['result']['cell_thermal'][i]!=reference['result']['cell_thermal'][i]:
                        raise AssertionError('Active-cell thermal evidence differs.')
        return identities
    try:
        # Preload optional scientific libraries before comparing geometry work.
        import vtk,scipy.sparse.linalg
        # Repeating the baseline establishes native mesher repeatability before
        # attributing any full-mesh differences to the optimized routine.
        for label,function in [pair for pair in variants for _ in range(2)]:
            mesh._conforming_contours=function;stages.clear();start=time.perf_counter()
            result=service.execute(request);elapsed=time.perf_counter()-start
            identities=compare(result)
            if expected is None:expected=identities;reference=result
            if contours_equal is None and args.baseline_mesh and result.get('geometry'):
                contours_equal=True
                for layer in result['geometry']['layers']:
                    polygons=layer.get('mesh_regions') or layer['polygons']
                    if not polygons:continue
                    edge=min(float(request.get('edge_mm',.5)),.5)
                    if baseline._conforming_contours(polygons,maximum_edge=edge)!=optimized(polygons,maximum_edge=edge):
                        raise AssertionError('Conforming copper contours differ.')
            row={'mode':label,'seconds':elapsed,'stages_seconds':dict(stages),'sha256':identities}
            if result.get('mesh'):row['triangles']=len(result['mesh']['triangles'])
            if result.get('result'):row['loss_W']=result['result']['total_power_W']
            rows.append(row);print(json.dumps(row),flush=True)
            del result
    finally:
        mesh._conforming_contours=optimized
        for (module,name),function in originals.items():setattr(module,name,function)
    for label in ('worker_uncached','worker_cached'):
        start=time.perf_counter();result=service.run_job(request,timeout=600);elapsed=time.perf_counter()-start
        identities=compare(result)
        rows.append({'mode':label,'seconds':elapsed,'sha256':identities});print(label,elapsed,flush=True)
        del result
    if hashlib.sha256(source.read_bytes()).hexdigest()!=before:raise AssertionError('Source changed.')
    report={'source_sha256':before,'source_unchanged':True,'kicad':pcbnew.Version(),
            'python':sys.version,'request':request,'measurements':rows,'exact_electrical_field_equality':True,
            'active_cell_centroid_and_thermal_equality':True,'contours_exactly_equal':contours_equal,
            'mesh_identity_claimed':False,
            'baseline_mesh_sha256':hashlib.sha256(args.baseline_mesh.read_bytes()).hexdigest() if args.baseline_mesh else None}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
