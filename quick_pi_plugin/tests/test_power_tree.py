"""Power intent keeps evidence, signed rails and galvanic boundaries explicit."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import importlib.util

from quick_pi_plugin.power_tree import (empty_tree, infer_power_tree, load_power_tree,
                                       new_edge, new_node, save_power_tree,
                                       validate_power_tree)
from quick_pi_plugin.power_tree_ui import diagram_positions


def example(kind='isolated_dcdc', negative=False):
    tree = empty_tree({'source_sha256': 'saved-board-hash'})
    for key, role in [('input', 'source'), ('primary', 'rail'), ('regulator', kind),
                      ('secondary', 'rail'), ('device', 'load')]:
        node = new_node(key, role); node['reviewed'] = True
        if role == 'rail':
            node.update(net='VIN' if key == 'primary' else 'VOUT',
                        return_net='PGND' if key == 'primary' or kind != 'isolated_dcdc' else 'SGND',
                        domain='primary' if key == 'primary' or kind != 'isolated_dcdc' else 'secondary',
                        voltage_v=(-12 if key == 'primary' else -5) if negative else (12 if key == 'primary' else 5))
        tree['nodes'].append(node)
    for start, end in [('input', 'primary'), ('primary', 'regulator'),
                       ('regulator', 'secondary'), ('secondary', 'device')]:
        edge = new_edge(start, end); edge['reviewed'] = True; tree['edges'].append(edge)
    return tree


class PowerTreeTests(unittest.TestCase):
    def test_isolated_stage_keeps_distinct_references_and_no_resistor(self):
        tree = validate_power_tree(example(), require_reviewed=True)
        self.assertEqual(tree['nodes'][1]['return_net'], 'PGND')
        self.assertEqual(tree['nodes'][3]['return_net'], 'SGND')
        self.assertNotIn('resistance_ohm', str(tree))
        tree['nodes'][1]['return_net'] = 'changed'
        self.assertEqual(example()['nodes'][1]['return_net'], 'PGND')

    def test_isolation_cannot_be_shortened_by_domain_or_shared_net(self):
        for change in [{'return_net': 'PGND'}, {'domain': 'primary'}, {'net': 'VIN'}]:
            tree = example(); tree['nodes'][3].update(change)
            with self.assertRaisesRegex(ValueError, 'isolation|isolated|separate'):
                validate_power_tree(tree, require_reviewed=True)
        tree = example('dcdc'); tree['nodes'][3]['domain'] = 'secondary'
        with self.assertRaisesRegex(ValueError, 'separate isolation|non-isolated'):
            validate_power_tree(tree)

    def test_duplicate_physical_rail_cannot_hide_different_voltage_or_another_feed(self):
        tree=example()
        duplicate=deepcopy(tree['nodes'][3]);duplicate.update(id='other-rail',voltage_v=1000.)
        tree['nodes'].append(duplicate)
        with self.assertRaisesRegex(ValueError,'one rail node per physical net'):
            validate_power_tree(tree)

    def test_negative_ldo_voltage_is_preserved_signed(self):
        tree = validate_power_tree(example('ldo', negative=True), require_reviewed=True)
        self.assertEqual([node['voltage_v'] for node in tree['nodes'] if node['kind'] == 'rail'], [-12, -5])
        tree['nodes'][3]['voltage_v'] = 5
        self.assertEqual(validate_power_tree(tree)['nodes'][3]['voltage_v'], 5)
        # Intent accepts an explicit inverting DC/DC; it makes no regulator capability claim.

    def test_drafts_never_become_reviewed_by_validation(self):
        tree = empty_tree(); tree['nodes'].append(new_node('candidate'))
        self.assertFalse(validate_power_tree(tree)['nodes'][0]['reviewed'])
        with self.assertRaisesRegex(ValueError, 'review'):
            validate_power_tree(tree, require_reviewed=True)
        tree['nodes'][0]['reviewed'] = True
        with self.assertRaisesRegex(ValueError, 'net'):
            validate_power_tree(tree, require_reviewed=True)
        with self.assertRaises(ValueError): validate_power_tree(empty_tree(), require_reviewed=True)

    def test_rejects_wrong_edges_cycles_multiple_supplies_and_unknown_fields(self):
        tree = example(); tree['edges'].append(new_edge('primary', 'secondary'))
        with self.assertRaisesRegex(ValueError, 'alternate'): validate_power_tree(tree)
        tree = example(); tree['edges'].append(new_edge('secondary', 'regulator'))
        with self.assertRaisesRegex(ValueError, 'acyclic'): validate_power_tree(tree)
        tree = example(); tree['nodes'].append(new_node('other', 'source'))
        tree['edges'].append(new_edge('other', 'primary'))
        with self.assertRaisesRegex(ValueError, 'multiple feeds'): validate_power_tree(tree)
        tree = example(); tree['nodes'][2]['resistance_ohm'] = 0
        with self.assertRaisesRegex(ValueError, 'Unknown'): validate_power_tree(tree)

    def test_finite_values_boolean_review_and_budgets(self):
        for voltage in [True, float('inf'), float('nan'), '5']:
            tree = example(); tree['nodes'][1]['voltage_v'] = voltage
            with self.assertRaises(ValueError): validate_power_tree(tree)
        tree = example(); tree['nodes'][0]['reviewed'] = 'yes'
        with self.assertRaisesRegex(ValueError, 'true or false'): validate_power_tree(tree)
        tree = empty_tree(); tree['nodes'] = [new_node(str(n)) for n in range(257)]
        with self.assertRaisesRegex(ValueError, '256'): validate_power_tree(tree)

    def test_round_trip_and_changed_board_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'power-tree.json'
            save_power_tree(path, example(), require_reviewed=True)
            self.assertEqual(load_power_tree(path, require_reviewed=True), example())
            with self.assertRaisesRegex(ValueError, 'changed'):
                load_power_tree(path, inventory={'source_sha256': 'new-hash'})
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'UTF-8'): load_power_tree(path)

    def test_existing_net_and_footprint_identity_are_revalidated(self):
        tree = example(); tree['nodes'][2]['footprint_uuid'] = 'converter'
        inventory = {'nets': ['VIN', 'VOUT', 'PGND', 'SGND'],
                     'terminals': [{'footprint_uuid': 'converter'}]}
        validate_power_tree(tree, inventory=inventory)
        inventory['terminals'] = []
        with self.assertRaisesRegex(ValueError, 'footprint'): validate_power_tree(tree, inventory=inventory)

    def test_save_protects_sources_and_existing_file_on_failed_publication(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            board = Path(folder) / 'board.kicad_pcb'; board.write_text('board bytes', encoding='utf-8')
            tree = example(); tree['source']['board_path'] = str(board)
            with self.assertRaisesRegex(ValueError, '.json'): save_power_tree(board, tree)
            source_json = Path(folder) / 'input.json'; source_json.write_text('unique input', encoding='utf-8')
            tree['source']['source_path'] = str(source_json)
            with self.assertRaisesRegex(ValueError, 'overwrite'): save_power_tree(source_json, tree)
            output = Path(folder) / 'tree.json'; output.write_text('existing tree', encoding='utf-8')
            with patch('wayricad_runtime.report_ui.os.replace', side_effect=OSError('test failure')):
                with self.assertRaises(OSError): save_power_tree(output, tree)
            self.assertEqual(output.read_text(encoding='utf-8'), 'existing tree')
            self.assertEqual(board.read_text(encoding='utf-8'), 'board bytes')

    def test_inference_does_not_model_generic_ics_mosfets_or_resistors(self):
        rows = [{'id': '1', 'reference': ref, 'footprint_uuid': ref,
                 'net': net, 'component_value': value}
                for ref, value, net in [('U1', 'STM32', 'VDD'), ('Q1', 'MOSFET', 'SW'),
                                        ('R1', '10k', 'FB'), ('U2', 'LM1234', '-5V')]]
        original = deepcopy(rows)
        tree = infer_power_tree({'terminals': rows})
        self.assertEqual({node['net'] for node in tree['nodes']}, {'VDD', '-5V'})
        self.assertEqual(tree['edges'], [])
        self.assertTrue(all(node['voltage_v'] is None and not node['return_net'] and not node['reviewed'] for node in tree['nodes']))
        self.assertEqual(rows, original)

    def test_clear_value_is_candidate_but_connectivity_alone_is_not_role(self):
        rows = [dict(id='p' + str(i), reference='U1', footprint_uuid='u1', net=net,
                     component_value='Isolated DC/DC converter')
                for i, net in enumerate(['VIN', 'PGND', 'VOUT', 'SGND'])]
        tree = infer_power_tree({'terminals': rows})
        converter = next(node for node in tree['nodes'] if node['kind'] != 'rail')
        self.assertEqual(converter['kind'], 'isolated_dcdc')
        self.assertEqual(converter['confidence'], 'candidate')
        self.assertEqual(tree['edges'], [])

    def test_explicit_metadata_net_pairs_are_verified_and_remain_unreviewed(self):
        props = {'QuickPI:Role': 'isolated_dcdc', 'QuickPI:InputNet': 'VIN',
                 'QuickPI:InputReturn': 'PGND', 'QuickPI:InputDomain': 'primary',
                 'QuickPI:OutputNet': 'VOUT', 'QuickPI:OutputReturn': 'SGND',
                 'QuickPI:OutputDomain': 'secondary'}
        rows = [dict(id=str(i), reference='U1', footprint_uuid='u1', net=net,
                     component_properties=props)
                for i, net in enumerate(['VIN', 'PGND', 'VOUT', 'SGND'])]
        tree = infer_power_tree({'terminals': rows})
        self.assertEqual(len(tree['edges']), 2)
        self.assertTrue(all(not edge['reviewed'] for edge in tree['edges']))
        self.assertTrue(all(not node['reviewed'] for node in tree['nodes']))
        props['QuickPI:OutputReturn'] = 'INVENTED'
        self.assertEqual(len(infer_power_tree({'terminals': rows})['edges']), 1)
        props['QuickPI:OutputReturn'] = 'PGND'
        contradictory = infer_power_tree({'terminals': rows})
        self.assertEqual(len(contradictory['edges']), 1)
        self.assertIn('Rejected output metadata connection', contradictory['nodes'][0]['evidence'][-1])

    def test_layout_places_energy_downstream_and_keeps_disconnected_candidates(self):
        tree = example(); tree['nodes'].append(new_node('candidate'))
        positions = diagram_positions(tree)
        self.assertEqual(len(positions), 6)
        for edge in tree['edges']:
            self.assertLess(positions[edge['source']][0], positions[edge['target']][0])


@unittest.skipUnless(importlib.util.find_spec('wx'), 'Native wxPython runtime required')
class NativePowerTreeTests(unittest.TestCase):
    def test_native_editor_retains_negative_reference_and_reviews_edges(self):
        import wx
        from quick_pi_plugin.power_tree_ui import PowerTreeDialog
        app = wx.GetApp() or wx.App(False); parent = wx.Frame(None)
        inventory = {'nets': ['VIN', 'VOUT', 'PGND', 'SGND'], 'terminals': []}
        editor = PowerTreeDialog(parent, inventory, existing=example())
        try:
            editor.dialog.Show(); app.Yield()
            editor.selected = 'secondary'; editor._show_node()
            editor.fields['voltage_v'].SetValue('-5'); editor.reviewed.SetValue(True)
            self.assertTrue(editor._apply())
            result = editor._validate()
            self.assertEqual(result['nodes'][3]['voltage_v'], -5)
            self.assertEqual(result['nodes'][3]['return_net'], 'SGND')
            editor.edge_list.SetSelection(0); editor.edge_reviewed.SetValue(False); editor._review_edge()
            self.assertIsNone(editor._validate())
            self.assertIn('review this connection', editor.status.GetLabel())
            editor.edge_list.SetSelection(0); editor.edge_reviewed.SetValue(True); editor._review_edge()
            self.assertIsNotNone(editor._validate())
            editor.canvas.Refresh(); app.Yield()
        finally:
            editor.dialog.Destroy(); parent.Destroy(); app.Yield()


if __name__ == '__main__':
    unittest.main()
