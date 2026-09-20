"""Staged project edits, optimistic concurrency, backups, and offline installation.
KiCad 10 has no supported IPC custom-rule setter. Never hot-write an open project.
"""
import copy, datetime, difflib, hashlib, json, os, pathlib, shutil, tempfile
from dataclasses import dataclass, field
from .model import RuleDocument, lint, Issue
from .board import BoardContext

VERSION='0.3.0'
def digest(data):return hashlib.sha256(data).hexdigest()
def read_bytes(path):return path.read_bytes() if path.exists() else None

def atomic_write(path,data):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def flatten_scalars(value,path=()):
    if isinstance(value,dict):
        for k,v in value.items():yield from flatten_scalars(v,path+(k,))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from flatten_scalars(v,path+(i,))
    else:yield path,value

def get_path(value,path):
    for k in path:value=value[k]
    return value

def set_path(value,path,new):
    if not path:raise ValueError('Cannot replace entire project')
    parent=get_path(value,path[:-1]);parent[path[-1]]=new

def parse_scalar(text,old):
    if isinstance(old,bool):
        if text.lower() not in ('true','false'):raise ValueError('Boolean value must be true or false')
        return text.lower()=='true'
    if isinstance(old,int) and not isinstance(old,bool):return int(text)
    if isinstance(old,float):
        import math
        x=float(text)
        if not math.isfinite(x):raise ValueError('Nonfinite values are not supported')
        return x
    if old is None:
        if text.strip().lower()=='null':return None
        # Native null values are commonly inherited netclass dimensions.
        try:
            x=float(text)
            import math
            if not math.isfinite(x):raise ValueError()
            return x
        except ValueError:raise ValueError('Inherited/null fields accept null or a numeric override')
    return text

@dataclass
class Workspace:
    board_path: pathlib.Path = None
    originals: dict = field(default_factory=dict)
    document: RuleDocument = field(default_factory=RuleDocument)
    project: dict = field(default_factory=dict)
    board_text: str = ''
    context: BoardContext = field(default_factory=BoardContext)
    guards: list = field(default_factory=list)
    saved_state: str = ''
    metadata: dict = field(default_factory=dict)
    @classmethod
    def load(cls,path):
        path=pathlib.Path(path).expanduser().resolve()
        if path.suffix!='.kicad_pcb':raise ValueError('Open a saved .kicad_pcb board')
        if not path.is_file():raise FileNotFoundError(path)
        w=cls(board_path=path)
        for ext in ('.kicad_pcb','.kicad_pro','.kicad_dru','.constraint-studio.json'):
            p=path.with_suffix(ext);w.originals[ext]=read_bytes(p)
        w.board_text=w.originals['.kicad_pcb'].decode('utf-8-sig');w.context=BoardContext.load(w.board_text)
        if w.originals['.kicad_dru']:w.document=RuleDocument.load(w.originals['.kicad_dru'].decode('utf-8-sig'))
        if w.originals['.kicad_pro']:w.project=json.loads(w.originals['.kicad_pro'].decode('utf-8-sig'))
        if w.originals['.constraint-studio.json']:
            meta=json.loads(w.originals['.constraint-studio.json'].decode('utf-8'));w.guards=meta.get('courtyard_guards',[]);w.metadata={k:v for k,v in meta.items() if k not in ('version','courtyard_guards')}
        w.saved_state=w.state();return w
    def clone(self):
        # Board context is immutable in all editor workflows. Share the large parsed
        # tree and immutable bytes/text; copy only the editable rule/settings state.
        return Workspace(self.board_path,self.originals.copy(),copy.deepcopy(self.document),
            copy.deepcopy(self.project),self.board_text,self.context,copy.deepcopy(self.guards),self.saved_state,copy.deepcopy(self.metadata))
    def state(self):return digest(json.dumps([self.document.emit(),self.project,self.board_text,self.guards,self.metadata],sort_keys=True).encode())
    @property
    def dirty(self):return self.state()!=self.saved_state
    @property
    def netclasses(self):return [x.get('name','') for x in self.project.get('net_settings',{}).get('classes',[]) if x.get('name')]
    @property
    def floors(self):return self.project.get('board',{}).get('design_settings',{}).get('rules',{})
    def issues(self):
        out=lint(self.document,self.floors)
        from .routing_profiles import issues as routing_issues
        out.extend(routing_issues(self))
        for g in self.guards:
            if g.get('mode')=='footprint-owned-contours-v1':
                from .courtyards import check_regions
                state,msg=check_regions(self.context,g)
                out.append(Issue('info' if state=='current' else 'error',g.get('reference','?'),msg))
                continue
            if g.get('mode')=='footprint-owned-linear-courtyard':
                from .linked_areas import check_attached_guard
                ok,msg=check_attached_guard(self.context,g)
                out.append(Issue('info' if ok else 'error',g.get('reference','?'),msg))
                continue
            try:ok=self.context.fingerprint(g['reference'])==g['fingerprint']
            except ValueError:ok=False
            if not ok:out.append(Issue('error',g.get('reference','?'),'STALE COURTYARD AREA: footprint position/orientation/reference/courtyard changed. Rebuild the area and re-run DRC.'))
            else:out.append(Issue('warning',g['reference'],'Courtyard area is a saved-geometry snapshot, NOT linked to footprint motion. Moving/editing the component after export invalidates this scope.'))
            if g.get('area_fingerprint'):
                try:area_ok=self.context.area_fingerprint(g['name'])==g['area_fingerprint']
                except ValueError:area_ok=False
                if not area_ok:out.append(Issue('error',g['name'],'STALE COURTYARD AREA: the managed area geometry, layer set, or keepout status changed. Rebuild and validate.'))
        return out
    def refresh_board_context(self):self.context=BoardContext.load(self.board_text)
    def settings_rows(self):
        rows=[]
        for root in [('board','design_settings'),('net_settings',)]:
            try:value=get_path(self.project,root)
            except (KeyError,TypeError):continue
            rows.extend((root+p,v) for p,v in flatten_scalars(value))
        return rows
    def outputs(self):
        result={'.kicad_dru':self.document.emit().encode('utf-8')}
        old_project=self.originals.get('.kicad_pro')
        if self.project:
            if old_project and json.loads(old_project.decode('utf-8-sig'))==self.project:result['.kicad_pro']=old_project
            else:result['.kicad_pro']=(json.dumps(self.project,indent=2,ensure_ascii=False)+'\n').encode()
        if self.board_text:
            original=self.originals.get('.kicad_pcb')
            result['.kicad_pcb']=original if original and original.decode('utf-8-sig')==self.board_text else self.board_text.encode()
        if self.guards or self.metadata or self.originals.get('.constraint-studio.json'):
            result['.constraint-studio.json']=(json.dumps(dict(self.metadata,version=VERSION,courtyard_guards=self.guards),indent=2)+'\n').encode()
        return result
    def changes(self):
        return {ext:data for ext,data in self.outputs().items() if data!=self.originals.get(ext)}
    def review(self):
        blocks=[]
        for ext,data in self.changes().items():
            old=(self.originals.get(ext) or b'').decode('utf-8-sig')
            blocks.extend(difflib.unified_diff(old.splitlines(True),data.decode('utf-8').splitlines(True),
                fromfile='original/'+(self.board_path.stem if self.board_path else 'board')+ext,
                tofile='staged/'+(self.board_path.stem if self.board_path else 'board')+ext))
        return ''.join(blocks) or 'No file changes.\n'
    def verify_originals(self):
        if not self.board_path:raise ValueError('No project loaded')
        for ext,old in self.originals.items():
            if read_bytes(self.board_path.with_suffix(ext))!=old:raise RuntimeError('Project changed on disk: '+self.board_path.with_suffix(ext).name+'. Reload instead of overwriting external edits.')
    def export_bundle(self,directory):
        if not self.board_path:raise ValueError('Open a saved project first')
        directory=pathlib.Path(directory).expanduser().resolve()
        if directory==self.board_path.parent:raise ValueError('Use a separate review folder, never the live project directory')
        directory.mkdir(parents=True,exist_ok=True)
        if any(directory.iterdir()):raise ValueError('Choose an empty review directory to avoid overwriting earlier exports')
        files={}
        for ext,data in self.outputs().items():
            dest=directory/(self.board_path.stem+ext);atomic_write(dest,data)
            files[dest.name]={'sha256':digest(data),'target':str(self.board_path.with_suffix(ext)),
                'original_sha256':digest(self.originals[ext]) if self.originals.get(ext) is not None else None,
                'changed':data!=self.originals.get(ext)}
        manifest={'application':'Constraint Studio','version':VERSION,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source_board':str(self.board_path),'files':files,'issues':[vars(x) for x in self.issues()],
            'warning':'Native GUI/DRC acceptance required. Close the source project before applying. Bundle contains board/project/rules only; external assets and schematic are not copied.'}
        atomic_write(directory/'constraint-studio-manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
        atomic_write(directory/'REVIEW.diff',self.review().encode())
        atomic_write(directory/'READ-ME-FIRST.txt',b'Open the staged board in a separate KiCad instance for review. Source files have NOT been changed.\nRefill zones and run native DRC. Review external dependencies; this is not an archival project bundle.\nBefore applying: close all source-project editors, inspect REVIEW.diff and native reports.\nUse apply_review.py from the source release, which checks fingerprints and makes backups.\nDetached snapshot areas do NOT follow footprint movement. Footprint-owned areas are different: validate native transforms and rebuild after courtyard edits.\n')
        # Carry a small, offline GUI apply utility with each review. No installation,
        # service or network; it still requires Python with wx or Tk on the host.
        helper=directory/'_apply'/'constraint_studio';helper.mkdir(parents=True)
        for name in ('__init__.py','catalog.py','sexpr.py','expressions.py','model.py','board.py','workspace.py','offline_gui.py','linked_areas.py','courtyards.py','routing_profiles.py','LICENSE','LICENSE.original.txt'):
            source=pathlib.Path(__file__).with_name(name)
            if source.exists():shutil.copy2(source,helper/name)
        launcher="import pathlib, sys\nsys.path.insert(0, str(pathlib.Path(__file__).parent / '_apply'))\nfrom constraint_studio.offline_gui import main\nmain(str(pathlib.Path(__file__).parent))\n"
        atomic_write(directory/'Apply Review.pyw',launcher.encode())
        atomic_write(directory/'Apply Review.cmd',b'@echo off\r\ncd /d "%~dp0"\r\nwhere py >nul 2>nul\r\nif not errorlevel 1 (py -3 "Apply Review.pyw" & exit /b)\r\nif exist "%ProgramFiles%\\KiCad\\10.0\\bin\\python.exe" ("%ProgramFiles%\\KiCad\\10.0\\bin\\python.exe" "Apply Review.pyw" & exit /b)\r\npython "Apply Review.pyw"\r\nif errorlevel 1 pause\r\n')
        self.saved_state=self.state()
        return directory


def apply_bundle(directory,project_closed=False,allow_lint_errors=False):
    """Explicit OFFLINE operation. Multi-file transaction with backup + best-effort rollback.
    Original file hashes and exported hashes are mandatory. A KiCad lock is a
    secondary guard; project_closed is a user attestation, not OS process detection.
    """
    if not project_closed:raise RuntimeError('Explicit confirmation that all source-project KiCad editors are closed is required')
    directory=pathlib.Path(directory).resolve()
    manifest=json.loads((directory/'constraint-studio-manifest.json').read_text('utf-8'))
    if manifest.get('application')!='Constraint Studio':raise ValueError('Unknown review bundle')
    if not allow_lint_errors and any(i['severity']=='error' for i in manifest.get('issues',[])):raise ValueError('Bundle has local lint errors; fix and export again')
    board=pathlib.Path(manifest['source_board']).resolve()
    for p in board.parent.glob('~*'+board.stem+'*'):
        if p.name.endswith('.lck'):raise RuntimeError('KiCad lock detected: '+p.name)
    pending=[]
    for name,entry in manifest['files'].items():
        if pathlib.Path(name).name!=name:raise ValueError('Invalid bundle path')
        p=directory/name;target=pathlib.Path(entry['target']).resolve()
        allowed={board.with_suffix(e) for e in ('.kicad_pcb','.kicad_pro','.kicad_dru','.constraint-studio.json')}
        if target not in allowed or p.suffix!=target.suffix:raise ValueError('Unexpected target in manifest')
        data=p.read_bytes()
        if digest(data)!=entry['sha256']:raise ValueError('Review file changed after export: '+name+'. Re-export rather than applying stale validation.')
        old=read_bytes(target);h=digest(old) if old is not None else None
        if h!=entry['original_sha256']:raise RuntimeError('Source changed since review was exported: '+target.name)
        if entry['changed']:pending.append((target,data,old))
    if not pending:return None
    backup=board.parent/('.constraint-studio-backups/'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True,exist_ok=False)
    journal={str(p):{'existed':old is not None,'sha256':digest(old) if old is not None else None} for p,_,old in pending}
    atomic_write(backup/'journal.json',json.dumps(journal,indent=2).encode())
    for p,_,old in pending:
        if old is not None:atomic_write(backup/p.name,old)
    written=[]
    try:
        for p,data,old in pending:atomic_write(p,data);written.append((p,old))
    except BaseException:
        for p,old in reversed(written):
            if old is None:p.unlink(missing_ok=True)
            else:atomic_write(p,old)
        raise
    return backup
