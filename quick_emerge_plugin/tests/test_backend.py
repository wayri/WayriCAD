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
        self.bounds = None
        self.thickness = None
        self.geo = self
        self.lib = self
        self.PEC = object()
        self.mw = self
        self.mesher = self
        self.EMSolver = {'SUPERLU': 'SUPERLU'}
    def set_solver(self, solver): self.solver = solver
    def Simulation(self, *args): return self
    def Material(self, **kwargs): return object()
    def Box(self, *args, **kwargs): return Shape()
    def XYPlate(self, *args, **kwargs): return Shape()
    def Plate(self, *args, **kwargs): return Shape()
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
