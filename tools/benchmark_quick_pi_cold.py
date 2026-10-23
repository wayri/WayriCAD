"""Compare fresh Quick PI workers from two checkouts using one saved request.

Run with a Python that can launch the installed KiCad scientific Python. No
result cache, mesh coarsening or warm worker is used. Output contains local
paths and complete result fields; review before publishing it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time


def _read_only(request):
    if request.get('action') not in ('solve','batch'):
        raise ValueError('Use a solved path or multi-net batch request.')
    if request.get('action')=='batch' and any('electrothermal' in case for case in request.get('study',{}).get('cases',[])):
        raise ValueError('Use fixed-temperature DC for exact field benchmarking.')
    def check(value):
        if isinstance(value,dict):
            if 'html_output' in value:raise ValueError('Remove report publication from the timing request.')
            if value.get('model_dimension','2.5d')!='2.5d':
                raise ValueError('Exact field benchmarking currently supports 2.5D copper only.')
            for child in value.values():check(child)
        elif isinstance(value,list):
            for child in value:check(child)
    check(request)


def _child(checkout,request_path,destination):
    sys.path.insert(0,str(checkout))
    start=time.perf_counter()
    from quick_pi_plugin.service import run_job
    request=json.loads(request_path.read_text(encoding='utf-8-sig'))
    result=run_job(request,timeout=1800)
    elapsed=time.perf_counter()-start
    destination.write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
    destination.with_suffix('.timing.json').write_text(json.dumps({'seconds':elapsed}),encoding='utf-8')


def _electrical(bundle):
    # VTK can choose different equal-quality triangles in zero-current lands.
    # Compare every potential, current, cell loss, terminal and conservation
    # field; inactive centroids/thermal budgets are not mesh identity evidence.
    result=bundle['result']
    fields={k:v for k,v in result.items() if k not in ('cell_centroid_mm','cell_thermal','analytics')}
    active=[i for i,vector in enumerate(result['cell_J_A_mm2']) if vector is not None and any(vector)]
    return {'geometry':bundle['geometry'],'electrical':fields,
            'active_centroids':[result['cell_centroid_mm'][i] for i in active],
            'active_thermal':[result['cell_thermal'][i] for i in active]}


def _evidence(result):
    if 'batch' not in result:return [_electrical(result)]
    batch=result['batch']
    if batch['status']!='COMPLETED':raise ValueError('A benchmark case did not complete; inspect its saved result.')
    evidence=[]
    for case in batch['cases']:
        evidence.append(_electrical(case['electrical']))
        if case.get('return_conduction'):evidence.append(_electrical(case['return_conduction']))
        if case.get('electrothermal'):raise ValueError('Use fixed-temperature DC for exact field benchmarking.')
    for group in batch.get('shared_returns',[]):
        # Keep coupling budgets and physical ground voltages as well as the
        # return field, with the same inactive-land mesh exception as supplies.
        coupled={k:v for k,v in group.items() if k!='return_conduction'}
        coupled['return_conduction']=_electrical(group['return_conduction'])
        evidence.append(coupled)
    return evidence


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path)
    parser.add_argument('baseline',type=Path,help='Complete baseline checkout or isolated package root')
    parser.add_argument('candidate',type=Path)
    parser.add_argument('output',type=Path,help='New directory for measurements and full results')
    parser.add_argument('--python',type=Path,required=True,help='Native KiCad Python with scientific dependencies')
    parser.add_argument('--trials',type=int,default=3)
    args=parser.parse_args(argv)
    if not 1<=args.trials<=10:parser.error('--trials must be 1–10')
    request=json.loads(args.request.read_text(encoding='utf-8-sig'));_read_only(request)
    board=Path(request['board_path']).resolve();before=hashlib.sha256(board.read_bytes()).hexdigest()
    for checkout in (args.baseline,args.candidate):
        if not (checkout/'quick_pi_plugin/service.py').is_file() or not (checkout/'wayricad_runtime/runtime_setup.py').is_file():
            raise ValueError('Each checkout needs Quick PI and its matching shared runtime.')
    args.output.mkdir(parents=True,exist_ok=False)
    frozen=args.output.resolve()/'request.json';frozen.write_text(json.dumps(request),encoding='utf-8')
    rows=[];expected=None
    for trial in range(args.trials):
        for label,checkout in (('baseline',args.baseline),('candidate',args.candidate)):
            destination=args.output.resolve()/f'{label}-{trial+1}.json'
            command=[str(args.python.resolve()),'-I',str(Path(__file__).resolve()),'--child',
                     str(checkout.resolve()),str(frozen),str(destination)]
            start=time.perf_counter()
            with destination.with_suffix('.log').open('w',encoding='utf-8') as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1900)
            process_seconds=time.perf_counter()-start
            result=json.loads(destination.read_text(encoding='utf-8'))
            evidence=_evidence(result)
            digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,allow_nan=False).encode()).hexdigest()
            if expected is None:expected=digest
            if digest!=expected:raise AssertionError('Electrical fields or geometry differ; inspect full saved results.')
            if hashlib.sha256(board.read_bytes()).hexdigest()!=before:raise AssertionError('Saved board changed.')
            row={'variant':label,'trial':trial+1,'seconds':json.loads(destination.with_suffix('.timing.json').read_text())['seconds'],
                 'process_seconds':process_seconds,'electrical_sha256':digest}
            rows.append(row);print(json.dumps(row),flush=True)
            del result,evidence
    medians={label:statistics.median(r['seconds'] for r in rows if r['variant']==label) for label in ('baseline','candidate')}
    summary={'source_sha256':before,'source_unchanged':True,'trials':rows,'median_seconds':medians,
             'speedup':medians['baseline']/medians['candidate'],'exact_electrical_comparison':True,
             'scope':'Fresh processes and workers, existing dependencies; operating-system file cache is not flushed.'}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    if len(sys.argv)==5 and sys.argv[1]=='--child':
        _child(*map(Path,sys.argv[2:]))
    else:main()
