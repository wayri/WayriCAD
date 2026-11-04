import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from review_comments_plugin.web_documents import ReviewDocuments


def schematic(*sheets):
    children = ' '.join(
        f'(sheet (property "Sheetfile" "{filename}"))' for filename in sheets)
    return f'(kicad_sch {children})'


class ReviewDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_paired_board_and_recursive_schematic_catalog(self):
        board = self.root / 'Demo.kicad_pcb'
        board.write_text('(kicad_pcb)', encoding='utf-8')
        main = self.root / 'Demo.kicad_sch'
        main.write_text(schematic('sub/Channel.kicad_sch', 'sub/Channel.kicad_sch'), encoding='utf-8')
        child = self.root / 'sub/Channel.kicad_sch'
        child.parent.mkdir()
        child.write_text(schematic('Leaf.kicad_sch'), encoding='utf-8')
        (child.parent / 'Leaf.kicad_sch').write_text(schematic(), encoding='utf-8')
        catalog = ReviewDocuments(board)
        self.assertEqual(catalog.selected_id, 'Demo.kicad_pcb')
        self.assertEqual([entry['id'] for entry in catalog.entries()],
                         ['Demo.kicad_pcb', 'Demo.kicad_sch',
                          'sub/Channel.kicad_sch', 'sub/Leaf.kicad_sch'])
        payload = catalog.load('sub/Channel.kicad_sch')
        self.assertEqual(payload['path'], 'sub/Channel.kicad_sch')
        self.assertEqual(payload['current_document_id'], payload['path'])
        self.assertEqual(payload['view'], 'schematic')
        self.assertEqual(payload['source'], schematic('Leaf.kicad_sch'))
        self.assertEqual(payload['source_sha256'], hashlib.sha256(child.read_bytes()).hexdigest())
        self.assertEqual(payload['documents'], catalog.entries())
        self.assertEqual(catalog.path_for('Demo.kicad_pcb'), board)

    def test_exact_id_and_stale_digest_guard(self):
        board = self.root / 'Demo.kicad_pcb'
        board.write_text('initial', encoding='utf-8')
        catalog = ReviewDocuments(board)
        digest = catalog.load('Demo.kicad_pcb')['source_sha256']
        catalog.assert_current('Demo.kicad_pcb', digest)
        for bad in ('../Demo.kicad_pcb', 'file:///Demo.kicad_pcb',
                    'https://example.test/board', 'other.kicad_pcb'):
            with self.assertRaisesRegex(ValueError, 'not registered'):
                catalog.load(bad)
        board.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            catalog.assert_current('Demo.kicad_pcb', digest)

    def test_rejects_external_child_and_oversized_catalog(self):
        project = self.root / 'project'
        project.mkdir()
        main = project / 'Main.kicad_sch'
        main.write_text(schematic('../outside.kicad_sch'), encoding='utf-8')
        (self.root / 'outside.kicad_sch').write_text(schematic(), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'outside'):
            ReviewDocuments(main)
        main.write_text(schematic(), encoding='utf-8')
        with patch('review_comments_plugin.web_documents.MAX_SOURCE_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'bounded|limit'):
                ReviewDocuments(main)

    def test_rejects_change_during_file_read(self):
        board = self.root / 'Demo.kicad_pcb'
        board.write_text('initial', encoding='utf-8')
        catalog = ReviewDocuments(board)
        original = Path.read_bytes

        def change_after_read(path):
            data = original(path)
            if path == board:
                board.write_text('changed', encoding='utf-8')
            return data

        with patch.object(Path, 'read_bytes', change_after_read):
            with self.assertRaisesRegex(ValueError, 'changed during read'):
                catalog.load('Demo.kicad_pcb')

    def test_repository_multisheet_fixture(self):
        repository = Path(__file__).resolve().parents[2]
        root = repository / 'bom_studio_plugin/examples/vendor_splitting/BOM_Demo.kicad_sch'
        catalog = ReviewDocuments(root)
        self.assertEqual([row['id'] for row in catalog.entries()],
                         ['BOM_Demo.kicad_sch', 'Channel.kicad_sch'])
        self.assertIn('(kicad_sch', catalog.load('Channel.kicad_sch')['source'])

    def test_rejects_file_replaced_by_link_before_load(self):
        board = self.root / 'Demo.kicad_pcb'
        board.write_text('board', encoding='utf-8')
        catalog = ReviewDocuments(board)
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == board or original(path)):
            with self.assertRaisesRegex(ValueError, 'linked'):
                catalog.load('Demo.kicad_pcb')

    def test_ancestor_alias_is_accepted_but_selected_and_parent_links_are_rejected(self):
        real = self.root / 'real' / 'Project'
        real.mkdir(parents=True)
        board = real / 'Main.kicad_pcb'
        board.write_text('(kicad_pcb)', encoding='utf-8')
        alias = self.root / 'alias'
        try:
            alias.symlink_to(real.parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('directory symlinks are unavailable in this environment')
        selected = alias / 'Project' / board.name
        self.assertFalse(selected.is_symlink())
        self.assertFalse(selected.parent.is_symlink())
        catalog = ReviewDocuments(selected)
        self.assertEqual(catalog.root, real)
        self.assertEqual(catalog.path_for(board.name), board)
        self.assertEqual(catalog.load(board.name)['source'], '(kicad_pcb)')
        with self.assertRaisesRegex(ValueError, 'Choose a saved'):
            ReviewDocuments(alias / 'Project')
        selected_link = real / 'Linked.kicad_pcb'
        selected_link.symlink_to(board)
        with self.assertRaisesRegex(ValueError, 'Choose a saved'):
            ReviewDocuments(selected_link)
        parent_link = self.root / 'Project-link'
        parent_link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Choose a saved'):
            ReviewDocuments(parent_link / board.name)

    def test_linked_schematic_child_is_rejected(self):
        root = self.root / 'Root.kicad_sch'
        child = self.root / 'Child.kicad_sch'
        target = self.root / 'Real.kicad_sch'
        root.write_text(schematic('Child.kicad_sch'), encoding='utf-8')
        target.write_text(schematic(), encoding='utf-8')
        try:
            child.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('file symlinks are unavailable in this environment')
        with self.assertRaisesRegex(ValueError, 'linked'):
            ReviewDocuments(root)


if __name__ == '__main__':
    unittest.main()
