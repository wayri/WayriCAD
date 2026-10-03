"""PCB paths must match KiCad's exported sheet stamps literally."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_native_associations_test'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
schematic = importlib.import_module(PACKAGE + '.schematic')
netlist = importlib.import_module(PACKAGE + '.netlist')
sexpr = importlib.import_module(PACKAGE + '.sexpr')
model = importlib.import_module(PACKAGE + '.model')
board_module = importlib.import_module(PACKAGE + '.board')


def exported_paths(xml_file):
    """Independent XML read: no plugin path normalization or inferred root."""
    rows = {}
    for component in ET.parse(xml_file).getroot().findall('./components/comp'):
        sheet = component.find('sheetpath')
        stamps = sheet.get('tstamps', '') if sheet is not None else ''
        symbol = component.findtext('tstamps', '').strip()
        rows[component.get('ref')] = '/' + '/'.join(p for p in (stamps + '/' + symbol).split('/') if p)
    return rows


class AssociationPathTests(unittest.TestCase):
    def test_root_free_pcb_path_preserves_schematic_identity(self):
        root = '11111111-1111-4111-8111-111111111111'
        sheet = '22222222-2222-4222-8222-222222222222'
        symbol = '33333333-3333-4333-8333-333333333333'
        full = '/' + root + '/' + sheet + '/' + symbol
        self.assertEqual(schematic.pcb_association_path(full, root), '/' + sheet + '/' + symbol)
        self.assertEqual(full, '/' + root + '/' + sheet + '/' + symbol)
        with self.assertRaises(model.MergeError):
            schematic.pcb_association_path(full, sheet)

    def test_parser_does_not_add_root_to_native_xml(self):
        root = '11111111-1111-4111-8111-111111111111'
        sheet = '22222222-2222-4222-8222-222222222222'
        symbol = '33333333-3333-4333-8333-333333333333'
        with tempfile.TemporaryDirectory() as folder:
            xml_file = Path(folder) / 'export.xml'
            xml_file.write_text('<export><components><comp ref="R1"><sheetpath tstamps="/' +
                                sheet + '/"/><tstamps>' + symbol +
                                '</tstamps></comp></components><nets/></export>', encoding='utf-8')
            expected = exported_paths(xml_file)['R1']
            self.assertEqual(netlist.Netlist.read(xml_file, root_uuid=root).components['R1']['paths'], {expected})
            self.assertEqual(expected, '/' + sheet + '/' + symbol)

    def test_legacy_target_path_is_diagnosed_without_board_edit(self):
        root = '11111111-1111-4111-8111-111111111111'
        sheet = '22222222-2222-4222-8222-222222222222'
        symbol = '33333333-3333-4333-8333-333333333333'
        native_path = '/' + sheet + '/' + symbol
        footprint = ['footprint', 'Example:R', ['property', 'Reference', 'R1'],
                     ['path', root + native_path]]
        board = ['kicad_pcb', footprint]
        exported = netlist.Netlist(components={'R1': {'paths': {native_path}}})
        before = sexpr.dumps(board)
        with self.assertRaisesRegex(model.MergeError, 'PCB footprint R1 has association path'):
            board_module.verify_native_associations(board, exported)
        self.assertEqual(sexpr.dumps(board), before)
        sexpr.put(footprint, 'path', native_path)
        board_module.verify_native_associations(board, exported)


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_ASSOCIATIONS') == '1',
                     'Opt-in KiCad 10 CLI/pcbnew association workflow')
class NativeAssociationTests(unittest.TestCase):
    def test_routed_import_matches_literal_native_export(self):
        from test_sections_native import make_fixture
        insertion = importlib.import_module(PACKAGE + '.insertion')
        with tempfile.TemporaryDirectory(prefix='fusion-native-associations-') as folder:
            base = Path(folder).resolve()
            target, _ = make_fixture(base / 'target')
            source, _ = make_fixture(base / 'source')
            incoming = model.SourceSpec(source.project, 'Incoming', variant='<Default>')
            insertion.preview_import(target.project, [incoming], True, base / 'candidate')
            candidate = base / 'candidate'
            cli = netlist.KiCadCLI()
            xml_file = base / 'candidate-export.xml'
            cli.export_netlist(candidate / 'board.kicad_sch', xml_file)
            native = exported_paths(xml_file)
            board = sexpr.load(candidate / 'board.kicad_pcb')
            root_uuid = sexpr.value(sexpr.load(candidate / 'board.kicad_sch'), 'uuid')
            footprints = sexpr.children(board, 'footprint')
            self.assertEqual(len(footprints), 2)
            for footprint in footprints:
                ref = sexpr.propval(footprint, 'Reference')
                self.assertEqual(sexpr.value(footprint, 'path'), native[ref])
                self.assertNotEqual(native[ref].split('/')[1], root_uuid)


if __name__ == '__main__':
    unittest.main()
