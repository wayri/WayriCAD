"""Automatic scope resolution and cache revision/isolation regressions."""
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_sections import PACKAGE, SectionTests, model, sx, sch

d=importlib.import_module(PACKAGE+'.source_detection')


class SourceDetectionTests(unittest.TestCase):
    def test_project_board_root_and_repeated_child_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,path=SectionTests().fixture(root)
            for suffix in ('.kicad_pro','.kicad_sch','.kicad_pcb'):
                choice=d.detect_source(root/('board'+suffix))[0]
                self.assertEqual(choice.kind,'project');self.assertEqual(choice.project,spec.project)
            choice=d.detect_source(root/'child.kicad_sch')[0]
            self.assertEqual(choice.kind,'sheet');self.assertEqual(len(choice.sheet_paths),2)
            self.assertEqual(choice.sheet_paths[0],path)
            self.assertFalse(choice.selection['whole_project'])
            (root/'board.kicad_pcb').unlink()
            self.assertEqual(d.detect_source(root/'board.kicad_pro')[0].kind,'schematic')

    def test_ambiguous_owners_remain_separate_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);SectionTests().fixture(root)
            (root/'other.kicad_pro').write_text('{}')
            (root/'other.kicad_sch').write_bytes((root/'board.kicad_sch').read_bytes())
            choices=d.detect_source(root/'child.kicad_sch')
            self.assertEqual({Path(choice.project).stem for choice in choices},{'board','other'})

    def test_board_only_and_standalone_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pcb=root/'standalone.kicad_pcb';pcb.write_text('(kicad_pcb)')
            self.assertEqual(d.detect_source(pcb)[0].kind,'layout')
            schematic=root/'standalone.kicad_sch';schematic.write_text('(kicad_sch (uuid "root"))')
            self.assertEqual(d.detect_source(schematic)[0].kind,'schematic')
            with self.assertRaises(model.MergeError):d.detect_source(root/'missing.kicad_pro')

    def test_cache_reuses_parse_but_rehashes_bytes_and_copies_mutable_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'board.kicad_sch';path.write_text('(kicad_sch (paper "A4"))')
            with mock.patch.object(sx,'loads',wraps=sx.loads) as parse:
                first=d.read_schematic(path);first.append(['changed'])
                second=d.read_schematic(path)
                self.assertIsNone(sx.child(second,'changed'));self.assertEqual(parse.call_count,1)
                path.write_text('(kicad_sch (paper "A3"))')
                third=d.read_schematic(path)
                self.assertEqual(sx.value(third,'paper'),'A3');self.assertEqual(parse.call_count,2)

    def test_repeated_sheet_occurrences_read_and_parse_unique_files_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,path=SectionTests().fixture(root)
            with mock.patch.object(d,'read_schematic',wraps=d.read_schematic) as read:
                source=sch.discover(spec,sch.new_uuid())
            self.assertEqual(read.call_count,2)
            self.assertEqual([record.old_ref for record in source.symbols],['R1','R2'])
            self.assertIsNot(source.sheets[1].tree,source.sheets[2].tree)
            self.assertEqual(len(source.hashes),3)

    def test_scope_catalogue_matches_import_metadata_without_generating_import_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            spec,_=SectionTests().fixture(Path(folder))
            source=sch.discover(spec,sch.new_uuid())
            with mock.patch.object(sch,'new_uuid',side_effect=AssertionError('UI metadata must not allocate IDs')):
                catalogue=d.sheet_catalogue(spec)
            self.assertEqual([item['sheet_path'] for item in catalogue],[sheet.old_path for sheet in source.sheets[1:]])
            self.assertEqual([item['descendant_symbols'] for item in catalogue],[1,1])
