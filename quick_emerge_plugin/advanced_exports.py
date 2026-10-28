"""Bounded live-solver DXF and official Optycal far-field exports.

These operations require live EMerge geometry and complex fields. No export is
reconstructed from scalar JSON or field magnitudes. Artifact staging is private
to a simulation run; source custody is rechecked before publication. The b9
surface_model exporter is deliberately unused because it repeats excitation 1.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

MAX_EXPORT_BYTES=32*1024*1024
MAX_SLICES=8
MAX_EXCITATION_FREQUENCIES=16
ANGLE_STEP_DEG=15.0


def parse_dxf_heights_mm(raw):
    """Parse a literal comma-separated millimetre list, never expressions."""
    if isinstance(raw,str):
        parts=raw.split(',')
        if any(not re.fullmatch(r'\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*',v) for v in parts):raise ValueError('DXF heights must be comma-separated numeric millimetres, without expressions')
    elif isinstance(raw,(list,tuple)):parts=list(raw)
    else:raise ValueError('DXF heights must be a literal list or comma-separated millimetres')
    if not 1<=len(parts)<=MAX_SLICES:raise ValueError('Choose 1 to 8 distinct DXF heights')
    values=[]
    for value in parts:
        if isinstance(value,bool):raise ValueError('DXF height cannot be boolean')
        try:value=float(value)
        except (ValueError,TypeError,OverflowError) as exc:raise ValueError('DXF height must be numeric') from exc
        if not math.isfinite(value) or abs(value)>2000:raise ValueError('DXF heights must be finite and within +/-2000 mm')
        values.append(value)
    if len(set(values))!=len(values):raise ValueError('DXF heights must be distinct')
    return values


def require_export_dependencies(config):
    """Optional preflight; selected export capabilities must actually exist."""
    a=config.get('advanced',{})
    for key in ('export_dxf','export_optycal'):
        if type(a.get(key,False)) is not bool:raise ValueError(key+' must be boolean')
    if a.get('export_dxf'):
        parse_dxf_heights_mm(a.get('export_dxf_z_mm','0'))
        try:
            import ezdxf
            from emerge.write import export_dxf
        except ImportError as exc:raise RuntimeError('DXF export needs the EMerge dxf extra (ezdxf) in the selected qualified solver runtime') from exc
    if a.get('export_optycal'):
        _optycal_consumer()


OPTYCAL_CONSUMER_REVISION='6d1d6e79b83a26849e161459e932e2c4a7ab6de3'
OPTYCAL_FORMAT_REFERENCE='https://github.com/FennisRobert/Optycal/blob/'+OPTYCAL_CONSUMER_REVISION+'/src/optycal/antennas/antenna_model.py'


def _optycal_consumer():
    """Wire-format dependencies only; the unreleased GUI package is not needed.

    Independent implementation of the documented official FarfieldDataset
    MsgPack protocol. The actual pinned official reader is exercised in QA;
    no third-party consumer implementation is copied into the plugin.
    """
    try:
        import msgpack
        import msgpack_numpy
    except ImportError as exc:raise RuntimeError('Optycal far-field export needs msgpack and msgpack-numpy in the selected solver runtime') from exc
    return msgpack,msgpack_numpy


def _write_optycal_msgpack(dataset,path):
    msgpack,msgpack_numpy=_optycal_consumer()
    def encode(value):
        if isinstance(value,complex):return {'__complex__':True,'real':float(value.real),'imag':float(value.imag)}
        return msgpack_numpy.encode(value)
    payload=msgpack.packb(dataset,default=encode,use_bin_type=True)
    if len(payload)>MAX_EXPORT_BYTES:raise ValueError('Optycal export exceeds 32 MiB')
    with Path(path).open('xb') as stream:stream.write(payload)


def read_optycal_msgpack(path):
    """Read the documented official data format with bounded local input."""
    path=Path(path)
    if path.stat().st_size>MAX_EXPORT_BYTES:raise ValueError('Optycal data exceeds 32 MiB')
    msgpack,msgpack_numpy=_optycal_consumer()
    def decode(value):
        # msgpack-numpy accepts object arrays through pickle.loads. This
        # scalar/vector field format permits only plain numerical dtypes,
        # including on nested descriptors, and never invokes that path.
        if isinstance(value,dict) and b'nd' in value:
            import numpy as np
            descriptor=value.get(b'type')
            if value.get(b'kind') in (b'O',b'V') or not isinstance(descriptor,(str,bytes)):
                raise ValueError('Object/structured arrays are forbidden in numeric Optycal data')
            try:dtype=np.dtype(descriptor)
            except (TypeError,ValueError) as exc:raise ValueError('Unsupported numeric Optycal dtype') from exc
            if dtype.hasobject or dtype.kind not in 'biufc':
                raise ValueError('Object/non-numeric arrays are forbidden in Optycal data')
        value=msgpack_numpy.decode(value)
        if isinstance(value,dict) and value.get('__complex__') is True:
            return complex(value['real'],value['imag'])
        return value
    return _validate_farfield_dataset(msgpack.unpackb(path.read_bytes(),object_hook=decode,raw=False))


def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _source_current(source):
    from .model import source_identity
    if not isinstance(source,dict) or not isinstance(source.get('path'),str) or source_identity(source['path'])!=source:raise ValueError('Source board changed; exports cannot be associated with this run')


def _artifact(run_dir,stage,path,**metadata):
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(stage.resolve()):raise ValueError('Export did not create a regular staged file')
    size=path.stat().st_size
    if not 0<size<=MAX_EXPORT_BYTES:raise ValueError('Export is empty or exceeds the 32 MiB per-artifact budget')
    return {'path':(Path('exports')/path.name).as_posix(),'staged_path':path.relative_to(run_dir).as_posix(),
            'bytes':size,'sha256':_hash(path),**metadata}


def export_dxf_sheets(model,stage,heights_mm):
    """Export exact planar sheets at requested Z, in metres, with explicit units.

    Public EMerge export_dxf exports sheets already lying in a plane. It does
    not cut arbitrary solid sections. Empty heights are errors, not fabricated
    bounding outlines. Upstream unlabelled coordinates are metres; set INSUNITS
    and sheet elevation explicitly without changing those coordinates.
    """
    import numpy as np
    import ezdxf
    from emerge.write import export_dxf
    outputs=[]
    for index,height in enumerate(parse_dxf_heights_mm(heights_mm)):
        path=Path(stage)/f'geometry-sheet-{index+1:02d}.dxf'
        if path.exists():raise ValueError('Staged DXF destination already exists')
        export_dxf(model,str(path),height*.001)
        if not path.is_file():raise ValueError(f'No actual planar sheet exists at Z={height:g} mm; DXF export does not slice solid volumes')
        doc=ezdxf.readfile(path);entities=list(doc.modelspace())
        if not entities or any(e.dxftype()!='LWPOLYLINE' for e in entities):raise ValueError('DXF export must contain actual planar polylines')
        layer=f'Z_{height:.12g}_mm'
        if layer not in doc.layers:doc.layers.new(layer)
        points=[]
        for entity in entities:
            xy=np.asarray(list(entity.get_points('xy')),dtype=float)
            if xy.ndim!=2 or xy.shape[1]!=2 or len(xy)<3 or not np.isfinite(xy).all():raise ValueError('DXF sheet contains invalid coordinates')
            if not entity.closed:raise ValueError('DXF sheet contains an unclosed polygon')
            entity.dxf.layer=layer;entity.dxf.elevation=height*.001
            points.extend(xy.tolist())
        doc.header['$INSUNITS']=6 # AutoCAD metres, not a guessed millimetre scale.
        doc.header['$MEASUREMENT']=1
        doc.saveas(path)
        reopened=ezdxf.readfile(path)
        if reopened.header.get('$INSUNITS')!=6 or len(reopened.modelspace())!=len(entities):raise ValueError('DXF failed readback validation')
        outputs.append((path,{'format':'DXF R2010 planar sheets','coordinate_unit':'m','slice_height_mm':height,
                              'polyline_count':len(entities),'xy_bounds_m':np.asarray(points).min(axis=0).tolist()+np.asarray(points).max(axis=0).tolist(),
                              'limits':['Planar sheet geometry only; no arbitrary solid cross-section or manufacturing acceptance is inferred.']}))
    return outputs


def _validate_farfield_dataset(dataset):
    import numpy as np
    if not isinstance(dataset,dict) or set(dataset)!={'solutions','thetas','phis'}:raise ValueError('Upstream Optycal far-field schema changed')
    theta=np.asarray(dataset['thetas']);phi=np.asarray(dataset['phis'])
    if theta.ndim!=1 or phi.ndim!=1 or min(len(theta),len(phi))<2 or not all(np.isfinite(v).all() for v in (theta,phi)) or np.any(np.diff(theta)<=0) or np.any(np.diff(phi)<=0):raise ValueError('Invalid far-field angular axes')
    solutions=dataset['solutions']
    if not isinstance(solutions,list) or not 1<=len(solutions)<=8:raise ValueError('Optycal export supports 1 to 8 actual frequencies')
    for solution in solutions:
        if not math.isfinite(float(solution['freq'])) or solution['freq']<=0 or not math.isfinite(float(solution['k0'])):raise ValueError('Invalid Optycal frequency')
        count=solution['n_excitations']
        if type(count) is not int or not 1<=count<=8 or len(solution['excitations'])!=count or len(solution['fields'])!=count:raise ValueError('Invalid Optycal excitation count')
        for field in solution['fields']:
            for quantity in ('E','H'):
                array=np.asarray(field[quantity])
                if array.shape!=(3,len(theta),len(phi)) or not np.isfinite(array).all():raise ValueError('Optycal complex fields are nonfinite or misaligned')
    return dataset


def export_optycal_farfield(data,boundary,stage):
    """Use the official EMerge producer and documented official MsgPack format.

    EMerge b9 farfield_model correctly activates each port; unlike its defective
    surface_model, this is qualified per excitation. Preserve all original live
    excitation dictionaries even if the export or data validation fails.
    """
    import numpy as np
    from emerge.optycal import farfield_model
    _optycal_consumer()
    fields=list(data.field.iter())
    if not 1<=len(fields)<=8 or sum(len(f.port_modes) for f in fields)>MAX_EXCITATION_FREQUENCIES:raise ValueError('Optycal export budget is at most 8 frequencies and 16 frequency/excitation pairs')
    if any(not 1<=len(f.port_modes)<=8 for f in fields):raise ValueError('Optycal export requires 1 to 8 actual driven port/mode excitations; scattered and thermal fields are unsupported')
    surface=fields[0].mesh.boundary_surface(boundary.tags)
    if surface.tris.shape[1]>10000:raise ValueError('Optycal far-field surface exceeds the 10,000-triangle export budget')
    previous=[deepcopy(f.excitation) for f in fields]
    try:
        dataset=_validate_farfield_dataset(farfield_model(data,boundary,dangle_deg=ANGLE_STEP_DEG))
    finally:
        for field,excitation in zip(fields,previous):field.excitation=excitation
    if any(f.excitation!=old for f,old in zip(fields,previous)):raise ValueError('Live field excitation could not be restored')
    path=Path(stage)/'optycal-farfield.msgpack'
    if path.exists():raise ValueError('Staged Optycal destination already exists')
    _write_optycal_msgpack(dataset,path)
    reloaded=read_optycal_msgpack(path)
    expected=[float(solution['freq']) for solution in dataset['solutions']]
    if len(reloaded['solutions'])!=len(expected):raise ValueError('Optycal data readback changed frequency count')
    for original,restored in zip(dataset['solutions'],reloaded['solutions']):
        if restored['excitations']!=original['excitations'] or restored['freq']!=original['freq']:raise ValueError('Optycal data readback changed port or frequency identity')
        for before,after in zip(original['fields'],restored['fields']):
            for key in ('E','H'):
                if not np.array_equal(before[key],after[key]):raise ValueError('Optycal data readback changed actual complex '+key+' samples')
    return path,{'format':'Official Optycal FarfieldDataset MsgPack','qualified_consumer_version':'0.3.0', 'qualified_consumer_revision':OPTYCAL_CONSUMER_REVISION,
                 'consumer_verification':'Pinned official 0.3.0 FarfieldDataset reader exercised in QA; GUI package is not required at export time',
                 'format_reference':OPTYCAL_FORMAT_REFERENCE,
                 'upstream_schema':'Unversioned public FarfieldDataset dictionary (Optycal 0.3.0 baseline)',
                 'producer_api':'emerge.optycal.farfield_model','consumer_api':'optycal.antennas.antenna_model.FarfieldDataset.from_msgpack',
                 'frequency_hz':expected,'angle_step_deg':ANGLE_STEP_DEG,
                 'excitation_count':dataset['solutions'][0]['n_excitations'],'E_unit':'V/m at normalized far-field radius 1 m','H_unit':'A/m at normalized far-field radius 1 m',
                 'limits':['Far-field complex samples only; no Optycal physical-optics simulation, efficiency or convergence qualification is implied.',
                           'The defective EMerge b9 surface_model export is not used.']}


def export_live_outputs(model,data,config,boundary,run_dir,source,config_sha256):
    """Prepare selected live exports, returning a staged result-bound manifest."""
    from .model import config_digest
    a=config.get('advanced',{})
    if not a.get('export_dxf',False) and not a.get('export_optycal',False):return None
    require_export_dependencies(config)
    if config_digest(config)!=config_sha256:raise ValueError('Export configuration does not match the reviewed run')
    _source_current(source)
    run_dir=Path(run_dir).resolve(strict=True)
    if not run_dir.is_dir():raise ValueError('Exports require the existing dedicated run directory')
    if shutil.disk_usage(run_dir).free<256*1024*1024:raise ValueError('Less than 256 MiB free; choose another run destination before exporting')
    stage=Path(tempfile.mkdtemp(prefix='export-stage-',dir=run_dir))
    artifacts=[]
    if a.get('export_dxf'):
        for path,metadata in export_dxf_sheets(model,stage,a.get('export_dxf_z_mm','0')):artifacts.append(_artifact(run_dir,stage,path,**metadata))
    if a.get('export_optycal'):
        path,metadata=export_optycal_farfield(data,boundary,stage);artifacts.append(_artifact(run_dir,stage,path,**metadata))
    if sum(item['bytes'] for item in artifacts)>64*1024*1024:raise ValueError('Combined exports exceed the 64 MiB run budget')
    _source_current(source)
    return {'schema':1,'state':'staged','source':deepcopy(source),'config_sha256':config_sha256,
            'backend_version':importlib.metadata.version('emerge'),'artifacts':artifacts,
            'publication':'Only published artifact manifests are linked from a completed result.'}


def publish_exports(run_dir,manifest):
    """Publish staged artifacts without overwriting any existing file.

    On failure, remove only newly linked files from this attempted publication.
    Retain task-owned staged originals for diagnosis; no result is published.
    The caller publishes result.json last, after this function returns.
    """
    if manifest is None:return None
    if not isinstance(manifest,dict) or manifest.get('schema')!=1 or manifest.get('state')!='staged':raise ValueError('Expected a staged export manifest')
    run_dir=Path(run_dir).resolve(strict=True)
    _source_current(manifest['source'])
    sources=[];destinations=[]
    for item in manifest['artifacts']:
        source=run_dir/item['staged_path'];destination=run_dir/item['path']
        if Path(item['staged_path']).is_absolute() or Path(item['path']).is_absolute() or '..' in Path(item['staged_path']).parts or '..' in Path(item['path']).parts:raise ValueError('Export manifest paths must remain inside the run directory')
        if source.parent.parent!=run_dir or not source.parent.name.startswith('export-stage-') or source.parent.is_symlink() or source.is_symlink() or not source.resolve().is_relative_to(run_dir):raise ValueError('Export source is outside its owned staging directory')
        if destination.parent!=run_dir/'exports' or destination.is_symlink() or destination.exists():raise ValueError('Export destination already exists or is outside the run export directory')
        if not source.is_file() or source.stat().st_size!=item['bytes'] or _hash(source)!=item['sha256']:raise ValueError('Staged export bytes changed before publication')
        sources.append(source);destinations.append(destination)
    if len(set(destinations))!=len(destinations):raise ValueError('Duplicate export destinations')
    export_dir=run_dir/'exports'
    if export_dir.is_symlink() or (hasattr(export_dir,'is_junction') and export_dir.is_junction()):raise ValueError('Export destination directory cannot be a link')
    export_dir.mkdir(exist_ok=True)
    created=[]
    try:
        for source,destination in zip(sources,destinations):
            # An exclusive hard link on the same run volume publishes complete
            # bytes atomically and fails if another writer owns the filename.
            os.link(source,destination);created.append(destination)
        _source_current(manifest['source'])
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        raise
    for source in sources:source.unlink()
    for directory in set(source.parent for source in sources):
        if directory.parent==run_dir and directory.name.startswith('export-stage-'):
            try:directory.rmdir()
            except OSError:pass
    for item in manifest['artifacts']:item.pop('staged_path',None)
    manifest['state']='published'
    return manifest
