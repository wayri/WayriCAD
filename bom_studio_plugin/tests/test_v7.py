"""Captured asset closure, independent previews, catalogue search and export.
Fixtures are synthetic; a parsed round-trip is not a running KiCad host test.
"""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import base64,ctypes,ctypes.util,gzip,io,json,os,shutil,tempfile,unittest,zipfile,importlib.util
from test_v6 import EngFixture
from bomstudio import assetbundle as a, assetpreview as pv, catalogbrowse as cb, nativepreview as np, meshpreview as mp, partsdb as db, engineering as eng, cli
from bomstudio.sexpr import parse,quote,apply_edits
from bomstudio.native import BASE,Project
from bomstudio.engine import Workspace

WRL=b'''#VRML V2.0 utf8
DEF Body Shape { appearance Appearance { material Material { diffuseColor 0.13 0.25 0.38 } } geometry Box { size 1.6 0.8 0.45 } }
Transform { translation 0.7 0 0 children [ Shape { appearance Appearance { material Material { diffuseColor 0.75 0.77 0.78 } } geometry Box { size 0.25 0.84 0.5 } } ] }
Transform { translation -0.7 0 0 children [ USE Body ] }
'''

def zstd(raw):
 try:
  import zstandard
 except ImportError:
  name=ctypes.util.find_library('zstd')
  if not name:raise RuntimeError('Install the declared zstandard dependency to run embedded-asset tests.')
  z=ctypes.CDLL(name);z.ZSTD_compressBound.argtypes=[ctypes.c_size_t];z.ZSTD_compressBound.restype=ctypes.c_size_t;size=z.ZSTD_compressBound(len(raw));out=ctypes.create_string_buffer(size);source=ctypes.create_string_buffer(raw);z.ZSTD_compress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];z.ZSTD_compress.restype=ctypes.c_size_t;n=z.ZSTD_compress(out,size,source,len(raw),3);return out.raw[:n]
 return zstandard.ZstdCompressor(level=3).compress(raw)

def embedded(name,raw,checksum=None):
 return '(embedded_files (file (name '+quote(name)+') (type model) (data |\n'+base64.b64encode(zstd(raw)).decode()+'\n|) (checksum '+quote(checksum or a.sha(raw))+')))'

class Assets(EngFixture):
 @unittest.skipUnless(importlib.util.find_spec('zstandard'), 'Python Zstandard package not installed in this test interpreter')
 def test_python_decoder_does_not_require_system_library(self):
  with patch('ctypes.util.find_library',return_value=None),patch('ctypes.CDLL',side_effect=AssertionError('No host DLL should be loaded')):
   self.assertEqual(a.zstd_decode(zstd(WRL)),WRL)
 def test_explicit_workspace_library_overrides_installed_table(self):
  fp,_=self.setup_assets()
  cfg=self.dir/'config/kicad/10.0';cfg.mkdir(parents=True)
  installed=self.dir/'installed.pretty';installed.mkdir()
  (installed/fp.name).write_text('(footprint "Different" (pad "9" smd rect))',encoding='utf-8')
  (cfg/'fp-lib-table').write_text('(fp_lib_table (lib (name "Resistor_SMD") (type "KiCad") (uri '+quote(str(installed))+')))',encoding='utf-8')
  resolver=a.Resolver(self.ws)
  self.assertEqual(resolver.library_file('Resistor_SMD:R_0603_1608Metric','footprint')[0],fp.resolve())
 def setup_assets(self,uri='${KIPRJMOD}/models/body.wrl',extra=''):
  fp=self.footprint();folder=self.dir/'models';folder.mkdir(exist_ok=True);model=folder/'body.wrl';model.write_bytes(WRL)
  txt=fp.read_text();fp.write_text(txt[:-1]+'\n(model '+quote(uri)+' (offset (xyz 1 2 3)) (scale (xyz 1 2 1)) (rotate (xyz 0 0 90)))\n'+extra+'\n)');self.ws.save();return fp,model
 def harvest(self,**kw):
  plan=db.harvest([str(self.path)],**kw);self.assertFalse(plan['failures']);db.import_harvest(self.lib,plan,'IMPORT','Fixture author');pid=db.record_identity(self.row('R1')['fields']);return plan,self.lib.get(pid)
 def test_external_three_asset_capture(self):
  fp,model=self.setup_assets();plan,p=self.harvest();self.assertEqual({x['kind'] for x in p['assets']},{'symbol','footprint','model'});self.assertEqual(a.summary(p)['model_state'],'stored');self.assertEqual(a.read_blob(self.lib,a.sha(WRL)),WRL);self.assertIn(str(model),plan['sources']);self.assertTrue(self.lib.verify()['ok'])
 def test_transform_and_visibility_retained(self):
  self.setup_assets();_,p=self.harvest();m=a.select_set(p)['models'][0];self.assertEqual(m['offset'],[1,2,3]);self.assertEqual(m['scale'],[1,2,1]);self.assertEqual(m['rotation'],[0,0,90]);self.assertTrue(m['visible'])
 def test_multiple_models_same_file_dedup(self):
  fp,m=self.setup_assets(extra='(model "${KIPRJMOD}/models/body.wrl" (hide yes) (offset (xyz 4 5 6)))');_,p=self.harvest();s=a.select_set(p);self.assertEqual(len(s['models']),2);self.assertEqual(sum(x['kind']=='model' for x in p['assets']),1);self.assertFalse(s['models'][1]['visible'])
 def test_different_files_same_name_stored_separately(self):
  fp,m=self.setup_assets(extra='(model "${KIPRJMOD}/other/body.wrl")');o=self.dir/'other';o.mkdir();(o/'body.wrl').write_bytes(WRL+b'\n# different file\n');_,p=self.harvest();self.assertEqual(a.summary(p)['model'],2)
 def test_missing_model_reported(self):
  self.setup_assets(uri='${KIPRJMOD}/absent.step');_,p=self.harvest();self.assertEqual(a.summary(p)['model_state'],'missing');self.assertFalse(a.summary(p)['complete_references']);self.assertIn('does not exist',a.select_set(p)['models'][0]['error'])
 def test_unassigned_not_missing(self):
  self.footprint();self.ws.save();_,p=self.harvest();self.assertEqual(a.summary(p)['model_state'],'not_assigned')
 def test_legacy_requires_reharvest(self):
  p=self.part();self.assertEqual(a.summary(p)['model_state'],'not_captured')
 def test_scope_embedded_in_footprint(self):
  self.setup_assets(uri='kicad-embed://body.wrl',extra=embedded('body.wrl',WRL));_,p=self.harvest();self.assertEqual(a.summary(p)['model'],1);self.assertEqual(a.select_set(p)['models'][0]['embedded_name'],'body.wrl')
 def test_embedded_modern_mmh3(self):
  self.setup_assets(uri='kicad-embed://body.wrl',extra=embedded('body.wrl',WRL,a.murmur128(WRL)));_,p=self.harvest();self.assertEqual(a.summary(p)['model'],1)
 def test_embedded_legacy_mmh3(self):
  self.setup_assets(uri='kicad-embed://body.wrl',extra=embedded('body.wrl',WRL,a.murmur128(WRL,True)));_,p=self.harvest();self.assertEqual(a.summary(p)['model'],1)
 def test_embedded_bad_checksum_never_falls_back(self):
  self.setup_assets(uri='kicad-embed://body.wrl',extra=embedded('body.wrl',WRL,'0'*64));_,p=self.harvest();self.assertEqual(a.summary(p)['model'],0);self.assertIn('checksum',a.select_set(p)['issues'][-1]['message'])
 def test_embedded_owner_board_lookup(self):
  self.setup_assets(uri='kicad-embed://body.wrl');b=self.path.with_suffix('.kicad_pcb');b.write_text('(kicad_pcb (version 20260306) '+embedded('body.wrl',WRL)+')');plan,p=self.harvest();self.assertEqual(a.summary(p)['model'],1);self.assertIn(str(b),plan['sources'])
 def test_model_source_drift_blocks_import(self):
  fp,m=self.setup_assets();plan=db.harvest([str(self.path)]);m.write_bytes(WRL+b'\n')
  with self.assertRaises(ValueError):db.import_harvest(self.lib,plan,'IMPORT','Tester')
  self.assertEqual(self.lib.info()['parts'],0)
 def test_deleted_sources_do_not_break_previews_or_export(self):
  fp,m=self.setup_assets();_,p=self.harvest();fp.unlink();m.unlink();self.path.unlink();self.assertIn('<svg',pv.preview(self.lib,p['id'],'symbol')['svg']);self.assertGreater(pv.preview(self.lib,p['id'],'model')['triangle_count'],0);self.assertTrue(db.export_native_library(self.lib,[p['id']],require_complete=True)[0])
 def test_all_reference_native_export(self):
  self.setup_assets();_,p=self.harvest();raw,_,_=db.export_native_library(self.lib,[p['id']],require_complete=True)
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   ft=parse(z.read(next(x for x in z.namelist() if x.endswith('.kicad_mod'))).decode());link=ft.one('model').val();self.assertTrue(link.startswith('${KIPRJMOD}/WayriCAD.3dshapes/'));self.assertEqual(z.read(link.replace('${KIPRJMOD}/','')),WRL);self.assertEqual(a.xyz(ft.one('model').one('offset'),[]),[1,2,3]);manifest=json.loads(z.read('manifest.json'));self.assertTrue(manifest['complete_references']);self.assertTrue(all(a.sha(z.read(k))==h for k,h in manifest['files'].items()))
 def test_require_complete_refuses_missing_model(self):
  self.setup_assets(uri='missing.step');_,p=self.harvest()
  with self.assertRaises(ValueError):db.export_native_library(self.lib,[p['id']],require_complete=True)
 def test_partial_export_carries_warning(self):
  self.setup_assets(uri='missing.step');_,p=self.harvest();raw,_,_=db.export_native_library(self.lib,[p['id']])
  with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertFalse(json.loads(z.read('manifest.json'))['complete_references'])
 def test_wrong_set_rejected(self):
  self.setup_assets();_,p=self.harvest()
  with self.assertRaises(ValueError):a.describe(self.lib,p['id'],set_id='made-up')
 def test_download_checks_membership(self):
  self.setup_assets();_,p=self.harvest();other=self.part(MPN='unrelated')
  with self.assertRaises(ValueError):a.download_asset(self.lib,other['id'],a.sha(WRL))
 def test_original_download_byte_identical(self):
  self.setup_assets();_,p=self.harvest();raw,name,_=a.download_asset(self.lib,p['id'],a.sha(WRL));self.assertEqual(raw,WRL);self.assertTrue(name.endswith('.wrl'))
 def test_tampered_blob_preview_refused(self):
  self.setup_assets();_,p=self.harvest();self.lib.db.execute('UPDATE assets SET body=? WHERE hash=?',(b'tampered',a.sha(WRL)))
  with self.assertRaises(ValueError):pv.preview(self.lib,p['id'],'model')
  self.assertFalse(self.lib.verify()['ok'])
 def test_native_font_payload_removed(self):
  fake='(embedded_files (file (name "private.ttf") (type font) (data |AAAA|) (checksum "none")))';self.setup_assets(extra=fake);_,p=self.harvest();self.assertTrue(all(b'private.ttf' not in a.read_blob(self.lib,x['hash']) for x in p['assets']));self.assertNotIn('font',[x['kind'] for x in p['assets']])
 def test_path_alias(self):
  self.setup_assets(uri=':LEGACY:body.wrl');_,p=self.harvest(asset_options={'path_aliases':{'LEGACY':str(self.dir/'models')}});self.assertEqual(a.summary(p)['model'],1)
 def test_kicad_native_environment_path(self):
  self.setup_assets(uri='${KICAD10_3DMODEL_DIR}/body.wrl')
  with patch.dict(os.environ,{'KICAD10_3DMODEL_DIR':str(self.dir/'models')}):_,p=self.harvest()
  self.assertEqual(a.summary(p)['model'],1)
 def test_explicit_root_and_recursive_variable(self):
  self.setup_assets(uri='${ASSET}/body.wrl');_,p=self.harvest(asset_options={'variables':{'ASSET':'${ROOT}','ROOT':str(self.dir/'models')}});self.assertEqual(a.summary(p)['model'],1)
 def test_saved_project_variable_path_edit(self):
  self.setup_assets(uri='${MODELPATH}/body.wrl');self.ws.set_variables('project',{'MODELPATH':str(self.dir/'models')});self.ws.save();_,p=self.harvest();self.assertEqual(a.summary(p)['model'],1)
 def test_cyclic_path_variable_is_missing_not_wrong_file(self):
  self.setup_assets(uri='${A}/body.wrl');_,p=self.harvest(asset_options={'variables':{'A':'${B}','B':'${A}'}});self.assertIn('Cyclic',a.select_set(p)['models'][0]['error'])
 def test_metadata_only_does_not_claim_model_capture(self):
  self.setup_assets();_,p=self.harvest(capture_assets=False);self.assertEqual(p['assets'],[]);self.assertEqual(a.summary(p)['model_state'],'not_captured')
 def test_idempotent_model_import(self):
  self.setup_assets();plan,p=self.harvest();n=self.lib.info()['assets'];self.assertEqual(db.import_harvest(self.lib,plan,'IMPORT','Tester')['count'],0);self.assertEqual(self.lib.info()['assets'],n)
 def test_set_tamper_rejected_atomically(self):
  self.setup_assets();plan=db.harvest([str(self.path)]);part=next(x for x in plan['parts'] if x['asset_sets'][0].get('models'));part['asset_sets'][0]['models'][0]['offset']=[9,9,9];plan['fingerprint']=db.digest({k:v for k,v in plan.items() if k!='fingerprint'})
  with self.assertRaises(ValueError):db.import_harvest(self.lib,plan,'IMPORT','Tester')
  self.assertEqual(self.lib.info()['parts'],0);self.assertEqual(self.lib.info()['assets'],0)
 def test_asset_filter_and_numeric_catalogue_query(self):
  self.setup_assets();_,p=self.harvest();p=self.revise(p,fields={'Temp_Max':'176 F'})
  r=cb.search(self.lib,has_asset='all3',filters=[{'field':'Temp_Max','op':'<=','value':'80','unit':'C'}]);self.assertEqual(r['total'],1);self.assertEqual(r['items'][0]['id'],p['id']);self.assertTrue(r['fields'])
 def test_notes_search(self):
  p=self.revise(self.part(),notes='SpecialCryogenicCode');self.assertEqual(cb.search(self.lib,'SpecialCryogenicCode')['total'],1)
 def test_empty_numeric_does_not_become_zero(self):
  self.part(Temp_Max='');r=cb.search(self.lib,filters=[{'field':'Temp_Max','op':'<','value':'80','unit':'C'}]);self.assertEqual(r['total'],0);self.assertEqual(r['numeric_unknown']['Temp_Max'],1)
 def test_arbitrary_custom_property_filter(self):
  self.part(Subsystem='Harness');self.assertEqual(cb.search(self.lib,filters=[{'field':'Subsystem','op':'equals','value':'harness'}])['total'],1)
 def test_invalid_filters_fail_closed(self):
  for rules in ([{'field':'Temp_Max','op':'eval','value':'bad'}],[{'field':'Mass','op':'<','value':'unknown'}],[{'field':'Mass','op':'<','value':'1','exec':'oops'}]):
   with self.subTest(rules=rules),self.assertRaises(ValueError):cb.search(self.lib,filters=rules)
 def test_external_footprint_table(self):
  fp,m=self.setup_assets();(self.dir/'fp-lib-table').write_text('(fp_lib_table (lib (name "Resistor_SMD") (type "KiCad") (uri '+quote(str(fp.parent))+')))');plan,p=self.harvest();self.assertEqual(a.summary(p)['footprint'],1);self.assertIn(str(self.dir/'fp-lib-table'),plan['sources'])
 def test_saved_board_footprint_by_uuid(self):
  fp,m=self.setup_assets();r=self.row('R1');txt=fp.read_text().replace('(footprint "R_0603_1608Metric"','(footprint "Resistor_SMD:R_0603_1608Metric" (at 30 40 0) (path '+quote(r['id'])+')');board=self.path.with_suffix('.kicad_pcb');board.write_text('(kicad_pcb (version 20260306) '+txt+')');fp.unlink();_,p=self.harvest();s=a.select_set(p);self.assertEqual(s['footprint_representation'],'board-footprint');self.assertTrue(db.export_native_library(self.lib,[p['id']],choices={p['id']:s['id']},require_complete=True)[0])
 def test_backside_export_refused_not_mis_mirrored(self):
  with self.assertRaises(ValueError):a.normalize_footprint(b'(footprint "x" (layer "B.Cu") (at 1 2 90))')
 def test_stale_revision_preserves_old_assets(self):
  self.setup_assets();_,p=self.harvest();self.revise(p,fields={'Notes':'new metadata'});self.assertEqual(a.describe(self.lib,p['id'],1)['revision'],1);self.assertTrue(pv.preview(self.lib,p['id'],'footprint',1)['svg'])

class NativeDrawing(unittest.TestCase):
 def test_svg_symbol_pin_names_escaped(self):
  raw=b'(symbol "T" (symbol "T_1_1" (rectangle (start -2 2) (end 2 -2)) (pin input line (at -5 0 0) (length 3) (name "<script>" ) (number "1"))))';p=np.svg_preview(raw,'symbol');self.assertIn('&lt;script&gt;',p['svg']);self.assertNotIn('<script>',p['svg']);self.assertEqual(p['pins'][0]['number'],'1')
 def test_svg_arc_and_circle(self):
  p=np.svg_preview(b'(footprint "T" (layer "F.Cu") (fp_circle (center 0 0) (end 1 0) (layer "F.SilkS")) (fp_arc (start 1 0) (mid 0 1) (end -1 0) (layer "F.SilkS")))','footprint');self.assertIn('<circle',p['svg']);self.assertIn('<path',p['svg'])
 def test_layer_visibility(self):
  p=np.svg_preview(b'(footprint "T" (fp_line (start 0 0) (end 1 1) (layer "F.SilkS")))','footprint',layers=['F.Cu']);self.assertEqual(p['primitive_count'],0)
 def test_alternate_unit_selection(self):
  raw=b'(symbol "T" (symbol "T_1_1" (circle (center 0 0) (radius 1))) (symbol "T_2_1" (circle (center 0 0) (radius 3))))';a1=np.svg_preview(raw,'symbol');a2=np.svg_preview(raw,'symbol',unit=2);self.assertEqual(a1['units'],[1,2]);self.assertGreater(a2['bounds'][2],a1['bounds'][2])
 def test_unsupported_primitive_notice(self):
  p=np.svg_preview(b'(symbol "T" (symbol "T_1_1" (bezier (pts (xy 0 0)))))','symbol');self.assertTrue(p['warnings'])
 def test_nonfinite_coordinate_rejected(self):
  with self.assertRaises(ValueError):np.svg_preview(b'(footprint "T" (fp_line (start nan 0) (end 1 1)))','footprint')
 def test_inheritance_flatten(self):
  p='(symbol "Parent" (property "Value" "old") (symbol "Parent_1_1" (circle (center 0 0) (radius 2))))';c='(symbol "Child" (extends "Parent") (property "Value" "new"))';s=a.flatten_symbol(p,c);self.assertNotIn('extends',s);self.assertIn('Child_1_1',s);self.assertIn('"new"',s)

class MeshDrawing(unittest.TestCase):
 def test_vrml_transform_def_use(self):
  r=mp.vrml(WRL);self.assertEqual(r['triangle_count'],36);self.assertAlmostEqual(r['bounds'][0][0],-1.5)
 def test_vrml_reject_remote_inline(self):
  with self.assertRaises(ValueError):mp.vrml(b'#VRML V2.0 utf8\nInline { url ["https://bad.invalid/model"] }')
 def test_vrml_script_refused(self):
  with self.assertRaises(ValueError):mp.vrml(b'#VRML V2.0 utf8\nScript { url ["javascript:alert(1)"] }')
 def test_vrml_polygon_quad(self):
  r=mp.vrml(b'#VRML V2.0 utf8\nShape { geometry IndexedFaceSet { coord Coordinate { point [0 0 0,1 0 0,1 1 0,0 1 0] } coordIndex [0,1,2,3,-1] } }');self.assertEqual(r['triangle_count'],2)
 def test_vrml_invalid_index(self):
  with self.assertRaises(ValueError):mp.vrml(b'#VRML V2.0 utf8\nShape { geometry IndexedFaceSet { coord Coordinate { point [0 0 0] } coordIndex [0,1,99,-1] } }')
 def test_wrz_roundtrip(self):
  r=mp.convert(gzip.compress(WRL),'.wrz');self.assertEqual(r['triangle_count'],36)
 def test_zip_model_no_path_extraction(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('../../test.wrl',WRL)
  r=mp.convert(b.getvalue(),'.wrz');self.assertEqual(r['triangle_count'],36)
 def test_multi_file_compressed_model_refused(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('a.wrl',WRL);z.writestr('b.wrl',WRL)
  with self.assertRaises(ValueError):mp.convert(b.getvalue(),'.wrz')
 def test_ascii_stl(self):
  r=mp.stl(b'solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid');self.assertEqual(r['triangle_count'],1)
 def test_obj_concave_ear_clipping(self):
  r=mp.obj(b'v 0 0 0\nv 2 0 0\nv 2 2 0\nv 1 1 0\nv 0 2 0\nf 1 2 3 4 5');self.assertEqual(r['triangle_count'],3)
 @unittest.skipUnless(importlib.util.find_spec('OCP'),'Optional OCP unavailable')
 def test_actual_opencascade_step(self):
  from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
  from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'shape.step';w=STEPControl_Writer();w.Transfer(BRepPrimAPI_MakeBox(1,2,3).Shape(),STEPControl_AsIs);w.Write(str(f));r=mp.convert(f.read_bytes(),'.step');self.assertEqual(r['triangle_count'],12);self.assertEqual(r['bounds'],[[0.,0.,0.],[1.,2.,3.]])
 def test_triangle_limit(self):
  with patch.object(mp,'MAX_TRIANGLES',0),self.assertRaises(ValueError):mp.vrml(WRL)
 def test_bounded_unknown_format(self):
  with self.assertRaises(ValueError):mp.convert(b'anything','.dll')

if __name__=='__main__':unittest.main()
