"""Capability discovery; no optimistic KiCad-11 version-number assumptions."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from .native import SAFE_VERSION


def cli_path():
    found=shutil.which('kicad-cli')
    if found:return found
    candidates=[]
    if sys.platform=='win32':
        for base in ('C:/Program Files/KiCad',os.environ.get('PROGRAMFILES','')+'/KiCad'):
            p=Path(base)
            if p.is_dir():candidates.extend(sorted(p.glob('*/bin/kicad-cli.exe'),reverse=True))
    if sys.platform=='darwin':candidates.append(Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'))
    return str(next((p for p in candidates if p.is_file()),''))


def capabilities():
    path=cli_path();version='Not found';variant=False;error=''
    if path:
        try:
            kwargs={'capture_output':True,'text':True,'encoding':'utf-8','errors':'replace','timeout':15}
            if sys.platform=='win32':kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
            p=subprocess.run([path,'version'],**kwargs);version=p.stdout.strip() or p.stderr.strip()
            help_run=subprocess.run([path,'sch','export','bom','--help'],**kwargs)
            variant=help_run.returncode==0 and '--variant' in help_run.stdout
        except (OSError,subprocess.SubprocessError) as exc:error=str(exc)
    return {'python':sys.version.split()[0],'platform':sys.platform,'kicad_cli':path,'cli_version':version,
            'native_bom_variant_flag':variant,'native_write_format':SAFE_VERSION,'live_schematic_editing':False,
            'ipc_runtime':bool(os.environ.get('KICAD_API_SOCKET')),'error':error,
            'kicad11':'No blanket certification. Future file versions and unknown variant attributes block production output/native sync until a tested adapter is added.'}
