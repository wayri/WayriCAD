"""Typed, read-only command adapters for the local Assistant.

Compilation returns data, never executes a process or writes a file. Arguments
are separate subprocess tokens; neither free-form commands nor configuration
files can introduce switches, destinations or executable paths.
"""
from __future__ import annotations

import math
from pathlib import Path

from .tool_cli import COMMANDS
from .fanout_profiles import FANOUT_PATTERNS


def field(label, kind='text', **options):
    return dict(label=label, kind=kind, **options)


BOARD = field('Saved PCB', 'path')
PROJECT = field('Saved project or schematic', 'path')
NET = field('Exact net name')
PAD = field('Pad identifier, for example U1.1')
POSITIVE = dict(minimum=0, exclusive_minimum=True)


def number(label, unit='', **options):
    return field(label, 'number', unit=unit, **options)


ACTIONS = {}


def _add(identifier, tool, title, phrases, required=(), fields=None,
         effect='inspect', summary=''):
    ACTIONS[identifier] = dict(tool=tool, title=title, phrases=list(phrases),
        required=list(required), fields=fields or {}, effect=effect,
        summary=summary or title)


for _tool in COMMANDS:
    if _tool == 'assistant':
        continue
    _add(_tool + '.help', _tool, 'Help: ' + _tool,
         ('help ' + _tool, _tool + ' commands'), effect='help',
         summary='Show existing CLI usage only; no design analysis is run.')

for _tool in ('signal-integrity', 'trace-impedance'):
    _add(_tool + '.inspect', _tool, 'Inspect board nets and endpoints',
         ('list ' + _tool + ' nets', 'inspect ' + _tool), ('board',),
         dict(board=BOARD, net=NET))

_add('quick-emerge.runtime', 'quick-emerge', 'Inspect EMerge solver runtime',
     ('emerge runtime', 'check emerge installation'),
     summary='Inspect the explicitly prepared interpreter; no installation or simulation is performed.')

_add('quick-pi.solve', 'quick-pi', 'DC rail analysis',
     ('quick pi', 'power integrity', 'voltage drop', 'dc rail'),
     ('board', 'net', 'source', 'sink', 'voltage', 'current'),
     dict(board=BOARD, net=NET, source=PAD, sink=PAD,
          voltage=number('Source voltage', 'V', **POSITIVE),
          current=number('Sink current', 'A', **POSITIVE),
          mesh_edge=number('Mesh edge', 'mm', **POSITIVE),
          return_nets=field('Explicit return nets', 'list'),
          temperature=number('Copper temperature', 'C')), effect='analysis',
     summary='2.5D DC analysis with explicit source voltage and sink current; no inferred loads.')
_add('quick-pi.verify', 'quick-pi', 'PI analytical benchmarks',
     ('verify pi solver', 'pi benchmarks'), effect='analysis')

_add('signal-integrity.screen', 'signal-integrity', 'Signal route screening',
     ('quick si', 'signal integrity', 'screen signal', 'route delay'),
     ('board', 'net', 'start', 'end', 'rise_ns', 'frequency_mhz', 'source_ohm'),
     dict(board=BOARD, net=NET, start=PAD, end=PAD,
          rise_ns=number('Driver rise time', 'ns', **POSITIVE),
          frequency_mhz=number('Screening frequency', 'MHz', **POSITIVE),
          source_ohm=number('Driver resistance', 'ohm', minimum=0),
          load_ohm=number('Receiver resistance; omit for open circuit', 'ohm', **POSITIVE),
          return_nets=field('Explicit return nets', 'list')),
     effect='analysis', summary='Route screening, not protocol compliance; omitted receiver load means open circuit.')
_add('signal-integrity.profiles', 'signal-integrity', 'List SI screening profiles',
     ('si profiles', 'protocol profiles'))

_add('quick-therm.analyze', 'quick-therm', 'Component thermal screening',
     ('quick therm', 'thermal analysis', 'component temperatures'),
     ('board', 'power_field', 'theta_ja_field', 'ambient'),
     dict(board=BOARD, power_field=field('Power dissipation footprint field'),
          theta_ja_field=field('Junction-to-ambient K/W footprint field'),
          ambient=number('Ambient temperature', 'C'),
          refs=field('Dissipating component references', 'list')),
     effect='analysis', summary='Air-environment component R-theta screening using explicit saved field mappings; not a board-field FEM solve.')

_add('trace-impedance.path', 'trace-impedance', 'Trace RLC and impedance',
     ('trace impedance', 'rlc path', 'calculate trace rlc'),
     ('board', 'net', 'start', 'end', 'frequency_mhz'),
     dict(board=BOARD, net=NET, start=PAD, end=PAD,
          frequency_mhz=number('Analysis frequency', 'MHz', **POSITIVE)), effect='analysis')
_add('trace-impedance.cross-section', 'trace-impedance', 'Transmission-line cross section',
     ('microstrip impedance', 'stripline impedance', 'coplanar impedance', 'cross section impedance'),
     ('topology', 'width_mm', 'height_mm', 'er'),
     dict(topology=field('Line topology', 'choice', choices=['microstrip', 'symmetric-stripline', 'cpw', 'grounded-cpw', 'edge-coupled-stripline']),
          width_mm=number('Trace width', 'mm', **POSITIVE), height_mm=number('Reference separation', 'mm', **POSITIVE),
          er=number('Relative permittivity', minimum=1), copper_mm=number('Copper thickness', 'mm', minimum=0),
          gap_mm=number('Lateral ground slot or pair gap', 'mm', **POSITIVE)), effect='analysis')

_add('fanout-generator.preview', 'fanout-generator', 'Preview component fanout',
     ('fanout', 'escape routing', 'connector fanout'), ('board', 'refs', 'pattern'),
     dict(board=BOARD, refs=field('Reference wildcard, e.g. U1 or J*'),
          pattern=field('Fanout style', 'choice', choices=list(FANOUT_PATTERNS)),
          width=number('Track width', 'mm', **POSITIVE), length=number('Escape length', 'mm', **POSITIVE),
          clearance=number('Clearance', 'mm', minimum=0), add_vias=field('Add vias', 'boolean')),
     effect='preview', summary='Read-only plan and SVG; project rules and the planner determine accepted candidates.')
_add('via-stitching.preview', 'via-stitching', 'Preview via stitching',
     ('stitching', 'stitch ground vias'), ('board', 'net'),
     dict(board=BOARD, net=NET, spacing=number('Via pitch', 'mm', **POSITIVE)), effect='preview')
_add('via-stitching.guard', 'via-stitching', 'Preview guard vias along signal nets',
     ('guard selected routes', 'guard via stitching', 'via fence', 'guard selected nets'),
     ('board','guard_net','signal_nets','spacing','offset'),
     dict(board=BOARD,guard_net=field('Guard/stitching net, distinct from signal nets'),
          signal_nets=field('Exact signal nets to follow','list'),
          spacing=number('Via pitch','mm',**POSITIVE),offset=number('Trace centreline to via offset','mm',**POSITIVE),
          side=field('Guard side','choice',choices=['Both','Left','Right'])),effect='preview',
     summary='Read-only via fence on an explicit guard net; existing filled-copper, edge and clearance checks remain required.')
_add('silkscreen-label-placer.preview', 'silkscreen-label-placer', 'Preview reference placement',
     ('silkscreen', 'place references', 'fix reference labels'), ('board',),
     dict(board=BOARD, refs=field('Exact references; omit for board', 'list')),
     effect='preview', summary='Reference fields only; source PCB, values and manual text remain unchanged.')
_add('trace-refiner.preview', 'trace-refiner', 'Preview trace refinement',
     ('refine traces', 'trace refiner', 'remove routing kinks'), ('board',),
     dict(board=BOARD, nets=field('Exact nets', 'list'), layers=field('Copper layers', 'list'),
          center_contacts=field('Center contacting endpoints instead', 'boolean')), effect='preview')
_add('component-arranger.preview', 'component-arranger', 'Preview component arrangement',
     ('arrange components', 'placement preview'), ('board', 'refs'),
     dict(board=BOARD, refs=field('Exact footprint references', 'list'), anchor=field('Anchor reference'),
          sides=field('Allowed sides', 'choice', choices=['top', 'bottom', 'both']),
          density=number('Placement density', minimum=0.05, maximum=1)), effect='preview')
_add('copper-balancer.preview', 'copper-balancer', 'Preview copper balance',
     ('balance copper', 'copper balance'), ('board',), dict(board=BOARD), effect='preview')
_add('layer-counter.preview', 'layer-counter', 'Preview layer counter',
     ('layer counter', 'layer numbering'), ('board',), dict(board=BOARD), effect='preview')
_add('mechanical-check.analyze', 'mechanical-check', 'Mechanical screening report',
     ('mechanical check', 'mechanical screening', 'component collisions'), ('board',),
     dict(board=BOARD), effect='analysis', summary='Saved-board screening using existing default rules; not automatic mechanical repair.')
_add('embed-3d.inspect', 'embed-3d', 'Inspect archived board footprints and models',
     ('inspect embedded board archive', 'board model archive'), ('board',), dict(board=BOARD),
     summary='Inspect an existing WayriCAD Embed3D archive; reports an error when the PCB has not been packaged.')
_add('embed-3d.scan', 'embed-3d', 'Scan footprint model references',
     ('inspect 3d models', 'missing models', 'model links'), ('footprint',),
     dict(footprint=field('Saved .kicad_mod footprint', 'path')),
     summary='Scan one footprint file for embedded or unresolved model references; never embeds or changes it.')
_add('extract-pins.board', 'extract-pins', 'Extract PCB pins',
     ('extract pins', 'list board pins', 'pin inventory'), ('board',), dict(board=BOARD))
_add('project-fusion.detect', 'project-fusion', 'Detect project import scope',
     ('fusion', 'detect project scope', 'inspect import'), ('project',), dict(project=PROJECT))
_add('variant-manager.list', 'variant-manager', 'List saved variants',
     ('variants', 'list variants'), ('project',), dict(project=PROJECT))
for _name in ('info', 'fields', 'check'):
    _add('bom-studio.' + _name, 'bom-studio', 'Analytics Studio: ' + _name,
         ('analytics ' + _name, 'bom ' + _name), ('project',), dict(project=PROJECT))

_add('protocol-constraints.compose', 'protocol-constraints', 'Suggest protocol constraints',
     ('detect protocols', 'suggest constraints'), ('nets',), dict(nets=field('Exact net names', 'list')),
     effect='preview', summary='Generate suggestions from supplied names; does not change native rules or establish compliance.')
_add('bulk-label-editor.preview', 'bulk-label-editor', 'Preview label replacement',
     ('rename labels', 'bulk labels'), ('values', 'pattern', 'replacement'),
     dict(values=field('Existing label values', 'list'), pattern=field('Wildcard match'), replacement=field('Replacement', allow_empty=True)),
     effect='preview')
_add('harness-workbench.build', 'harness-workbench', 'Build harness report from pin documents',
     ('harness report', 'build harness'), ('documents',), dict(documents=field('Pin document files', 'paths')),
     effect='analysis', summary='Read supplied documents and automatically match exact non-power net names; inspect findings.')

_heater = dict(width_mm=number('Heater width', 'mm', **POSITIVE), height_mm=number('Heater height', 'mm', **POSITIVE),
    trace_width_mm=number('Trace width', 'mm', **POSITIVE), spacing_mm=number('Trace spacing', 'mm', **POSITIVE),
    copper_um=number('Copper thickness', 'um', **POSITIVE), voltage_v=number('Applied voltage', 'V', **POSITIVE))
_add('heater-designer.analyze', 'heater-designer', 'Analyze copper serpentine heater',
     ('heater analysis', 'heater design'), tuple(_heater), _heater, effect='analysis',
     summary='Single-layer copper serpentine electrical model; thermal simulation is not requested.')
_coil = dict(outer_width_mm=number('Coil width', 'mm', **POSITIVE), outer_height_mm=number('Coil height', 'mm', **POSITIVE),
    turns=field('Turns', 'integer', minimum=1, maximum=1000), trace_width_mm=number('Trace width', 'mm', **POSITIVE),
    spacing_mm=number('Trace spacing', 'mm', **POSITIVE), copper_um=number('Copper thickness', 'um', **POSITIVE),
    layers=field('Series copper layers', 'integer', minimum=1, maximum=16),
    frequency_khz=number('Frequency', 'kHz', **POSITIVE), current_a=number('Current', 'A', **POSITIVE),
    voltage_v=number('Voltage', 'V', **POSITIVE))
_add('planar-magnetics.analyze', 'planar-magnetics', 'Analyze rectangular air-core coil',
     ('planar coil', 'magnetics analysis'), tuple(_coil), _coil, effect='analysis',
     summary='Rectangular series spiral, air core; static electrical/voice-coil model with no dynamics requested.')
_metrics = dict(minimum_track_mm=number('Measured minimum track', 'mm', **POSITIVE),
    minimum_clearance_mm=number('Measured minimum clearance', 'mm', minimum=0),
    minimum_drill_mm=number('Measured minimum drill', 'mm', **POSITIVE),
    minimum_annular_ring_mm=number('Measured minimum annular ring', 'mm', minimum=0),
    maximum_via_aspect_ratio=number('Measured maximum via aspect ratio', **POSITIVE),
    copper_layers=field('Copper layers', 'integer', minimum=1, maximum=64))
_add('manufacturing-readiness.audit', 'manufacturing-readiness', 'Audit supplied manufacturing metrics',
     ('manufacturing audit', 'fabrication screening'), tuple(_metrics), _metrics, effect='analysis',
     summary='Checks user-supplied metrics against the built-in demo profile, not a board measurement or fabrication signoff.')


def _text(value, label, allow_empty=False):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError(label + ' must be bounded text.')
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or value.startswith('-'):
        raise ValueError(label + ' contains control characters or an option prefix.')
    if not value.strip() and not allow_empty:
        raise ValueError(label + ' is required.')
    return value


def _validate(value, spec):
    kind, label = spec['kind'], spec['label']
    if kind in ('number', 'integer'):
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or abs(value) > 1e12 or not math.isfinite(value)):
            raise ValueError(label + ' must be finite numeric data.')
        if kind == 'integer' and not isinstance(value, int):
            raise ValueError(label + ' must be an integer.')
        if ('minimum' in spec and (value < spec['minimum'] or (spec.get('exclusive_minimum') and value == spec['minimum']))) or ('maximum' in spec and value > spec['maximum']):
            raise ValueError(label + ' is outside the allowed range.')
    elif kind == 'boolean':
        if not isinstance(value, bool):
            raise ValueError(label + ' must be boolean.')
    elif kind in ('list', 'paths'):
        if not isinstance(value, list) or not 1 <= len(value) <= 256:
            raise ValueError(label + ' requires 1–256 entries.')
        value = [_validate(item, field(label, 'path' if kind == 'paths' else 'text')) for item in value]
    else:
        value = _text(value, label, spec.get('allow_empty', False))
        if kind == 'choice' and value not in spec['choices']:
            raise ValueError(label + ' must be one of the listed choices.')
        if kind == 'path':
            if value in ('-', '.'):
                raise ValueError(label + ' must identify an input file.')
            value = str(Path(value).expanduser().resolve())
    return value


def compile_action(action_id, params, context, output_dir):
    """Compile a fixed action with explicit typed inputs into subprocess data.

    Context supplies only absent board/project fields. The caller creates a
    unique run directory and writes returned generated documents exclusively.
    No arbitrary config, shell, source writes, installers or apply commands are
    exposed. The eventual runner must check input existence and preserve hashes.
    """
    if action_id not in ACTIONS:
        raise ValueError('Unknown Assistant action.')
    spec = ACTIONS[action_id]
    if not isinstance(params, dict) or set(params) - set(spec['fields']):
        raise ValueError('Unknown action parameters.')
    if not isinstance(context, dict):
        raise ValueError('Context must be an object.')
    values = dict(params)
    for key in ('board', 'project'):
        if key in spec['fields'] and key not in values and context.get(key):
            values[key] = context[key]
    missing = [key for key in spec['required'] if key not in values]
    if missing:
        raise ValueError('Required inputs: ' + ', '.join(missing))
    values = {key: _validate(value, spec['fields'][key]) for key, value in values.items()}
    root = Path(output_dir).resolve()
    result = dict(tool=spec['tool'], arguments=[], outputs=[], documents={}, input_files=[], assumptions=[])
    for key, value in values.items():
        if spec['fields'][key]['kind'] == 'path': result['input_files'].append(value)
        if spec['fields'][key]['kind'] == 'paths': result['input_files'].extend(value)
    args = result['arguments']

    def output(flag='--output', name='report.json'):
        result['outputs'].append(name)
        args.extend([flag, str(root / name)])

    def option(key, flag=None):
        if key in values:
            args.append((flag or '--' + key.replace('_', '-')) + '=' + str(values[key]))

    def repeats(key, flag):
        for value in values.get(key, []): args.append(flag + '=' + value)

    def request(document):
        result['documents']['request.json'] = document
        args.extend(['--request', str(root / 'request.json')])
        output()

    if spec['effect'] == 'help': args.append('--help')
    elif action_id in ('signal-integrity.inspect', 'trace-impedance.inspect'):
        args.extend(['inspect', values['board']]); option('net'); output()
    elif action_id == 'quick-emerge.runtime': args.append('--check-runtime')
    elif action_id == 'quick-pi.verify': args.append('--verify'); output()
    elif action_id == 'quick-pi.solve':
        args.append(values['board'])
        for key in ('net', 'source', 'sink', 'voltage', 'current', 'temperature'): option(key)
        if 'mesh_edge' in values: option('mesh_edge')
        else: args.append('--auto-mesh')
        if values.get('return_nets'):
            args.extend(['--return-path', '--return-nets', *values['return_nets']])
        output(); output('--html', 'report.html')
        if 'temperature' not in values: result['assumptions'].append('Copper temperature uses the CLI default of 20 C.')
    elif action_id == 'signal-integrity.screen':
        args.extend(['screen', values['board']])
        for key in ('net', 'start', 'end', 'rise_ns', 'frequency_mhz', 'source_ohm', 'load_ohm'): option(key)
        repeats('return_nets', '--return-net'); output(); output('--html', 'report.html')
        if 'load_ohm' not in values: result['assumptions'].append('Receiver is an open circuit.')
    elif action_id == 'signal-integrity.profiles': args.append('profiles')
    elif action_id == 'quick-therm.analyze':
        args.extend([values['board'], '--environment=air'])
        for key in ('power_field', 'theta_ja_field', 'ambient'): option(key)
        if 'refs' in values: args.extend(['--thermal-refs', *values['refs']])
        output(); output('--html', 'report.html')
    elif action_id == 'trace-impedance.path':
        args.extend(['path', values['board']])
        for key in ('net', 'start', 'end', 'frequency_mhz'): option(key)
        output(); result['assumptions'].append('CLI Auto reference-plane selection is used; inspect returned evidence.')
    elif action_id == 'trace-impedance.cross-section':
        if values['topology'] in ('cpw', 'grounded-cpw', 'edge-coupled-stripline') and 'gap_mm' not in values:
            raise ValueError('Required inputs: gap_mm')
        args.append('cross-section')
        for key in values: option(key)
        output()
        if 'copper_mm' not in values: result['assumptions'].append('Zero-thickness copper approximation.')
    elif action_id in ('fanout-generator.preview', 'via-stitching.preview', 'via-stitching.guard'):
        args.extend(['plan', '--board', values['board'], '--settings', str(root / 'settings.json')])
        if action_id.startswith('fanout'):
            settings = {key: value for key, value in values.items() if key not in ('board', 'refs')}
            settings.update(scope='Reference wildcard', ref=values['refs'], use_netclass_rules=True)
        elif action_id=='via-stitching.guard':
            if values['guard_net'] in values['signal_nets']:
                raise ValueError('The guard net must be distinct from the signal nets.')
            settings=dict(mode='Guard selected routes',net_choice=values['guard_net'],guard_nets=values['signal_nets'],
                          spacing=values['spacing'],guard_offset=values['offset'],guard_side=values.get('side','Both'))
        else:
            settings = {key: value for key, value in values.items() if key not in ('board', 'net')}
            settings['net_choice'] = values['net']
        result['documents']['settings.json'] = settings
        output(); output('--svg', 'preview.svg')
        result['assumptions'].append('Unspecified geometry uses the existing planner defaults; review preview dimensions.')
    elif action_id == 'silkscreen-label-placer.preview':
        args.extend(['preview', values['board'], '--references-only'])
        if 'refs' in values: args.extend(['--refs', *values['refs']])
        output(); output('--report', 'report.html')
    elif action_id == 'trace-refiner.preview':
        args.append(values['board']); repeats('nets', '--net'); repeats('layers', '--layer')
        if values.get('center_contacts'): args.append('--center-contacts')
        output('--report')
        result['assumptions'].append('Read-only planner defaults and protected-net exclusions apply; native validation is not run.')
    elif action_id == 'component-arranger.preview':
        if any(',' in ref for ref in values['refs']): raise ValueError('References cannot contain commas.')
        args.extend([values['board'], '--refs=' + ','.join(values['refs'])])
        for key in ('anchor', 'sides', 'density'): option(key)
        output('--report'); result['assumptions'].append('Existing placement planner defaults apply to omitted settings.')
    elif action_id in ('copper-balancer.preview', 'layer-counter.preview'): args.append(values['board'])
    elif action_id == 'mechanical-check.analyze': args.append(values['board']); output(name='mechanical')
    elif action_id == 'embed-3d.inspect': args.extend(['inspect-board', values['board'], '--json'])
    elif action_id == 'embed-3d.scan': args.extend(['scan', values['footprint'], '--json'])
    elif action_id == 'extract-pins.board': args.extend(['board-extract', values['board'], '--include-power']); output()
    elif action_id == 'project-fusion.detect': args.extend(['detect', values['project']]); output()
    elif action_id == 'variant-manager.list': args.extend(['list', values['project']])
    elif action_id.startswith('bom-studio.'):
        args.extend([action_id.split('.')[1], values['project'], '--source-only']); output()
    elif action_id == 'protocol-constraints.compose': request(dict(nets=values['nets']))
    elif action_id == 'bulk-label-editor.preview': request(dict(values, regex=False))
    elif action_id == 'harness-workbench.build':
        request(dict(documents=values['documents'], auto_match=True, include_power=False, include_html=True))
        result['assumptions'].append('Automatic non-power net-name matching is enabled; mappings must be reviewed.')
    elif action_id == 'heater-designer.analyze':
        request(dict(spec=dict(values, layers=1, pattern='Serpentine', material='copper')))
    elif action_id == 'planar-magnetics.analyze':
        request(dict(spec=dict(values, shape='Rectangular spiral', layer_connection='Series',
                              core_name='Air / no core', external_field_ut=0), actuator='Voice coil'))
        result['assumptions'].append('No applied external magnetic field; series layer vias use the backend default board thickness of 1.6 mm.')
    elif action_id == 'manufacturing-readiness.audit':
        request(dict(metrics=dict(values, routed_edge_unknown=True)))
        result['assumptions'].append('Built-in demo fabricator profile; routed-edge distance is UNKNOWN, not measured.')
    else: raise ValueError('No allowlisted adapter for this action.')
    # No declared source file may alias any generated destination.
    destinations = [root / path for path in [*result['outputs'], *result['documents']]]
    for source in result['input_files']:
        path = Path(source).resolve()
        if any(path == dest or dest in path.parents for dest in destinations):
            raise ValueError('An input aliases the private output directory.')
        if path == root or root in path.parents:
            raise ValueError('Inputs must be outside the run directory.')
    return result
