import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from embed_3d_plugin.paths import Resolver, ResolutionError, exact_name_candidates
from embed_3d_plugin.core import Planner


class NativePathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.stock = self.root/'KiCad 10'/'share'/'kicad'/'3dmodels'
        self.fpdir = self.root/'KiCad 10'/'share'/'kicad'/'footprints'
        self.stock.mkdir(parents=True); self.fpdir.mkdir(parents=True)
        self.project = self.root/'project'; self.project.mkdir()
        self.path = self.stock/'Resistor_SMD.3dshapes'/'R_0402_1005Metric.step'
        self.path.parent.mkdir(); self.path.write_bytes(b'ISO-10303-21; test opaque bytes; END-ISO-10303-21;')
    def tearDown(self): self.tmp.cleanup()

    def native(self):
        thread = threading.get_ident()
        values = {'KICAD10_3DMODEL_DIR': str(self.stock), 'KICAD10_FOOTPRINT_DIR': str(self.fpdir), 'MY_LIVE_ONLY': str(self.stock)}
        def expand(text, project):
            if threading.get_ident() != thread:
                raise AssertionError('Native function called outside main thread')
            for key, value in values.items(): text = text.replace('${'+key+'}', value)
            return text
        return SimpleNamespace(ExpandEnvVarSubstitutions=expand)

    def test_live_default_not_in_environment_is_captured(self):
        r = Resolver(self.project)
        r.variables.pop('KICAD10_3DMODEL_DIR', None)
        r.capture_native(self.native())
        self.assertEqual(r.resolve('${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/'+self.path.name), self.path)
        self.assertTrue(r.native_available)

    def test_stock_relative_path_supported(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock})
        self.assertEqual(r.resolve('Resistor_SMD.3dshapes/'+self.path.name), self.path)

    def test_undefined_old_version_falls_back(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock})
        r.variables.pop('KICAD9_3DMODEL_DIR', None)
        self.assertEqual(r.resolve('${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/'+self.path.name), self.path)

    def test_explicit_old_version_not_silently_redirected(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock, 'KICAD9_3DMODEL_DIR': self.root/'missing'})
        with self.assertRaises(ResolutionError): r.resolve('${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/'+self.path.name)

    def test_kisys_fallback(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock})
        r.variables.pop('KISYS3DMOD', None)
        self.assertEqual(r.resolve('${KISYS3DMOD}/Resistor_SMD.3dshapes/'+self.path.name), self.path)

    def test_session_override_wins_over_runtime(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': str(self.root/'Chosen')})
        r.capture_native(self.native(), references=['${KICAD10_3DMODEL_DIR}/X.step'])
        self.assertEqual(r.expand('${KICAD10_3DMODEL_DIR}'), str(self.root/'Chosen'))
        self.assertNotIn('${KICAD10_3DMODEL_DIR}/X.step', r.native_references)

    def test_native_reference_frozen_for_worker(self):
        ref = '${MY_LIVE_ONLY}/Resistor_SMD.3dshapes/'+self.path.name
        r = Resolver(self.project); r.capture_native(self.native(), references=[ref])
        result = []
        thread = threading.Thread(target=lambda: result.append(r.resolve(ref)))
        thread.start(); thread.join()
        self.assertEqual(result, [self.path])

    def test_native_project_expansion_does_not_override_selected_project(self):
        r = Resolver(self.project)
        native = SimpleNamespace(ExpandEnvVarSubstitutions=lambda value, project: value.replace('${KIPRJMOD}', '/wrong/project'))
        r.capture_native(native, references=['${KIPRJMOD}/part.step'])
        self.assertEqual(r.expand('${KIPRJMOD}'), str(self.project))

    def test_footprint_library_default_and_bad_neighbor(self):
        (self.project/'fp-lib-table').write_text('(fp_lib_table\n(lib(name "Broken")(type "KiCad")(uri "${UNDEFINED_X}/bad"))\n(lib(name "Resistor_SMD")(type "KiCad")(uri "${KICAD10_FOOTPRINT_DIR}/Resistor_SMD.pretty")))')
        r = Resolver(self.project); r.capture_native(self.native())
        self.assertEqual(r.footprint_libraries(self.project)['Resistor_SMD'], self.fpdir/'Resistor_SMD.pretty')

    def test_diagnostics_do_not_dump_credentials(self):
        r = Resolver(self.project, {'SECRET_API_TOKEN': 'DONT_DUMP_ME'})
        self.assertNotIn('DONT_DUMP_ME', json.dumps(r.diagnostics()))

    def test_exact_filename_find_not_fuzzy_and_not_format_swap(self):
        refs = ['bad/'+self.path.name, 'bad/R_0603_1608Metric.step', 'bad/R_0402_1005Metric.wrl']
        found = exact_name_candidates(refs, [self.stock])
        self.assertEqual(found[self.path.name], [self.path])
        self.assertEqual(found['R_0603_1608Metric.step'], [])
        self.assertEqual(found['R_0402_1005Metric.wrl'], [])

    def test_duplicate_basename_remains_multiple_candidates(self):
        another = self.stock/'User'; another.mkdir(); second = another/self.path.name; second.write_bytes(b'different')
        found = exact_name_candidates([self.path.name], [self.stock])
        self.assertEqual(set(found[self.path.name]), {self.path, second})

    def test_search_cancel_and_budget(self):
        with self.assertRaises(InterruptedError): exact_name_candidates([self.path.name], [self.stock], lambda: True)
        with self.assertRaises(ValueError): exact_name_candidates([self.path.name], [self.stock], max_files=0)

    def test_native_resistor_capacitor_ic_links_embed_bytes_and_transforms(self):
        r = Resolver(self.project); r.capture_native(self.native())
        for folder, filename in (('Resistor_SMD', self.path.name), ('Capacitor_SMD', 'C_0201_0603Metric.step'), ('Package_SO', 'SOIC-8_3.9x4.9mm_P1.27mm.step')):
            path = self.stock/(folder+'.3dshapes')/filename
            path.parent.mkdir(exist_ok=True); path.write_bytes(b'model '+folder.encode())
            text = '(footprint "X" (model "${KICAD10_3DMODEL_DIR}/'+folder+'.3dshapes/'+filename+'" (offset (xyz -1 2 3)) (scale (xyz 0.5 2 3)) (rotate (xyz 90 180 17))))'
            p = Planner(r).scan(text)
            self.assertEqual(p.rows[0].status, 'Ready')
            self.assertIn('(rotate (xyz 90 180 17))', p.build())

    def test_source_and_stock_conflict_is_not_silently_chosen(self):
        direct = self.project/'Resistor_SMD.3dshapes'; direct.mkdir(); (direct/self.path.name).write_bytes(b'different')
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock})
        with self.assertRaisesRegex(ResolutionError, 'Ambiguous'): r.resolve('Resistor_SMD.3dshapes/'+self.path.name)

    def test_no_native_api_uses_offline_defaults(self):
        r = Resolver(self.project, {'KICAD10_3DMODEL_DIR': self.stock}); r.capture_native(SimpleNamespace())
        self.assertEqual(r.resolve('Resistor_SMD.3dshapes/'+self.path.name), self.path)
