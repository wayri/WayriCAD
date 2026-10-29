"""Isolated, custody-bound network postprocessing of a saved EMerge result.

Usage: selected-solver-python -I network_worker.py request.json
The output is a derived scalar network, never a modified electromagnetic result.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

if __package__ in (None,''):
    import importlib.util
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('quick_emerge_plugin',root/'__init__.py',submodule_search_locations=[str(root)])
    module=importlib.util.module_from_spec(spec);sys.modules['quick_emerge_plugin']=module
    # The generated PCM initializer registers editor actions; workers must not run it.
    __package__='quick_emerge_plugin'
    # PCM installs carry the runtime inside this plugin; source checkouts use
    # the repository copy. Both are explicit trusted code locations under -I.
    runtime_root=root if (root/'wayricad_runtime').is_dir() else root.parent
    if (runtime_root/'wayricad_runtime').is_dir():sys.path.insert(0,str(runtime_root))

from .model import config_digest,source_identity
from .network import from_result
from .network_extensions import apply_operation,deserialize_network,diagnostics

MAX_RESULT_BYTES=32*1024*1024


def _read(path):
    if path.stat().st_size>MAX_RESULT_BYTES:raise ValueError('Network input exceeds the 32 MiB limit')
    data=path.read_bytes()
    return data,hashlib.sha256(data).hexdigest()


def _source_check(result):
    if result.get('config_sha256')!=config_digest(result.get('config')):raise ValueError('Source result configuration hash is invalid')
    try:json.dumps(result,allow_nan=False)
    except (ValueError,TypeError) as exc:raise ValueError('Source result contains nonfinite or non-JSON evidence') from exc
    source=result.get('source')
    if not isinstance(source,dict) or not isinstance(source.get('path'),str) or source_identity(source.get('path'))!=source:raise ValueError('Source PCB changed since the solve; the network is stale')
    if result.get('region_sha256'):
        from .region_backend import region_digest
        if region_digest(result['region'])!=result['region_sha256']:raise ValueError('Source result geometry hash changed')
    if result.get('import_source'):
        a=result['config'].get('advanced',{})
        if a.get('import_kind','none')!='none':
            from .advanced_imports import verify_import
            if verify_import(a)!=result['import_source']:raise ValueError('Imported source changed since solve')
        else:
            imported=result['import_source']
            _,digest=_read(Path(imported['path']))
            if digest!=imported['sha256']:raise ValueError('Imported geometry changed since solve')


def run_request(request_path):
    from wayricad_runtime.report_ui import publish_documents
    request_path=Path(request_path).resolve(strict=True)
    if request_path.stat().st_size>1024*1024:raise ValueError('Network request exceeds 1 MiB')
    raw=request_path.read_bytes();request=json.loads(raw)
    required={'schema','source_result_path','source_result_sha256','operation','output_path'}
    if not isinstance(request,dict) or set(request)!=required or type(request['schema']) is not int or request['schema']!=1:raise ValueError('Unsupported network request schema or arguments')
    source_path=Path(request['source_result_path']).resolve(strict=True)
    output_path=Path(request['output_path']).expanduser().absolute()
    if output_path.suffix.lower()!='.json':raise ValueError('Derived-network output must be a JSON file')
    content,digest=_read(source_path)
    if digest!=request['source_result_sha256']:raise ValueError('Saved source result changed after the network operation was reviewed')
    result=json.loads(content);_source_check(result)
    original=from_result(result)
    derived=apply_operation(original,request['operation'])
    derived_network=deserialize_network(derived['derived_network'])
    payload={'schema':1,'kind':'derived-network','source_result':{'path':str(source_path),'sha256':digest},
             'source_board':result['source'],'operation':request['operation'],**derived,
             'diagnostics':diagnostics(derived_network),
             'limits':['Derived scalar response only; original solved electromagnetic fields and geometry are unchanged.',
                       'Transformations do not establish mesh convergence or physical component/package accuracy.']}
    _source_check(result)
    if _read(source_path)[1]!=digest or request_path.read_bytes()!=raw:raise ValueError('Network inputs changed during postprocessing; no derived result was published')
    sources=[request_path,source_path,result['source']['path']]
    if result.get('import_source') and Path(result['import_source']['path']).is_file():sources.append(result['import_source']['path'])
    publish_documents({output_path:json.dumps(payload,indent=2,allow_nan=False)+'\n'},sources=sources)
    return payload


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if len(args)!=1:raise ValueError('Provide exactly one network request JSON path')
    try:
        payload=run_request(args[0])
        print(json.dumps({'status':'completed','output_path':str(Path(json.loads(Path(args[0]).read_text(encoding='utf-8'))['output_path']).resolve()),'network_sha256':payload['derived_network']['network_sha256']}))
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(json.dumps({'status':'failed','error':str(exc)}))
        return 2


if __name__=='__main__':raise SystemExit(main())
