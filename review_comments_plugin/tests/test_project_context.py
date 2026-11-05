"""Read-only bounded worktree evidence; Git object reads are deterministic fakes."""
import hashlib
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from review_comments_plugin import project_context as pc
from review_comments_plugin.context_status import classify_context


BOARD = b'(kicad_pcb (version 20240108) (footprint "R" (uuid "u1") (property "Reference" "R1") (property "Value" "10k")))'


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'board.kicad_pcb').write_bytes(BOARD)
        self.scope = dict(repository='example/design', ref='a' * 40, file='board.kicad_pcb')
        self.target = dict(self.scope, uuid='u1')
        self.originals = {('a' * 40, 'board.kicad_pcb'): BOARD}
        self.head = 'a' * 40
        self.mock = patch.object(pc, '_git', side_effect=self.git)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def git(self, root, arguments):
        if arguments == ['rev-parse', '--show-toplevel']:
            return str(self.root).encode()
        if arguments == ['rev-parse', '--verify', 'HEAD^{commit}']:
            return self.head.encode()
        revision, name = arguments[-1].split(':', 1)
        try:
            data = self.originals[revision, name]
        except KeyError:
            raise subprocess.CalledProcessError(128, ['git']) from None
        return str(len(data)).encode() if arguments[0] == 'cat-file' else data

    def inventory(self):
        return pc.build_inventory(self.root, self.scope, [{'id': 'a1', 'anchor': self.target}])

    def test_known_paths_only_with_original_commit_baseline(self):
        (self.root / 'unrelated.kicad_pcb').write_bytes(b'not a valid design')
        result = self.inventory()
        self.assertTrue(result['complete'])
        self.assertEqual(result['knownPaths'], ['board.kicad_pcb'])
        self.assertEqual(result['files']['board.kicad_pcb']['objectIds'], ['u1'])
        self.assertEqual(result['provenance'], 'working-tree')
        self.assertEqual(result['originalInventories']['a' * 40]['provenance'], 'git-commit')
        self.assertEqual(result, self.inventory())

    def test_working_tree_changes_do_not_claim_committed_content(self):
        (self.root / 'board.kicad_pcb').write_bytes(BOARD.replace(b'10k', b'20k'))
        result = self.inventory()
        classification = classify_context(self.target, result,
            original_inventory=result['originalInventories']['a' * 40])
        self.assertEqual(classification['status'], 'changed')
        self.assertEqual(result['scope']['ref'], self.scope['ref'])

    def test_actual_head_is_selected_and_old_anchor_is_preserved(self):
        self.head = 'b' * 40
        result = self.inventory()
        self.assertTrue(result['verified'])
        self.assertEqual(result['scope']['ref'], self.head)
        self.assertEqual(self.target['ref'], 'a' * 40)

    def test_proven_missing_known_path_retains_complete_inventory(self):
        self.target['file'] = 'removed/old.kicad_pcb'
        self.originals['a' * 40, self.target['file']] = BOARD
        result = self.inventory()
        self.assertTrue(result['complete'])
        self.assertIn(self.target['file'], result['knownPaths'])
        self.assertNotIn(self.target['file'], result['files'])
        self.assertEqual(classify_context(self.target, result)['reason'], 'missing-file')

    def test_permission_failure_never_establishes_deletion(self):
        with patch.object(pc, '_read', side_effect=PermissionError('private diagnostic')):
            result = self.inventory()
        self.assertFalse(result['complete'])
        self.assertNotIn('private diagnostic', str(result))
        self.assertEqual(classify_context(self.target, result)['status'], 'unavailable')

    def test_parse_failure_and_missing_git_object_are_unavailable(self):
        (self.root / 'board.kicad_pcb').write_bytes(b'(incomplete')
        self.assertFalse(self.inventory()['complete'])
        (self.root / 'board.kicad_pcb').write_bytes(BOARD)
        self.originals.clear()
        self.assertFalse(self.inventory()['complete'])

    def test_source_change_during_observation_is_rejected(self):
        real = pc._read
        changed = False
        def changing(root, name):
            nonlocal changed
            result = real(root, name)
            if name == 'board.kicad_pcb' and not changed:
                changed = True
                (self.root / name).write_bytes(BOARD.replace(b'10k', b'20k'))
            return result
        with patch.object(pc, '_read', side_effect=changing):
            self.assertFalse(self.inventory()['complete'])

    def test_head_change_during_observation_is_rejected(self):
        calls = 0
        def changing(root, arguments):
            nonlocal calls
            if arguments == ['rev-parse', '--verify', 'HEAD^{commit}']:
                calls += 1
                return (('a' if calls == 1 else 'b') * 40).encode()
            return self.git(root, arguments)
        with patch.object(pc, '_git', side_effect=changing):
            self.assertFalse(self.inventory()['complete'])

    def test_bom_rows_fields_variants_and_source_hashes_are_merged(self):
        snapshot = pc.load_bom(self.root / 'board.kicad_pcb', self.root)
        row = snapshot['rows'][0]
        self.target.update(objectId=row['id'], context=dict(type='bom', rowId=row['id'], field='Value',
                                       sourceFiles=snapshot['source_hashes']), variant='<Default>')
        result = self.inventory()
        record = result['files']['board.kicad_pcb']
        self.assertTrue(record['bomComplete'])
        self.assertIn(row['id'], record['objectIds'])
        self.assertIn('Value', record['fieldsByObject'][row['id']])
        self.assertIn('board.kicad_pro', result['knownPaths'])
        self.assertEqual(classify_context(self.target, result)['status'], 'current')

    def test_missing_linked_bom_source_is_proven_without_faking_bom_completion(self):
        self.target['objectId'] = 'row-1'
        self.target['context'] = dict(type='bom', rowId='row-1', sourceFiles={
            'board.kicad_pcb': hashlib.sha256(BOARD).hexdigest(), 'child.kicad_sch': '1' * 64})
        result = self.inventory()
        self.assertTrue(result['complete'])
        self.assertNotIn('bomComplete', result['files']['board.kicad_pcb'])
        self.assertEqual(classify_context(self.target, result)['reason'], 'missing-source-file')

    def test_native_duplicate_uuid_is_not_silently_deduplicated(self):
        (self.root / 'board.kicad_pcb').write_bytes(b'(kicad_pcb (uuid u1) (uuid u1))')
        result = self.inventory()
        self.assertEqual(classify_context(self.target, result)['status'], 'ambiguous')

    def test_foreign_and_oversized_evidence_fail_closed(self):
        self.target['repository'] = 'other/design'
        self.assertFalse(self.inventory()['complete'])
        self.target['repository'] = 'example/design'
        with patch.object(pc, 'MAX_FILE_BYTES', 8):
            self.assertFalse(self.inventory()['complete'])

    def test_linked_file_is_not_read(self):
        (self.root / 'other.kicad_pcb').write_bytes(BOARD)
        (self.root / 'board.kicad_pcb').unlink()
        try:
            (self.root / 'board.kicad_pcb').symlink_to(self.root / 'other.kicad_pcb')
        except OSError:
            self.skipTest('Symlink creation is unavailable.')
        self.assertFalse(self.inventory()['complete'])


@unittest.skipUnless(shutil.which('git'), 'Git is unavailable')
class RealGitContextTests(unittest.TestCase):
    def test_real_immutable_blob_baseline_and_current_worktree(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment, clear=True):
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(['git', '-c', 'core.hooksPath=' + str(root / '.no-hooks'),
                    '-c', 'user.name=Test Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', *args], cwd=root, check=True,
                    capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
            git('-c', 'init.defaultBranch=main', 'init', '--quiet', '--template=')
            (root / 'board.kicad_pcb').write_bytes(BOARD)
            git('add', '--', 'board.kicad_pcb')
            git('commit', '--quiet', '-m', 'Fixture')
            revision = git('rev-parse', 'HEAD').decode().strip()
            target = dict(repository='example/design', ref=revision, file='board.kicad_pcb', uuid='u1')
            (root / 'board.kicad_pcb').write_bytes(BOARD.replace(b'10k', b'20k'))
            inventory = pc.build_inventory(root, target, [dict(id='a1', anchor=target)])
            self.assertTrue(inventory['verified'])
            self.assertEqual(classify_context(target, inventory,
                original_inventory=inventory['originalInventories'][revision])['status'], 'changed')


if __name__ == '__main__':
    unittest.main()
