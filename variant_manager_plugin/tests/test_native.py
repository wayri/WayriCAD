"""Opt-in KiCad CLI serialization and net identity checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from variant_manager_plugin.wayri_variants import service as S

@unittest.skipUnless(os.environ.get('VARIANT_NATIVE') == '1', 'Opt-in KiCad 10 native fixture')
class NativeVariants(unittest.TestCase):
    def test_hierarchy_native_netlist_and_variant_bom(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'project_fusion_plugin/tests'))
        from test_sections_native import make_fixture, sx
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/'source';make_fixture(home)
            project=home/'board.kicad_pro'
            project.write_text(json.dumps({'schematic':{'variants':[]}}))
            for path in home.glob('*.kicad_sch'):
                text=path.read_text().replace('20250114','20260306')
                path.write_text(text)
            before=S.inventory(project)
            row=next(r for r in before['objects'] if r['kind']=='symbol')
            plan=S.preview(project,[{'op':'create','name':'Assembly'},
                {'op':'edit','variant':'Assembly','keys':[row['key']],
                 'fields':{'Value':'22k'},'flags':{'dnp':True}},
                {'op':'duplicate','source':'Assembly','name':'Second'},
                {'op':'promote','source':'Assembly','preserve_old':'Original'}])
            board=project.with_suffix('.kicad_pcb').read_bytes()
            S.apply(plan,editors_closed=True)
            cli=os.environ.get('KICAD_CLI','C:/Program Files/KiCad/10.0/bin/kicad-cli.exe')
            output=home/'after.xml'
            result=subprocess.run([cli,'sch','export','netlist','--format','kicadxml','-o',str(output),str(project.with_suffix('.kicad_sch'))],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            import xml.etree.ElementTree as ET
            xml=ET.parse(output)
            self.assertEqual(xml.findtext('.//comp/value'),'22k')
            self.assertEqual(xml.find('.//comp').attrib['ref'],'R1')
            self.assertEqual(board,project.with_suffix('.kicad_pcb').read_bytes())
            self.assertEqual(S.inventory(project)['objects'][1]['states']['Original']['fields']['Value'],'10k')
            import csv
            for variant, expected_value, expected_dnp in [('Assembly','22k','dnp'),('Original','10k','')]:
                bom = home/(variant+'.csv')
                result=subprocess.run([cli,'sch','export','bom','--variant',variant,
                    '--fields','Reference,Value,DNP,EXCLUDE_FROM_BOM',
                    '--labels','Reference,Value,DNP,Excluded','-o',str(bom),
                    str(project.with_suffix('.kicad_sch'))],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                with bom.open(encoding='utf-8-sig',newline='') as stream:
                    rows=list(csv.DictReader(stream))
                self.assertEqual(rows[0]['Value'],expected_value)
                self.assertEqual(rows[0]['DNP'].lower(),expected_dnp)
            # Native PDF parsing traverses root + child sheet and detects malformed tokens.
            result=subprocess.run([cli,'sch','export','pdf','-o',str(home/'after.pdf'),str(project.with_suffix('.kicad_sch'))],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertGreater((home/'after.pdf').stat().st_size,1000)

if __name__=='__main__': unittest.main()
