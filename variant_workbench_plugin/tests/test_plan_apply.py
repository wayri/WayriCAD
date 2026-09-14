"""Semantic safety regressions for named variant edits."""
import json
from pathlib import Path
import tempfile
import unittest

from variant_workbench_plugin import kicad_variant_manager as v


SCHEMATIC = '''(kicad_sch (version 20260306) (uuid "root")
 (symbol (uuid "resistor") (property "Reference" "R1")
  (property "Value" "10k") (in_bom yes) (on_board yes) (dnp no)
  (instances
   (project "fixture"
    (path "/root" (reference "R1") (unit 1)
    )
   )
  )
 )
)
'''


class PlanApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'fixture.kicad_sch'
        self.root.write_text(SCHEMATIC, encoding='utf-8')
        self.project = self.root.with_suffix('.kicad_pro')
        self.project.write_text(json.dumps({'schematic': {'variants': []}}), encoding='utf-8')
        v.apply_plan(v.plan_duplicate_variant(self.root, v.DEFAULT_VARIANT, 'Assembly'))
        self.patch = v.VariantPatch(str(self.root), 'resistor', '/root', 'Assembly',
                                   dnp=True, field_updates={'Value': '22k'})

    def test_preview_apply_preserves_default_and_creates_restorable_backup(self):
        original = self.root.read_bytes()
        plan = v.plan_patch_variants(self.root, [self.patch])
        self.assertEqual(self.root.read_bytes(), original)
        backups = v.apply_plan(plan)
        self.assertEqual(backups[0].read_bytes(), original)
        rows, _ = v.collect_matrix_rows(self.root)
        self.assertEqual(rows[0].base.fields['Value'], '10k')
        self.assertFalse(rows[0].base.dnp)
        self.assertEqual(rows[0].states['Assembly'].fields['Value'], '22k')
        self.assertTrue(rows[0].states['Assembly'].dnp)

    def test_stale_plan_does_not_overwrite_new_input(self):
        plan = v.plan_patch_variants(self.root, [self.patch])
        edited = self.root.read_text(encoding='utf-8') + '\n'
        self.root.write_text(edited, encoding='utf-8')
        before = sorted(Path(self.tmp.name).iterdir())
        with self.assertRaisesRegex(v.VariantPromoterError, 'changed since preview'):
            v.apply_plan(plan)
        self.assertEqual(self.root.read_text(encoding='utf-8'), edited)
        self.assertEqual(sorted(Path(self.tmp.name).iterdir()), before)

    def test_patch_does_not_change_other_named_assembly(self):
        v.apply_plan(v.plan_duplicate_variant(self.root, 'Assembly', 'Other'))
        v.apply_plan(v.plan_patch_variants(self.root, [self.patch]))
        rows, _ = v.collect_matrix_rows(self.root)
        self.assertEqual(rows[0].states['Other'].signature(), rows[0].base.signature())


if __name__ == '__main__':
    unittest.main()
