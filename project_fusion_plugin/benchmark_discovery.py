"""Reproducible source parser benchmark; does not cache native acceptance.

Run from the repository root with ``python -m project_fusion_plugin.benchmark_discovery``
under a headless package context, or run this saved script directly. It builds a
synthetic project with 100 occurrences of one populated child sheet, compares
full import discovery with lightweight scope metadata and emits JSON. Temporary
input files are discarded.
"""
from pathlib import Path
from types import ModuleType
import importlib
import json
import statistics
import sys
import tempfile
import time
from unittest import mock

if __package__ in (None,''):
    package=ModuleType('_fusion_benchmark');package.__path__=[str(Path(__file__).parent)]
    sys.modules[package.__name__]=package;__package__=package.__name__

from . import source_detection as detection
from . import schematic as schematic
from . import sexpr as sx
from .model import SourceSpec


def benchmark(occurrences=100,symbols=20,runs=3):
    with tempfile.TemporaryDirectory(prefix='fusion-discovery-benchmark-') as folder:
        root=Path(folder);root_id=schematic.new_uuid()
        ids=[schematic.new_uuid() for _ in range(occurrences)]
        sheets=' '.join('(sheet (uuid "'+ident+'") (property "Sheetname" "Page '+str(index)+'") '
                        '(property "Sheetfile" "child.kicad_sch"))' for index,ident in enumerate(ids))
        (root/'board.kicad_pro').write_text('{}')
        (root/'board.kicad_sch').write_text('(kicad_sch (version 20260306) (uuid "'+root_id+'") (lib_symbols) '+sheets+')')
        symbols_text=[]
        for index in range(symbols):
            instances=' '.join('(path "/'+root_id+'/'+ident+'" (reference "R'+str(page*symbols+index+1)+'") (unit 1))'
                               for page,ident in enumerate(ids))
            symbols_text.append('(symbol (lib_id "Device:R") (uuid "'+schematic.new_uuid()+'") (unit 1) '
                                '(property "Reference" "R'+str(index+1)+'") (property "Value" "1k") '
                                '(instances (project "board" '+instances+')))')
        (root/'child.kicad_sch').write_text('(kicad_sch (version 20260306) (uuid "'+schematic.new_uuid()+
                                            '") (lib_symbols (symbol "Device:R")) '+' '.join(symbols_text)+')')
        spec=SourceSpec(str(root/'board.kicad_pro'),'Example')
        samples={};counts={}
        for label,action in [('full_import_discovery',lambda:schematic.discover(spec,schematic.new_uuid(),require_board=False)),
                             ('scope_catalogue',lambda:detection.sheet_catalogue(spec))]:
            durations=[]
            with mock.patch.object(sx,'loads',wraps=sx.loads) as parse:
                for _ in range(runs):
                    started=time.perf_counter();action()
                    durations.append(time.perf_counter()-started)
                counts[label]=parse.call_count
            samples[label]=statistics.median(durations)
        return {'occurrences':occurrences,'symbols_per_occurrence':symbols,'runs':runs,
                'median_seconds':samples,'parses':counts,
                'speedup':samples['full_import_discovery']/samples['scope_catalogue'],
                'scope':'Saved syntax discovery only; fresh native validation is not cached.'}


if __name__=='__main__':print(json.dumps(benchmark(),indent=2))
