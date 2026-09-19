"""Invoke the REAL KiCad CLI on an exported board. No fake semantic/geometric DRC."""
import datetime, hashlib, json, os, pathlib, re, shutil, subprocess

def find_cli(explicit=''):
    if explicit:
        p=pathlib.Path(explicit).expanduser()
        if p.is_file():return str(p)
        raise FileNotFoundError('kicad-cli not found at '+explicit)
    p=shutil.which('kicad-cli')
    if p:return p
    if os.name=='nt':
        root=pathlib.Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'KiCad'
        candidates=list(root.glob('10*/bin/kicad-cli.exe'))
        if candidates:return str(sorted(candidates,reverse=True)[0])
    for p in ('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli','/usr/bin/kicad-cli'):
        if pathlib.Path(p).is_file():return p
    raise FileNotFoundError('kicad-cli is unavailable. Set its path in Review; local lint is NOT native validation.')

def native_drc(board,cli='',timeout=180):
    board=pathlib.Path(board).resolve()
    if not board.is_file():raise FileNotFoundError(board)
    exe=find_cli(cli);report=board.parent/'constraint-studio-native-drc.json'
    inputs={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (board,board.with_suffix('.kicad_dru'),board.with_suffix('.kicad_pro')) if p.exists()}
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    if report.exists():report.unlink()
    command=[exe,'pcb','drc','--format','json','--output',str(report),'--severity-all','--exit-code-violations','--refill-zones',str(board)]
    # No shell; no commands, paths, or expressions are executed from rule text.
    result=subprocess.run(command,cwd=str(board.parent),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    data=None
    if report.exists():
        try:data=json.loads(report.read_text('utf-8'))
        except (ValueError,OSError):pass
    after={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (board,board.with_suffix('.kicad_dru'),board.with_suffix('.kicad_pro')) if p.exists()}
    text=result.stdout+'\n'+result.stderr
    parse_error=bool(re.search(r'(error\s+parsing|parse\s+error|syntax\s+error|unknown\s+constraint|unrecognized\s+constraint)',text,re.I))
    state='input-changed' if inputs!=after else 'execution-error' if result.returncode not in (0,5) or not isinstance(data,dict) or parse_error else 'violations' if result.returncode==5 else 'report-produced'
    return {'status':state,'input_sha256':inputs,'input_unchanged':inputs==after,'started_utc':started,'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None,'command':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr,
            'report':str(report) if report.exists() else None,'data':data,
            'note':'This is a native report, not certification. Zones were requested to be refilled in memory, without --save-board; external assets may be needed.'}
