"""Run a bounded real FEM screening sweep; preserve failures and source identity."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def operating_volumes(target):
    """Include Windows paging volumes even when all solver files live elsewhere."""
    volumes={target.anchor,Path(os.environ.get('TEMP',target.parent)).anchor}
    if os.name=='nt':
        volumes.add(os.environ.get('SystemDrive','C:')+'\\')
        try:
            raw=subprocess.check_output([
                'powershell.exe','-NoProfile','-NonInteractive','-Command',
                '@(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop | Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress'
            ],text=True,timeout=15)
            names=json.loads(raw) if raw.strip() else []
            if isinstance(names,str): names=[names]
            if not isinstance(names,list) or any(not isinstance(name,str) for name in names):
                raise ValueError('Unexpected paging-volume response')
            volumes.update(Path(name).anchor for name in names)
        except (OSError,subprocess.SubprocessError,ValueError) as exc:
            raise RuntimeError('Cannot verify Windows paging volumes; screening was not started.') from exc
    return {volume for volume in volumes if volume}


def check_operating_reserve(target):
    for volume in sorted(operating_volumes(target)):
        if shutil.disk_usage(volume).free < 100*1024**3:
            raise RuntimeError('Required 100 GiB operating reserve unavailable on '+volume+
                               '; includes system/paging volumes, not only solver output.')


def run(args):
    from quick_emerge_plugin.backend import atomic_json, run_request
    from quick_emerge_plugin.model import config_digest, source_identity, validate_config
    from quick_emerge_plugin.research_antennas import example_config
    target=args.run_dir.resolve()
    check_operating_reserve(target)
    if target.exists() and any(target.iterdir()):
        raise ValueError('Evidence directory is not empty; choose a new run directory.')
    config=example_config(args.template)
    config.update(f_start_hz=args.start_ghz*1e9,f_stop_hz=args.stop_ghz*1e9,points=args.points)
    if args.mesh_edge_mm is not None: config['mesh_edge_mm']=args.mesh_edge_mm
    if args.resolution is not None: config['resolution']=args.resolution
    config=validate_config(config)
    target.mkdir(parents=True,exist_ok=True)
    board=target/'context.kicad_pcb'
    board.write_bytes((ROOT/'quick_emerge_plugin/tests/fixtures/region_coupon.kicad_pcb').read_bytes())
    request=target/'request.json'
    atomic_json(request,dict(config=config,config_sha256=config_digest(config),source=source_identity(board)))
    atomic_json(target/'status.json',{'status':'prepared','qualification':'screening only; not paper agreement or convergence'})
    if args.prepare_only: return
    if args.mesh_diagnostics: os.environ['WAYRICAD_GMSH_VERBOSE']='1'
    os.chdir(target)
    atomic_json(target/'status.json',{'status':'running','qualification':'screening only; not paper agreement or convergence'})
    try:
        run_request(request)
        atomic_json(target/'status.json',{'status':'completed','qualification':'screening only; not paper agreement or convergence'})
    except Exception as exc:
        atomic_json(target/'status.json',{'status':'failed','error':str(exc)})
        raise


if __name__=='__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='backslashreplace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template')
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--start-ghz',type=float,required=True)
    parser.add_argument('--stop-ghz',type=float,required=True)
    parser.add_argument('--points',type=int,default=3)
    parser.add_argument('--mesh-edge-mm',type=float)
    parser.add_argument('--resolution',type=float)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--mesh-diagnostics',action='store_true',help='Print Gmsh progress; does not change physics or mesh settings')
    run(parser.parse_args())
