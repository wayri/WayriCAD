"""Evidence boundaries for read-only comment-context classification."""
from copy import deepcopy
import unittest

from review_comments_plugin.context_status import classify_context, propose_status_event


class ContextStatusTests(unittest.TestCase):
    def setUp(self):
        self.target = dict(repository='example/design', ref='a' * 40,
                           file='board.kicad_pcb', uuid='object-one', reference='R1')
        self.inventory = dict(scope=dict(repository='example/design', ref='a' * 40),
                              verified=True, complete=True, files={
                                  'board.kicad_pcb': dict(sha256='1' * 64, objectIds=['object-one'],
                                                        fieldsByObject={'object-one': ['Value', 'MPN']},
                                                        variants=['production'])})

    def classify(self, **kwargs):
        return classify_context(self.target, self.inventory, **kwargs)

    def test_current_preserves_original_and_does_not_mutate_inputs(self):
        self.target['position'] = {'x': 1, 'y': 2}
        before = deepcopy((self.target, self.inventory))
        outcome = self.classify()
        self.assertEqual((outcome['status'], outcome['reason']), ('current', 'identity-present'))
        self.assertEqual(outcome['anchor'], self.target)
        outcome['anchor']['position']['x'] = 9
        self.assertEqual((self.target, self.inventory), before)

    def test_older_revision_is_not_an_orphan_or_automatic_migration(self):
        self.inventory['scope']['ref'] = 'b' * 40
        outcome = self.classify()
        self.assertEqual(outcome['status'], 'older-revision')
        self.assertEqual(outcome['anchor']['ref'], 'a' * 40)
        self.assertEqual(outcome['checkedScope']['ref'], 'b' * 40)

    def test_changed_requires_two_verified_exact_revision_digests(self):
        original = deepcopy(self.inventory)
        self.inventory['scope']['ref'] = 'b' * 40
        self.inventory['files']['board.kicad_pcb']['sha256'] = '2' * 64
        self.assertEqual(self.classify(original_inventory=original)['status'], 'changed')
        original['scope']['ref'] = 'c' * 40
        self.assertEqual(self.classify(original_inventory=original)['status'], 'older-revision')
        original['scope']['ref'] = 'a' * 40
        original['verified'] = False
        self.assertEqual(self.classify(original_inventory=original)['status'], 'older-revision')

    def test_working_tree_change_at_same_head_uses_commit_baseline(self):
        original = deepcopy(self.inventory)
        self.inventory['files']['board.kicad_pcb']['sha256'] = '2' * 64
        self.assertEqual(self.classify(original_inventory=original)['status'], 'changed')

    def test_proven_missing_file_and_object_are_distinct(self):
        self.inventory['files']['board.kicad_pcb']['objectIds'] = []
        self.assertEqual(self.classify()['reason'], 'missing-object')
        self.inventory['files'] = {}
        outcome = self.classify()
        self.assertEqual((outcome['status'], outcome['reason']), ('orphan', 'missing-file'))

    def test_read_failures_and_incomplete_results_never_prove_deletion(self):
        for failure in (None, {}, {'error': 'Permission denied'},
                        dict(self.inventory, files={}, verified=False),
                        dict(self.inventory, files={}, complete=False),
                        dict(self.inventory, files={}, complete=1),
                        dict(self.inventory, files=None)):
            with self.subTest(failure=failure):
                result = classify_context(self.target, failure)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(propose_status_event(result, '123'))

    def test_provider_host_and_repository_isolation(self):
        for change in ({'repository': 'other/design'}, {'provider': 'gitlab', 'host': 'https://gitlab.com'}):
            with self.subTest(change=change):
                selected = deepcopy(self.inventory)
                selected['scope'].update(change)
                selected['files'] = {}
                self.assertEqual(classify_context(self.target, selected)['status'], 'unavailable')
        self.target.update(provider='gitlab', host='https://gitlab.one')
        self.inventory['scope'].update(provider='gitlab', host='https://gitlab.two')
        self.assertEqual(self.classify()['reason'], 'different-repository')

    def test_missing_identity_collection_is_unknown_not_missing(self):
        del self.inventory['files']['board.kicad_pcb']['objectIds']
        self.assertEqual(self.classify()['reason'], 'object-inventory-unavailable')

    def test_duplicate_and_conflicting_object_ids_are_ambiguous(self):
        self.inventory['files']['board.kicad_pcb']['objectIds'] *= 2
        outcome = self.classify()
        self.assertEqual(outcome['status'], 'ambiguous')
        self.assertIsNone(propose_status_event(outcome, '123'))
        self.target['objectId'] = 'different-object'
        self.assertEqual(self.classify()['reason'], 'conflicting-object-identities')

    def test_reference_never_substitutes_for_stable_identity(self):
        del self.target['uuid']
        self.inventory['files']['board.kicad_pcb']['references'] = {'R1': ['object-one']}
        self.assertEqual(self.classify()['reason'], 'stable-object-identity-required')

    def test_variant_missing_unknown_and_duplicate(self):
        self.target['variant'] = 'prototype'
        record = self.inventory['files']['board.kicad_pcb']
        self.assertEqual(self.classify()['reason'], 'missing-variant')
        del record['variants']
        self.assertEqual(self.classify()['reason'], 'variant-inventory-unavailable')
        record['variants'] = ['prototype', 'prototype']
        self.assertEqual(self.classify()['status'], 'ambiguous')

    def test_bom_field_missing_is_not_inferred_from_an_unread_object(self):
        self.target.update(kind='bom', field='Tolerance')
        record = self.inventory['files']['board.kicad_pcb']
        self.assertEqual(self.classify()['reason'], 'missing-field')
        record['fieldsByObject'] = {}
        self.assertEqual(self.classify()['reason'], 'field-inventory-unavailable')
        record['fieldsByObject'] = {'object-one': {'Tolerance': '5%'}}
        self.assertEqual(self.classify()['status'], 'current')
        record['fieldsByObject']['object-one'] = ['Tolerance', 'Tolerance']
        self.assertEqual(self.classify()['status'], 'ambiguous')

    def test_field_key_extension_and_non_kicad_inventory_path(self):
        self.target.update(file='manufacturing/bom.csv', kind='bom', bomField='MPN')
        self.inventory['files'][self.target['file']] = self.inventory['files'].pop('board.kicad_pcb')
        self.assertEqual(self.classify(field_key='bomField')['status'], 'current')
        target = dict(repository='example/design', ref='a' * 40, file='output/top.gbr', kind='gerber')
        self.inventory['files']['output/top.gbr'] = {}
        self.assertEqual(classify_context(target, self.inventory)['status'], 'current')

    def test_invalid_paths_and_mutable_refs_are_unavailable(self):
        for path in ('../board.kicad_pcb', '/board.kicad_pcb', 'dir/../board.kicad_pcb',
                     'C:/private/board.kicad_pcb', 'dir\\board.kicad_pcb'):
            with self.subTest(path=path):
                self.assertEqual(classify_context(dict(self.target, file=path), self.inventory)['status'], 'unavailable')
        self.inventory['scope']['ref'] = 'main'
        self.assertEqual(self.classify()['status'], 'unavailable')

    def test_status_proposal_is_deterministic_and_keeps_original_anchor(self):
        self.inventory['files'] = {}
        result = self.classify()
        event = propose_status_event(result, '123')
        self.assertEqual(event, propose_status_event(deepcopy(result), '123'))
        self.assertEqual(len(event['eventId']), 64)
        self.assertEqual(event['anchor'], self.target)
        self.assertNotEqual(event['eventId'], propose_status_event(result, '456')['eventId'])
        self.inventory['scope']['ref'] = 'b' * 40
        self.assertNotEqual(event['eventId'], propose_status_event(self.classify(), '123')['eventId'])
        self.assertNotIn('createdAt', event)

    def test_gerber_context_uses_artifact_identity_and_hash_not_origin_uuid(self):
        self.target['context'] = dict(type='gerber', file='output/top.gbr', sha256='3' * 64)
        self.inventory['files']['output/top.gbr'] = dict(sha256='3' * 64)
        outcome = self.classify()
        self.assertEqual(outcome['status'], 'current')
        self.assertEqual(outcome['anchor']['file'], 'board.kicad_pcb')
        self.assertEqual(outcome['evidence']['file'], 'output/top.gbr')
        self.inventory['files']['output/top.gbr']['sha256'] = '4' * 64
        self.assertEqual(self.classify()['status'], 'changed')
        del self.inventory['files']['output/top.gbr']['sha256']
        self.assertEqual(self.classify()['reason'], 'source-digest-unavailable')
        del self.inventory['files']['output/top.gbr']
        self.assertEqual(self.classify()['reason'], 'missing-file')

    def test_bom_context_requires_its_own_successful_complete_extraction(self):
        self.target['context'] = dict(type='bom', rowId='row-1', field='MPN',
                                     sourceFiles={'board.kicad_pcb': '1' * 64})
        record = self.inventory['files']['board.kicad_pcb']
        self.assertEqual(self.classify()['reason'], 'bom-inventory-unavailable')
        record['bomComplete'] = True
        self.assertEqual(self.classify()['reason'], 'missing-object')
        record['objectIds'].append('row-1')
        self.assertEqual(self.classify()['reason'], 'field-inventory-unavailable')
        record['fieldsByObject']['row-1'] = ['MPN']
        self.assertEqual(self.classify()['status'], 'current')
        record['fieldsByObject']['row-1'] = []
        self.assertEqual(self.classify()['reason'], 'missing-field')

    def test_bom_provenance_missing_changed_and_unread_sources(self):
        self.target['context'] = dict(type='bom', rowId='row-1', sourceFiles={
            'board.kicad_pcb': '1' * 64, 'symbols.kicad_sch': '2' * 64})
        record = self.inventory['files']['board.kicad_pcb']
        record.update(bomComplete=True, objectIds=['row-1'])
        self.assertEqual(self.classify()['reason'], 'missing-source-file')
        self.inventory['files']['symbols.kicad_sch'] = {}
        self.assertEqual(self.classify()['status'], 'unavailable')
        self.inventory['files']['symbols.kicad_sch']['sha256'] = '3' * 64
        self.assertEqual(self.classify()['status'], 'changed')
        self.inventory['files']['symbols.kicad_sch']['sha256'] = '2' * 64
        self.assertEqual(self.classify()['status'], 'current')

    def test_all_variants_is_not_a_named_variant_and_project_inventory_is_authority(self):
        self.target['variant'] = '*'
        del self.inventory['files']['board.kicad_pcb']['variants']
        self.assertEqual(self.classify()['status'], 'current')
        self.target['variant'] = 'prototype'
        self.inventory['variants'] = ['prototype']
        self.assertEqual(self.classify()['status'], 'current')
        self.inventory['files']['board.kicad_pcb']['variants'] = ['prototype']
        self.inventory['variants'] = []
        self.assertEqual(self.classify()['reason'], 'missing-variant')

    def test_malformed_context_and_source_provenance_are_unavailable(self):
        for context in ([], {'type': 'other'}, {'type': 'bom', 'rowId': 'row-1'},
                        {'type': 'gerber', 'file': '../outside.gbr', 'sha256': '3' * 64},
                        {'type': 'gerber', 'file': 'output/top.gbr', 'sha256': 'not-a-hash'},
                        {'type': 'bom', 'rowId': 'row-1', 'sourceFiles': {'/private/file': '1' * 64}}):
            with self.subTest(context=context):
                self.target['context'] = context
                self.assertEqual(self.classify()['status'], 'unavailable')

    def test_transition_predecessor_distinguishes_repeated_orphan_after_recovery(self):
        current = self.classify()
        self.inventory['files'] = {}
        orphan = self.classify()
        first = propose_status_event(orphan, '123')
        restored = propose_status_event(current, '123', previous_event_id=first['eventId'])
        repeated = propose_status_event(orphan, '123', previous_event_id=restored['eventId'])
        self.assertNotEqual(first['eventId'], repeated['eventId'])
        self.assertEqual(repeated, propose_status_event(orphan, '123', previous_event_id=restored['eventId']))

    def test_bounded_path_inventory_does_not_claim_whole_repository_deletion(self):
        self.inventory.update(files={}, knownPaths=['other.kicad_pcb'])
        self.assertEqual(self.classify()['reason'], 'path-inventory-unavailable')
        self.inventory['knownPaths'].append(self.target['file'])
        self.assertEqual(self.classify()['reason'], 'missing-file')

    def test_missing_known_bom_source_precedes_incomplete_bom_extraction(self):
        self.target['context'] = dict(type='bom', rowId='row-1', sourceFiles={
            'board.kicad_pcb': '1' * 64, 'child.kicad_sch': '2' * 64})
        self.inventory['knownPaths'] = ['board.kicad_pcb']
        self.assertEqual(self.classify()['status'], 'unavailable')
        self.inventory['knownPaths'].append('child.kicad_sch')
        self.assertEqual(self.classify()['reason'], 'missing-source-file')
        self.inventory['complete'] = False
        self.assertEqual(self.classify()['status'], 'unavailable')

    def test_long_bom_field_names_match_the_context_wire_limit(self):
        name = 'Field' * 60
        self.target.update(context=dict(type='bom', rowId='row-1', field=name,
                                       sourceFiles={'board.kicad_pcb': '1' * 64}))
        self.inventory['files']['board.kicad_pcb'].update(
            bomComplete=True, objectIds=['row-1'], fieldsByObject={'row-1': [name]})
        self.assertEqual(self.classify()['status'], 'current')

    def test_inventory_provenance_is_validated_and_preserved_in_evidence(self):
        self.inventory['files'] = {}
        for provenance in ('working-tree', 'git-commit'):
            with self.subTest(provenance=provenance):
                self.inventory['provenance'] = provenance
                result = self.classify()
                self.assertEqual(result['status'], 'orphan')
                self.assertEqual(result['evidence']['provenance'], provenance)
                self.assertEqual(result['anchor'], self.target)
                self.assertEqual(propose_status_event(result, '123')['evidence']['provenance'], provenance)
        self.inventory['provenance'] = 'unverified-or-private-diagnostic'
        result = self.classify()
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('provenance', result['evidence'])
        self.assertIsNone(propose_status_event(result, '123'))


if __name__ == '__main__':
    unittest.main()
