"""Exact legacy identity/power preservation and unpublished-failure checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bomstudio import migration as m
from bomstudio.sexpr import parse, properties


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.source = self.home / 'source'
        self.source.mkdir()
        self.root = self.source / 'test.kicad_sch'
        self.root.write_text('''(kicad_sch (version 20211123) (uuid root)
          (lib_symbols (symbol "power:P" (power)
            (symbol "P_1_1" (pin power_in line hide (name "P")))))
          (symbol (lib_id "power:P") (uuid placed) (unit 1)
            (property "Reference" "#PWR01") (property "Value" "Display"))
          (symbol_instances (path "/placed" (reference "#PWR01") (unit 1)
            (value "Display") (footprint ""))))''', encoding='utf-8')

    def records(self):
        docs, visits = m._hierarchy(self.root)
        return m._legacy_records(self.root, docs, visits)

    def test_equivalent_path_spelling_uses_canonical_hierarchy_keys(self):
        alias = self.root.parent / '..' / self.root.parent.name / self.root.name
        docs, visits = m._hierarchy(alias)
        records = m._legacy_records(alias, docs, visits)
        stage = self.home / 'stage'; stage.mkdir()
        target = stage / self.root.name
        target.write_text('(kicad_sch (symbol (uuid placed) (property "Value" "Display")))', encoding='utf-8')
        m._restore_instances(stage, alias.parent, records, 'test')
        m._restore_effective_fields(stage, alias.parent, records, {'components': []})
        self.assertEqual(properties(parse(target.read_text(encoding='utf-8')).one('symbol'))['Value'][0], 'P')

    def test_legacy_power_name_and_identity_are_authoritative(self):
        row = next(iter(self.records().values()))[0]
        self.assertEqual(row, ('root', '#PWR01', '1', 'Display', '', 'P'))

    def test_restore_modern_instance_and_old_power_electrical_name(self):
        records = self.records()
        stage = self.home / 'stage'; stage.mkdir()
        target = stage / self.root.name
        target.write_text('(kicad_sch (version 20260306) (uuid root) '
                          '(symbol (uuid placed) (property "Value" "Display")))', encoding='utf-8')
        m._restore_instances(stage, self.source, records, 'test')
        m._restore_effective_fields(stage, self.source, records, {'components': []})
        node = parse(target.read_text(encoding='utf-8')).one('symbol')
        instance = node.one('instances').one('project').one('path')
        self.assertEqual(instance.val(), '/root')
        self.assertEqual(instance.get('reference'), '#PWR01')
        self.assertEqual(properties(node)['Value'][0], 'P')

    def test_incomplete_annotation_is_rejected(self):
        text = self.root.read_text(encoding='utf-8').replace('"/placed"', '"/unknown"')
        self.root.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.records()

    def test_resolved_xml_fields_do_not_bake_source_expressions(self):
        stage=self.home/'stage';stage.mkdir();target=stage/self.root.name
        target.write_text('(kicad_sch (symbol (uuid placed) (property "Value" "${RAIL}")))',encoding='utf-8')
        m._restore_effective_fields(stage,self.source,self.records(),{'components':[]})
        self.assertEqual(properties(parse(target.read_text(encoding='utf-8')).one('symbol'))['Value'][0],'${RAIL}')

    def test_existing_or_nested_destination_is_rejected(self):
        for target in (self.source, self.source / 'nested'):
            with self.assertRaisesRegex(ValueError, 'new destination'):
                m.upgrade_copy(self.root, target)

    def test_connectivity_change_aborts_without_publishing_or_source_edit(self):
        original = self.root.read_bytes(); target = self.home / 'output'
        with patch.object(m, 'executable', return_value=('cli', '10.0.5')), \
             patch.object(m, '_run'), patch.object(m, '_restore_instances'), \
             patch.object(m, '_restore_effective_fields', return_value=0), \
             patch.object(m, '_netlist', side_effect=[{'components': [], 'nets': []},
                                                     {'components': [], 'nets': ['changed']}]):
            with self.assertRaisesRegex(ValueError, 'connectivity'):
                m.upgrade_copy(self.root, target)
        self.assertFalse(target.exists())
        self.assertEqual(self.root.read_bytes(), original)

    def test_outside_hierarchy_is_rejected(self):
        (self.home / 'outside.kicad_sch').write_text('(kicad_sch (version 20260306))', encoding='utf-8')
        self.root.write_text('(kicad_sch (version 20211123) '
                            '(sheet (uuid s) (property "Sheetfile" "../outside.kicad_sch")))', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'outside'): m._hierarchy(self.root)

    def test_unsupported_native_version_is_rejected(self):
        with patch.object(m, '_run', return_value='11.0.0'):
            with self.assertRaisesRegex(ValueError, 'validated for KiCad 10'): m.executable('cli')


if __name__ == '__main__': unittest.main()
