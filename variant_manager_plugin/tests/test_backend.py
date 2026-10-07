import json
from pathlib import Path
import tempfile
import unittest
from variant_manager_plugin.wayri_variants import service as S

SCHEMATIC = '''(kicad_sch (version 20260306) (generator eeschema) (generator_version "10.0")
(uuid "11111111-1111-1111-1111-111111111111")
(unknown_future "preserve me")
(symbol (uuid "22222222-2222-2222-2222-222222222222")
(property "Reference" "R1") (property "Value" "10k")
(in_bom yes) (on_board yes) (dnp no) (in_pos_files yes)
(instances (project "board" (path "/11111111-1111-1111-1111-111111111111"
(reference "R1") (unit 1)
(variant (name "A") (field (name "Value") (value "20k")))
(variant (name "B") (field (name "Value") (value "30k"))))))))
'''

class VariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'board.kicad_sch'
        self.root.write_text(SCHEMATIC)
        self.root.with_suffix('.kicad_pro').write_text(json.dumps({'schematic': {'variants': [{'name':'A'}, {'name':'B'}]}}))
        self.root.with_suffix('.kicad_pcb').write_bytes(b'(kicad_pcb (version 20260306) (generator pcbnew))')
        self.key = S.inventory(self.root)['objects'][0]['key']

    def test_batch_and_backup_restore(self):
        original = self.root.read_bytes()
        plan = S.preview(self.root, [{'op':'duplicate','source':'A','name':'C'},
            {'op':'edit','variant':'C','keys':[self.key],'fields':{'Value':'40k'},'flags':{'dnp':True}},
            {'op':'rename','source':'B','name':'Production'},
            {'op':'swap','left':'A','right':'C'}, {'op':'delete','variants':['Production']}])
        self.assertEqual(original, self.root.read_bytes())
        self.assertTrue(plan.rows)
        backup = S.apply(plan, editors_closed=True)
        states = S.inventory(self.root)['objects'][0]['states']
        self.assertEqual(states['A']['fields']['Value'], '40k')
        self.assertTrue(states['A']['dnp'])
        self.assertIn('(unknown_future "preserve me")',self.root.read_text())
        self.assertEqual(b'(kicad_pcb (version 20260306) (generator pcbnew))',self.root.with_suffix('.kicad_pcb').read_bytes())
        restore = S.plan_restore_sources(self.root, backup)
        S.apply(restore, editors_closed=True)
        self.assertEqual(original,self.root.read_bytes())

    def test_merge_conflict(self):
        with self.assertRaisesRegex(S.Error,'Merge conflicts'):
            S.preview(self.root,[{'op':'merge','source':'A','target':'B'}])
        plan = S.preview(self.root,[{'op':'merge','source':'A','target':'B','policy':'source'}])
        S.apply(plan,editors_closed=True)
        self.assertEqual(S.inventory(self.root)['objects'][0]['states']['B']['fields']['Value'],'20k')

    def test_promote_preserves_old_and_inheritance(self):
        plan = S.preview(self.root,[{'op':'promote','source':'A','preserve_old':'Original'}])
        S.apply(plan,editors_closed=True)
        states = S.inventory(self.root)['objects'][0]['states']
        self.assertEqual(states[S.DEFAULT]['fields']['Value'],'20k')
        self.assertEqual(states['Original']['fields']['Value'],'10k')
        self.assertEqual(states['B']['fields']['Value'],'30k')

    def test_stale_and_locks(self):
        plan = S.preview(self.root,[{'op':'create','name':'C'}])
        self.root.write_text(SCHEMATIC+'\n')
        with self.assertRaisesRegex(S.Error,'stale'):
            S.apply(plan,editors_closed=True)
        self.root.write_text(SCHEMATIC)
        (self.root.parent/('~'+self.root.name+'.lck')).touch()
        with self.assertRaisesRegex(S.Error,'lock'):
            S.apply(plan,editors_closed=True)

    def test_reviewed_candidate_cannot_change_after_preview(self):
        plan=S.preview(self.root,[{'op':'create','name':'C'}])
        name=next(iter(plan.writes))
        plan.writes[name]+=b'\n'
        with self.assertRaisesRegex(S.Error,'changed in memory'):
            S.apply(plan,editors_closed=True)
        self.assertEqual(self.root.read_text(),SCHEMATIC)

    def test_identity_edit_rejected(self):
        with self.assertRaisesRegex(S.Error,'Identity'):
            S.preview(self.root,[{'op':'edit','variant':'A','keys':[self.key],'fields':{'Reference':'R2'}}])

    def test_reused_instances_keep_distinct_overrides(self):
        second = '(path "/11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333" (reference "R2") (unit 1) (variant (name "A") (field (name "Value") (value "33k"))))'
        tree = S.E.SExprParser(SCHEMATIC).parse()
        project = tree.child_node('symbol').child_node('instances').child_node('project')
        original = SCHEMATIC[:project.end-1] + second + SCHEMATIC[project.end-1:]
        self.root.write_text(original)
        inventory = S.inventory(self.root)
        self.assertEqual(len(inventory['objects']), 2)
        plan = S.preview(self.root, [{'op':'duplicate','source':'A','name':'C'}])
        S.apply(plan, editors_closed=True)
        self.assertEqual({row['states']['C']['fields']['Value'] for row in S.inventory(self.root)['objects']}, {'20k','33k'})
        with self.assertRaisesRegex(S.Error,'reused hierarchical instances'):
            S.preview(self.root, [{'op':'promote','source':'A'}])

    def test_missing_field_and_unknown_field_token(self):
        with self.assertRaisesRegex(S.Error,'does not exist in the base'):
            S.preview(self.root,[{'op':'edit','variant':'A','keys':[self.key],'fields':{'Missing':'invented'}}])
        self.root.write_text(SCHEMATIC.replace('(value "20k")','(value "20k") (future_geometry 1)'))
        with self.assertRaisesRegex(S.Error,'Unsupported variant field token'):
            S.preview(self.root,[{'op':'create','name':'C'}])

    def test_unknown_variant_token_rejected(self):
        self.root.write_text(SCHEMATIC.replace('(name "A")','(name "A") (future_flag yes)'))
        with self.assertRaisesRegex(S.Error,'Unsupported variant token'):
            S.preview(self.root,[{'op':'create','name':'C'}])

if __name__=='__main__': unittest.main()
