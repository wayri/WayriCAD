"""Opt-in KiCad 10 regression for 100 mixed project and section instances.

Run with FUSION_NATIVE_100=1 using KiCad's bundled Python. Set
FUSION_NATIVE_100_OUTPUT to a new directory to retain the native artifacts.
"""
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import replace
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_instances_native_test'
pkg = ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg
sections = importlib.import_module(PACKAGE + '.sections')
sx = importlib.import_module(PACKAGE + '.sexpr')
model = importlib.import_module(PACKAGE + '.model')
netlist = importlib.import_module(PACKAGE + '.netlist')
engine = importlib.import_module(PACKAGE + '.engine')

# Reuse the established KiCad-native routed hierarchical fixture. Loading by
# path also works when this test is invoked outside unittest discovery.
fixture_path = Path(__file__).with_name('test_sections_native.py')
fixture_spec = importlib.util.spec_from_file_location('_fusion_instances_fixture', fixture_path)
fixture_module = importlib.util.module_from_spec(fixture_spec)
sys.modules[fixture_spec.name] = fixture_module
fixture_spec.loader.exec_module(fixture_module)
make_fixture = fixture_module.make_fixture


def _counts(board):
    return {tag: len(sx.children(board, tag)) for tag in
            ('footprint', 'segment', 'via', 'zone', 'gr_line', 'gr_rect')}


def _findings(drc):
    return dict(sorted(Counter(item['type'] for item in drc['violations']).items()))


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_100') == '1',
                     'Opt in with FUSION_NATIVE_100=1 and KiCad bundled Python')
class NativeHundredInstanceTests(unittest.TestCase):
    def test_fifty_projects_and_fifty_routed_sections(self):
        retained = os.environ.get('FUSION_NATIVE_100_OUTPUT')
        if retained:
            Path(retained).mkdir(parents=True, exist_ok=False)
        context = nullcontext(retained) if retained else tempfile.TemporaryDirectory(
            prefix='fusion-native-hundred-')
        with context as folder:
            base = Path(folder).resolve()
            started = time.monotonic()
            whole, sheet_path = make_fixture(base / 'source')
            plan = sections.preview_section(whole, sheet_path, [0, 0, 20, 20])
            self.assertEqual(plan['report']['counts']['footprint'], 1)
            self.assertEqual(plan['report']['counts']['segment'], 2)
            self.assertEqual(plan['report']['counts']['via'], 1)
            self.assertEqual(plan['report']['counts']['zone'], 1)
            section = sections.apply_section(plan, base / 'section')
            self.assertEqual(section.kind, 'section')
            self.assertEqual(section.section_origin['sheet_path'], sheet_path)
            self.assertEqual(section.section_origin['region_mm'], [0, 0, 20, 20])

            source_hashes = sections.fingerprint(base / 'source')
            section_hashes = sections.fingerprint(base / 'section')
            source_board = sx.load(base / 'source/board.kicad_pcb')
            section_board = sx.load(base / 'section/board.kicad_pcb')
            self.assertEqual(_counts(source_board)['segment'], 2)
            self.assertEqual(_counts(section_board)['segment'], 2)
            self.assertEqual(_counts(section_board)['zone'], 1)

            # DRC can save/refill a board. Run the whole-source baseline on a
            # disposable copy so the saved source hashes remain meaningful.
            baseline_dir = base / 'baseline'
            shutil.copytree(base / 'source', baseline_dir)
            cli = netlist.KiCadCLI()
            whole_drc = cli.drc(baseline_dir / 'board.kicad_pcb',
                                baseline_dir / 'drc.json')
            section_drc = json.loads((base / 'section/section-drc.json').read_text(
                encoding='utf-8-sig'))
            self.assertFalse(whole_drc['schematic_parity'])
            self.assertFalse(section_drc['schematic_parity'])

            sources = []
            for index in range(50):
                sources.append(replace(whole, alias=f'PROJECT_{index + 1:03}'))
                sources.append(replace(section, alias=f'SECTION_{index + 1:03}'))
            self.assertEqual(Counter(spec.kind for spec in sources),
                             {'project': 50, 'section': 50})
            options = model.Options(
                sources=sources, destination=str(base / 'merged'), name='Combined',
                columns=10, acknowledge_outline_change=True,
                accept_primary_settings=True, saved_sources_confirmed=True)
            result = engine.merge(options)
            elapsed = round(time.monotonic() - started, 3)
            output = Path(result['directory'])
            report = json.loads((output / 'reports/merge-report.json').read_text(
                encoding='utf-8-sig'))
            merged = sx.load(output / 'Combined.kicad_pcb')
            counts = _counts(merged)
            for tag, expected in (('footprint', 100), ('segment', 200),
                                  ('via', 100), ('zone', 100)):
                self.assertEqual(counts[tag], expected, tag)
            self.assertEqual(report['validation_backend'], 'native-kicad-cli')
            self.assertEqual(report['connectivity']['components'], 100)
            self.assertEqual(report['connectivity']['pins'], 200)
            self.assertEqual(report['connectivity']['electrical_partitions'],
                             'exact match; sources isolated')
            self.assertEqual(report['bom']['included_quantity'], 100)
            self.assertEqual(Counter(item['kind'] for item in
                                     report['summary']['sources']),
                             {'project': 50, 'section': 50})
            self.assertEqual(len(report['summary']['sources']), 100)
            for item in report['summary']['sources']:
                if item['kind'] == 'section':
                    self.assertEqual(item['section_origin'], section.section_origin)
                else:
                    self.assertFalse(item['section_origin'])

            combined_root = sx.value(sx.load(output / 'Combined.kicad_sch'), 'uuid')
            combined = netlist.Netlist.read(output / 'reports/combined.xml',
                                            root_uuid=combined_root)
            self.assertEqual(len(combined.components), 100)
            self.assertEqual(len(combined.pins), 200)
            self.assertEqual(len(combined.nets), 200)
            self.assertTrue(all(len(endpoints) == 1 for endpoints in
                                combined.nets.values()))
            refs_by_source = defaultdict(set)
            for item in report['references']:
                refs_by_source[item['source']].add(item['new_reference'])
            self.assertEqual(len(refs_by_source), 100)
            self.assertTrue(all(len(refs) == 1 for refs in refs_by_source.values()))
            self.assertEqual(len(set.union(*refs_by_source.values())), 100)
            source_nets = {}
            for alias, refs in refs_by_source.items():
                ref = next(iter(refs))
                source_nets[alias] = {combined.pins[(ref, pin)] for pin in ('1', '2')}
                self.assertEqual(len(source_nets[alias]), 2)
            self.assertEqual(len(set.union(*source_nets.values())), 200)

            merged_drc = json.loads((output / 'reports/drc.json').read_text(
                encoding='utf-8-sig'))
            self.assertFalse(merged_drc['schematic_parity'])
            self.assertFalse(merged_drc['unconnected_items'])
            expected_findings = Counter(_findings(whole_drc))
            expected_findings = Counter({key: value * 50 for key, value in
                                          expected_findings.items()})
            expected_findings.update({key: value * 50 for key, value in
                                      _findings(section_drc).items()})
            actual_findings = Counter(_findings(merged_drc))
            self.assertEqual(actual_findings, expected_findings)
            self.assertEqual(actual_findings.get('shorting_items', 0), 0)
            self.assertEqual(sections.fingerprint(base / 'source'), source_hashes)
            self.assertEqual(sections.fingerprint(base / 'section'), section_hashes)

            evidence = {
                'kicad_version': cli.version,
                'instance_count': len(sources),
                'kinds': dict(Counter(spec.kind for spec in sources)),
                'fixture': 'one R1, two segments, one via and one zone per instance',
                'elapsed_seconds_including_fixture_and_section_extraction': elapsed,
                'merged_board_counts': counts,
                'combined_netlist': {
                    'components': len(combined.components),
                    'nets': len(combined.nets),
                    'pins': len(combined.pins),
                    'unique_source_net_sets': len(source_nets),
                    'exact_isolated_partitions': True,
                },
                'bom_included_quantity': report['bom']['included_quantity'],
                'drc_baselines': {
                    'whole_project': _findings(whole_drc),
                    'extracted_section': _findings(section_drc),
                    'merged': dict(actual_findings),
                    'schematic_parity_findings': len(merged_drc['schematic_parity']),
                    'unconnected_items': len(merged_drc['unconnected_items']),
                },
                'source_hashes_unchanged': True,
                'section_hashes_unchanged': True,
                'native_merge_completed': True,
            }
            (base / 'native-hundred-validation.json').write_text(
                json.dumps(evidence, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
