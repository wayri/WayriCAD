"""Automatic status writes require stable evidence and are never retried ambiguously."""
from copy import deepcopy
import unittest

from review_comments_plugin.context_status import classify_context
from review_comments_plugin.context_sync import (
    ContextTracker, make_status_event, parse_status_events, status_markdown,
)
from review_comments_plugin.model import markdown, note
from review_comments_plugin.providers import Provider as RealProvider


class Provider:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.posts = []
        self.reads = 0
        self.read_error = None
        self.write_error = None
        self.before_read = None

    def snapshot(self):
        self.reads += 1
        if self.read_error:
            raise self.read_error
        if self.before_read:
            self.before_read()
        return deepcopy(self.rows)

    def publish(self, body):
        self.posts.append(body)
        if self.write_error:
            raise self.write_error
        identifier = str(900 + len(self.posts))
        self.rows.append(dict(id=identifier, body=body, author='reviewer'))
        return identifier


class ContextSyncTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(repository='example/design', ref='a' * 40, file='board.kicad_pcb')
        self.target = dict(self.scope, uuid='u1')
        self.annotation = note('Check this part', self.target)
        self.annotation['id'] = 'annotation-1'
        self.rows = [dict(id='10', body=markdown(self.annotation), author='engineer')]
        self.inventory = dict(scope=self.scope, verified=True, complete=True,
                              knownPaths=['board.kicad_pcb'], files={
                                  'board.kicad_pcb': dict(sha256='1' * 64, objectIds=[])})
        self.provider = Provider(self.rows)
        self.provider.scope = deepcopy(self.scope)
        self.tracker = ContextTracker(inventory_builder=lambda *args: deepcopy(self.inventory))

    def update(self, rows=None, **options):
        return self.tracker.update(deepcopy(self.provider.rows if rows is None else rows),
                                   self.provider, '/unused', self.scope, **options)

    def test_two_observations_preflight_and_one_append_keep_original_unchanged(self):
        first = self.update()
        self.assertEqual(first[0]['contextStatus'][0]['status'], 'orphan')
        self.assertEqual(self.provider.posts, [])
        self.update()
        self.assertEqual(len(self.provider.posts), 1)
        self.assertEqual(self.provider.reads, 1)
        self.assertEqual(self.provider.rows[0], self.rows[0])
        self.assertNotIn('contextStatus', self.rows[0])
        self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_initial_current_and_older_revision_never_publish(self):
        self.inventory['files']['board.kicad_pcb']['objectIds'] = ['u1']
        for revision in ('a' * 40, 'b' * 40):
            self.inventory['scope'] = dict(self.scope, ref=revision)
            self.update()
            self.update()
        self.assertEqual(self.provider.posts, [])

    def test_unavailable_observation_breaks_consecutive_evidence(self):
        self.update()
        self.inventory['complete'] = False
        self.update()
        self.inventory['complete'] = True
        self.update()
        self.assertEqual(self.provider.posts, [])
        self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_read_only_setting_keeps_diagnostics_without_provider_preflight(self):
        self.update(auto_publish=False)
        outcome = self.update(auto_publish=False)
        self.assertEqual(outcome[0]['contextStatus'][0]['status'], 'orphan')
        self.assertEqual((self.provider.reads, self.provider.posts), (0, []))

    def test_deleted_original_at_preflight_is_not_updated(self):
        self.update()
        self.provider.before_read = lambda: self.provider.rows.clear()
        self.assertEqual(self.update(), [])
        self.assertEqual(self.provider.posts, [])

    def test_edited_anchor_at_preflight_is_not_updated(self):
        self.update()
        changed = deepcopy(self.annotation)
        changed['anchor']['uuid'] = 'u2'
        self.provider.before_read = lambda: self.provider.rows[0].update(body=markdown(changed))
        self.update()
        self.assertEqual(self.provider.posts, [])

    def test_source_change_during_preflight_is_not_published(self):
        self.update()
        self.provider.before_read = lambda: self.inventory['files']['board.kicad_pcb'].update(sha256='2' * 64)
        self.update()
        self.assertEqual(self.provider.posts, [])

    def test_fresh_remote_duplicate_prevents_second_client_append(self):
        self.update()
        classification = classify_context(self.target, self.inventory)
        event = make_status_event(classification, '10', 'annotation-1')
        self.provider.rows.append(dict(id='55', body=status_markdown(event)))
        self.update(rows=self.rows)
        self.assertEqual(self.provider.posts, [])

    def test_uncertain_publication_halts_even_if_later_snapshot_has_no_event(self):
        self.update()
        self.provider.write_error = TimeoutError('secret diagnostic')
        self.update()
        self.assertTrue(self.tracker.halted)
        self.assertNotIn('secret diagnostic', self.tracker.warning)
        self.provider.write_error = None
        for _ in range(3):
            self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_success_without_visible_readback_never_retries(self):
        self.update()
        self.update()
        self.provider.rows = deepcopy(self.rows)
        for _ in range(3):
            self.update()
        self.assertEqual(len(self.provider.posts), 1)
        self.assertIn('readback', self.tracker.warning)

    def test_preflight_read_failure_requires_new_stable_observations(self):
        self.update()
        self.provider.read_error = OSError('network unavailable')
        self.update()
        self.assertFalse(self.tracker.halted)
        self.provider.read_error = None
        self.update()
        self.assertEqual(self.provider.posts, [])
        self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_recovery_and_second_orphan_have_distinct_transition_ids(self):
        self.update()
        self.update()
        self.inventory['files']['board.kicad_pcb']['objectIds'] = ['u1']
        self.update()
        self.update()
        self.inventory['files']['board.kicad_pcb']['objectIds'] = []
        self.update()
        self.update()
        events = parse_status_events(self.provider.rows, self.scope)
        self.assertEqual([event['status'] for event in events], ['orphan', 'current', 'orphan'])
        self.assertEqual(len({event['eventId'] for event in events}), 3)
        self.assertEqual(events[2]['previousEventId'], events[1]['eventId'])

    def test_duplicate_annotation_identity_is_ambiguous(self):
        self.provider.rows.append(dict(self.rows[0], id='11'))
        result = self.update()
        self.update()
        self.assertTrue(all(row['contextStatus'][0]['status'] == 'ambiguous' for row in result))
        self.assertEqual(self.provider.posts, [])

    def test_older_revision_restoration_and_repeated_orphan_preserve_original_anchor(self):
        self.update()
        self.update()
        self.inventory['scope'] = dict(self.scope, ref='b' * 40)
        self.inventory['files']['board.kicad_pcb']['objectIds'] = ['u1']
        self.update()
        self.update()
        self.inventory['files']['board.kicad_pcb']['objectIds'] = []
        self.update()
        self.update()
        events = parse_status_events(self.provider.rows, self.scope)
        self.assertEqual([event['status'] for event in events], ['orphan', 'older-revision', 'orphan'])
        self.assertEqual(len({event['eventId'] for event in events}), 3)
        self.assertTrue(all(event['anchor'] == self.target for event in events))
        self.assertEqual(events[1]['checkedScope']['ref'], 'b' * 40)
        self.assertEqual(events[2]['previousEventId'], events[1]['eventId'])

    def test_invalid_context_extension_cannot_become_a_legacy_object_orphan(self):
        malformed = note('BOM context missing', dict(self.scope, kind='bom', objectId='bom:row'))
        self.provider.rows[0]['body'] = markdown(malformed)
        result = self.update()
        self.update()
        self.assertEqual(result[0]['contextStatus'][0]['status'], 'unavailable')
        self.assertEqual(self.provider.posts, [])

    def test_foreign_anchor_and_corrupt_status_marker_are_ignored(self):
        foreign = note('Other project', dict(self.target, repository='other/design'))
        self.provider.rows.append(dict(id='11', body=markdown(foreign)))
        classification = classify_context(self.target, self.inventory)
        event = make_status_event(classification, '10', 'annotation-1')
        event['eventId'] = '0' * 64
        self.provider.rows.append(dict(id='12', body=status_markdown(event)))
        outcome = self.update()
        self.assertEqual(outcome[1]['contextStatus'], [])
        self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_ambiguous_status_history_blocks_automatic_transition(self):
        orphan = classify_context(self.target, self.inventory)
        changed = dict(orphan, status='changed', reason='source-content-changed')
        for index, classification in enumerate((orphan, changed)):
            event = make_status_event(classification, '10', 'annotation-1')
            self.provider.rows.append(dict(id=str(30 + index), body=status_markdown(event)))
        self.update()
        self.update()
        self.assertEqual(self.provider.posts, [])
        self.assertIn('ambiguous', self.tracker.warning)

    def test_only_one_status_is_posted_per_refresh(self):
        second = note('Second object', dict(self.target, uuid='u2'))
        self.provider.rows.append(dict(id='11', body=markdown(second)))
        self.update()
        self.update()
        self.assertEqual(len(self.provider.posts), 1)

    def test_row_bound_and_duplicate_provider_rows_fail_closed(self):
        self.update(rows=self.rows * 5002)
        self.update(rows=self.rows * 2)
        self.assertEqual(self.provider.posts, [])
        self.assertIn('complete', self.tracker.warning)

    def test_human_status_identifies_original_reason_and_revision(self):
        event = make_status_event(classify_context(self.target, self.inventory), '10', 'annotation-1')
        provider = RealProvider(dict(self.scope, kind='issue', number=7))
        body = status_markdown(event, provider)
        self.assertIn('[comment 10](https://github.com/example/design/issues/7#issuecomment-10)', body)
        self.assertIn('Reason: missing object.', body)
        self.assertIn(self.scope['ref'], body)
        self.assertEqual(parse_status_events([dict(body=body)], self.scope), [event])
        body = status_markdown(event, self.provider)
        self.assertIn('comment 10', body)
        self.assertNotIn('](', body)

    def test_preflight_preserves_existing_annotations_but_does_not_invent_new_authority(self):
        enriched = deepcopy(self.rows)
        enriched[0]['annotations'] = [deepcopy(self.annotation)]
        enriched[0]['anchors'] = [deepcopy(self.target)]
        self.update(rows=enriched)
        result = self.update(rows=enriched)
        self.assertEqual(result[0]['annotations'], enriched[0]['annotations'])
        self.assertEqual(result[0]['anchors'], enriched[0]['anchors'])

    def test_foreign_provider_cannot_receive_automatic_project_status(self):
        self.provider.scope['repository'] = 'other/design'
        self.update()
        self.update()
        self.assertEqual(self.provider.posts, [])
        self.assertIn('destination', self.tracker.warning)

    def test_non_boolean_auto_publish_setting_does_not_authorize_a_write(self):
        self.update(auto_publish='false')
        self.update(auto_publish='false')
        self.assertEqual(self.provider.posts, [])

    def test_working_tree_status_reports_local_observation_not_commit_deletion(self):
        self.inventory['provenance'] = 'working-tree'
        self.update()
        self.update()
        body = self.provider.posts[0]
        self.assertIn('Local saved working-tree observation', body)
        self.assertIn('HEAD baseline: ' + self.scope['ref'], body)
        self.assertIn('may include uncommitted changes', body)
        self.assertNotIn('Checked saved files at revision', body)
        event = parse_status_events(self.provider.rows, self.scope)[0]
        self.assertEqual(event['evidence']['provenance'], 'working-tree')
        self.assertEqual(event['anchor'], self.target)

    def test_explicit_commit_inventory_retains_revision_wording(self):
        self.inventory['provenance'] = 'git-commit'
        event = make_status_event(classify_context(self.target, self.inventory), '10', 'annotation-1')
        body = status_markdown(event)
        self.assertIn('Checked saved files at revision ' + self.scope['ref'], body)
        self.assertNotIn('HEAD baseline', body)

    def test_prepublish_guard_runs_after_preflight_immediately_before_send(self):
        operations = []
        def inventory(*args):
            operations.append('inventory')
            return deepcopy(self.inventory)
        def guard():
            operations.append('guard')
        publish = self.provider.publish
        def guarded_publish(body):
            operations.append('publish')
            return publish(body)
        self.tracker.inventory_builder = inventory
        self.provider.before_read = lambda: operations.append('snapshot')
        self.provider.publish = guarded_publish
        self.update(prepublish=guard)
        self.assertEqual(operations, ['inventory'])
        operations.clear()
        self.update(prepublish=guard)
        self.assertEqual(operations, ['inventory', 'snapshot', 'inventory', 'guard', 'publish'])

    def test_prepublish_guard_rejects_origin_change_outside_anchor_inventory(self):
        # The injected bounded inventory describes the annotation; caller also
        # owns an originating editor file whose digest changes during preflight.
        source = {'digest': 'unchanged'}
        def guard():
            if source['digest'] != 'unchanged':
                raise ValueError('private source diagnostic')
        self.update(prepublish=guard)
        self.provider.before_read = lambda: source.update(digest='changed')
        self.update(prepublish=guard)
        self.assertEqual(self.provider.posts, [])
        self.assertFalse(self.tracker.halted)
        self.assertIsNone(self.tracker._pending)
        self.assertIn('No status update was sent', self.tracker.warning)
        self.assertIn('selected saved source', self.tracker.warning)
        self.assertNotIn('private source diagnostic', self.tracker.warning)
        self.provider.before_read = None
        source['digest'] = 'unchanged'
        self.update(prepublish=guard)
        self.assertEqual(self.provider.posts, [])
        self.update(prepublish=guard)
        self.assertEqual(len(self.provider.posts), 1)


if __name__ == '__main__':
    unittest.main()
