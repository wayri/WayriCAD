"""Report scopes use declared full paths, nets, pins and route direction."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from wayricad_runtime.report_context import organize_report, report_context, report_context_html


ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT/'docs/examples/pocket-kivi'/(name+'.pocket-kivi.json')).read_text())


def section(bundle, title):
    return next(row for row in report_context(bundle) if row['title'] == title)


def test_public_pi_fixture_keeps_full_net_pin_direction_and_source_path():
    bundle = example('quick-pi')
    before = deepcopy(bundle)
    sources = section(bundle, 'Full recorded source paths')['rows']
    assert any(row[2] == 'example.kicad_pcb' for row in sources)
    networks = section(bundle, 'PI nets and series-network scope')['rows']
    assert networks[0][1] == '/Front outputs/SLOT1'
    endpoints = section(bundle, 'PI source and load pin groups')['rows']
    assert endpoints[0][3] == 'J1.1' and endpoints[1][3] == 'U1.1'
    assert '/Front outputs/SLOT1' in report_context_html(bundle)
    assert bundle == before


def test_descriptive_labels_do_not_hide_explicit_pin_numbers():
    bundle={'request':{'net':'VDD','source_terminals':['one','two'],'sink_terminal':'load'},
            'geometry':{'net':'VDD','terminals':[
                {'id':'one','reference':'J1','pad_number':'7','label':'Supply','net':'VDD'},
                {'id':'two','reference':'J1','pad_number':'8','label':'Supply','net':'VDD'},
                {'id':'load','reference':'U1','pin_number':'14','label':'VDD','net':'VDD'}]}}
    html=report_context_html(bundle)
    assert 'J1.7 (Supply), J1.8 (Supply)' in html
    assert 'U1.14 (VDD)' in html


def test_grouped_series_fixture_lists_every_pin_and_ordered_network():
    from quick_pi_plugin.service import series_execute
    from quick_pi_plugin.tests.test_series_groups import extract, mesh_for, native_board, request

    with patch('quick_pi_plugin.board_geometry.extract', side_effect=extract), \
            patch('quick_pi_plugin.mesh.build_mesh', side_effect=lambda geo, **kwargs: mesh_for(geo['net'])):
        bundle = series_execute(native_board(), Path('C:/Projects/Example/board.kicad_pcb'), request())
    bundle['request']['board_path'] = 'C:/Projects/Example/board.kicad_pcb'
    endpoints = section(bundle, 'PI source and load pin groups')['rows']
    assert endpoints[0][3] == 'J1.1, J1.2'
    assert endpoints[1][3] == 'U1.1, U1.2'
    stages = section(bundle, 'Explicit PI series stages')['rows']
    assert stages[0][2:4] == ('A', 'Q1.1, Q1.2')
    assert stages[0][6:8] == ('Q1.3, Q1.4', 'B')
    html = report_context_html(bundle)
    assert 'Series network: A, B · Path: J1.1, J1.2 → Load 1: U1.1, U1.2' in html
    assert 'C:/Projects/Example/board.kicad_pcb' in html
    assert 'Q1.5' not in html  # Unassigned gate does not enter the path.


def test_si_study_keeps_each_explicit_route_and_failed_case_unknown():
    from signal_integrity_advisor_plugin.study import run_study
    from signal_integrity_advisor_plugin.tests.test_study import case
    from types import SimpleNamespace

    def analyze(board, net, start, end, reference, **inputs):
        path = {'net_name': net, 'start_pad': start, 'end_pad': end,
                'reference_layer': 'B.Cu', 'length_mm': 12,
                'segments': [{'kind': 'track', 'layer': 'F.Cu', 'start_mm': [0,1],
                              'end_mm': [12,1], 'length_mm': 12, 'reference_net': '/GND',
                              'reference_layer': 'B.Cu', 'impedance_ohm': 50, 'status': 'SCREENED'}]}
        return {'status': 'SCREENED', 'path': path}, SimpleNamespace(board_items=[], net_name=net)

    config = {'cases': [case('data', '/BUS/DATA'),
                        case('clock', '/BUS/CLOCK', start='U1.2', end='J1.2')]}
    report = run_study(object(), config, analyzer=analyze)
    rows = section(report, 'SI signal paths and endpoints')['rows']
    assert [row[2:5] for row in rows] == [('/BUS/DATA', 'U1.1', 'J1.1'),
                                          ('/BUS/CLOCK', 'U1.2', 'J1.2')]
    assert any(row['title'].startswith('SI net /BUS/CLOCK · Path U1.2 → J1.2')
               for row in report_context(report))
    html = report_context_html(report)
    assert 'Combined SI signal-path scope — /BUS/DATA: U1.1 → J1.1; /BUS/CLOCK: U1.2 → J1.2' in html
    assert '/GND' in html
    failed = run_study(object(), {'cases': [case('bad', '/BUS/BAD', start='')]}, analyzer=analyze)
    row = section(failed, 'SI signal paths and endpoints')['rows'][0]
    assert row[1] == '/BUS/BAD' and row[2] == 'Unknown' and row[3] == 'Unknown'


def test_thermal_fixture_uses_declared_source_net_and_heat_path():
    bundle = example('quick-therm')
    rows = section(bundle, 'Thermal component source nets and heat paths')['rows']
    assert rows[0][1] == '/Front outputs/SLOT1'
    assert rows[0][3] == 'board'


def test_pi_multiple_loads_and_batch_scope_name_every_pin_group_and_net():
    terminals = [dict(id=name, label=name, net=net) for name, net in (
        ('J1.1', '/VCC'), ('J1.2', '/VCC'), ('U1.1', '/VCC'),
        ('U2.1', '/VCC'), ('U2.2', '/VCC'), ('J2.1', '/GND'), ('U3.1', '/GND'))]
    first = {'request': {'net': '/VCC', 'source_terminals': ['J1.1', 'J1.2'],
                         'sinks': [{'terminals': ['U1.1'], 'current_A': 1},
                                   {'terminals': ['U2.1', 'U2.2'], 'current_A': 2}]},
             'geometry': {'net': '/VCC', 'terminals': terminals}}
    second = {'request': {'net': '/GND', 'source_terminal': 'J2.1',
                          'sink_terminal': 'U3.1', 'sink_current': 3},
              'geometry': {'net': '/GND', 'terminals': terminals}}
    single = report_context_html(first)
    assert 'Net: /VCC · Path: J1.1, J1.2 → Load 1: U1.1; Load 2: U2.1, U2.2' in single
    aggregate = {'batch': {'cases': [{'name': 'Supply', 'electrical': first},
                                     {'name': 'Return', 'electrical': second}]}}
    html = report_context_html(aggregate)
    assert 'Combined PI case scope — Supply: /VCC · Path: J1.1, J1.2 → Load 1: U1.1; Load 2: U2.1, U2.2' in html
    assert 'Return: /GND · Path: J2.1 → Load 1: U3.1' in html
    assert '<h3>PI case Return · Net /GND · source and load pins</h3>' in html


def test_emerge_region_ports_keep_declared_nets_coordinates_and_unknown_pins():
    from quick_emerge_plugin.region_ports import plan_region
    from quick_emerge_plugin.tests.test_region_ports import coupon

    region = plan_region(coupon(), 'SIG', 'GND')
    result = {'config': {'mode': 'pcb_region', 'signal_net': 'SIG', 'reference_net': 'GND'},
              'model_scope': 'saved-rule-area-copper', 'port_count': len(region['ports']),
              'region': region, 'source': {'path': 'C:/Projects/Example/rf.kicad_pcb'}}
    ports = section(result, 'EMerge declared boundary ports (not PCB pins)')['rows']
    assert len(ports) == len(region['ports'])
    assert ports[0][1:3] == ('SIG', 'GND') and ports[0][-1] == 'Unknown'
    assert [float(value) for value in ports[0][3].split(',')] == region['ports'][0]['a_mm']
    html = report_context_html(result)
    assert 'Net: SIG · Reference net: GND · Boundary ports:' in html
    assert 'C:/Projects/Example/rf.kicad_pcb' in html
    template = {'config': {'mode': 'pcb_line'}, 'model_scope': 'parametric-template',
                'port_count': 2, 'source': {'path': 'C:/Projects/Example/rf.kicad_pcb'}}
    assert 'PCB net and pin path: Unknown' in report_context_html(template)
    assert not any('boundary ports' in row['title'].lower() for row in report_context(template))


def test_organizer_places_emerge_context_after_header_inside_main():
    result = {'config': {'mode': 'pcb_region', 'signal_net': '/RF/SIG',
                         'reference_net': '/RF/GND'}, 'port_count': 1,
              'source': {'path': 'C:/Projects/Example/rf.kicad_pcb'}}
    html = ('<html><head><style>h1{color:black}</style></head><body><main class="page">'
            '<header><h1>EMerge</h1><p>Summary</p></header><nav id="contents">Contents</nav>'
            '<section id="plot"><h2>Plot</h2></section></main></body></html>')
    organized = organize_report(html, result)
    assert organized.index('</header>') < organized.index('report-context')
    assert organized.index('report-scoped-body') < organized.index('id="plot"')
    assert organized.index('</section></main>') > organized.index('id="plot"')
    assert organized.count('<main class="page">') == 1


def test_organizer_wraps_existing_plots_under_scope_and_preserves_document():
    bundle = {'source_path': 'C:/Projects/Example/<board>.kicad_pcb',
              'path': {'net_name': '/A&B', 'start_pad': 'J1.1', 'end_pad': 'U1.2'}}
    html = ('<!doctype html><html><head><script>const keep="<h1>fake</h1>";</script></head>'
            '<body><h1 id="title">Report</h1><h2 id="plot">Plot</h2><svg id="field"></svg>'
            '<script>draw("field");const end="</body>";</script></body></html>')
    organized = organize_report(html, bundle)
    assert organized.startswith('<!doctype html><html><head><script>const keep="<h1>fake</h1>";</script></head>')
    assert organized.index('</head>') < organized.index('report-context')
    assert '<h1 id="title">Report</h1>' in organized
    assert '<h2 id="plot">Plot</h2><svg id="field"></svg>' in organized
    assert '<script>draw("field");const end="</body>";</script>' in organized
    assert organized.index('const end=') < organized.index('</section></body></html>')
    assert 'C:/Projects/Example/&lt;board&gt;.kicad_pcb' in organized
    assert 'Net: /A&amp;B · Path: J1.1 → U1.2' in organized
    assert organized.index('report-context') < organized.index('id="plot"')
    assert organized.index('report-scoped-body') < organized.index('id="plot"')
    assert organize_report(organized, bundle) == organized
    assert organize_report('new html', {'model': 'explicit'}) == 'new html'
    assert organize_report(html, {'model': 'explicit'}) == html
