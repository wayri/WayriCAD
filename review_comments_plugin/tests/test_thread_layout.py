"""One-level visual threading preserves provider data and diagnoses bad links."""
import unittest

from review_comments_plugin.thread_layout import flat_threads


class ThreadLayoutTests(unittest.TestCase):
    def test_multilevel_replies_flatten_to_one_indent_and_keep_peer_order(self):
        rows = [dict(id='root-a'), dict(id='root-b'),
                dict(id='a-1', parentId='root-a'), dict(id='b-1', parentId='root-b'),
                dict(id='a-2', parentId='root-a'), dict(id='a-deep', parentId='a-1'),
                dict(id='b-2', parentId='root-b')]
        result = flat_threads(rows)
        self.assertEqual([row['id'] for row in result],
                         ['root-a', 'a-1', 'a-deep', 'a-2', 'root-b', 'b-1', 'b-2'])
        self.assertEqual([row['replyDepth'] for row in result], [0, 1, 1, 1, 0, 1, 1])
        self.assertEqual([row['threadRoot'] for row in result[:4]], ['root-a'] * 4)
        self.assertEqual(rows[5], dict(id='a-deep', parentId='a-1'))
        self.assertIsNot(result[5], rows[5])

    def test_orphan_and_ambiguous_parent_remain_visible_with_diagnostics(self):
        rows = [dict(id='dup'), dict(id='dup'), dict(id='orphan', parentId='gone'),
                dict(id='child', parentId='dup'), dict(id='ok')]
        result = flat_threads(rows)
        self.assertEqual(len(result), len(rows))
        self.assertEqual([row.get('replyIssue') for row in result],
                         ['duplicate-id', 'duplicate-id', 'missing-parent', 'ambiguous-parent', None])
        self.assertEqual([row['replyDepth'] for row in result], [0, 0, 1, 0, 0])
        self.assertIsNone(result[2]['threadRoot'])
        self.assertIsNone(result[0]['threadRoot'])

    def test_cycle_is_broken_at_earliest_row_without_losing_descendant(self):
        rows = [dict(id='a', parentId='b'), dict(id='b', parentId='c'),
                dict(id='c', parentId='a'), dict(id='tail', parentId='b')]
        result = flat_threads(rows)
        self.assertEqual([row['id'] for row in result], ['a', 'c', 'b', 'tail'])
        self.assertEqual([row['replyDepth'] for row in result], [0, 1, 1, 1])
        self.assertEqual([row.get('replyIssue') for row in result], ['cycle', 'cycle', 'cycle', None])
        self.assertTrue(all(row['threadRoot'] == 'a' for row in result))

    def test_self_cycle_and_bound(self):
        self.assertEqual(flat_threads([dict(id='a', parentId='a')])[0]['replyIssue'], 'cycle')
        with self.assertRaisesRegex(ValueError, 'limit'):
            flat_threads([dict(id=str(index)) for index in range(5002)])


if __name__ == '__main__':
    unittest.main()
