"""Isolated native normalization for IPC and command-line project libraries."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def normalize(source, selected_uuids=None):
    data = run({'action': 'normalize', 'source': str(Path(source).resolve()),
                'selected': sorted(selected_uuids) if selected_uuids is not None else None})
    return data['normalized'], data['source_hash']


def validate_project(stage, pcb_name=None, schematic_name=None):
    return run({'action': 'validate', 'source': str(Path(stage).resolve()),
                'pcb': pcb_name, 'schematic': schematic_name})


def run(payload):
    from wayricad_runtime.native_analysis import native_python, child_environment
    with tempfile.TemporaryDirectory(prefix='wayricad-library-normalize-') as tmp:
        request = Path(tmp)/'request.json'; output = Path(tmp)/'normalized.json'
        request.write_text(json.dumps(payload), encoding='utf-8')
        try:
            result = subprocess.run([str(native_python()), '-I', '-X', 'faulthandler', str(Path(__file__).resolve()), str(request), str(output)],
                                    env=child_environment(), capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            detail = exc.stderr or ''
            if isinstance(detail, bytes):
                detail = detail.decode('utf-8', errors='replace')
            raise RuntimeError('Native asset operation exceeded 180 seconds; the isolated worker was stopped. '
                               + detail[-3000:]) from exc
        if result.returncode:
            raise RuntimeError('Native asset operation failed (exit '+str(result.returncode)+'): '+result.stderr[-3000:])
        try:
            data = json.loads(output.read_text(encoding='utf-8-sig'))
        except (ValueError,OSError) as exc:
            raise RuntimeError('Native asset worker returned no valid result. '+(result.stderr or result.stdout)[-3000:]) from exc
        if not isinstance(data,dict):raise RuntimeError('Native asset worker returned an invalid result object.')
        return data


def main():
    os.environ['WAYRICAD_EMBED3D_NO_REGISTER']='1'
    import faulthandler
    faulthandler.dump_traceback_later(60,repeat=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sys.path.insert(0,str(root))
    if (root.parent/'wayricad_runtime').is_dir():sys.path.insert(0,str(root.parent))
    package = 'wayricad_asset_worker'
    spec = importlib.util.spec_from_file_location(package, root/'__init__.py', submodule_search_locations=[str(root)])
    loaded = importlib.util.module_from_spec(spec); sys.modules[package] = loaded; spec.loader.exec_module(loaded)
    from importlib import import_module
    import pcbnew
    NativeBridge = import_module('.native', package).NativeBridge
    request = json.loads(args.request.read_text(encoding='utf-8'))
    bridge = NativeBridge(pcbnew)
    if request['action'] == 'normalize':
        normalized, digest = bridge.extract_normalized_footprints(
            request['source'], selected_uuids=set(request['selected']) if request['selected'] is not None else None)
        result = {'normalized': normalized, 'source_hash': digest}
    else:
        stage = Path(request['source'])
        if request.get('pcb'):
            bridge.validate_portable_board(stage / request['pcb'])
        count = 0
        for path in stage.rglob('*.kicad_mod'):
            fp = bridge.deserialize(path.read_text(encoding='utf-8'))
            bridge._release_scratch(fp)
            count += 1
        if request.get('schematic'):
            import_module('.cli_validation', package).validate_schematic(stage / request['schematic'])
        result = {'native_footprints': count, 'pcb': bool(request.get('pcb')), 'schematic': bool(request.get('schematic'))}
    bridge.release_detached()
    args.output.write_text(json.dumps(result), encoding='utf-8')
    faulthandler.cancel_dump_traceback_later()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
