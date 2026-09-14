"""Optional local KiCad CLI schematic parser/netlist acceptance. No shell/downloads."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def find_cli():
    found=shutil.which('kicad-cli')
    if found: return Path(found)
    roots=[Path(sys.executable).parent]
    mod=sys.modules.get('pcbnew')
    if mod and getattr(mod,'__file__',None):
        base=Path(mod.__file__).resolve()
        roots += [base.parent,base.parent.parent/'bin',base.parent.parent.parent/'bin']
    if os.name=='nt':
        for env in ('ProgramW6432','ProgramFiles'):
            if os.environ.get(env):
                for version in ('11.0','10.0'):
                    roots.append(Path(os.environ[env])/'KiCad'/version/'bin')
    for root in roots:
        for name in ('kicad-cli.exe','kicad-cli'):
            path=root/name
            if path.is_file(): return path
    return None


def validate_schematic(path, executable=None):
    executable=executable or find_cli()
    if executable is None: raise ValueError('KiCad CLI was not found. Add the KiCad bin folder to PATH or explicitly disable optional native validation.')
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    version=subprocess.run([str(executable),'--version'],capture_output=True,text=True,timeout=30,**flags)
    if version.returncode or not version.stdout.strip().startswith(('10.','11.')):
        raise ValueError('Native validation requires a KiCad 10 or 11 CLI')
    with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-sch-validate-') as tmp:
        target=Path(tmp)/'check.net'
        result=subprocess.run([str(executable),'sch','export','netlist','--output',str(target),str(path)],
                              capture_output=True,text=True,timeout=180,**flags)
        if result.returncode or not target.is_file():
            raise ValueError('KiCad schematic parser/netlist validation failed:\n'+result.stdout+'\n'+result.stderr)
    return {'cli_version':version.stdout.strip(),'check':'schematic netlist export; not ERC or visual acceptance'}
