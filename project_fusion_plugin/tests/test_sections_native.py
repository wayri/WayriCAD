"""Opt-in native fixture: FUSION_NATIVE_SECTIONS=1 with KiCad Python."""
import importlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_fusion_sections_native_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
s=importlib.import_module(PACKAGE+'.sections')
sx=importlib.import_module(PACKAGE+'.sexpr')
model=importlib.import_module(PACKAGE+'.model')
sch=importlib.import_module(PACKAGE+'.schematic')
net=importlib.import_module(PACKAGE+'.netlist')
engine=importlib.import_module(PACKAGE+'.engine')
board_module=importlib.import_module(PACKAGE+'.board')

def make_fixture(root):
    import pcbnew
    root.mkdir()
    rid=sch.new_uuid(); sheet=sch.new_uuid(); childroot=sch.new_uuid(); symbol=sch.new_uuid()
    resources=Path(pcbnew.__file__).parents[2]/'share/kicad'
    if not resources.is_dir():resources=Path('C:/Program Files/KiCad/10.0/share/kicad')
    library=sx.load(resources/'symbols/Device.kicad_sym')
    resistor=next(n for n in sx.children(library,'symbol') if n[1]=='R')
    import copy
    resistor=copy.deepcopy(resistor);resistor[1]=sx.q('Device:R')
    child=['kicad_sch',['version','20250114'],['generator',sx.q('eeschema')],['uuid',sx.q(childroot)],['paper',sx.q('A4')],
           ['lib_symbols',resistor],sx.loads(f'''(symbol (lib_id "Device:R") (at 20 20 0) (unit 1)
             (in_bom yes) (on_board yes) (dnp no) (uuid "{symbol}")
             (property "Reference" "R1" (at 22 19 0) (effects (font (size 1.27 1.27))))
             (property "Value" "10k" (at 22 21 0) (effects (font (size 1.27 1.27))))
             (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 20 20 0) (effects (font (size 1.27 1.27)) (hide yes)))
             (instances (project "board" (path "/{rid}/{sheet}" (reference "R1") (unit 1)))))''')]
    top=sx.loads(f'''(kicad_sch (version 20250114) (generator "eeschema") (uuid "{rid}") (paper "A4")
       (lib_symbols) (sheet (at 20 20) (size 20 20) (stroke (width 0) (type default)) (fill (color 0 0 0 0))
       (uuid "{sheet}") (property "Sheetname" "Module" (at 20 19 0) (effects (font (size 1.27 1.27))))
       (property "Sheetfile" "child.kicad_sch" (at 20 41 0) (effects (font (size 1.27 1.27))))
       (instances (project "board" (path "/{rid}" (page "2"))))) (sheet_instances (path "/" (page "1"))))''')
    sx.save(root/'board.kicad_sch',top);sx.save(root/'child.kicad_sch',child)
    (root/'board.kicad_pro').write_text('{}')
    cli=net.KiCadCLI();xml=cli.export_netlist(root/'board.kicad_sch',root/'fixture.xml')
    b=pcbnew.BOARD()
    io=pcbnew.PCB_IO_KICAD_SEXPR();fp=io.FootprintLoad(str(resources/'footprints/Resistor_SMD.pretty'),'R_0603_1608Metric')
    fp.SetFPID(pcbnew.LIB_ID('Resistor_SMD','R_0603_1608Metric'));fp.SetReference('R1');fp.SetValue('10k')
    fp.SetPath(pcbnew.KIID_PATH('/'+sheet+'/'+symbol));fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10),pcbnew.FromMM(10)));b.Add(fp)
    info={}
    for i,name in enumerate(sorted(xml.nets),1):
        info[name]=pcbnew.NETINFO_ITEM(b,name,i);b.Add(info[name])
    for pad in fp.Pads():
        name=xml.pins.get(('R1',pad.GetNumber()))
        if name:pad.SetNet(info[name])
    first=next(p for p in fp.Pads() if p.GetNumber()=='1')
    for start,end in ((first.GetPosition(),pcbnew.VECTOR2I(pcbnew.FromMM(5),pcbnew.FromMM(10))),
                      (pcbnew.VECTOR2I(pcbnew.FromMM(5),pcbnew.FromMM(10)),pcbnew.VECTOR2I(pcbnew.FromMM(5),pcbnew.FromMM(5)))):
        track=pcbnew.PCB_TRACK(b);track.SetStart(start);track.SetEnd(end);track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.F_Cu);track.SetNet(first.GetNet());b.Add(track)
    via=pcbnew.PCB_VIA(b);via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(5),pcbnew.FromMM(5)));via.SetWidth(pcbnew.FromMM(.6));via.SetDrill(pcbnew.FromMM(.3));via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);via.SetNet(first.GetNet());b.Add(via)
    zone=pcbnew.ZONE(b);zone.SetLayer(pcbnew.F_Cu);zone.SetNet(first.GetNet());outline=zone.Outline();outline.NewOutline()
    for x,y in ((2,2),(8,2),(8,8),(2,8)):outline.Append(pcbnew.FromMM(x),pcbnew.FromMM(y))
    b.Add(zone)
    for start,end in (((-2,-2),(22,-2)),((22,-2),(22,22)),((22,22),(-2,22)),((-2,22),(-2,-2))):
        edge=pcbnew.PCB_SHAPE(b);edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in start]));edge.SetEnd(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in end]))
        edge.SetLayer(pcbnew.Edge_Cuts);edge.SetWidth(pcbnew.FromMM(.05));b.Add(edge)
    line=pcbnew.PCB_SHAPE(b);line.SetShape(pcbnew.SHAPE_T_SEGMENT);line.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(12),pcbnew.FromMM(12)));line.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(15),pcbnew.FromMM(12)));line.SetLayer(pcbnew.Dwgs_User);line.SetWidth(pcbnew.FromMM(.1));b.Add(line)
    pcbnew.SaveBoard(str(root/'board.kicad_pcb'),b)
    return model.SourceSpec(str(root/'board.kicad_pro'),'SECTION',variant='<Default>'),'/'+rid+'/'+sheet

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_SECTIONS')=='1','Opt-in native KiCad workflow')
class NativeSectionTests(unittest.TestCase):
    def test_routed_depth_zero_excludes_nested_sheet_and_preserves_routing(self):
        with tempfile.TemporaryDirectory(prefix='fusion-routed-depth-') as temp:
            base = Path(temp).resolve()
            spec, path = make_fixture(base/'source')
            child = sx.load(base/'source/child.kicad_sch')
            nested_id = sch.new_uuid()
            child.append(sx.loads(f'''(sheet (at 40 40) (size 20 20)
                (stroke (width 0) (type default)) (fill (color 0 0 0 0))
                (uuid "{nested_id}")
                (property "Sheetname" "Nested" (at 40 39 0) (effects (font (size 1.27 1.27))))
                (property "Sheetfile" "nested.kicad_sch" (at 40 61 0) (effects (font (size 1.27 1.27))))
                (instances (project "board" (path "{path}" (page "3")))))'''))
            sx.save(base/'source/child.kicad_sch', child)
            sx.save(base/'source/nested.kicad_sch', sx.loads(f'''(kicad_sch
                (version 20250114) (generator "eeschema") (uuid "{sch.new_uuid()}")
                (paper "A4") (lib_symbols))'''))
            before = s.fingerprint(base/'source')
            plan = s.preview_section(spec, path, [0, 0, 20, 20], max_depth=0)
            self.assertEqual(plan['report']['max_depth'], 0)
            self.assertEqual(plan['report']['descendant_sheets'], 1)
            self.assertEqual(plan['report']['counts']['segment'], 2)
            extracted = s.apply_section(plan, base/'depth-section')
            self.assertFalse(sx.children(sx.load(Path(extracted.project).with_suffix('.kicad_sch')), 'sheet'))
            self.assertEqual(before, s.fingerprint(base/'source'))

    def test_extract_and_merge_preserve_routing(self):
        retained=os.environ.get('FUSION_NATIVE_SECTIONS_OUTPUT')
        if retained:Path(retained).mkdir(parents=True,exist_ok=False)
        context=nullcontext(retained) if retained else tempfile.TemporaryDirectory(prefix='fusion-native-section-')
        with context as folder:
            base=Path(folder);spec,path=make_fixture(base/'source')
            hashes=s.fingerprint(base/'source')
            plan=s.preview_section(spec,path,[0,0,20,20])
            self.assertEqual(plan['report']['counts']['segment'],2)
            self.assertEqual(plan['report']['counts']['via'],1)
            self.assertEqual(plan['report']['counts']['zone'],1)
            extracted=s.apply_section(plan,base/'section')
            self.assertEqual(s.fingerprint(base/'source'),hashes)
            source_board=sx.load(base/'source/board.kicad_pcb');section_board=sx.load(base/'section/board.kicad_pcb')
            before=board_module.geometry_signature(source_board);after=board_module.geometry_signature(section_board)
            self.assertEqual(before,after)
            second,_=make_fixture(base/'second');second.alias='OTHER'
            options=model.Options([extracted,second],str(base/'merged'),name='Combined',
                                  acknowledge_outline_change=True,accept_primary_settings=True,saved_sources_confirmed=True)
            result=engine.merge(options)
            merged=sx.load(base/'merged/Combined.kicad_pcb')
            for tag,count in (('segment',4),('via',2),('zone',2),('footprint',2)):
                self.assertEqual(len(sx.children(merged,tag)),count)
            self.assertTrue((base/'merged/reports/report.json').exists() or result is not None)
            (base/'native-validation.json').write_text(json.dumps({'kicad_version':net.KiCadCLI().version,
                'section_report':plan['report'],'source_unchanged':True,'extracted_geometry_matches_source':True,
                'merged_counts':{tag:len(sx.children(merged,tag)) for tag in ('footprint','segment','via','zone','gr_line')},
                'native_merge_completed':True},indent=2),encoding='utf-8')

if __name__=='__main__':unittest.main()
