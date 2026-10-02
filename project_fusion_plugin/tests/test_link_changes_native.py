"""Native XML proves source pin rewiring is flagged by linked-update analysis."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from test_sections_native import make_fixture

ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_link_changes_native_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
m=importlib.import_module(PACKAGE+'.link_changes')
sx=importlib.import_module(PACKAGE+'.sexpr')
sch=importlib.import_module(PACKAGE+'.schematic')

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_LINKS')=='1','Native KiCad linked-update opt-in')
class LinkChangesNative(unittest.TestCase):
    def test_native_shorting_pins_is_major_and_field_change_is_minor(self):
        with tempfile.TemporaryDirectory() as temp:
            spec,_=make_fixture(Path(temp).resolve()/'source')
            old=m.snapshot_source(spec)
            child=Path(spec.project).parent/'child.kicad_sch'
            tree=sx.load(child)
            for start,end in (((20,16.19),(30,16.19)),((30,16.19),(30,23.81)),((30,23.81),(20,23.81))):
                tree.append(['wire',['pts',['xy',*map(str,start)],['xy',*map(str,end)]],
                             ['stroke',['width','0'],['type','default']],['uuid',sx.q(sch.new_uuid())]])
            sx.save(child,tree)
            wired=m.snapshot_source(spec)
            report=m.compare_snapshots(old,wired)
            self.assertEqual(report['summary']['pin_connections'],2)
            self.assertEqual(len(wired['nets']),1)
            self.assertTrue(report['requires_major_acknowledgement'])
            sx.prop(sx.children(tree,'symbol')[0],'Value')[2]=sx.q('22k')
            sx.save(child,tree)
            value=m.snapshot_source(spec)
            changes=m.compare_snapshots(wired,value)
            self.assertEqual(changes['major_changes'],0)
            self.assertGreater(changes['minor_changes'],0)

if __name__=='__main__':unittest.main()
