"""Read-only launch identity and bounded duplicate-plugin discovery."""
from pathlib import Path
import json
import os
import sys
from . import __version__


def runtime_info(app=None):
    root=Path(__file__).resolve().parents[1]
    return {'version':__version__,'installation':str(root),'entrypoint':str(Path(sys.argv[0]).resolve()),
            'interpreter':sys.executable,'pid':os.getpid(),'ui_mode':getattr(app,'ui_mode','none'),
            'toolbar_entrypoint':'desktop_entrypoint.py','inherited_ipc':bool(os.environ.get('KICAD_API_SOCKET'))}


def diagnostic(app=None,roots=None):
    from .desktop import diagnostic as desktop
    here=Path(__file__).resolve().parents[1]
    if roots is None:
        documents=Path(os.environ.get('KICAD_DOCUMENTS_HOME',str(Path.home()/'Documents'/'KiCad')))
        roots=[documents/'10.0'/'plugins',Path.home()/'.local/share/KiCad/10.0/plugins',here.parent]
        third=os.environ.get('KICAD10_3RD_PARTY')
        if third:roots.append(Path(third)/'plugins')
    found={};warnings=[];count=0
    for root in dict.fromkeys(str(Path(x).expanduser()) for x in roots):
        p=Path(root)
        if not p.is_dir():continue
        # Matches KiCad's manifest discovery without full-disk scans or any writes.
        for directory,dirs,files in os.walk(p,followlinks=False):
            dirs[:]=[x for x in dirs if x not in ('.venv','venv','.git','__pycache__')]
            if len(Path(directory).relative_to(p).parts)>=4:dirs[:]=[]
            count+=1
            if count>3000:warnings.append('Scan reached 3000 directories; listing is incomplete.');break
            if 'plugin.json' not in files:continue
            file=Path(directory)/'plugin.json'
            try:
                if file.stat().st_size>128*1024:continue
                j=json.loads(file.read_text(encoding='utf-8-sig'))
                if j.get('identifier') not in ('com.github.wayri.wayricad.bom-studio','org.wayricad.bomstudio'):continue
                found[str(file.resolve())]={'manifest':str(file.resolve()),'running_copy':file.parent.resolve()==here,
                    'entrypoints':[a.get('entrypoint','') for a in j.get('actions',[])],
                    'hint':'Move an obsolete manual copy OUTSIDE scanned directories; renaming inside plugins is insufficient.'}
            except (ValueError,OSError,TypeError):continue
        if count>3000:break
    return {'schema':'wayricad-runtime-diagnostic-1','runtime':runtime_info(app),'desktop':desktop(),
            'installations':list(found.values()),'warnings':warnings,'read_only':True,
            'notice':'Reports configured/common locations, not running processes. No installation or user data was changed. Paths may be private; review before sharing.'}
