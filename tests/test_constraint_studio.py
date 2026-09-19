"""Integration checks for staged protocol edits and honest scope feedback."""
import math
from pathlib import Path
import shutil
import runpy
import tempfile
import unittest
import zipfile

from build_pcm import create_plugin_zip
from protocol_constraint_composer_plugin.analysis import Assignment, PRESETS, ProtocolPreset, generate_rules, merge_managed_rules
from protocol_constraint_composer_plugin.constraint_studio.inspection import Item, evaluate
from protocol_constraint_composer_plugin.constraint_studio.model import Rule, RuleDocument, Constraint
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace, apply_bundle
from protocol_constraint_composer_plugin.studio_bridge import overview, scope_preview, stage_protocol_rules

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'protocol_constraint_composer_plugin'


class ConstraintStudioTests(unittest.TestCase):
    def test_protocol_backend_remains_standalone_for_pin_extractor(self):
        module = runpy.run_path(str(PLUGIN / 'analysis.py'))
        self.assertIn('WayriCAD USB2', module['generate_rules']([module['Assignment']('USB2', 'USB_D+', 'user')]))

    def test_protocol_staging_preserves_existing_rules_and_is_idempotent(self):
        workspace = Workspace()
        workspace.document = RuleDocument.load('(version 1)\n(rule "manual" (constraint clearance (min 0.2mm)))\n')
        text = generate_rules([Assignment('USB2', 'USB_D+', 'user')])
        stage_protocol_rules(workspace, text)
        first = workspace.document.emit()
        stage_protocol_rules(workspace, text)
        self.assertEqual(first, workspace.document.emit())
        self.assertEqual('manual', workspace.document.rules[0].name)

    def test_invalid_staging_does_not_replace_document(self):
        workspace = Workspace(); original = workspace.document
        with self.assertRaises(ValueError): stage_protocol_rules(workspace, '(rule broken')
        self.assertIs(original, workspace.document)

    def test_net_name_quotes_backslashes_and_unicode_roundtrip(self):
        for name in ["USB_O'Brien", 'USB_"D+"', r'USB_\D+', 'USB_µ']:
            text = generate_rules([Assignment('USB2', name, 'user')])
            doc = RuleDocument.load('(version 1)\n' + text)
            result = evaluate(doc.rules[0].condition, Item('1', 'Pad', net=name, properties={'NetName': name}))
            self.assertIs(True, result.value, name)

    def test_nonfinite_negative_dimensions_are_rejected(self):
        for value in [math.nan, math.inf, -0.1]:
            preset = ProtocolPreset('USB2', (), value, .2, .2, .1, 90)
            with self.assertRaises(ValueError):
                generate_rules([Assignment('USB2', 'USB_D+', 'user')], {'USB2': preset})

    def test_ambiguous_managed_markers_are_rejected(self):
        begin = '# BEGIN WAYRICAD MANAGED PROTOCOL RULES'; end = '# END WAYRICAD MANAGED PROTOCOL RULES'
        for existing in [begin, end, end + '\n' + begin, begin + begin + end]:
            with self.assertRaises(ValueError): merge_managed_rules(existing, '')

    def test_scope_distinguishes_unknown_and_disabled(self):
        w = Workspace()
        w.document.append(Rule('pair', condition="A.NetName == 'USB' && B.NetName == 'GND'"))
        item = Item('1', 'Pad', net='USB', properties={'NetName': 'USB'})
        self.assertIsNone(scope_preview(w, 0, [item])[0][1])
        w.document.rules[0].enabled = False
        self.assertIs(False, scope_preview(w, 0, [item])[0][1])

    def test_scope_respects_layer_clause(self):
        w = Workspace(); w.document.append(Rule('front', layer='F.Cu'))
        item = Item('1', 'Track', layers=('B.Cu',))
        self.assertIs(False, scope_preview(w, 0, [item])[0][1])

    def fixture(self, folder):
        for source in (PLUGIN / 'examples/workflow_demo').glob('*'):
            if source.is_file(): shutil.copy2(source, folder / source.name)
        return folder / 'workflow_demo.kicad_pcb'

    def test_export_apply_guards_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw); board = self.fixture(folder)
            w = Workspace.load(board)
            originals = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
            stage_protocol_rules(w, generate_rules([Assignment('USB2', 'USB_D+', 'user')]))
            self.assertIn('.kicad_dru', overview(w)['changed'])
            bundle = w.export_bundle(folder / 'review')
            for path, original in originals.items(): self.assertEqual(original, path.read_bytes())
            with self.assertRaises(RuntimeError): apply_bundle(bundle)
            rules = board.with_suffix('.kicad_dru'); rules.write_text('(version 1)\n# external edit\n', encoding='utf-8')
            with self.assertRaises(RuntimeError): apply_bundle(bundle, project_closed=True)
            self.assertIn('external edit', rules.read_text())
            self.assertTrue((bundle / '_apply/constraint_studio/LICENSE').exists())

    def test_packaged_engine_help_and_no_legacy_action(self):
        with tempfile.TemporaryDirectory() as raw:
            archive, _ = create_plugin_zip(PLUGIN, '3.1.1', Path(raw), {})
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                for suffix in ['studio_ui.py', 'studio_bridge.py', 'constraint_studio/ui.py',
                               'constraint_studio/help/topics.json', 'constraint_studio/LICENSE', 'SOURCE_PROVENANCE.json',
                               'docs/USER_GUIDE.md', 'examples/workflow_demo/workflow_demo.kicad_pcb']:
                    self.assertIn('plugins/' + suffix, names)
                self.assertNotIn('plugins/constraint_studio/action.py', names)


if __name__ == '__main__': unittest.main()
