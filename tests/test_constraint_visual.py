"""Functional contracts for the visual shell, independent of wx/WebView."""
import copy
from pathlib import Path
import unittest

from protocol_constraint_composer_plugin.constraint_studio.model import Rule, Constraint, RuleDocument
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace
from protocol_constraint_composer_plugin.studio_model import snapshot, mutation, inspect_scope, compile_matrix

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'protocol_constraint_composer_plugin/examples/workflow_demo/workflow_demo.kicad_pcb'


class VisualWorkbenchTests(unittest.TestCase):
    def setUp(self): self.w = Workspace.load(BOARD)

    def change(self, method, **data):
        return mutation(self.w, method, dict(data, revision=self.w.state()))

    def test_snapshot_exposes_full_vocabulary_and_real_items(self):
        data = snapshot(self.w)
        self.assertEqual(34, len(data['specs']))
        self.assertGreater(len(data['items']), 10)
        self.assertTrue(data['regions'])
        self.assertEqual(6, len(data['profiles']))

    def test_cell_edit_is_atomic_and_does_not_change_source(self):
        before = BOARD.with_suffix('.kicad_dru').read_bytes()
        staged = self.change('set_value', rule=0, constraint=0, field='min', value='0.3mm')
        self.assertEqual('0.3mm', staged.document.rules[0].constraints[0].values['min'])
        self.assertNotEqual(staged.state(), self.w.state())
        self.assertEqual(before, BOARD.with_suffix('.kicad_dru').read_bytes())

    def test_invalid_numeric_input_does_not_mutate_workspace(self):
        old = self.w.state()
        with self.assertRaises(ValueError): self.change('set_value', rule=0, constraint=0, field='min', value='bad')
        self.assertEqual(old, self.w.state())

    def test_stale_revision_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            mutation(self.w, 'toggle', {'index': 0, 'revision': 'old'})

    def test_rule_form_preserves_opaque_native_syntax(self):
        self.w.document = RuleDocument.load('(version 1)\n(rule "opaque" (condition "A.Type == \'Pad\'") (future_rule abc) (constraint clearance (min 0.2mm) (future_value 9)))')
        row = snapshot(self.w)['rules'][0]; row['name'] = 'Renamed'; row['constraints'][0]['index'] = 0
        staged = self.change('save_rule', index=0, rule=row)
        self.assertIn('(future_rule abc)', staged.document.emit())
        self.assertIn('(future_value 9)', staged.document.emit())

    def test_all_numeric_constraint_forms_can_be_created(self):
        for spec in snapshot(self.w)['specs']:
            if not spec['fields']: continue
            value = '1' if spec['unit'] in ('ratio','count') else '45deg' if spec['unit']=='deg' else '0.2mm'
            row = {'name': spec['key'], 'constraints': [{'kind':spec['key'], 'values':{key:value for key in spec['fields']}}]}
            with self.subTest(spec=spec['key']):
                staged = self.change('save_rule', index=None, rule=row)
                self.assertEqual(spec['key'], staged.document.rules[-1].constraints[0].kind)

    def test_matrix_is_symmetric_and_replaces_only_named_group(self):
        data = dict(group='Signals', labels=['Default','HighSpeed'], cells=[{'i':0,'j':1,'value':'0.25mm'}], scope='netclass', kind='clearance')
        first = self.change('matrix', **data)
        second = mutation(first, 'matrix', dict(data, revision=first.state()))
        self.assertEqual(len(first.document.rules), len(second.document.rules))
        self.assertEqual(self.w.document.rules[0].state(), first.document.rules[0].state())
        data['cells'].append({'i':1,'j':0,'value':'0.3mm'})
        with self.assertRaisesRegex(ValueError, 'Asymmetric'): compile_matrix(data)

    def test_profile_installs_and_protects_manual_edits(self):
        data = dict(id='routing.netclass', instance='USB routing', bindings={'netclass':'Default','width':'0.2mm','via':'0.6mm','drill':'0.3mm'})
        first = self.change('profile', **data)
        self.assertIn('USB routing', first.metadata['profile_instances'])
        first.document.rules[-1].name = 'Manual edit'
        with self.assertRaisesRegex(ValueError, 'edited manually'):
            mutation(first,'profile',dict(data,revision=first.state()))

    def test_netclass_inherit_and_unknown_fields_are_preserved(self):
        self.w.project['net_settings']['classes'][0]['custom'] = 'preserve'
        staged = self.change('netclass', index=0, key='clearance', value='')
        self.assertIsNone(staged.project['net_settings']['classes'][0]['clearance'])
        self.assertEqual('preserve', staged.project['net_settings']['classes'][0]['custom'])
        with self.assertRaises(ValueError): self.change('netclass', index=0, key='clearance', value='nan')

    def test_pair_inspection_requires_both_objects(self):
        self.w.document.append(Rule('pair', "A.Type == 'Pad' && B.Type == 'Pad'", constraints=[Constraint('clearance',{'min':'0.2mm'})]))
        item = next(i['index'] for i in snapshot(self.w)['items'] if i['kind']=='Pad')
        result = inspect_scope(self.w,dict(rule=len(self.w.document.rules)-1,a=item,kind='clearance'))
        self.assertIsNone(result['trace']['rows'][0]['match'])
        result = inspect_scope(self.w,dict(rule=len(self.w.document.rules)-1,a=item,b=item,kind='clearance'))
        self.assertIs(True,result['trace']['rows'][0]['match'])

    def test_unknown_commands_and_invalid_indices_are_rejected(self):
        for method,data in [('delete',{'index':-1}),('toggle',{'index':True}),('anything',{})]:
            with self.assertRaises(ValueError): self.change(method,**data)


if __name__ == '__main__': unittest.main()
