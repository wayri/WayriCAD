"""Optional real-host tests. Disabled unless WAYRICAD_EMBED3D_NATIVE_TESTS=1.

Never edit pcbnew.GetBoard(). All objects and output folders are disposable.
Schematic CLI acceptance is parser/netlist only, not interactive visual/ERC testing.
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from embed_3d_plugin.cli_validation import find_cli, validate_schematic

ENABLE=os.environ.get('WAYRICAD_EMBED3D_NATIVE_TESTS')=='1'
PCB=ENABLE and importlib.util.find_spec('pcbnew') is not None
CLI=ENABLE and find_cli() is not None

@unittest.skipUnless(PCB,'Real KiCad 10 pcbnew unavailable/not enabled; unbundle native normalization not verified')
class NativeUnbundleTests(unittest.TestCase):
    def test_ordinary_board_as_placed_extract_and_relink(self):
        import pcbnew
        from embed_3d_plugin.native import NativeBridge
        from embed_3d_plugin.core import Planner
        from embed_3d_plugin.paths import Resolver
        from embed_3d_plugin.unbundle import extract_pcb,relink_pcb
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bridge=NativeBridge(pcbnew);bridge.board=pcbnew.BOARD()
            source=root/'test.kicad_pcb';bridge.board.SetFileName(str(source))
            model=root/'box.wrl';model.write_text('#VRML V2.0 utf8\nShape { geometry Box { size 1 2 3 } }\n')
            raw='(footprint "Lab:Part" (version 20241229) (generator "pcbnew") (layer "B.Cu") (at 15 20 137) (pad "1" smd rect (at 1 2) (size 1 2) (layers "B.Cu" "B.Mask")) (model "'+model.as_posix()+'" (offset (xyz -1 2 3)) (scale (xyz 0.5 2 3)) (rotate (xyz 10 20 -30))))'
            fp=bridge.deserialize(Planner(Resolver(root)).scan(raw).build());fp.SetReference('U1');bridge.board.Add(fp);fp.thisown=False
            bridge.snapshot_board(source)
            normalized,digest=bridge.extract_normalized_footprints(source)
            self.assertEqual(len(normalized),1)
            plan=extract_pcb(source,root/'assets',normalized=normalized,normalized_source_hash=digest);plan.publish(root/'assets')
            out=root/'out'
            relink_pcb(source,root/'assets',out,apply=True,prune=True,validate=lambda stage:bridge.validate_portable_board(stage/source.name))
            self.assertTrue((out/source.name).is_file())

@unittest.skipUnless(CLI,'Real KiCad 10 CLI unavailable/not enabled; schematic parser/netlist acceptance not verified')
class NativeSymbolPortabilityTests(unittest.TestCase):
    def run_cycle(self,local=False):
        from embed_3d_plugin.symbols import embed_symbols,extract_symbols,relink_symbols
        from test_symbols import schematic
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'circuit.kicad_sch';source.write_text(schematic())
            validate_schematic(source)
            embed_symbols(source,root/'embedded',local_links=local,apply=True,
                          validate=lambda stage:validate_schematic(stage/source.name))
            bundled=root/'embedded'/source.name;plan=extract_symbols(bundled);plan.publish(root/'assets')
            relink_symbols(bundled,root/'assets',root/'external',prune=True,apply=True,
                           validate=lambda stage:validate_schematic(stage/source.name))
            self.assertTrue((root/'external'/source.name).is_file())
    def test_schematic_embed_extract_external_relink_native_parser(self):self.run_cycle()
    def test_schematic_embed_local_library_ids_native_parser(self):self.run_cycle(True)
