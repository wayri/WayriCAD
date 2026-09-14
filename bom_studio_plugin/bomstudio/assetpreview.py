"""Preview service: association checks, bounded derived cache, no source-file reads."""
from __future__ import annotations
import hashlib
import json
import threading
from collections import OrderedDict
from . import assetbundle, nativepreview, meshpreview

_CACHE=OrderedDict();_LOCK=threading.Lock();_BYTES=0;MAX_CACHE=64*1024*1024

def capabilities():
    import importlib.util,ctypes.util,sys
    return {'native_svg':True,'vrml97':True,'stl':True,'obj':True,'step_iges_brep':importlib.util.find_spec('OCP') is not None,
            'python_executable':sys.executable,'embedded_zstd_module':importlib.util.find_spec('zstandard') is not None,'system_zstd_detected':bool(ctypes.util.find_library('zstd')),'optional_requirement':'requirements-preview.txt','offline':True,'renderer':'Original WayriCAD SVG/WebGL inspection renderer; STEP tessellation uses optional OpenCascade.'}

def preview(lib,pid,kind,revision=None,set_id=None,model_index=0,unit=1,style=1,layers=None,show_labels=True,cancel=None):
    if kind not in ('symbol','footprint','model'):raise ValueError('Choose symbol, footprint or model preview.')
    part=lib.get(pid,revision);s=assetbundle.select_set(part,set_id);model=None
    if kind=='model':
        if isinstance(model_index,bool) or not isinstance(model_index,int) or not 0<=model_index<200:raise ValueError('Invalid model reference index.')
        model=next((m for m in s.get('models',[]) if m.get('index')==model_index),None)
        if not model:raise ValueError('No model is assigned at this index. Re-harvest old catalogues to capture model references.')
        h=model.get('hash')
        if not h:raise ValueError('3D source was not captured: '+model.get('error','missing file'))
    else:h=s.get(kind+'_hash')
    if not h:raise ValueError('No captured '+kind+' in this observation set. Re-harvest with asset capture enabled.')
    if not any(a.get('hash')==h and a.get('kind')==kind for a in part.get('assets',[])):raise ValueError('Preview asset does not belong to this part revision.')
    raw=assetbundle.read_blob(lib,h) # verify actual stored bytes even on a cache hit
    ext=(model.get('extension') if model else '') or ''
    key=json.dumps([h,kind,ext,unit,style,layers,show_labels,'v7'],sort_keys=True)
    with _LOCK:encoded=_CACHE.get(key)
    if encoded:result=json.loads(encoded)
    else:
        result=meshpreview.convert(raw,ext,cancel) if kind=='model' else nativepreview.svg_preview(raw,kind,unit,style,layers,show_labels)
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        global _BYTES
        if len(encoded)<MAX_CACHE:
            with _LOCK:
                if key not in _CACHE:
                    while _CACHE and _BYTES+len(encoded)>MAX_CACHE:
                        _,old=_CACHE.popitem(last=False);_BYTES-=len(old)
                    _CACHE[key]=encoded;_BYTES+=len(encoded)
    return {**result,'asset_hash':h,'part_id':pid,'revision':part['revision'],'asset_set':s['id'],'kind':kind,'model_reference':model,
            'source':'Captured catalogue bytes. No original project/library path was opened for preview.'}
