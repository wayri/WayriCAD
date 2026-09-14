"""Explicit detached GUI launch for user-initiated interactive job-set commands."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import threading

# Hold detached children until they exit when a long-running caller stays alive.
# A CLI caller may exit immediately; the OS then owns the detached child.
_children = {}

def _reap(process):
    try:
        process.wait()
    finally:
        _children.pop(process.pid, None)



def detached(project=None,demo=False,no_browser=False,port=0,no_auto_link=False,analytics_demo=False,engineering_demo=False,ui=None):
    directory=Path(tempfile.mkdtemp(prefix='wayricad-gui-session-'))
    ready=directory/'session.json';log=directory/'launcher.log'
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'entrypoint.py'),'--session-file',str(ready),'--port',str(port)]
    if project:command.append(str(Path(project).expanduser().resolve()))
    if demo:command.append('--demo')
    if analytics_demo:command.append('--analytics-demo')
    if engineering_demo:command.append('--engineering-demo')
    if no_browser:command.append('--no-browser')
    if ui:command.extend(['--ui',ui])
    if no_auto_link:command.append('--no-auto-link')
    kwargs={'stdin':subprocess.DEVNULL}
    if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS
    else:kwargs['start_new_session']=True
    with log.open('wb') as stream:
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,**kwargs)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if ready.is_file():
            try:result=json.loads(ready.read_text(encoding='utf-8'))
            except json.JSONDecodeError:time.sleep(.05);continue
            _children[process.pid] = process
            threading.Thread(target=_reap, args=(process,), daemon=True, name='wayricad-gui-reaper').start()
            return dict(result,log=str(log),session_directory=str(directory),detached=True,
                        note='Private session URL. Use Quit in the GUI to stop; closing the tab alone does not stop the process.')
        if process.poll() is not None:raise OSError('GUI process exited before readiness. Inspect '+str(log))
        time.sleep(.05)
    process.terminate()
    try:process.wait(timeout=3)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    raise OSError('GUI startup did not publish readiness and was stopped. Inspect '+str(log))
