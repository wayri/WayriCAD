"""Discover and dispatch every WayriCAD tool without importing native GUIs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

CONTROL_METHODS={
    'bulk-label-editor':'bulk-label.preview','harness-workbench':'harness.build',
    'heater-designer':'heater.analyze','manufacturing-readiness':'manufacturing.audit',
    'planar-magnetics':'magnetics.analyze','protocol-constraints':'protocol-constraints.compose',
}
# Modules are fixed application code, never supplied by a request document.
COMMANDS={
    'assistant':('wayricad_runtime.assistant',(), 'Local plain-English command planning, reviewed execution and reports'),
    'bom-studio':('bom_studio_plugin.bomstudio.cli',(), 'Analytics Studio: fields, BOM, variants, analytics and pipelines'),
    'component-arranger':('component_arranger_plugin.cli',(), 'Group, preview, validate and export placement'),
    'copper-balancer':('copper_balancer_plugin.cli',(), 'Preview and export copper balance changes'),
    'embed-3d':('embed_3d_plugin.__main__',(), 'Project-local libraries and 3D models'),
    'extract-pins':('extract_pins_plugin',(), 'Inspect, extract pins, reports and diagrams'),
    'fanout-generator':('wayricad_runtime.cli',('fanout',), 'Settings, preview plan and reviewed candidate export'),
    'layer-counter':('layer_counter_plugin.cli',(), 'Preview and export copper-layer counters'),
    'mechanical-check':('mechanical_check_plugin.cli',(), 'Saved-board mechanical screening and solid inspection'),
    'project-fusion':('project_fusion_plugin',(), 'Analyze and merge saved projects'),
    'quick-pi':('quick_pi_plugin.cli',(), 'DC copper, grouped pads, shared returns and melting/bottleneck screens'),
    'quick-therm':('quick_therm_plugin.cli',(), 'Board/component temperature screening and thermal reports'),
    'signal-integrity':('signal_integrity_advisor_plugin.cli',(), 'Route, return-path and neighbour-exposure maps with local coupled-line crosstalk'),
    'silkscreen-label-placer':('silkscreen_label_plugin.cli',(), 'Read-only placement preview and settings; apply remains in the GUI'),
    'trace-impedance':('trace_impedance_plugin.cli',(), 'Trace, differential-pair and filled-zone RLC estimates'),
    'trace-refiner':('trace_refiner_plugin.cli',(), 'Preview, validate and export refined traces'),
    'variant-manager':('variant_manager_plugin.wayri_variants.cli',(), 'Variant inventory and reviewed batch operations'),
    'via-stitching':('wayricad_runtime.cli',('stitching',), 'Settings, preview plan and reviewed candidate export'),
}
for _name in CONTROL_METHODS:
    COMMANDS[_name]=('wayricad_runtime.control_cli',(_name,), 'Headless JSON parameters: '+CONTROL_METHODS[_name]+'; GUI write operations are separate')
ALIASES={'coordinator':'assistant','analytics':'bom-studio','quick-si':'signal-integrity','rlc':'trace-impedance','silkscreen':'silkscreen-label-placer','constraint-studio':'protocol-constraints','fusion':'project-fusion'}


def tool_id(value):
    value=ALIASES.get(value,value)
    if value not in COMMANDS:raise ValueError('Unknown tool: '+value)
    return value


def catalogue():
    return {'schema':'wayricad.tools/v1','tools':[{
        'id':name,'description':COMMANDS[name][2],
        'help':['wayricad','tools','run',name,'--','--help'],
        'module':COMMANDS[name][0], 'prefix':list(COMMANDS[name][1]),
        'control_method':CONTROL_METHODS.get(name),
        'scope':'Only the listed headless commands; native GUI actions are not implied.'}
        for name in sorted(COMMANDS)],'aliases':ALIASES}


def command(name,arguments,python=None):
    name=tool_id(name);module,prefix,_=COMMANDS[name]
    return [str(python or sys.executable),'-m',module,*prefix,*arguments]


def runtime_check(python):
    script="import importlib.util,json,sys;print(json.dumps({'python':sys.version.split()[0],'modules':{n:importlib.util.find_spec(n) is not None for n in ('pcbnew','wx','numpy','scipy')}}))"
    result=subprocess.run([str(python),'-c',script],capture_output=True,text=True,timeout=15)
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'Interpreter check failed')
    return json.loads(result.stdout)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='operation',required=True)
    subs.add_parser('list',help='List all 24 tools and their real headless command surfaces.')
    show=subs.add_parser('show',help='Describe one tool and how to obtain command help.');show.add_argument('tool')
    doctor=subs.add_parser('doctor',help='Check an interpreter without importing a GUI or loading a board.')
    doctor.add_argument('--python',type=Path,default=Path(sys.executable))
    run=subs.add_parser('run',help='Dispatch a tool; arguments after TOOL (optionally --) go unchanged to its CLI.')
    run.add_argument('--python',type=Path,help='Explicit prepared interpreter, e.g. KiCad 10 Python for native board commands.')
    run.add_argument('tool');run.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    try:
        if args.operation=='list':print(json.dumps(catalogue(),indent=2));return 0
        if args.operation=='show':
            name=tool_id(args.tool);print(json.dumps(next(t for t in catalogue()['tools'] if t['id']==name),indent=2));return 0
        if args.operation=='doctor':print(json.dumps(runtime_check(args.python),indent=2));return 0
        arguments=args.arguments[1:] if args.arguments[:1]==['--'] else args.arguments
        env=os.environ.copy();library=str(Path(__file__).resolve().parents[1])
        env['PYTHONPATH']=library+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        return subprocess.run(command(args.tool,arguments,args.python),env=env).returncode
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)}),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
