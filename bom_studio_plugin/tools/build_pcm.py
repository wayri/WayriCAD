#!/usr/bin/env python3
"""Build a deterministic WayriCAD PCM Install-from-File ZIP from this plugin tree.

No network access, publishing or package installation. Existing outputs are refused.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import zipfile
from validate_pcm import MANIFEST, PackageError, json_object, safe_name, validate

STAMP=(2026,9,10,0,0,0)
IGNORE_DIRS={'__pycache__','.git','.venv','.mypy_cache','.pytest_cache','test-artifacts'}

def collect(plugin: Path) -> dict[str,bytes]:
    plugin=plugin.resolve()
    meta=json_object((plugin/'tools/pcm-package.json').read_bytes(),'pcm-package.json')
    payload={'metadata.json':(json.dumps(meta,indent=2,ensure_ascii=False)+'\n').encode(),
             'resources/icon.png':(plugin/'resources/icon-64.png').read_bytes()}
    for path in sorted(plugin.rglob('*')):
        relative=path.relative_to(plugin)
        if any(part in IGNORE_DIRS for part in relative.parts):continue
        if path.is_symlink():raise PackageError(f'Refusing symlink: {relative}')
        if not path.is_file():continue
        if path.suffix.lower() in ('.pyc','.pyo','.zip','.log') or path.name in ('.DS_Store','PACKAGE_MANIFEST.json'):continue
        name='plugins/'+relative.as_posix();safe_name(name)
        payload[name]=path.read_bytes()
    manifest={'schema':'wayricad-pcm-manifest-1','version':meta['versions'][0]['version'],
              'files':{name:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in sorted(payload.items())}}
    payload[MANIFEST]=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode()
    return payload

def build(plugin: Path, output: Path, schema_dir: Path | None=None) -> dict:
    output=output.resolve();plugin=plugin.resolve()
    if output.is_relative_to(plugin):raise PackageError('Output ZIP must be outside the plugin source tree')
    payload=collect(plugin)
    # Exclusive creation prevents accidental overwrites, including concurrent builds.
    with output.open('xb') as f:
        try:
            with zipfile.ZipFile(f,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                order=['metadata.json','resources/icon.png']+sorted(k for k in payload if k not in ('metadata.json','resources/icon.png'))
                for name in order:
                    info=zipfile.ZipInfo(name,STAMP);info.compress_type=zipfile.ZIP_DEFLATED
                    info.create_system=3;mode=0o755 if name.endswith('.sh') else 0o644
                    info.external_attr=(stat.S_IFREG|mode)<<16
                    z.writestr(info,payload[name],compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        except BaseException:
            f.close();output.unlink(missing_ok=True);raise
    try:return validate(output,schema_dir)
    except BaseException:output.unlink(missing_ok=True);raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--schema-dir',type=Path,help='Optional directory of the recorded official schema snapshots')
    args=parser.parse_args(argv)
    try:print(json.dumps(build(args.plugin_dir,args.output,args.schema_dir),indent=2));return 0
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
