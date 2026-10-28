"""Typed export custody and actual upstream writer/consumer acceptance."""
import ast
import dataclasses
import io
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose

from quick_emerge_plugin.advanced_exports import (parse_dxf_heights_mm,export_dxf_sheets,export_optycal_farfield,
                                                 export_live_outputs,publish_exports,require_export_dependencies,read_optycal_msgpack)
from quick_emerge_plugin.model import source_identity,config_digest


QA_CONSUMER=Path(__file__).resolve().parents[2]/'.validation/quick-emerge-v2/exports/qa/FarfieldDataset-official.py'
QA_CONSUMER_SHA256='e1db4c536eb807c4290f65eb0fe91de6c15286251333ea759fcab31158f23836'


def official_consumer():
    """Execute only the exact pinned public consumer classes, unchanged.

    QA-only source/its license and primary URL are retained in .validation.
    No external package entry point or GUI module is imported or modified.
    """
    import msgpack,msgpack_numpy
    from scipy.interpolate import RegularGridInterpolator
    import types,typing
    source=QA_CONSUMER.read_bytes()
    if hashlib.sha256(source).hexdigest()!=QA_CONSUMER_SHA256:raise ValueError('Pinned official Optycal QA source changed')
    tree=ast.parse(source.decode('utf-8'))
    classes=[node for node in tree.body if isinstance(node,ast.ClassDef) and node.name in ('PortModeExcitation','FarfieldDataset')]
    if len(classes)!=2:raise ValueError('Official consumer classes missing')
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    module=ast.fix_missing_locations(ast.Module(body=[future]+classes,type_ignores=[]))
    name='_quick_emerge_pinned_optycal_qa'
    import sys
    namespace=types.ModuleType(name);sys.modules[name]=namespace
    namespace.__dict__.update({'np':np,'RegularGridInterpolator':RegularGridInterpolator,'dataclass':dataclasses.dataclass,'io':io,'msgpack':msgpack,'msgpack_numpy':msgpack_numpy,'Path':Path,'Optional':typing.Optional,'Sequence':typing.Sequence,'Union':typing.Union,'BinaryIO':typing.BinaryIO})
    exec(compile(module,str(QA_CONSUMER),'exec'),namespace.__dict__)
    return namespace.FarfieldDataset


class ExportContractTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[2]/'.validation/quick-emerge-v2/exports';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(self.temp.name)
        self.board=self.root/'source.kicad_pcb';self.board.write_text('(kicad_pcb)');self.source=source_identity(self.board)
    def tearDown(self):self.temp.cleanup()

    def test_literal_heights_and_rejection(self):
        self.assertEqual(parse_dxf_heights_mm('-1, 0, +1.2e-3'),[-1,0,.0012])
        self.assertEqual(parse_dxf_heights_mm([0,-1]),[0,-1])
        for value in ('0,0','1+2','nan','inf','__import__("os")','',True,[False],[2001],list(range(9))):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_dxf_heights_mm(value)

    def manifest(self):
        stage=self.root/'export-stage-owned';stage.mkdir()
        path=stage/'geometry-sheet-01.dxf';path.write_bytes(b'exported geometry')
        return {'schema':1,'state':'staged','source':self.source,'config_sha256':'a'*64,'artifacts':[{'path':'exports/geometry-sheet-01.dxf','staged_path':'export-stage-owned/geometry-sheet-01.dxf','bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}

    def test_publish_checks_exact_bytes_and_source_then_cleans_only_empty_staging(self):
        manifest=self.manifest();published=publish_exports(self.root,manifest)
        self.assertIs(published,manifest);self.assertEqual(manifest['state'],'published')
        self.assertNotIn('staged_path',manifest['artifacts'][0])
        self.assertEqual((self.root/'exports/geometry-sheet-01.dxf').read_bytes(),b'exported geometry')
        self.assertFalse((self.root/'export-stage-owned').exists())
        with self.assertRaises(ValueError):publish_exports(self.root,manifest)

    def test_stale_or_tampered_staging_is_not_published(self):
        manifest=self.manifest()
        staged=self.root/manifest['artifacts'][0]['staged_path'];staged.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'changed'):publish_exports(self.root,manifest)
        self.assertFalse((self.root/'exports').exists())
        staged.write_bytes(b'exported geometry');self.board.write_text('(changed)')
        with self.assertRaisesRegex(ValueError,'changed'):publish_exports(self.root,manifest)
        self.assertTrue(staged.exists())

    def test_publish_never_overwrites_and_rejects_traversal(self):
        manifest=self.manifest();folder=self.root/'exports';folder.mkdir();target=folder/'geometry-sheet-01.dxf';target.write_bytes(b'preexisting')
        with self.assertRaisesRegex(ValueError,'already exists'):publish_exports(self.root,manifest)
        self.assertEqual(target.read_bytes(),b'preexisting')
        manifest['artifacts'][0]['path']='../geometry.dxf'
        with self.assertRaisesRegex(ValueError,'inside'):publish_exports(self.root,manifest)

    def test_failed_multifile_publication_rolls_back_only_new_links(self):
        manifest=self.manifest();second=self.root/'export-stage-owned/other.msgpack';second.write_bytes(b'field')
        manifest['artifacts'].append({'path':'exports/other.msgpack','staged_path':'export-stage-owned/other.msgpack','bytes':5,'sha256':hashlib.sha256(b'field').hexdigest()})
        import os
        original=os.link;count=[0]
        def fail_second(*args):
            count[0]+=1
            if count[0]==2:raise OSError('simulated publication failure')
            return original(*args)
        with patch('quick_emerge_plugin.advanced_exports.os.link',fail_second),self.assertRaises(OSError):publish_exports(self.root,manifest)
        self.assertFalse((self.root/'exports/geometry-sheet-01.dxf').exists())
        self.assertTrue((self.root/'export-stage-owned/geometry-sheet-01.dxf').exists())
        self.assertTrue(second.exists());self.assertEqual(manifest['state'],'staged')


    @unittest.skipUnless(importlib.util.find_spec('msgpack_numpy'),'MsgPack NumPy dependency required')
    def test_object_array_descriptor_never_reaches_pickle_loader(self):
        import msgpack
        path=self.root/'untrusted.msgpack'
        payloads=[{b'nd':True,b'kind':b'O',b'type':'|O',b'shape':[1],b'data':b'not a pickle'},
                  {b'nd':True,b'kind':b'V',b'type':[['nested','|O']],b'shape':[1],b'data':b'not a pickle'},
                  {b'nd':False,b'type':'|O',b'data':b'not a pickle'},
                  {b'nd':True,b'type':[['nested',[['object','|O']]]],b'shape':[1],b'data':b'not a pickle'}]
        for payload in payloads:
            with self.subTest(payload=payload):
                path.write_bytes(msgpack.packb(payload,use_bin_type=True))
                with patch('msgpack_numpy.pickle.loads',side_effect=AssertionError('unsafe object decoder called')) as loader:
                    with self.assertRaisesRegex(ValueError,'Object|numeric'):read_optycal_msgpack(path)
                    loader.assert_not_called()


    def test_unrequested_exports_do_not_import_optional_dependencies(self):
        self.assertIsNone(export_live_outputs(None,None,{'advanced':{}},None,self.root,self.source,'unused'))
        require_export_dependencies({'advanced':{}})
        with self.assertRaises(ValueError):require_export_dependencies({'advanced':{'export_dxf':1}})

    @unittest.skipUnless(importlib.util.find_spec('emerge') and importlib.util.find_spec('ezdxf'),'Actual EMerge dxf extra required')
    def test_real_dxf_sheet_roundtrip_metres_height_and_no_solid_slice(self):
        import emerge as em
        import ezdxf
        model=em.Simulation('DXFSheetAcceptance');model.mw.set_frequency_range(1e9,2e9,2)
        sheet=em.geo.XYPlate(.010,.004,position=(-.005,-.002,0)).set_material(em.lib.PEC)
        air=em.geo.Box(.020,.014,.010,position=(-.010,-.007,-.005)).background()
        model.commit_geometry();model.mesher.set_face_size(sheet,.002);model.generate_mesh()
        stage=self.root/'stage';stage.mkdir()
        outputs=export_dxf_sheets(model,stage,[0]);self.assertEqual(len(outputs),1)
        path,metadata=outputs[0];doc=ezdxf.readfile(path)
        self.assertEqual(doc.header['$INSUNITS'],6)
        entities=list(doc.modelspace());self.assertEqual(len(entities),1)
        points=np.asarray(list(entities[0].get_points('xy')))
        assert_allclose(points.min(axis=0),[-.005,-.002],atol=1e-10)
        assert_allclose(points.max(axis=0),[.005,.002],atol=1e-10)
        self.assertEqual(entities[0].dxf.elevation,0)
        self.assertEqual(metadata['coordinate_unit'],'m')
        empty=self.root/'empty';empty.mkdir()
        with self.assertRaisesRegex(ValueError,'No actual planar sheet'):export_dxf_sheets(model,empty,[1])

    @unittest.skipUnless(importlib.util.find_spec('emerge') and importlib.util.find_spec('msgpack_numpy') and QA_CONSUMER.exists(),'Actual EMerge and pinned official Optycal QA reader required')
    def test_real_optycal_official_consumer_and_distinct_excitations_restored(self):
        import emerge as em
        FarfieldDataset=official_consumer()
        from quick_emerge_plugin.backend import build_geometry
        from quick_emerge_plugin.qualification import smoke_configs
        c=smoke_configs()[0][1];c.update(points=2,field_grid=3)
        model,air,ports,widths,thickness=build_geometry(em,np,c)
        model.generate_mesh()
        for i,(port,width) in enumerate(zip(ports,widths),1):model.mw.bc.LumpedPort(port,i,width=width,height=thickness,direction=em.ZAX,Z0=c['z0_ohm'])
        boundary=air.boundary();model.mw.bc.AbsorbingBoundary(boundary)
        data=model.mw.run_sweep()
        fields=list(data.field.iter())
        for field in fields:field.set_excitations(.3,.7j)
        original=[deepcopy(field.excitation) for field in fields]
        stage=self.root/'stage';stage.mkdir()
        path,metadata=export_optycal_farfield(data,boundary,stage)
        restored=FarfieldDataset.from_msgpack(path)
        self.assertEqual(restored.n_excitations,2);self.assertEqual(restored.n_frequencies,2)
        self.assertEqual(metadata['format'],'Official Optycal FarfieldDataset MsgPack')
        for field,previous in zip(fields,original):self.assertEqual(field.excitation,previous)
        # Independent actual public field excitation loop: detect b9 surface
        # export's duplicate-excitation bug rather than merely load a writer.
        raw=restored.raw;th=raw['thetas'];ph=raw['phis']
        field=fields[0];independent=[]
        try:
            for index in range(2):
                weights=[0,0];weights[index]=1;field.set_excitations(*weights)
                ff=field.farfield_3d(boundary,th,ph)
                independent.append(np.asarray(ff.E.F))
                assert_allclose(raw['solutions'][0]['fields'][index]['E'],ff.E.F,rtol=1e-10,atol=1e-12)
                assert_allclose(raw['solutions'][0]['fields'][index]['H'],ff.H.F,rtol=1e-10,atol=1e-12)
        finally:field.excitation=original[0]
        self.assertGreater(np.linalg.norm(independent[0]-independent[1]),1e-8*np.linalg.norm(independent[0]))
        self.assertEqual(field.excitation,original[0])


if __name__=='__main__':unittest.main()
