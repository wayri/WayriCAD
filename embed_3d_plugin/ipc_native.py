"""Saved-file asset operations for IPC hosts without embedded Python/SWIG."""
from pathlib import Path
import subprocess
import tempfile
import os
from .native import NativeBridge
from .sexpr import parse
from .cli_validation import find_cli


class IPCBridge:
    supports_normalization=True
    supports_live_tools=False
    supports_native_roundtrip=False
    capability_note=('Embed3D updates saved project files with backups. Save and close editors before applying. '
                     'As-placed normalization uses the installed KiCad 10 native helper; live-board tools require the legacy adapter.')
    model_structure=staticmethod(NativeBridge.model_structure)
    check_payloads=NativeBridge.check_payloads

    def __init__(self,pcbnew):
        self.board=pcbnew.GetBoard();self.version=pcbnew.Version();self.leases=[]
    def project_path(self):return Path(self.board.GetFileName()).parent
    def prepare_resolver(self,resolver,references=()):return resolver
    def deserialize(self,text):
        raise RuntimeError('Native footprint parsing is unavailable through IPC; use validate_footprint_file for CLI parser acceptance.')
    def serialize(self,text):
        raise RuntimeError('Native footprint serialization is unavailable through IPC.')
    def extract_normalized_footprints(self,source_path,cancelled=None,selected_uuids=None):
        from .native_worker import normalize
        if cancelled and cancelled():raise InterruptedError('Normalization cancelled')
        return normalize(source_path,selected_uuids)
    def _validate_export(self,source,kind):
        cli=find_cli()
        if not cli:raise RuntimeError('KiCad CLI is required to validate the output board.')
        source=Path(source)
        if not source.is_file():raise ValueError('Validation source is missing: '+str(source))
        with tempfile.TemporaryDirectory(prefix='wayricad-board-check-') as tmp:
            command=[str(cli),kind,'export','svg','--layers','F.Cu','--output',tmp+os.sep,str(source)]
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            result=subprocess.run(command,capture_output=True,text=True,timeout=180,**options)
            if result.returncode or not any(Path(tmp).rglob('*.svg')):
                raise ValueError('KiCad parser validation failed: '+result.stdout+'\n'+result.stderr)
    def validate_portable_board(self,source):self._validate_export(source,'pcb')
    def validate_footprint_file(self,source):self._validate_export(source,'fp')
