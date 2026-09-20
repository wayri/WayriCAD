"""Bounded simulations using KiCad's ngspice shared library in an isolated process."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def discover_library():
    override=os.environ.get('WAYRICAD_KICAD_NGSPICE')
    if override:
        path=Path(override).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in ('.dll','.so','.dylib') and '.so.' not in path.name:
            raise RuntimeError('WAYRICAD_KICAD_NGSPICE must name the ngspice shared library used by KiCad.')
        return path
    candidates=[]
    from .runtime_setup import native_python
    try:active=Path(native_python())
    except RuntimeError:active=None
    if active:
        candidates.extend([active.parent/'ngspice.dll',active.parent/'libngspice.dylib',active.parent.parent/'lib/libngspice.so'])
        if sys.platform=='darwin':
            bundle=next((p for p in active.parents if p.name=='Contents'),None)
            if bundle:candidates.extend(bundle.glob('**/libngspice*.dylib'))
    python=os.environ.get('WAYRICAD_KICAD_PYTHON')
    if python:candidates.append(Path(python).parent/'ngspice.dll')
    if sys.platform=='win32':
        for base in (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'KiCad',):
            if base.is_dir():
                candidates.extend(sorted(base.glob('*/bin/ngspice.dll'),key=lambda p:tuple(int(n) for n in re.findall(r'\d+',p.parent.parent.name)),reverse=True))
    elif sys.platform=='darwin':
        for base in (Path('/Applications/KiCad/KiCad.app/Contents'),Path.home()/'Applications/KiCad/KiCad.app/Contents'):
            candidates.extend(base.glob('**/libngspice*.dylib'))
    else:
        for base in ('/usr/lib','/usr/lib/x86_64-linux-gnu','/usr/lib/aarch64-linux-gnu','/usr/local/lib'):
            candidates.extend(Path(base).glob('libngspice.so*'))
    for path in candidates:
        if path.is_file():return path.resolve()
    raise RuntimeError('KiCad ngspice shared library was not found. Install KiCad simulation support or set WAYRICAD_KICAD_NGSPICE to the library used by KiCad; no external simulator fallback is used.')


def _request(netlist,analysis,vectors,frequency_hz,frequency_stop_hz,points,points_per_decade,time_step_s=None,duration_s=None):
    if not isinstance(netlist,str) or not netlist.strip() or len(netlist)>200000:raise ValueError('Supply a nonempty generated SPICE deck up to 200 kB.')
    # Only generated lumped circuits. No scripting, includes, model files,
    # expression sources or arbitrary ngspice commands cross this interface.
    allowed={'.subckt','.ends','.end','.param'}
    if not netlist.splitlines()[0].strip() or netlist.splitlines()[0].lstrip().startswith('.'):
        raise ValueError('The first SPICE line must be a descriptive title or comment.')
    for index,line in enumerate(netlist.splitlines()):
        line=line.strip()
        if not line or line.startswith('*') or index==0:continue
        token=line.split()[0].lower()
        if token.startswith('.') and token not in allowed:raise ValueError('Unsupported SPICE directive: '+token)
        if not token.startswith('.') and token[0] not in 'rlcviefghkx':raise ValueError('Only generated lumped SPICE elements are supported.')
        if any(c in line for c in (';','`','$')):raise ValueError('SPICE commands and substitutions are not allowed.')
    if analysis not in ('op','ac','tran'):raise ValueError('Analysis must be op, ac or tran.')
    if not isinstance(vectors,(list,tuple)) or not 1<=len(vectors)<=32 or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.:#()+-]{1,100}',v) for v in vectors):raise ValueError('Choose 1–32 simple SPICE vector names.')
    def positive(v):return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) and v>0
    if not positive(frequency_hz):raise ValueError('AC frequency must be positive and finite.')
    stop=frequency_hz if frequency_stop_hz is None else frequency_stop_hz
    if not positive(stop) or stop<frequency_hz:raise ValueError('AC stop frequency must be finite and >= start.')
    if isinstance(points,bool) or not isinstance(points,int) or not 1<=points<=1000:raise ValueError('AC points must be 1–1000.')
    command='op'
    if analysis=='ac':
        if points_per_decade is not None:
            if isinstance(points_per_decade,bool) or not isinstance(points_per_decade,int) or not 1<=points_per_decade<=100 or math.ceil((math.log10(stop)-math.log10(frequency_hz))*points_per_decade)+1>1000:raise ValueError('AC logarithmic sweep exceeds the bounded point count.')
            command=f'ac dec {points_per_decade} {frequency_hz:.15g} {stop:.15g}'
        else:command=f'ac lin {points} {frequency_hz:.15g} {stop:.15g}'
    if analysis=='tran':
        if not positive(time_step_s) or not positive(duration_s) or not math.isfinite(duration_s/time_step_s) or duration_s/time_step_s>10000:raise ValueError('Transient requires finite positive duration/time step and <=10000 requested steps.')
        command=f'tran {time_step_s:.15g} {duration_s:.15g} 0 {time_step_s:.15g} uic'
    return dict(netlist=netlist,analysis=analysis,vectors=list(vectors),command=command)


def simulate(netlist, *, analysis='op',vectors,frequency_hz=1000.,frequency_stop_hz=None,points=1,points_per_decade=None,timeout=30.,time_step_s=None,duration_s=None):
    request=_request(netlist,analysis,vectors,frequency_hz,frequency_stop_hz,points,points_per_decade,time_step_s,duration_s)
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=300:raise ValueError('Timeout must be between zero and 300 seconds.')
    request['library']=str(discover_library())
    from .runtime_setup import native_python,child_environment
    with tempfile.TemporaryDirectory(prefix='wayricad-spice-') as temp:
        source=Path(temp)/'request.json';output=Path(temp)/'response.json'
        source.write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        try:
            process=subprocess.run([str(native_python()),'-I',str(Path(__file__).resolve()),'--worker',str(source),str(output)],env=child_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired as exc:raise TimeoutError('KiCad ngspice simulation timed out; reduce sweep points or inspect the circuit.') from exc
        if not output.is_file():raise RuntimeError(f'KiCad ngspice worker exited without results (code {process.returncode}); check library/Python architecture compatibility.')
        result=json.loads(output.read_text(encoding='utf-8'))
        if result.get('error'):raise RuntimeError(result['error'])
        if process.returncode:raise RuntimeError('KiCad ngspice worker failed.')
        return result


def _worker(request):
    import ctypes as c
    path=Path(request['library']);handles=[]
    if sys.platform=='win32':handles.append(os.add_dll_directory(str(path.parent)))
    dll=c.CDLL(str(path));log=[];exit_status=[]
    msg_type=c.CFUNCTYPE(c.c_int,c.c_char_p,c.c_int,c.c_void_p)
    exit_type=c.CFUNCTYPE(c.c_int,c.c_int,c.c_bool,c.c_bool,c.c_int,c.c_void_p)
    bg_type=c.CFUNCTYPE(c.c_int,c.c_bool,c.c_int,c.c_void_p)
    @msg_type
    def message(text,identifier,user):
        if len(log)<300:log.append(text.decode(errors='replace')[:1000])
        return 0
    @exit_type
    def exited(status,immediate,quit,identifier,user):
        log.append('ngspice exit '+str(status));exit_status.append(status);return 0
    @bg_type
    def background(running,identifier,user):return 0
    dll.ngSpice_Init.argtypes=[msg_type,msg_type,exit_type,c.c_void_p,c.c_void_p,bg_type,c.c_void_p]
    dll.ngSpice_Init(message,message,exited,None,None,background,None)
    dll.ngSpice_Command.argtypes=[c.c_char_p];dll.ngSpice_Circ.argtypes=[c.POINTER(c.c_char_p)]
    class Complex(c.Structure):_fields_=[('real',c.c_double),('imag',c.c_double)]
    class Vector(c.Structure):_fields_=[('name',c.c_char_p),('type',c.c_int),('flags',c.c_short),('real',c.POINTER(c.c_double)),('complex',c.POINTER(Complex)),('length',c.c_int)]
    dll.ngGet_Vec_Info.argtypes=[c.c_char_p];dll.ngGet_Vec_Info.restype=c.POINTER(Vector)
    lines=[line.encode() for line in request['netlist'].splitlines()];array=(c.c_char_p*(len(lines)+1))(*lines,None)
    if dll.ngSpice_Circ(array)!=0:raise RuntimeError('KiCad ngspice rejected the circuit: '+'\n'.join(log[-15:]))
    if dll.ngSpice_Command(request['command'].encode())!=0:raise RuntimeError('KiCad ngspice analysis failed: '+'\n'.join(log[-15:]))
    if exit_status:raise RuntimeError('KiCad ngspice exited during analysis: '+str(exit_status))
    if any(line.lower().startswith('stderr error') for line in log):raise RuntimeError('KiCad ngspice reported an error: '+'\n'.join(log[-15:]))
    result={}
    for name in request['vectors']:
        pointer=dll.ngGet_Vec_Info(name.encode())
        if not pointer or not 0<pointer.contents.length<=(20001 if request['analysis']=='tran' else 1001):raise RuntimeError('Missing or oversized result vector '+name+': '+'\n'.join(log[-15:]))
        value=pointer.contents
        real=[value.complex[i].real if value.complex else value.real[i] for i in range(value.length)]
        imag=[value.complex[i].imag if value.complex else 0. for i in range(value.length)]
        if not all(math.isfinite(v) for v in real+imag):raise RuntimeError('Simulation returned nonfinite results.')
        result[name]=dict(real=real,imag=imag)
    dll.ngSpice_Command(b'version')
    version=next((match.group(0) for line in log for match in [re.search(r'ngspice-\d+(?:\.\d+)*',line)] if match), 'version unavailable')
    return dict(engine='KiCad ngspice shared library',version=version,path=str(path),analysis=request['analysis'],vectors=result,log=log)


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--worker':raise SystemExit(2)
    try:response=_worker(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    except Exception as exc:response={'error':str(exc)}
    Path(sys.argv[3]).write_text(json.dumps(response,allow_nan=False),encoding='utf-8')
    raise SystemExit(2 if response.get('error') else 0)
