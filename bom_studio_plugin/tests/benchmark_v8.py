"""Disposable synthetic catalogue benchmark; no production-project extrapolation."""
from pathlib import Path
import argparse,json,sys,tempfile,time,platform,statistics
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio import partsdb,catalogbrowse,catalogbrowse_legacy

def run(count=10000,iterations=12):
 def measure(fn):
  t=time.perf_counter();r=fn();return (time.perf_counter()-t)*1000,r
 def stats(x):
  return {'median_ms':round(statistics.median(x),3),'p95_ms':round(sorted(x)[max(0,__import__('math').ceil(.95*len(x))-1)],3),'max_ms':round(max(x),3),'samples':len(x)}
 with tempfile.TemporaryDirectory(prefix='wayricad-benchmark8-') as d:
  with partsdb.Library(Path(d)/'catalogue',True) as lib:
   start=time.perf_counter()
   with lib.transaction():
    for i in range(count):
     f={'Manufacturer':f'Synthetic maker {i%12}','MPN':f'BENCH-{i:06d}','Value':'10k' if i%2 else '100n','Footprint':'Resistor_SMD:R_0603_1608Metric' if i%2 else 'Capacitor_SMD:C_0603_1608Metric','Description':'chip resistor' if i%2 else 'ceramic capacitor','Temp_Max':str(60+i%100)}
     record={'id':partsdb.record_identity(f),'fields':f,'kind':'orderable','reference_hint':'R1' if i%2 else 'C1','status':'candidate','tags':['synthetic benchmark only'],'sources':[{'project':'Synthetic source '+str(j),'reference':str(i),'notes':'Synthetic provenance.'*20} for j in range(3)],'assets':[],'evidence':[],'conflicts':[],'internal_pn':f'BENCHIPN-{i}'}
     lib.put(record,'benchmark','Synthetic data, not a manufacturer part')
   insertion=time.perf_counter()-start;epoch=lib.meta('epoch')
   cold,r=measure(lambda:catalogbrowse.search(lib,limit=50,summary=True));assert r['total']==count and r['records_loaded']==50
   warm=[];legacy=[];exact=[];typed=[]
   for i in range(iterations):
    ms,r=measure(lambda:catalogbrowse.search(lib,limit=50,summary=True));warm.append(ms)
    ms,r=measure(lambda:catalogbrowse_legacy.search(lib,limit=50));legacy.append(ms);assert r['total']==count
    ms,r=measure(lambda:catalogbrowse.search(lib,query=f'BENCH-{i:06d}',summary=True));exact.append(ms);assert r['total']==1
    ms,r=measure(lambda:catalogbrowse.search(lib,filters=[{'field':'Temp_Max','op':'<','value':'80','unit':'C'}],limit=50,summary=True));typed.append(ms)
   assert lib.meta('epoch')==epoch
   return {'schema':'wayricad-finder-benchmark-1','version':'0.8.0','platform':platform.platform(),'python':platform.python_version(),'parts':count,'insert_seconds':round(insertion,3),'cold_index_and_first_page_ms':round(cold,3),'warm_browse':stats(warm),'legacy_browse_same_data':stats(legacy),'warm_exact_search':stats(exact),'typed_scan_80C':stats(typed),'records_loaded_per_browse':50,'authoritative_epoch_unchanged':True,'limits':'Synthetic local metadata, three short provenance records per part, no assets. Warm-cache results on this shared machine. Cold query builds a derived index. Typed predicates may scan the matching index set. Not a native KiCad, real design, Windows, screen-reader or large-CAD benchmark.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--count',type=int,default=10000);p.add_argument('--iterations',type=int,default=12);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if not 1<=a.count<=100000 or not 1<=a.iterations<=100:raise SystemExit('Invalid benchmark limits')
 r=run(a.count,a.iterations)
 with a.output.open('x') as f:json.dump(r,f,indent=2)
 print(json.dumps(r,indent=2))
