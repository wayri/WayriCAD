import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quick_emerge_plugin import compatibility, qualification


def fake_result(config, **kwargs):
    study = config['advanced']['study']
    if study == 'thermal':
        return dict(port_count=0, s_parameters={}, thermal=dict(x_mm=[0., 1.], y_mm=[0., 1.], temperature_k=[[300.,300.],[300.,300.]], reference_peak_k=300., peak_k=300., reference_transient_peak_k=300., transient={'time_s':[0.,config['advanced']['thermal_time_s']]}))
    count = 0 if study == 'scattering' else (config['advanced']['array_count_x']*config['advanced']['array_count_y'] if study == 'array' else (2 if study in ('periodic','waveguide') else (1 if config['mode'] == 'patch' else 2)))
    points = config['points']
    result = {'frequencies_hz': [config['f_start_hz'] + i * (config['f_stop_hz'] - config['f_start_hz']) / (points - 1)
                                 for i in range(points)],
              's_parameters': {f'S{i}{j}': [[.1, 0.] for _ in range(points)]
                               for i in range(1, count + 1) for j in range(1, count + 1)},
              'field': {'x_mm': list(range(5)), 'y_mm': list(range(5)),
                        'norm_e_v_m': [[None, 0., 1., 2., 3.] for _ in range(5)]}}
    if study == 'array':
        result['array']={'superposition_relative_error':0.}
    if study == 'waveguide':
        result['waveguide']={'maximum_s21_complex_error':0.}
    if config['advanced']['coupled_thermal']:
        result['thermal']={'peak_k':300.,'coupling':'dielectric only'}
    if study == 'scattering':
        result['scattering'] = dict(theta_rad=[0.,1.], phi_rad=[0.,1.], rcs_m2=[[1.,1.],[1.,1.]])
    if config['mode'] == 'patch':
        result['radiation'] = {'theta_rad': [0., 1.], 'phi_rad': [-1., 0., 1.],
                               'norm_e': [[0., 1., 0.], [1., 2., 1.]]}
    return result


class QualificationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.tmp'
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / compatibility.CERTIFICATE_NAME

    def test_templates_and_polygon_region_certificate(self):
        with patch.object(qualification.importlib.metadata, 'version', return_value='3.1.0'), \
                patch.object(qualification.backend, 'solve', side_effect=fake_result) as solve, \
                patch.object(qualification, 'qualify_extended_apis', return_value=['extended-fixture-checks']) as extras:
            cert = qualification.qualify(self.output)
        self.assertEqual(len(solve.call_args_list), 16)
        extras.assert_called_once_with(self.output.parent)
        self.assertIn('extended-fixture-checks',cert['checks'])
        self.assertEqual([call.args[0]['mode'] for call in solve.call_args_list[:4]], ['pcb_line', 'patch', 'pcb_line', 'pcb_region'])
        self.assertEqual(solve.call_args_list[2].args[0]['sweep'], 'adaptive')
        self.assertTrue(all(call.kwargs.get('qualifying') is True for call in solve.call_args_list))
        self.assertEqual(solve.call_args_list[3].kwargs['region']['area']['id'], 'qualification-coupon')
        self.assertIn('polygon_region_linear', cert['checks'])
        self.assertEqual(compatibility.runtime_certificate(self.output.parent), cert)

    def test_old_version_does_not_solve_or_certify(self):
        with patch.object(qualification.importlib.metadata, 'version', return_value='2.99'), \
                patch.object(qualification.backend, 'solve') as solve:
            with self.assertRaises(RuntimeError):
                qualification.qualify(self.output)
        solve.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_solve_does_not_certify(self):
        with patch.object(qualification.importlib.metadata, 'version', return_value='3.0.0b9'), \
                patch.object(qualification.backend, 'solve', side_effect=RuntimeError('mesh failure')):
            with self.assertRaises(RuntimeError):
                qualification.qualify(self.output)
        self.assertFalse(self.output.exists())

    def test_malformed_samples(self):
        config = qualification.smoke_configs()[1][1]
        mutations = [
            lambda r: r.update(frequencies_hz=[1., 1., 2.]),
            lambda r: r['s_parameters']['S11'].pop(),
            lambda r: r['s_parameters']['S11'][0].__setitem__(0, float('nan')),
            lambda r: r['field']['norm_e_v_m'][0].pop(),
            lambda r: r['field'].update(norm_e_v_m=[[None] * 5 for _ in range(5)]),
            lambda r: r['field']['norm_e_v_m'][0].__setitem__(0, -1.),
            lambda r: r['radiation'].update(norm_e=[[0.] * 3 for _ in range(2)]),
            lambda r: r['radiation'].update(norm_e=[[1.] * 2 for _ in range(3)]),
            lambda r: r['radiation']['norm_e'][0].__setitem__(0, float('inf')),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                result = copy.deepcopy(fake_result(config))
                mutate(result)
                with self.assertRaises(ValueError):
                    qualification.check_result(result, config)
                with patch.object(qualification.importlib.metadata, 'version', return_value='3.1'), \
                        patch.object(qualification.backend, 'solve', return_value=result):
                    with self.assertRaises(ValueError):
                        qualification.qualify(self.output)
                self.assertFalse(self.output.exists())

    def test_certificate_rejects_stale_and_malformed(self):
        self.assertIsNone(compatibility.runtime_certificate(self.output.parent))
        cert = dict(schema=1, issuer=compatibility.CERTIFICATE_ISSUER, version='3.1',
                    adapter_signature=compatibility.adapter_signature())
        for key, value in [('schema', True), ('version', 3), ('version', ''),
                           ('issuer', 'other'), ('adapter_signature', 'stale')]:
            self.output.write_text(json.dumps(dict(cert, **{key: value})), encoding='utf-8')
            self.assertIsNone(compatibility.runtime_certificate(self.output.parent))
        self.output.write_text('{bad', encoding='utf-8')
        self.assertIsNone(compatibility.runtime_certificate(self.output.parent))

    def test_signature_is_deterministic_and_tracks_exact_bytes(self):
        original = compatibility.adapter_signature()
        self.assertEqual(len(original), 64)
        self.assertEqual(original, compatibility.adapter_signature())
        with patch.object(compatibility.Path, 'read_bytes', return_value=b'changed'):
            self.assertNotEqual(original, compatibility.adapter_signature())


if __name__ == '__main__':
    unittest.main()
