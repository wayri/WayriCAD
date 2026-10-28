import importlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from quick_emerge_plugin import backend
from quick_emerge_plugin.model import config_digest, source_identity, validate_config


class Shape:
    def set_material(self, *args): return self
    def background(self): return self


class Recorder:
    def __init__(self):
        self.xy_plates = []
        self.port_origins = []
        self.unions = []
        self.bounds = None
        self.thickness = None
        self.geo = self
        self.lib = self
        self.PEC = object()
        self.mw = self
        self.mesher = self
        self.EMSolver = {'SUPERLU': 'SUPERLU'}
    def set_solver(self, solver):
        self.solver = solver
        return self
    def set_nthreads(self, threads): self.threads = threads
    def Simulation(self, *args): return self
    def Material(self, **kwargs): return object()
    def Box(self, *args, **kwargs): return Shape()
    def XYPlate(self, *args, **kwargs):
        shape = Shape()
        self.xy_plates.append((args, kwargs, shape))
        return shape
    def Plate(self, origin, *args, **kwargs):
        self.port_origins.append(origin)
        return Shape()
    def add(self, main, tool):
        fused = Shape()
        self.unions.append((main, tool, fused))
        return fused
    def remove(self, *args): return Shape()
    def PCB(self, thickness, **kwargs):
        self.thickness, self.unit = thickness, kwargs['unit']
        return self
    def new(self, x, y, width, direction, *, trace_layer):
        self.trace_layer = trace_layer
        return self
    def store(self, *args): return self
    def straight(self, *args): return self
    def compile_paths(self, *args): return Shape()
    def set_bounds(self, *args): self.bounds = args
    def generate_pcb(self): return Shape()
    def load(self, name): return name
    def lumped_port(self, *args): return Shape()
    def set_resolution(self, *args): pass
    def set_frequency_range(self, *args): pass
    def commit_geometry(self): pass
    def set_boundary_size(self, *args): pass
    def set_face_size(self, *args): pass


class BackendTests(unittest.TestCase):
    def test_import_does_not_load_solver(self):
        code = "import sys; import quick_emerge_plugin.backend; assert 'emerge' not in sys.modules"
        subprocess.run([sys.executable, '-c', code], check=True)

    def test_anisotropic_geometry_and_units(self):
        config = validate_config({'mode': 'pcb_line', 'substrate_x_mm': 80, 'substrate_y_mm': 40})
        em = Recorder()
        _, _, _, widths, thickness = backend.build_geometry(em, np, config)
        self.assertEqual(em.thickness, 1.524)
        self.assertEqual(em.unit, .001)
        self.assertEqual(em.trace_layer, 1)
        self.assertEqual(em.solver, 'SUPERLU')
        self.assertEqual(em.bounds, (-40, -20, 40, 20))
        self.assertEqual(widths, [0.0032, 0.0032])
        self.assertAlmostEqual(thickness, .001524)

    def test_patch_external_feed_geometry_and_port_reference(self):
        base = dict(substrate_x_mm=40, substrate_y_mm=40, patch_width_mm=20,
                    patch_length_mm=20, feed_width_mm=2, inset_width_mm=3, inset_length_mm=5)
        for extension in (0, 5, 10):
            with self.subTest(extension_mm=extension):
                config = validate_config(dict(base, advanced={'patch_feed_extension_mm':extension}))
                em = Recorder()
                model, _, _, widths, thickness = backend.build_geometry(em, np, config)
                np.testing.assert_allclose(em.port_origins[0], [-.001, -.010-extension*.001, -.001524])
                self.assertEqual(widths, [.002])
                self.assertEqual(len(em.unions), int(extension > 0))
                if extension:
                    dimensions, position, strip = em.xy_plates[-2]
                    self.assertEqual(dimensions, (.002, extension*.001))
                    np.testing.assert_allclose(position['position'], [-.001, -.010-extension*.001, 0])
                    self.assertIs(em.unions[0][1], strip)
                    self.assertIs(model._quick_conductors[0], em.unions[0][2])
                else:
                    self.assertEqual(len(em.xy_plates), 4)

    def test_published_patch_offset_and_board_edge_port(self):
        config = validate_config(dict(substrate_x_mm=80, substrate_y_mm=80,
            patch_width_mm=41.3, patch_length_mm=31.9, feed_width_mm=3,
            inset_width_mm=1, inset_length_mm=10,
            advanced={'patch_feed_extension_mm':24.5, 'patch_offset_y_mm':.45}))
        em = Recorder()
        backend.build_geometry(em, np, config)
        np.testing.assert_allclose(em.port_origins[0], [-.0015, -.04, -.001524])
        self.assertAlmostEqual(em.xy_plates[0][1]['position'][1], -.0155)
        self.assertAlmostEqual(em.xy_plates[1][1]['position'][1], -.0155)
        self.assertAlmostEqual(em.xy_plates[2][1]['position'][1], -.0155)
        self.assertAlmostEqual(em.xy_plates[3][1]['position'][1], -.04)
        self.assertEqual(em.xy_plates[3][0], (.003, .0245))

    def test_runtime_errors(self):
        with patch.object(backend.importlib.metadata, 'version', side_effect=importlib.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                backend.runtime_info()
        with patch.object(backend.importlib.metadata, 'version', return_value='2.3.0'):
            with self.assertRaisesRegex(RuntimeError, '3.0.0b9'):
                backend.runtime_info()
        with patch.object(backend.importlib.metadata, 'version', return_value='3.0.0b9'):
            self.assertEqual(backend.runtime_info()['version'], '3.0.0b9')

    def test_stale_request_before_solve(self):
        root = Path(__file__).resolve().parents[2] / '.tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            board = Path(directory) / 'board.kicad_pcb'
            board.write_bytes(b'(kicad_pcb)\n')
            config = validate_config({})
            request = {'config': config, 'config_sha256': config_digest(config), 'source': source_identity(board)}
            path = Path(directory) / 'request.json'
            with patch.object(backend, 'solve') as solve:
                request['config_sha256'] = 'stale'
                path.write_text(json.dumps(request), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Setup changed'):
                    backend.run_request(path)
                request['config_sha256'] = config_digest(config)
                request['source']['sha256'] = 'stale'
                path.write_text(json.dumps(request), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'PCB changed'):
                    backend.run_request(path)
                solve.assert_not_called()

    def test_touchstone_three_port_is_row_major(self):
        with tempfile.TemporaryDirectory() as directory:
            result = dict(port_count=3, config={'mode':'pcb_line','z0_ohm':50}, frequencies_hz=[1e9], s_parameters={f'S{i}{j}':[[10*i+j,0]] for i in (1,2,3) for j in (1,2,3)})
            backend.write_touchstone(directory,result)
            row=(Path(directory)/'network.s3p').read_text().splitlines()[2].split()
            self.assertEqual([float(v) for v in row[1::2]], [11,12,13,21,22,23,31,32,33])

    def test_touchstone_port_order_and_nonfinite(self):
        root = Path(__file__).resolve().parents[2] / '.tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            result = {'config': {'mode': 'pcb_line', 'z0_ohm': 75}, 'frequencies_hz': [1e9],
                      's_parameters': {'S11': [[1, 2]], 'S21': [[3, 4]],
                                       'S12': [[5, 6]], 'S22': [[7, 8]]}}
            backend.write_touchstone(directory, result)
            lines = (Path(directory) / 'network.s2p').read_text().splitlines()
            self.assertEqual(lines[1], '# Hz S RI R 75')
            self.assertEqual([float(v) for v in lines[2].split()], [1e9, 1, 2, 3, 4, 5, 6, 7, 8])
            result['s_parameters']['S21'][0][0] = float('nan')
            with self.assertRaisesRegex(ValueError, 'Non-finite'):
                backend.write_touchstone(directory, result)


if __name__ == '__main__': unittest.main()
