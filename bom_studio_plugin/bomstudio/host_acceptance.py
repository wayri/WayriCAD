"""Real-host acceptance recorder and reproducible synthetic catalog benchmark.

Never substitutes a fake driver for KiCad. Manual GUI checks always stay pending.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from .native import Project,BASE,sha
from .engine import Workspace
from . import automation,partsdb

MANUAL=(
    'IPC plugin discovery and launch in the target KiCad installation',
    'BOM row and grouped-row selection -> PCB -> schematic with focus',
    'PCB footprint/pad/field and schematic symbol selection -> BOM',
    'Repeated-sheet UUID mapping, multi-unit symbols and no incorrect fallback',
    'Focus deferral during cell editing; hidden-row reveal/restore; no selection echo',
    'Actual Windows/macOS/Linux installer and native library chooser acceptance',
    'Keyboard-only operation and assistive screen-reader acceptance',
)

def run(directory,project=None,kicad_cli=None):
    out=Path(directory).expanduser().absolute()
    if out.exists():raise FileExistsError('Host-test output must be a new directory.')
    out.mkdir(parents=False)
    exe=kicad_cli or shutil.which('kicad-cli');checks=[]
    report={'schema':'wayricad-host-acceptance-1','generated_at':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'python':platform.python_version(),
            'executable':exe,'tests':checks,'manual_checks':[{'name':x,'status':'NOT_EXECUTED'} for x in MANUAL],'status':'UNAVAILABLE',
            'notice':'Only executed native commands may pass here. Manual GUI and other operating systems are never inferred from CLI success.'}
    def call(name,args,cwd=None):
        start=time.perf_counter();record={'name':name,'command':[str(x) for x in args]}
        try:
            done=subprocess.run(args,cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90,check=False,env={**os.environ,'QT_QPA_PLATFORM':'offscreen'})
            raw=done.stdout[:2*1024*1024];(out/(str(len(checks)+1).zfill(2)+'.log')).write_bytes(raw)
            record.update(exit_code=done.returncode,status='PASSED' if done.returncode==0 else 'FAILED',output=raw.decode('utf-8','replace')[:4000])
        except (OSError,subprocess.TimeoutExpired) as exc:record.update(status='FAILED',error=str(exc))
        record['seconds']=round(time.perf_counter()-start,6);checks.append(record);return record
    if not exe:
        checks.append({'name':'KiCad CLI discovery','status':'SKIPPED','reason':'kicad-cli is not installed/on PATH; supply --kicad-cli on a real host.'})
    else:
        version=call('Native version',[exe,'version'])
        if version['status']=='PASSED':
            source=Path(project).expanduser().absolute() if project else Path(__file__).resolve().parent.parent/'examples'/'BOM_Demo.kicad_pro'
            try:
                original=Project(source);root=original.root.parent;files=[];total=0
                for p in root.rglob('*'):
                    if any(x in ('.git','__pycache__','.wayricad-bom-backups','node_modules','.venv') or x.endswith('-backups') for x in p.relative_to(root).parts):continue
                    if p.is_symlink():continue
                    if p.is_file():
                        total+=p.stat().st_size;files.append(p)
                        if len(files)>2000 or total>100*1024*1024:raise ValueError('Host-test copy limit exceeded (2,000 files / 100 MiB); use a small disposable acceptance project.')
                for p in original.documents:
                    if not Path(p).is_relative_to(root):raise ValueError('External child sheet cannot be safely copied; provide a self-contained acceptance project.')
                copy=out/'project';copy.mkdir()
                for p in files:
                    dest=copy/p.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
                target=copy/source.relative_to(root);ws=Workspace(Project(target),load=False)
                xml=out/'native-netlist.xml';r=call('Native schematic load and netlist export',[exe,'sch','export','netlist','--format','kicadxml','--output',str(xml),str(ws.project.root)])
                if r['status']=='PASSED':
                    native_refs=sorted(c.attrib.get('ref') for c in ET.parse(xml).findall('.//components/comp'));expected=sorted(c.ref for c in ws.project.components if c.flags.get('in_bom',True))
                    # Netlist inclusion is not BOM inclusion. Record full differences, do not infer equality.
                    checks.append({'name':'Native reference comparison','status':'PASSED' if set(native_refs).issubset({c.ref for c in ws.project.components}) else 'FAILED','native_references':native_refs,'adapter_all_references':sorted(c.ref for c in ws.project.components),'scope':'Netlist membership may legitimately exclude non-netlist symbols; this checks unknown native references only.'})
                    from .writeback import compile_plan,apply_plan
                    c=next((c for c in ws.project.components if not c.ref.startswith('#')),None)
                    if c:
                        ws.edit([c.id],BASE,{'HostAcceptanceNote':'WayriCAD disposable-copy test'})
                        plan=compile_plan(ws);ws,_=apply_plan(ws,plan['fingerprint'],'APPLY',True)
                        call('Native reload after reviewed file write',[exe,'sch','export','netlist','--format','kicadxml','--output',str(out/'after-write.xml'),str(ws.project.root)])
                jobs=out/'jobs';jobs.mkdir();config=automation.default_pipeline();config.update(variants=[BASE],formats=['json'],reports=['checks'])
                for name,raw in automation.jobset_files(ws,str(jobs),config=config).items():(jobs/name).write_bytes(raw)
                call('Native Execute Command job-set run',[exe,'jobset','run','--file',str(jobs/'WayriCAD_BOM.kicad_jobset'),'--stop-on-error',str(ws.project.pro_path)],cwd=jobs)
            except Exception as exc:checks.append({'name':'Disposable-project acceptance','status':'FAILED','error':str(exc)})
        report['status']='PASSED_EXECUTED_CHECKS' if checks and all(c['status']=='PASSED' for c in checks) else 'FAILED'
    automation.write_new(out/'host-report.json',automation.json_bytes(report))
    return report


def benchmark(count=10000,queries=100):
    partsdb.number(count,'benchmark parts',1,100000);partsdb.number(queries,'query iterations',1,10000)
    timings=[];start=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='wayricad-benchmark-') as tmp:
        with partsdb.Library(Path(tmp)/'catalog',create=True) as lib:
            t=time.perf_counter()
            with lib.transaction():
                for i in range(count):
                    fields={'Manufacturer':'Synthetic benchmark only','MPN':f'BENCH-{i:07}','Value':f'{(i%999)+1}k','Footprint':'Resistor_SMD:R_0603_1608Metric','Subsystem':f'Zone{i%20}'}
                    p={'id':partsdb.record_identity(fields),'kind':'orderable','fields':fields,'status':'candidate','tags':['benchmark'],'sources':[],'assets':[],'evidence':[],'conflicts':[],'reference_hint':'R1','internal_pn':f'B-{i}'}
                    lib.put(p,'synthetic-benchmark','Synthetic performance data')
            insertion=time.perf_counter()-t
            for i in range(queries):
                t=time.perf_counter();page=lib.search(f'BENCH-{(i*97)%count:07}',limit=50);timings.append(time.perf_counter()-t)
                if page['total']!=1:raise AssertionError('Exact synthetic MPN search did not identify one record.')
            t=time.perf_counter();integrity=lib.verify();verification=time.perf_counter()-t
            size=sum(f.stat().st_size for f in (Path(tmp)/'catalog').rglob('*') if f.is_file());fts=lib.meta('fts')
    times=sorted(timings)
    return {'schema':'wayricad-benchmark-1','generated_at':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'python':platform.python_version(),
            'parts':count,'query_iterations':queries,'fts':fts,'insert_seconds':round(insertion,6),'query_median_ms':round(times[len(times)//2]*1000,4),
            'query_p95_ms':round(times[max(0,int(len(times)*.95)-1)]*1000,4),'query_max_ms':round(max(times)*1000,4),'verify_seconds':round(verification,6),'integrity':integrity,'database_bytes_including_wal':size,'total_seconds':round(time.perf_counter()-start,6),
            'limits':'Synthetic local SQLite metadata only; warm-cache queries, this environment, no production project parse/geometry, network, native KiCad, screen-reader or GUI benchmark. No extrapolation beyond the tested count.'}
