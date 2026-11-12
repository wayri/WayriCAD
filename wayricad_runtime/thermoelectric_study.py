"""Portable source-bound 3D studies shared by independent engineering plugins."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

MAX_BYTES = 16*1024*1024
MAX_REQUEST_NODES = 1_000_000
# Reports include duplicated cell fields, coordinates, faces and provenance.
# Keep their intake distinct from editable requests; sufficient for 50k cells.
MAX_REPORT_BYTES = 128*1024*1024
MAX_REPORT_NODES = 4_000_000
MAX_DEPTH = 32


def _check_tree(data,max_nodes):
    """Count values and object keys with O(depth), not O(width), working state."""
    nodes=0
    pending=[(iter((data,)),0)]
    while pending:
        iterator,depth=pending[-1]
        try:value=next(iterator)
        except StopIteration:
            pending.pop();continue
        nodes+=1
        if isinstance(value,dict):nodes+=len(value)
        if nodes>max_nodes:raise ValueError('Study JSON exceeds the aggregate node budget.')
        if depth>MAX_DEPTH:raise ValueError('Study JSON nesting exceeds 32 levels.')
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError('Non-finite JSON number.')
        if isinstance(value,dict):pending.append((iter(value.values()),depth+1))
        elif isinstance(value,list):pending.append((iter(value),depth+1))


def _parse_json(text,max_bytes,max_nodes):
    if not isinstance(text,str) or len(text)>max_bytes or len(text.encode('utf-8'))>max_bytes:
        raise ValueError(f'A 3D document must be bounded UTF-8 JSON ({max_bytes//(1024*1024)} MiB maximum).')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('Repeated study field: '+key)
            result[key]=value
        return result
    def invalid(value): raise ValueError('Non-finite JSON number: '+value)
    try:data=json.loads(text,object_pairs_hook=pairs,parse_constant=invalid)
    except RecursionError as exc:raise ValueError('Study JSON nesting exceeds the supported depth.') from exc
    if not isinstance(data,dict): raise ValueError('A 3D study must be a JSON object.')
    _check_tree(data,max_nodes)
    return data


def parse_study(text):
    """Parse editable request/mapping JSON: at most 16 MiB and 1M nodes.

    Nodes include every value/container and object key. The standard JSON
    decoder allocates the byte-bounded document before the node/depth checks;
    traversal itself keeps only one iterator per nesting level.
    """
    return _parse_json(text,MAX_BYTES,MAX_REQUEST_NODES)


def parse_report(text):
    """Parse and integrity-check exported evidence: at most 128 MiB/4M nodes.

    The larger budget is only for converged report envelopes, not requests.
    Hashes bind content against accidental changes, not authenticated origin.
    """
    return validate_report(_parse_json(text,MAX_REPORT_BYTES,MAX_REPORT_NODES))


def load_report(path):
    """Read a bounded exported JSON report, including a possible UTF-8 BOM."""
    with Path(path).open('rb') as stream:
        if os.fstat(stream.fileno()).st_size>MAX_REPORT_BYTES:
            raise ValueError('3D report exceeds 128 MiB.')
        payload=stream.read(MAX_REPORT_BYTES+1)
    if len(payload)>MAX_REPORT_BYTES:raise ValueError('3D report exceeds 128 MiB.')
    try:text=payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:raise ValueError('3D report must be UTF-8 JSON.') from exc
    return parse_report(text)


def run_study(request,cancel=None):
    from .thermoelectric3d import solve_thermoelectric3d
    encoded=json.dumps(request,sort_keys=True,allow_nan=False,separators=(',',':'))
    request=parse_study(encoded)
    try:result=solve_thermoelectric3d(request,cancel=cancel)
    except ImportError as exc:
        raise RuntimeError('3D solid studies require NumPy and SciPy in this plugin runtime. Use the managed scientific runtime setup; the reduced-order heater path remains available.') from exc
    import inspect
    kernel=Path(inspect.getsourcefile(solve_thermoelectric3d)).read_bytes()
    return dict(schema='wayricad.thermoelectric-study/v1',created_utc=datetime.now(timezone.utc).isoformat(),
                solver_source_sha256=hashlib.sha256(kernel).hexdigest(),
                request_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                units=dict(length='mm',temperature='C',voltage='V',current='A',power='W',current_density='A/m2'),
                result_sha256=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest(),
                request=request,result=result,
                notice='Steady 3D voxel screening; mesh convergence and material/contact evidence are required. Not fabrication or thermal safety approval.')


def save_document(path,text,*,sources=()):
    destination=Path(path).resolve()
    if destination.suffix.lower() not in ('.json','.html'): raise ValueError('Use a separate .json or .html destination.')
    for source in sources:
        source=Path(source).resolve()
        if destination==source or (destination.exists() and source.exists() and os.path.samefile(destination,source)):
            raise ValueError('Output must not overwrite the source study or board.')
    descriptor,temporary=tempfile.mkstemp(prefix='.thermoelectric-',suffix=destination.suffix,dir=destination.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,destination)
    finally:Path(temporary).unlink(missing_ok=True)


def validate_report(report):
    if not isinstance(report,dict) or report.get('schema')!='wayricad.thermoelectric-study/v1' or not isinstance(report.get('result'),dict) or not report['result'].get('converged') or not isinstance(report.get('request'),dict):
        raise ValueError('A converged shared 3D study is required.')
    for key,signature in (('request','request_sha256'),('result','result_sha256')):
        actual=hashlib.sha256(json.dumps(report[key],sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
        if actual!=report.get(signature):raise ValueError('Imported 3D '+key+' changed; rerun the study.')
    return report


def sample_temperature(report,x_mm,y_mm,z_mm,*,request_sha256=None):
    """Integrity-check evidence and probe an original cell, never nearest-fill."""
    validate_report(report)
    return _sample_temperature_validated(report,x_mm,y_mm,z_mm,request_sha256=request_sha256)


def _sample_temperature_validated(report,x_mm,y_mm,z_mm,*,request_sha256=None):
    """Internal batch probe: caller must validate once and not mutate the report."""
    import bisect
    if request_sha256 is not None and report['request_sha256']!=request_sha256:
        raise ValueError('Temperature study identity differs from the selected electrical study.')
    axes=report['result']['coordinates']['edges_mm'];indices=[]
    for axis,value in zip('xyz',(x_mm,y_mm,z_mm)):
        if not math.isfinite(value):raise ValueError('Probe coordinates must be finite.')
        edges=axes[axis]
        if value<edges[0] or value>edges[-1]:raise ValueError('Probe lies outside the solved volume.')
        indices.append(min(len(edges)-2,bisect.bisect_right(edges,value)-1))
    nx,ny,_nz=report['result']['coordinates']['shape_xyz']
    index=(indices[2]*ny+indices[1])*nx+indices[0]
    value=report['result']['temperatures_c'][index]
    if value is None:raise ValueError('Probe lies in an unsolved void cell.')
    return dict(temperature_c=value,cell_index=index,request_sha256=report['request_sha256'],location='original finite-volume cell')


def cli(argv=None):
    import argparse
    import sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--html',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.study.stat().st_size>MAX_BYTES:raise ValueError('Study exceeds 16 MiB.')
        request=parse_study(args.study.read_text(encoding='utf-8-sig'))
        if args.output and args.output.suffix.lower()!='.json':raise ValueError('JSON output requires a .json destination.')
        if args.html and args.html.suffix.lower()!='.html':raise ValueError('HTML output requires a .html destination.')
        if args.output and args.html and args.output.resolve()==args.html.resolve():raise ValueError('JSON and HTML output paths must differ.')
        for output in (args.output,args.html):
            if output and (output.resolve()==args.study.resolve() or (output.exists() and os.path.samefile(output,args.study))):
                raise ValueError('Output must not overwrite the source study.')
        report=run_study(request)
        payload=json.dumps(report,indent=2,allow_nan=False)+'\n'
        if args.output:save_document(args.output,payload,sources=[args.study])
        else:print(payload)
        if args.html:
            from .thermoelectric_report import render_report
            save_document(args.html,render_report(report),sources=[args.study])
        return 0
    except (OSError,ValueError,RuntimeError) as exc:
        print(json.dumps(dict(error=str(exc))),file=sys.stderr);return 2
    except KeyboardInterrupt:return 130


if __name__=='__main__':raise SystemExit(cli())
