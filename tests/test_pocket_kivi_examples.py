"""Actual saved-PCB sample custody, numerical arrays and viewer round trips."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=ROOT/'docs/examples/pocket-kivi'
NAMES=('quick-pi','quick-si','quick-therm','quick-therm-transient')


def load(name):return json.loads((EXAMPLES/(name+'.pocket-kivi.json')).read_bytes())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_every_example_uses_the_same_exact_included_saved_pcb_and_portable_paths():
    digest=sha(EXAMPLES/'example.kicad_pcb')
    provenance=json.loads((EXAMPLES/'provenance.json').read_bytes())
    assert digest==provenance['source_sha256']=='8d60e824376418fa4cad65d37c9d8c8dd5da60c5538b9bf0a11976dbb98f1e7e'
    for name in NAMES:
        report=load(name)
        assert report['source_path']=='example.kicad_pcb' and report['source_sha256']==digest
        assert report['pocket_kivi_export']['source_state']=='saved'
        assert report['pocket_kivi_export']['version']==provenance['producer_versions'][report['pocket_kivi_export']['tool']]
        assert report['pocket_kivi_export']['units']
        raw=(EXAMPLES/(name+'.pocket-kivi.json')).read_text(encoding='utf-8')
        assert ':\\' not in raw and ':/Users/' not in raw and ':\\\\Users\\' not in raw
    assert not list(EXAMPLES.glob('*.kicad_prl'))
    assert sum(path.stat().st_size for path in EXAMPLES.iterdir() if path.is_file())<5*1024*1024


def test_published_output_and_selected_producer_hashes_match_provenance():
    provenance=json.loads((EXAMPLES/'provenance.json').read_bytes())
    for name,digest in provenance['files'].items():assert sha(EXAMPLES/name)==digest
    assert provenance['producer_source_normalization']=='CRLF to LF only'
    for name,digest in provenance['producer_modules'].items():
        assert not Path(name).is_absolute()
        actual=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        assert actual==digest,'Producer changed; regenerate the saved-PCB examples.'
    assert provenance['checks']['native_saved_board_producers']=='passed'
    assert provenance['checks']['unchanged_source_bytes'] is True


def test_pi_arrays_nulls_saved_coordinates_and_independent_strip_reference():
    result=load('quick-pi');mesh=result['mesh'];solved=result['result']
    assert len(mesh['points_mm'])==180 and len(mesh['triangles'])==230
    assert len(solved['potential_V'])==len(mesh['points_mm'])
    assert sum(v is None for v in solved['potential_V'])==26 and solved['floating_triangles']==24
    assert len(solved['cell_power_W'])==len(solved['cell_J_A_mm2'])==230
    assert result['geometry']['net']=='/Front outputs/SLOT1'
    assert result['geometry']['layers'][0]['z_mm']==.0175
    assert solved['source_voltage_V']==3.3 and solved['sink_current_A']==.25
    expected_drop=.25*1.724e-8*.018/(.001*.000035)
    assert solved['voltage_drop_V']==pytest.approx(expected_drop,abs=1e-12)
    assert solved['total_power_W']==pytest.approx(.000554142857142941,abs=1e-15)
    assert solved['sink_voltage_V']==pytest.approx(3.297783428571428,abs=1e-12)


def test_si_real_route_bindings_explicit_uniform_assumptions_and_full_samples():
    result=load('quick-si');eye=result['eye']
    assert result['endpoint_bindings']==dict(net_name='/Front outputs/SLOT1',source='J1.1',sink='U1.1')
    assert result['board_item_ids']==['c1bf74a6-b509-583c-b3e7-8e8ade035886']
    assert result['path']['length_mm']==20.
    assert result['delay_ns']==pytest.approx(20*math.sqrt(3)/299.792458,abs=1e-15)
    assert result['inputs']['assumed_z0_ohm']==50 and result['inputs']['assumed_epsilon_eff']==3
    assert len(eye['time_ui'])==129 and len(eye['traces_v'])==127
    assert all(len(trace)==129 for trace in eye['traces_v'])
    assert len(eye['step_response']['time_ns'])==len(eye['step_response']['voltage_v'])==555
    fingerprints=result['source_fingerprints']
    assert fingerprints['example.kicad_pro']==sha(EXAMPLES/'example.kicad_pro')
    assert fingerprints['example.kicad_dru'] is None


def test_thermal_steady_source_mapping_cutout_gaps_and_balance():
    result=load('quick-therm');network=result['thermal_network']
    assert network['mesh']['active_cells_per_layer']==276
    assert network['mesh']['nx']==24 and network['mesh']['ny']==12
    assert [row['name'] for row in network['layers']]==['F.Cu','B.Cu']
    for layer in network['layers']:
        assert len(layer['values_c'])==12 and all(len(row)==24 for row in layer['values_c'])
        assert sum(v is None for row in layer['values_c'] for v in row)==12
    source=network['components'][0]
    assert source['source_net']=='/Front outputs/SLOT1' and source['source_pad_number']=='1'
    assert source['source_bbox_mm']==[24.,4.,26.,6.]
    assert source['power_w']==.05 and source['junction_c']==pytest.approx(36.31237007668578,abs=1e-10)
    assert abs(network['heat_balance']['residual_w'])<1e-10
    assert result['probes'][1]['status']=='UNKNOWN' and result['probes'][1]['temperature_c'] is None


def test_thermal_transient_layer_major_frame_coordinates_and_exact_probe_history():
    result=load('quick-therm-transient');transient=result['thermal_network']['transient'];spatial=transient['spatial_index']
    assert spatial['active_cells_per_layer']==276 and len(spatial['cells'])==276
    assert len(spatial['x_centers_mm'])==24 and len(spatial['y_centers_mm'])==12
    assert spatial['x_centers_mm'][0]==spatial['y_centers_mm'][0]==.625
    assert [layer['z_mm'] for layer in spatial['layers']]==[.0175,1.5825]
    assert [frame['time_s'] for frame in transient['frames']]==[0.,.5,1.]
    assert all(len(frame['temperatures_c'])==552 for frame in transient['frames'])
    assert set(transient['frames'][0]['temperatures_c'])=={20.}
    probes=json.loads((EXAMPLES/'viewer-probes.json').read_bytes())[-1]
    assert probes['cutout']['value'] is None
    assert probes['heater']['x']==24.375 and probes['heater']['y']==4.375
    index=spatial['cells'].index([spatial['x_centers_mm'].index(24.375),spatial['y_centers_mm'].index(4.375)])
    saved=[frame['temperatures_c'][index] for frame in transient['frames']]
    assert saved==[point['y'] for point in probes['history']['series'][0]['points']]
    assert saved==pytest.approx([20.,21.879388720174184,23.207663444711994],abs=1e-12)
    assert probes['heater']['value']==saved[-1]


def test_stored_viewer_probe_is_a_saved_pi_triangle_interpolation():
    rows=json.loads((EXAMPLES/'viewer-probes.json').read_bytes());probe=rows[0]['probe']
    assert probe['method']=='Interpolated saved nodes' and probe['unit']=='V'
    assert [probe['x'],probe['y'],probe['z']]==[15,5,.0175]
    assert probe['value']==pytest.approx(3.298891714285714,abs=1e-12)
    assert [len(row['plots']) for row in rows]==[3,3,2,4]


def test_actual_viewer_adapters_roundtrip_optional(tmp_path):
    extension=os.environ.get('POCKET_KIVI_VIEWER_EXTENSION')
    if not extension or not shutil.which('node'):pytest.skip('Set POCKET_KIVI_VIEWER_EXTENSION and provide Node.js for actual viewer adapter readback.')
    spec=importlib.util.spec_from_file_location('pocket_example_generator',ROOT/'tools/generate_pocket_kivi_examples.py')
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    for name in NAMES:shutil.copyfile(EXAMPLES/(name+'.pocket-kivi.json'),tmp_path/(name+'.pocket-kivi.json'))
    result=generator.viewer_checks(tmp_path,extension)
    assert result['status']=='passed'
    assert json.loads((tmp_path/'viewer-probes.json').read_bytes())==json.loads((EXAMPLES/'viewer-probes.json').read_bytes())


def test_native_saved_board_producer_reproduction_optional(tmp_path):
    native=os.environ.get('WAYRICAD_NATIVE_PYTHON')
    if not native:pytest.skip('Set WAYRICAD_NATIVE_PYTHON to an existing KiCad native Python for producer reproduction.')
    for name in ('example.kicad_pcb','example.kicad_pro'):shutil.copyfile(EXAMPLES/name,tmp_path/name)
    process=subprocess.run([native,str(ROOT/'tools/generate_pocket_kivi_examples.py'),'--output',str(tmp_path)],
        cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',timeout=120,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert process.returncode==0,process.stderr[-4000:]
    assert sha(tmp_path/'example.kicad_pcb')==sha(EXAMPLES/'example.kicad_pcb')
    for name in NAMES:
        actual=json.loads((tmp_path/(name+'.pocket-kivi.json')).read_bytes());stored=load(name)
        if name=='quick-pi':
            assert actual['mesh']['points_mm']==stored['mesh']['points_mm']
            assert actual['mesh']['triangles']==stored['mesh']['triangles']
            assert actual['result']['potential_V']==stored['result']['potential_V']
        elif name=='quick-si':
            assert actual['path']['length_mm']==stored['path']['length_mm']
            assert actual['eye']['traces_v']==stored['eye']['traces_v']
        elif name=='quick-therm':
            assert actual['thermal_network']['layers']==stored['thermal_network']['layers']
        else:
            assert actual['thermal_network']['transient']['spatial_index']==stored['thermal_network']['transient']['spatial_index']
            assert actual['thermal_network']['transient']['frames']==stored['thermal_network']['transient']['frames']
