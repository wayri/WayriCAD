#!/usr/bin/env python3
"""Validate this WayriCAD IPC package. Optional --schema-dir enables official JSON schemas.

This is an archive/schema check, NOT a KiCad-host installation or execution test.
Runtime: standard library; jsonschema is needed only for --schema-dir.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import zipfile
import zlib

MANIFEST = 'plugins/PACKAGE_MANIFEST.json'
SCHEMA_BLOBS = {
    'pcm.v1.schema.json': 'aab570f86911ec42f6e3b100d23e38465cea1989',
    'pcm.v2.schema.json': 'fea9c2f07c69d68ad984ef7d483c6a4537319825',
    'api.v1.schema.json': '4a63501e61131471fa8531b4f06025935382672b',
}

class PackageError(ValueError):
    """The package does not satisfy this distribution's documented contract."""

def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)

def json_object(data: bytes, name: str) -> dict:
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, f'{name}: duplicate JSON key {key!r}')
            out[key] = value
        return out
    try:
        obj = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                         parse_constant=lambda x: (_ for _ in ()).throw(PackageError(f'{name}: nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f'{name}: invalid UTF-8 JSON: {exc}') from exc
    require(isinstance(obj, dict), f'{name}: root must be an object')
    return obj

def safe_name(name: str) -> None:
    require(bool(name) and '\\' not in name and '\x00' not in name, f'Unsafe ZIP path: {name!r}')
    path = PurePosixPath(name)
    require(not path.is_absolute() and name == str(path), f'Noncanonical ZIP path: {name!r}')
    require(all(part not in ('.', '..') and ':' not in part for part in path.parts), f'Unsafe ZIP path: {name!r}')
    for part in path.parts:
        require(part.rstrip(' .') == part, f'Windows-ambiguous ZIP name: {name!r}')
        stem = part.split('.')[0].upper()
        require(stem not in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))},
                f'Windows-reserved ZIP name: {name!r}')
        require(not any(ord(c)<32 or c in '<>"|?*' for c in part), f'Unsafe ZIP name: {name!r}')

def png_info(data: bytes, expected: int) -> dict:
    require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'Icon is not a PNG')
    pos=8; chunks=[]; header=None; compressed=bytearray()
    while pos < len(data):
        require(pos+12<=len(data), 'Truncated PNG chunk')
        length=struct.unpack('>I',data[pos:pos+4])[0]; kind=data[pos+4:pos+8]
        require(length<=4*1024*1024 and pos+12+length<=len(data), 'Invalid PNG chunk length')
        payload=data[pos+8:pos+8+length]; crc=struct.unpack('>I',data[pos+8+length:pos+12+length])[0]
        require(zlib.crc32(kind+payload)&0xffffffff == crc, 'PNG chunk CRC mismatch')
        chunks.append(kind)
        if kind==b'IHDR':
            require(header is None and len(payload)==13 and len(chunks)==1, 'Invalid PNG IHDR')
            header=struct.unpack('>IIBBBBB',payload)
        if kind==b'IDAT': compressed.extend(payload)
        pos+=length+12
        if kind==b'IEND':
            require(length==0 and pos==len(data), 'Trailing PNG data')
            break
    require(header is not None and chunks[-1:]==[b'IEND'], 'PNG missing required chunks')
    w,h,depth,color,compression,filtering,interlace=header
    require((w,h)==(expected,expected), f'Icon dimensions must be {expected} x {expected}, got {w} x {h}')
    require((depth,color,compression,filtering,interlace)==(8,6,0,0,0), 'Expected 8-bit noninterlaced RGBA PNG')
    needed=h*(1+4*w)
    try:
        d=zlib.decompressobj(); raw=d.decompress(bytes(compressed),needed+1)
    except zlib.error as exc:
        raise PackageError(f'Invalid PNG compression: {exc}') from exc
    require(len(raw)==needed and d.eof and not d.unused_data, 'PNG decoded data size mismatch')
    require(all(raw[i*(1+4*w)]<=4 for i in range(h)), 'Invalid PNG scanline filter')
    return {'width':w,'height':h,'format':'RGBA8','crc':'passed'}

def validate(path: Path | str, schema_dir: Path | str | None = None) -> dict:
    path=Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            entries=z.infolist()
            require(0<len(entries)<=20000, 'Invalid archive entry count')
            require(sum(i.file_size for i in entries)<=512*1024*1024, 'Archive exceeds 512 MiB validation limit')
            names=set(); folded=set()
            for i in entries:
                require(not i.is_dir(), 'Explicit directory entries are not used by this package')
                safe_name(i.filename)
                require(i.filename not in names and i.filename.casefold() not in folded, 'Duplicate/case-colliding ZIP path')
                names.add(i.filename);folded.add(i.filename.casefold())
                require(not i.flag_bits&1, 'Encrypted ZIP is not allowed')
                require(i.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED), 'ZIP method is not PCM-compatible')
                mode=(i.external_attr>>16)&0xffff
                require(not stat.S_ISLNK(mode), 'Symlinks are not allowed')
                require(i.filename=='metadata.json' or i.filename.startswith(('plugins/','resources/')), 'Unexpected archive wrapper/top-level content')
            require('metadata.json' in names, 'Missing metadata.json at archive root')
            required=('plugins/plugin.json','plugins/entrypoint.py','plugins/cli.py','plugins/requirements.txt',
                      'plugins/bomstudio/__init__.py','plugins/bomstudio/server.py','plugins/bomstudio/engine.py',
                      'plugins/web/index.html','plugins/web/app.js','resources/icon.png',
                      'plugins/resources/ICON_LICENSE.md',MANIFEST)
            require(all(name in names for name in required), 'Missing IPC entrypoint/runtime/icon/license/manifest files')
            require(not any('__pycache__' in PurePosixPath(n).parts or n.endswith(('.pyc','.pyo')) for n in names), 'Generated Python bytecode must not be shipped')
            meta=json_object(z.read('metadata.json'),'metadata.json')
            plugin=json_object(z.read('plugins/plugin.json'),'plugin.json')
            for key in ('name','description','description_full','identifier','type','author','license','resources','versions'):
                require(key in meta,f'Missing required PCM key: {key}')
            require(meta['type']=='plugin','Package type must be plugin')
            require(isinstance(meta['identifier'],str) and re.fullmatch(r'[a-zA-Z][-a-zA-Z0-9.]{0,98}[a-zA-Z0-9]',meta['identifier']) is not None,'Invalid PCM identifier')
            require(isinstance(meta['versions'],list) and len(meta['versions'])==1,'Install-from-file package must describe exactly one version')
            v=meta['versions'][0]
            require(isinstance(v,dict) and v.get('runtime')=='ipc','PCM version runtime must explicitly be ipc')
            require(v.get('kicad_version')=='10.0','This package must declare KiCad 10.0 minimum')
            require(v.get('status') in ('development','testing','stable','deprecated'),'Invalid version status')
            require(isinstance(v.get('version'),str) and re.fullmatch(r'\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?',v['version']) is not None,'Invalid version number')
            require(not any(k.startswith('download_') for k in v),'Do not put repository-only download_* fields inside the ZIP')
            require(plugin.get('identifier')==meta['identifier'],'PCM/plugin identifiers disagree')
            require(plugin.get('runtime',{}).get('type')=='python','Expected Python IPC runtime')
            require(plugin.get('runtime',{}).get('min_version')=='3.10.0','Python 3.10+ declaration missing')
            actions=plugin.get('actions',[])
            require(len(actions)==1 and actions[0].get('identifier')=='open','Missing expected BOM action')
            action=actions[0]
            require(action.get('show-button') is True and action.get('scopes')==['pcb'],'Expected visible PCB action')
            ep=action.get('entrypoint','');safe_name(ep)
            require('plugins/'+ep in names,'Action entrypoint missing')
            icon_results={'resources/icon.png':png_info(z.read('resources/icon.png'),64)}
            for theme in ('light','dark'):
                icons=action.get('icons-'+theme)
                require(isinstance(icons,list) and len(icons)==3,f'Missing {theme} high-DPI PNG array')
                for icon,size in zip(icons,(24,48,96)):
                    safe_name(icon);name='plugins/'+icon
                    require(name in names,f'Missing icon {name}')
                    icon_results[name]=png_info(z.read(name),size)
            require(z.read('resources/icon.png')==z.read('plugins/resources/icon-64.png'),'PCM image must match packaged 64-pixel artwork')
            manifest=json_object(z.read(MANIFEST),MANIFEST)
            require(manifest.get('schema')=='wayricad-pcm-manifest-1','Unknown package manifest')
            declared=manifest.get('files')
            require(isinstance(declared,dict) and set(declared)==names-{MANIFEST},'Manifest membership mismatch')
            for name,record in declared.items():
                data=z.read(name)
                require(record.get('size')==len(data) and record.get('sha256')==hashlib.sha256(data).hexdigest(), f'Manifest integrity mismatch: {name}')
            require(z.testzip() is None,'ZIP CRC failure')
            schemas=[]
            if schema_dir is not None:
                try:import jsonschema
                except ImportError as exc:raise PackageError('Install jsonschema in the build environment to use --schema-dir') from exc
                # KiCad 10+ requires PCM v2 and the IPC schema. The legacy
                # PCM v1 snapshot is also checked when explicitly provided.
                require(all((Path(schema_dir)/n).is_file() for n in ('pcm.v2.schema.json','api.v1.schema.json')),
                        'Official schema validation needs PCM v2 and IPC v1 snapshots')
                for name,expected in SCHEMA_BLOBS.items():
                    if name=='pcm.v1.schema.json' and not (Path(schema_dir)/name).is_file():continue
                    data=(Path(schema_dir)/name).read_bytes()
                    actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                    require(actual==expected,f'Schema differs from the recorded upstream snapshot: {name}')
                    schema=json_object(data,name)
                    target=plugin if name.startswith('api.') else meta
                    jsonschema.Draft7Validator.check_schema(schema)
                    errors=list(jsonschema.Draft7Validator(schema).iter_errors(target))
                    require(not errors,f'{name}: '+ '; '.join(str(e.message) for e in errors))
                    schemas.append({'name':name,'git_blob_sha1':actual,'status':'passed'})
            pkg=meta['identifier'].replace('.','_')
            return {'schema':'wayricad-pcm-validation-1','ok':True,'version':v['version'],
                    'archive':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'zip_bytes':path.stat().st_size,'files':len(names),'uncompressed_bytes':sum(i.file_size for i in entries),
                    'zip_crc':'passed','per_file_integrity':'passed','icons':icon_results,
                    'official_schema_validation':schemas or 'not_requested (structural checks only)',
                    'installed_plugin_relative_path':f'plugins/{pkg}/plugin.json',
                    'host_installation_tested':False,
                    'notes':['Archive checks are not actual KiCad GUI installation or runtime acceptance.',
                             'First IPC environment provisioning may need Python/package access.',
                             'Metadata minimum 10.0 does not certify future KiCad versions.']}
    except (OSError,zipfile.BadZipFile,KeyError,TypeError,struct.error) as exc:
        raise PackageError(f'Cannot validate package: {exc}') from exc

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip',type=Path);parser.add_argument('--schema-dir',type=Path)
    parser.add_argument('--output',type=Path,help='Write a new JSON receipt; never overwrite')
    args=parser.parse_args(argv)
    try:
        result=validate(args.zip,args.schema_dir)
        data=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
        if args.output:
            with args.output.open('x',encoding='utf-8') as f:f.write(data)
        print(data,end='');return 0
    except (PackageError,OSError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
