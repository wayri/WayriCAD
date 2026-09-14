"""Delegate saved-source BOM export to the installed KiCad engine, without writes.

No shell, guessed feature flags, workspace-to-native sync or fallback parser.
The independent WayriCAD export engine remains available for staged/BOM-only data.
"""
from __future__ import annotations
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
from .compat import cli_path
from .native import BASE

NOTICE = ('Saved KiCad sources only; workspace edits and BOM-only variants are not included. '
          'Native output is not modified by WayriCAD grouping or spreadsheet-formula protection. '
          'KiCad 10 deprecates include_excluded_from_bom: the flag has no effect; verify native preset/population settings.')
OPTIONS = {'variant','preset','format_preset','fields','labels','group_by','sort_field','sort_asc',
           'filter','exclude_dnp','include_excluded_from_bom','field_delimiter','string_delimiter',
           'ref_delimiter','ref_range_delimiter','keep_tabs','keep_line_breaks'}
BOOLEANS = {'exclude_dnp','include_excluded_from_bom','keep_tabs','keep_line_breaks'}
LISTS = {'fields','labels','group_by'}


def _run(cmd, timeout=20):
    kw={'capture_output':True,'text':True,'encoding':'utf-8','errors':'replace','timeout':timeout,'stdin':subprocess.DEVNULL}
    if sys.platform=='win32':kw['creationflags']=subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def status():
    path=cli_path()
    if not path:return {'available':False,'reason':'kicad-cli not found. Install KiCad or add its bin directory to PATH.','version':'','options':[]}
    try:
        version=_run([path,'version']);h=_run([path,'sch','export','bom','--help'])
        if version.returncode or h.returncode:raise ValueError((h.stderr or version.stderr or 'Native BOM command unavailable.')[:2000])
        text=h.stdout+'\n'+h.stderr
        return {'available':True,'executable':path,'version':version.stdout.strip(),'help':text,
                'options':sorted(set(re.findall(r'--[a-z][a-z-]+',text))),'notice':NOTICE}
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        return {'available':False,'reason':str(exc),'version':'','options':[]}


def arguments(config, probe):
    if not isinstance(config,dict) or set(config)-OPTIONS:raise ValueError('Unknown native BOM configuration key.')
    args=[]
    for key,value in config.items():
        # The default assembly needs no variant feature on the installed CLI.
        if key=='variant' and isinstance(value,str) and value in ('',BASE):continue
        # False switches are not requested capabilities.
        if key in BOOLEANS and value is False:continue
        flag='--'+key.replace('_','-')
        if flag not in probe['options']:raise ValueError('This installed KiCad does not advertise '+flag)
        if key in BOOLEANS:
            if type(value) is not bool:raise ValueError(key+' needs a boolean.')
            if value:args.append(flag)
            continue
        if key=='sort_asc':
            if type(value) is not bool:raise ValueError('sort_asc needs a boolean.')
            # KiCad builds have exposed both a bool parameter and a switch.
            parameter=bool(re.search(r'--sort-asc\s+(?:VAR|BOOL|ASC|[A-Z][A-Z_]+)',probe.get('help','')))
            if parameter:args.extend([flag,'true' if value else 'false'])
            elif value:args.append(flag)
            continue
        if key in LISTS and isinstance(value,list):
            if len(value)>500 or any(not isinstance(x,str) or ',' in x for x in value):raise ValueError(key+' must be a bounded list without embedded commas.')
            value=','.join(value)
        if not isinstance(value,str) or len(value)>16000 or any(ord(x)<32 and x!='\t' for x in value):raise ValueError('Invalid native option '+key)
        if key=='variant' and value in ('',BASE):continue
        args.extend([flag,value])
    return args


def generate(ws,config=None,acknowledge_saved=False):
    if acknowledge_saved is not True:raise ValueError('Acknowledge saved native sources only before native export.')
    config=config or {};selected=config.get('variant','')
    if selected in ws.state['variants'] and ws.state['variants'][selected].get('bom_only'):
        raise ValueError('BOM-only variants cannot be sent to native KiCad. Use a WayriCAD export.')
    # Any non-native name (including derived unsynced variants) is refused.
    if selected not in ('',BASE) and selected not in ws.project.variant_descriptions:
        raise ValueError('Selected variant is not present in the saved native project.')
    ws.project.check_unchanged();probe=status()
    if not probe['available']:
        from .bridge import BridgeUnavailable
        raise BridgeUnavailable(probe['reason'])
    opts=arguments(config,probe)
    with tempfile.TemporaryDirectory(prefix='wayricad-native-bom-') as td:
        target=Path(td)/'bom.csv'
        cmd=[probe['executable'],'sch','export','bom',*opts,'--output',str(target),str(ws.project.root)]
        result=_run(cmd,120)
        if result.returncode:raise ValueError('KiCad BOM export failed: '+(result.stderr or result.stdout)[-4000:])
        if not target.is_file() or target.stat().st_size>128*1024*1024:raise ValueError('Native output missing or exceeds 128 MiB.')
        data=target.read_bytes()
    ws.project.check_unchanged()
    return {'data':data,'filename':ws.project.name+'__native_bom.csv','command':[probe['executable'],'sch','export','bom',*opts,'--output','<temporary output>',str(ws.project.root)],'notice':NOTICE,'version':probe['version']}
