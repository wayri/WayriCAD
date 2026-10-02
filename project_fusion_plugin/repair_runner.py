"""Private subprocess entry point; never register a plugin in a detached process."""
import json
from pathlib import Path
import sys
import types
from dataclasses import asdict

package=types.ModuleType('_fusion_repair_worker')
package.__path__=[str(Path(__file__).resolve().parent)]
sys.modules[package.__name__]=package
from _fusion_repair_worker.model import SourceSpec
from _fusion_repair_worker.netlist import KiCadCLI
from _fusion_repair_worker.repair import _compile_copy

if __name__=='__main__':
    data=json.load(sys.stdin)
    spec,report=_compile_copy(SourceSpec(**data['spec']),KiCadCLI(data['cli_path']),data['retain_blank'])
    print(json.dumps({'spec':asdict(spec),'report':report}))
