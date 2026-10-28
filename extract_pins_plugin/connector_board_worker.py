"""Read a saved mating board in native KiCad Python, outside the IPC facade."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def load_inventory(path, timeout=60):
    """Return serializable saved contacts without importing pcbnew in the caller.

    The installed IPC facade deliberately has no LoadBoard. This process boundary
    also prevents the native worker from replacing the live originating board.
    """
    from wayricad_runtime.runtime_setup import native_python, child_environment
    source=Path(path).resolve()
    if source.suffix.lower()!='.kicad_pcb' or not source.is_file():
        raise ValueError('Select an existing .kicad_pcb for connector B.')
    with tempfile.TemporaryDirectory(prefix='wayricad-connector-') as temporary:
        output=Path(temporary)/'contacts.json'
        completed=subprocess.run([str(native_python()),'-I',str(Path(__file__).resolve()),str(source),str(output)],
                                 capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,
                                 env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not output.is_file():
            raise RuntimeError('Native connector reader failed: '+(completed.stderr or completed.stdout)[-2000:])
        if output.stat().st_size>64*1024*1024:raise ValueError('External connector inventory exceeds its 64 MB review budget.')
        result=json.loads(output.read_text(encoding='utf-8'))
        if completed.returncode or result.get('error'):
            raise ValueError(result.get('error','Native connector extraction failed.'))
        return result


def extract_inventory(path):
    """Read native pad geometry only; called exclusively in a fresh worker."""
    import pcbnew
    source=Path(path);before=hashlib.sha256(source.read_bytes()).hexdigest()
    spec=importlib.util.spec_from_file_location('_connector_contacts',Path(__file__).parent/'core/connector_mating.py')
    geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
    board=pcbnew.LoadBoard(str(source));inventory={};errors={};contacts=0
    for index,footprint in enumerate(board.GetFootprints()):
        if index>=20000:raise ValueError('External board exceeds the 20,000-footprint review budget.')
        ref=str(footprint.GetReference()).strip()
        if not ref:continue
        try:
            pins=geometry.footprint_pins(footprint);contacts+=len(pins)
            if not pins:continue
            if contacts>200000:raise RuntimeError('External board exceeds the 200,000-contact review budget.')
            if ref in inventory or ref in errors:raise RuntimeError('External board has duplicate footprint references: '+ref)
            inventory[ref]=pins
        except ValueError as exc:errors[ref]=str(exc)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=before:
        raise ValueError('External board changed during native extraction. Load it again.')
    return dict(inventory=inventory,errors=errors,source_sha256=before)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board');parser.add_argument('output');args=parser.parse_args()
    try:result=extract_inventory(args.board);code=0
    except Exception as exc:result={'error':str(exc)};code=1
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return code


if __name__=='__main__':raise SystemExit(main())
