"""Saved-file asset operations for IPC hosts without embedded Python/SWIG."""
from pathlib import Path
import subprocess
import tempfile
import os
from .native import NativeBridge
from .sexpr import parse
from .cli_validation import find_cli


class IPCBridge:
    supports_normalization=False
    supports_live_tools=False
    supports_native_roundtrip=False
    capability_note=('IPC mode reads saved designs and creates new copies. Footprints use previously embedded archives; '
                     'as-placed footprint normalization and live-board tools require the KiCad 10 source plugin. '
                     'Validation uses the local KiCad CLI parser, not a footprint round-trip.')
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
    def extract_normalized_footprints(self,*args,**kwargs):
        raise RuntimeError('This IPC API does not expose native footprint-library normalization. Use previously embedded footprint archives, or uncheck Footprints to process symbols and 3D models. KiCad 10 source launch retains native normalization.')
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
