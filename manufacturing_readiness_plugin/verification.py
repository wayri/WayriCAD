"""Saved-input release gates; every result belongs to one immutable snapshot."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import tempfile
from .analysis import gate_key, saved_metrics, sexpr_tokens

SOURCE_SUFFIXES={'.kicad_pcb','.kicad_sch','.kicad_pro','.kicad_dru','.kicad_jobset','.kicad_sym','.kicad_mod','.step','.stp','.wrl'}


def drc_evidence(report,returncode):
    """Retain native findings even when KiCad exits 5 for design violations."""
    from collections import Counter
    data=json.loads(Path(report).read_text(encoding='utf-8'))
    keys=('violations','unconnected_items','schematic_parity')
    if (not isinstance(data,dict)
            or not all(isinstance(data.get(key),list) for key in keys[:2])
            or not isinstance(data.get('schematic_parity',[]),list)
            or any(not isinstance(item,dict) for key in keys for item in data.get(key,[]))):
        raise ValueError('KiCad did not return a recognizable JSON DRC report.')
    counts={key:len(data.get(key,[])) for key in keys}
    return {'clean':returncode==0 and not any(counts.values()),'findings':counts,
            'types':dict(Counter(item.get('type','unknown') for key in keys for item in data.get(key,[])))}


def find_cli():
    candidates=[Path(sys.executable).with_name('kicad-cli.exe'),Path(sys.executable).with_name('kicad-cli')]
    for variable in ('ProgramW6432','ProgramFiles'):
        if os.environ.get(variable):
            candidates += [Path(os.environ[variable])/'KiCad'/version/'bin'/'kicad-cli.exe' for version in ('11.0','10.0')]
    found=shutil.which('kicad-cli')
    if found:candidates.insert(0,Path(found))
    return next((path for path in candidates if path.is_file()),None)


def capture_inputs(board_path,project_directory,profile,jobset,live_text):
    board_path=Path(board_path).resolve();root=Path(project_directory).resolve()
    if not board_path.is_file() or board_path.parent!=root:
        raise ValueError('Choose the saved board’s own project directory, then save the board and project in KiCad.')
    files={}
    for path in root.rglob('*'):
        relative=path.relative_to(root)
        if any(part.startswith('.') or part.endswith('-backups') for part in relative.parts):continue
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Project source links outside the project must be made portable before release: '+str(relative))
            files[relative.as_posix()]=path.read_bytes()
    project_name=board_path.with_suffix('.kicad_pro').name
    if project_name not in files:raise ValueError('The saved PCB must have a matching .kicad_pro file.')
    job_name=''
    if jobset:
        job_path=Path(jobset).resolve()
        if not job_path.is_relative_to(root):raise ValueError('Save the selected jobset inside this project directory.')
        job_name=job_path.relative_to(root).as_posix()
        if job_name not in files:raise ValueError('The selected jobset is missing or is not a .kicad_jobset file.')
    if sexpr_tokens(files[board_path.name].decode('utf-8-sig'))!=sexpr_tokens(live_text):
        raise ValueError('The open board differs from its saved file. Save it in KiCad, then repeat the audit. IPC releases require exact serialized saved/live agreement.')
    return files,gate_key(files,profile,job_name,live_text),job_name


class VerificationSnapshot:
    def __init__(self,files,key,board_name,job_name):
        self.owner=tempfile.TemporaryDirectory(prefix='wayricad-manufacturing-')
        self.root=Path(self.owner.name);self.key=key;self.board_name=board_name;self.job_name=job_name
        self.sources={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
        self.drc=False;self.jobset=False;self.artifacts={};self.evidence={}
        for name,data in files.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.metrics=saved_metrics(files[board_name],files[Path(board_name).with_suffix('.kicad_pro').as_posix()])

    def validate(self,key):
        if key!=self.key:raise ValueError('Board, project, profile or selected jobset changed. Repeat the audit and verification.')
        for name,digest in self.sources.items():
            path=self.root/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('A verification command modified saved design inputs. Repeat the audit.')

    def record(self,kind,passed,details):
        self.validate(self.key)
        setattr(self,kind,bool(passed))
        self.evidence[kind]=details
        # Outputs from a selected jobset must be regenerated if DRC is rerun.
        if kind=='drc':self.jobset=False
        self.artifacts={path.relative_to(self.root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()}

    def ready(self,key):
        self.validate(key)
        if not self.drc or (self.job_name and not self.jobset):
            raise ValueError('Release requires passing DRC and the selected jobset for this exact snapshot.')
        return self.artifacts
