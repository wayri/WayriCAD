"""Import custody contracts and opt-in actual EMerge parser/mesh acceptance."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from quick_emerge_plugin.advanced_imports import (import_identity,verify_import,build_import)


def _real8(value):
    if value==0:return bytes(8)
    sign=0x80 if value<0 else 0;value=abs(value);exponent=64
    while value>=1:value/=16;exponent+=1
    while value<1/16:value*=16;exponent-=1
    return bytes([sign|exponent])+int(value*(1<<56)).to_bytes(7,'big')


def gds_fixture(path):
    def rec(kind,dtype,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,kind,dtype)+payload
    data=rec(0,2,struct.pack('>h',600))+rec(1,2,struct.pack('>12h',*([2026,1,1,0,0,0]*2)))
    data+=rec(2,6,b'REPORT_IMPORT_FIXTURE')+rec(3,5,_real8(.001)+_real8(1e-6))
    data+=rec(5,2,struct.pack('>12h',*([2026,1,1,0,0,0]*2)))+rec(6,6,b'TOP')
    data+=rec(8,0)+rec(13,2,struct.pack('>h',1))+rec(14,2,struct.pack('>h',0))
    data+=rec(16,3,struct.pack('>10i',0,0,1000,0,1000,1000,0,1000,0,0))+rec(17,0)+rec(7,0)+rec(4,0)
    path.write_bytes(data)


def gds_recipe():
    return {'schema':1,'reviewed':True,'units':'embedded','gds_db_unit_m':1e-6,
            'materials':{'PEC':{'type':'pec'}},'layers':[{'layer':1,'datatype':0,'name':'Metal','z_m':0,'thickness_m':.0002,'material':'PEC'}]}



def gerber_fixture(root):
    root.mkdir(parents=True,exist_ok=True)
    text='%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\n%ADD10C,0.600*%\nD10*\nX01000000Y01000000D03*\nM02*\n'
    for name in ('top.gbr','bottom.gbr'):(root/name).write_text(text,encoding='ascii')
    (root/'holes.drl').write_text('M48\n;FILE_FORMAT=3:3\nMETRIC,TZ\nT1C0.200\n%\nT1\nX1.000Y1.000\nM30\n',encoding='ascii')
    return {'schema':1,'reviewed':True,'units':'mm','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},
            'copper_layers':[{'file':'bottom.gbr','index':0,'name':'Bottom'},{'file':'top.gbr','index':1,'name':'Top'}],
            'substrate':{'thickness_mm':1,'material':'FR4','outline_mm':[[0,0],[2,0],[2,2],[0,2]]},
            'trace_material':'Cu','trace_thickness_um':35,'drills':[{'file':'holes.drl','plated':True}]}


def xml_fixture(root):
    text='<Stackup schemaVersion="3.1"><Materials><Material Name="FR4" Type="Dielectric" Permittivity="4.2" DielectricLossTangent="0.02"/></Materials><ELayers LengthUnit="mm"><Dielectrics><Dielectric Name="Substrate" Material="FR4" Zmin="-1" Zmax="0"/></Dielectrics><Layers><Layer Name="M1" Type="conductor" Material="PEC" Layer="1" Zmin="0" Zmax="0.2"/></Layers></ELayers></Stackup>'
    (root/'stack.xml').write_text(text,encoding='utf-8')
    return {'schema':1,'reviewed':True,'units':'embedded','xml_file':'stack.xml','layer_names':['M1'],'material_names':['FR4','AIR'],'gds_db_unit_m':1e-6}


def odb_fixture(root):
    (root/'matrix').mkdir(parents=True,exist_ok=True)
    matrix='STEP {\nCOL=1\nNAME=board\nID=1\n}\n'
    for row,name,kind in [(1,'top','SIGNAL'),(2,'core','DIELECTRIC'),(3,'bottom','SIGNAL')]:
        matrix+='LAYER {\nROW='+str(row)+'\nCONTEXT=BOARD\nTYPE='+kind+'\nNAME='+name+'\nPOLARITY=POSITIVE\nID='+str(row)+'\n}\n'
    (root/'matrix/matrix').write_text(matrix,encoding='ascii')
    step=root/'steps/board';step.mkdir(parents=True,exist_ok=True)
    def square(x0,y0,x1,y1):return 'UNITS=MM\nS P 0\nOB '+str(x0)+' '+str(y0)+' I\nOS '+str(x1)+' '+str(y0)+'\nOS '+str(x1)+' '+str(y1)+'\nOS '+str(x0)+' '+str(y1)+'\nOS '+str(x0)+' '+str(y0)+'\nOE\nSE\n'
    (step/'profile').write_text(square(0,0,2,2),encoding='ascii')
    for name in ('top','bottom'):
        layer=step/'layers'/name;layer.mkdir(parents=True,exist_ok=True)
        (layer/'features').write_text(square(.3,.3,1.7,1.7),encoding='ascii')
    return {'schema':1,'reviewed':True,'units':'embedded','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},'substrate_material':'FR4','trace_material':'Cu','stack_thickness_m':[.000035,.001,.000035],'layer_names':['top','bottom'],'reverse_stack':False,'generate_vias':False}


class ImportContractTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[2]/'.validation/quick-emerge-v2/imports'
        scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch)
        self.root=Path(self.temp.name)
        self.gds=self.root/'square.gds';gds_fixture(self.gds)
        self.recipe=self.root/'review.json';self.write_recipe(gds_recipe())
    def tearDown(self):self.temp.cleanup()
    def write_recipe(self,data):self.recipe.write_text(json.dumps(data),encoding='utf-8')
    def advanced(self,kind='gds',path=None):
        identity=import_identity(kind,path or self.gds,self.recipe)
        return {'import_kind':kind,'import_path':str(path or self.gds),'import_recipe_path':str(self.recipe),'import_sha256':identity['sha256']}

    def test_identity_contains_exact_file_bytes_and_recipe(self):
        identity=import_identity('gds',self.gds,self.recipe)
        self.assertEqual(identity['files'][0]['sha256'],hashlib.sha256(self.gds.read_bytes()).hexdigest())
        self.assertEqual(identity['files'][0]['relative_path'],'square.gds')
        self.assertEqual(identity['recipe_sha256'],hashlib.sha256(self.recipe.read_bytes()).hexdigest())
        self.assertEqual(verify_import(self.advanced()),identity)
        original=identity['sha256'];self.gds.write_bytes(self.gds.read_bytes()+b'\0\0')
        self.assertNotEqual(import_identity('gds',self.gds,self.recipe)['sha256'],original)

    def test_hash_covers_review_changes_and_stale_inputs(self):
        a=self.advanced();r=gds_recipe();r['layers'][0]['thickness_m']=.0003;self.write_recipe(r)
        with self.assertRaisesRegex(ValueError,'changed'):verify_import(a)
        r['reviewed']=False;self.write_recipe(r)
        with self.assertRaisesRegex(ValueError,'reviewed'):import_identity('gds',self.gds,self.recipe)

    def test_reject_unreviewed_units_unknown_material_and_zero_thickness_finite_material(self):
        recipes=[]
        r=gds_recipe();r['units']='guess';recipes.append(r)
        r=gds_recipe();r['gds_db_unit_m']=True;recipes.append(r)
        r=gds_recipe();r['layers'][0]['material']='Missing';recipes.append(r)
        r=gds_recipe();r['script']='run.py';recipes.append(r)
        r=gds_recipe();r['materials']['PEC']={'type':'conductor','conductivity_s_m':5.8e7};r['layers'][0]['thickness_m']=0;recipes.append(r)
        for r in recipes:
            with self.subTest(recipe=r),self.assertRaises(ValueError):
                self.write_recipe(r);import_identity('gds',self.gds,self.recipe)

    def test_whole_directory_manifest_detects_added_odb_file(self):
        odb=self.root/'odb';odb.mkdir();(odb/'matrix').write_text('reviewed source')
        self.write_recipe({'schema':1,'reviewed':True,'units':'embedded','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},'substrate_material':'FR4','trace_material':'Cu','stack_thickness_m':[.000035,.001,.000035],'layer_names':['top','bottom'],'reverse_stack':False,'generate_vias':False})
        a=self.advanced('odb',odb)
        (odb/'extra').write_text('new source member')
        with self.assertRaisesRegex(ValueError,'changed'):verify_import(a)

    def test_gerber_unit_and_drill_scope(self):
        fab=self.root/'fabrication';fab.mkdir()
        for name in ('top.gbr','bottom.gbr'):(fab/name).write_text('%FSLAX46Y46*%\n%MOMM*%\nM02*')
        (fab/'holes.drl').write_text('M48\nMETRIC\nT1C0.3\n%\nT1\nX0.5Y0.5\nM30')
        r={'schema':1,'reviewed':True,'units':'mm','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},
           'copper_layers':[{'file':'bottom.gbr','index':0,'name':'Bottom'},{'file':'top.gbr','index':1,'name':'Top'}],
           'substrate':{'thickness_mm':1,'material':'FR4','outline_mm':[[0,0],[1,0],[1,1],[0,1]]},
           'trace_material':'Cu','trace_thickness_um':35,'drills':[{'file':'holes.drl','plated':True}]}
        self.write_recipe(r);identity=import_identity('gerber',fab,self.recipe)
        self.assertEqual(len(identity['files']),3)
        (fab/'holes.drl').write_text('M48\nMETRIC\nG85X1Y1\nM30')
        with self.assertRaisesRegex(ValueError,'slots'):import_identity('gerber',fab,self.recipe)
        (fab/'holes.drl').write_text('M48\nINCH\nM30')
        with self.assertRaisesRegex(ValueError,'unit'):import_identity('gerber',fab,self.recipe)
        r['copper_layers'][0]['file']='../square.gds';self.write_recipe(r)
        with self.assertRaisesRegex(ValueError,'outside'):import_identity('gerber',fab,self.recipe)

    def test_xml_literal_only_and_manifest(self):
        xml=self.root/'stack.xml'
        xml.write_text('<Stackup schemaVersion="3.1"><ELayers LengthUnit="um"/></Stackup>')
        r={'schema':1,'reviewed':True,'units':'embedded','xml_file':'stack.xml','layer_names':['M1'],'material_names':['AIR','Cu'],'gds_db_unit_m':1e-6}
        self.write_recipe(r)
        identity=import_identity('gds_xml',self.gds,self.recipe)
        self.assertEqual(len(identity['files']),2)
        xml.write_text('<Stackup schemaVersion="3.1"><ELayers Value="=2**100000000"/></Stackup>')
        with self.assertRaisesRegex(ValueError,'literal'):import_identity('gds_xml',self.gds,self.recipe)
        xml.write_text('<!DOCTYPE Stackup [<!ENTITY x "injected">]><Stackup schemaVersion="3.1"/>')
        with self.assertRaisesRegex(ValueError,'DTD'):import_identity('gds_xml',self.gds,self.recipe)


    @unittest.skipUnless(importlib.util.find_spec('emerge'),'Actual EMerge solver runtime required')
    def test_native_gds_geometry_dimensions_and_tetrahedral_mesh(self):
        import emerge as em
        import gmsh
        model=em.Simulation('GDSImportAcceptance')
        model.mw.set_frequency_range(1e9,1.1e9,2)
        model.mw.set_resolution(.3)
        imported=build_import(em,self.advanced())
        self.assertEqual(len(imported['objects']),1)
        self.assertEqual(len(imported['conductors']),1)
        bounds=em.geo.bounding_box()
        for actual,expected in zip(bounds,[0,.001,0,.001,0,.0002]):
            self.assertAlmostEqual(float(actual),expected,delta=2e-7)
        em.geo.open_region(.0005,.0005,.0005)
        model.commit_geometry()
        model.mesher.set_boundary_size(imported['objects'][0],.0003)
        model.generate_mesh()
        nodes,_,_=gmsh.model.mesh.getNodes()
        _,elements,_=gmsh.model.mesh.getElements(3)
        self.assertGreater(len(nodes),0)
        self.assertGreater(sum(map(len,elements)),0)
        self.assertEqual(verify_import(self.advanced())['sha256'],imported['identity']['sha256'])


    def _native_import_mesh(self,kind,path,recipe,expected_bounds):
        import emerge as em
        import gmsh
        self.write_recipe(recipe)
        model=em.Simulation('FabricationImportAcceptance')
        model.mw.set_frequency_range(1e9,1.1e9,2);model.mw.set_resolution(.3)
        imported=build_import(em,self.advanced(kind,path))
        self.assertGreater(len(imported['objects']),0)
        self.assertGreater(len(imported['conductors']),0)
        bounds=em.geo.bounding_box()
        for actual,expected in zip(bounds,expected_bounds):self.assertAlmostEqual(float(actual),expected,delta=3e-7)
        em.geo.open_region(.0005,.0005,.0005);model.commit_geometry()
        for obj in imported['objects']:model.mesher.set_boundary_size(obj,.0004)
        model.generate_mesh()
        nodes,_,_=gmsh.model.mesh.getNodes();_,elements,_=gmsh.model.mesh.getElements(3)
        self.assertGreater(len(nodes),0);self.assertGreater(sum(map(len,elements)),0)
        self.assertEqual(verify_import(self.advanced(kind,path))['sha256'],imported['identity']['sha256'])
        return imported

    @unittest.skipUnless(importlib.util.find_spec('emcad') and importlib.util.find_spec('pygerber'),'Actual EMerge cad extra required')
    def test_native_gerber_excellon_geometry_and_mesh(self):
        path=self.root/'fab';recipe=gerber_fixture(path)
        imported=self._native_import_mesh('gerber',path,recipe,[0,.002,0,.002,-.001,.000035])
        self.assertGreaterEqual(len(imported['conductors']),3)
        self.assertEqual(imported['objects'][0].material.name,'FR4')

    @unittest.skipUnless(importlib.util.find_spec('emcad') and importlib.util.find_spec('emerge'),'Actual EMerge cad extra required')
    def test_native_gds_xml_stack_geometry_and_mesh(self):
        recipe=xml_fixture(self.root)
        imported=self._native_import_mesh('gds_xml',self.gds,recipe,[0,.001,0,.001,-.001,.0002])
        self.assertEqual(len(imported['objects']),2)
        self.assertEqual(imported['objects'][1].material.name,'FR4')

    @unittest.skipUnless(importlib.util.find_spec('emcad') and importlib.util.find_spec('emerge'),'Actual EMerge cad extra required')
    def test_native_odb_geometry_and_mesh(self):
        path=self.root/'odb';recipe=odb_fixture(path)
        imported=self._native_import_mesh('odb',path,recipe,[0,.002,0,.002,0,.001])
        self.assertEqual(len(imported['conductors']),2)
        self.assertEqual(imported['objects'][0].material.name,'FR4')

    def test_missing_optional_dependency_is_actionable_and_no_fake_geometry(self):
        from types import SimpleNamespace
        em=SimpleNamespace(lib=SimpleNamespace(PEC=object()),Material=lambda **kw:kw)
        a=self.advanced()
        with patch('quick_emerge_plugin.advanced_imports.importlib.import_module',side_effect=ImportError('absent')):
            with self.assertRaisesRegex(RuntimeError,'public import APIs'):build_import(em,a)


if __name__=='__main__':unittest.main()
