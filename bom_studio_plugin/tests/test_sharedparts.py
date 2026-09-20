"""Shared catalogue, workspace-only choices, and temporary global-table tests."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import unittest
import zipfile
import http.client
import threading

from test_v6 import EngFixture
import test_v7 as asset_fixture
from bomstudio import sharedparts as sp, partsdb, assembler_export as ae
from bomstudio.engine import Workspace
from bomstudio.native import Project, BASE
from bomstudio.sexpr import parse
from bomstudio.server import Server


class SharedParts(EngFixture):
    def app(self):
        return SimpleNamespace(workspace=self.ws, library_path=str(self.lib.root))

    def test_search_specs_and_unknowns(self):
        p=self.part(Dielectric='X7R')
        result=sp.suggestions(self.lib,p['fields'],'X7R')
        self.assertEqual(result['items'][0]['id'],p['id'])
        self.assertIn('Voltage',result['items'][0]['unknown'])
        self.assertIn('Not established',result['items'][0]['qualification'])

    def test_regex_and_invalid_regex(self):
        p=self.part(MPN='STM32F401',Manufacturer='Synthetic',Description='IC STM32')
        self.assertEqual(len(sp.suggestions(self.lib,{},'^IC.*|STM32.*',True)['items']),1)
        for regex in ('(a+)+$', 'a.*a.*', r'\1', 'x{100}', '[', 'a|'):
            with self.subTest(regex=regex),self.assertRaises(ValueError):sp.bounded_regex(regex)

    def test_blocked_candidates_hidden(self):
        p=self.part();self.revise(p,status='blocked')
        self.assertEqual(sp.suggestions(self.lib,p['fields'])['items'],[])

    def test_differences_not_approved(self):
        p=self.part(Value='22k')
        row=self.row('R1');r=sp.suggestions(self.lib,row['fields'])['items'][0]
        self.assertTrue(any(d['field']=='Value' for d in r['differences']))

    def test_plugin_only_choice_persists_undo_without_native_change(self):
        p=self.part();row=self.row('R1');app=self.app()
        before={f:f.read_bytes() for f in self.ws.project.documents}
        fields=dict(row['fields'])
        body={'component':row['id'],'id':p['id'],'revision':p['revision'],'note':'Needs pin review'}
        sp.dispatch(app,'choose',body)
        self.assertEqual(self.row('R1')['fields'],fields)
        self.ws.save();reload=Workspace(Project(self.path))
        self.assertEqual(len(reload.state['engineering']['shared_alternates']),1)
        self.assertTrue(all(f.read_bytes()==v for f,v in before.items()))
        self.ws.undo();self.assertFalse(self.ws.state.get('engineering',{}).get('shared_alternates'))

    def test_stale_choice_refused(self):
        p=self.part();self.revise(p,tags=['new'])
        with self.assertRaisesRegex(ValueError,'changed'):
            sp.dispatch(self.app(),'choose',{'component':self.row('R1')['id'],'id':p['id'],'revision':1})

    def test_clear_is_undoable(self):
        p=self.part();app=self.app();component=self.row('R1')['id']
        sp.dispatch(app,'choose',{'component':component,'id':p['id'],'revision':p['revision']})
        sp.dispatch(app,'clear',{'component':component})
        self.assertFalse(self.ws.state['engineering']['shared_alternates'])
        self.ws.undo();self.assertEqual(len(self.ws.state['engineering']['shared_alternates']),1)

    def test_authenticated_routes_and_bundled_script(self):
        app=self.app();app.token='fixture-token';app.link=SimpleNamespace(close=lambda:None);app.lock=threading.RLock()
        server=Server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(path,auth=False):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
            headers={'X-Bom-Token':app.token} if auth else {}
            if path.startswith('/api/'):
                headers['Content-Type']='application/json';c.request('POST',path,'{}',headers)
            else:c.request('GET',path,headers=headers)
            response=c.getresponse();result=response.status,response.read();c.close();return result
        try:
            self.assertEqual(call('/api/shared-parts/context')[0],401)
            status,data=call('/api/shared-parts/context',True)
            self.assertEqual(status,200);self.assertEqual(json.loads(data)['library'],str(self.lib.root))
            status,data=call('/sharedparts.js');self.assertEqual(status,200);self.assertIn(b'sharedControl',data)
        finally:server.shutdown();server.server_close();thread.join()

    def test_templates_cross_project_and_deduplicate(self):
        app=self.app();a=sp.dispatch(app,'templates-save',{});b=sp.dispatch(app,'templates-save',{})
        self.assertEqual(a['key'],b['key']);self.assertEqual(len(sp.dispatch(app,'templates-list',{})['items']),1)
        app.workspace=Workspace(Project(self.path));before=set(app.workspace.state['templates'])
        sp.dispatch(app,'templates-load',{'key':a['key']})
        self.assertTrue(before < set(app.workspace.state['templates']))

    def test_explicit_default_remembered(self):
        app=self.app()
        with patch('bomstudio.engineering.preference_file',return_value=self.dir/'prefs.json'):
            sp.dispatch(app,'open',{'path':str(self.lib.root)})
            self.assertEqual(sp.dispatch(SimpleNamespace(workspace=None),'context',{})['library'],str(self.lib.root))


class NativeShared(EngFixture):
    def setUp(self):
        super().setUp()
        asset_fixture.Assets.setup_assets(self)
        plan=partsdb.harvest([str(self.path)])
        pid=partsdb.record_identity(self.row('R1')['fields'])
        plan['parts']=[p for p in plan['parts'] if p['id']==pid]
        plan['fingerprint']=partsdb.digest({k:v for k,v in plan.items() if k!='fingerprint'})
        partsdb.import_harvest(self.lib,plan,'IMPORT','Test')
        self.plan=plan
        self.config=self.dir/'native-config';self.config.mkdir()
        self.symbol=b'(sym_lib_table\n  (version 7)\n  ; KEEP COMMENT\n  (lib (name "Existing") (type "KiCad") (uri "/keep/existing.kicad_sym"))\n)'
        (self.config/'sym-lib-table').write_bytes(self.symbol)

    def test_preview_readonly_and_repeatable(self):
        a=sp.native_preview(self.lib,self.config);b=sp.native_preview(self.lib,self.config)
        self.assertEqual(a,b);self.assertFalse((self.lib.root/'native').exists())
        self.assertEqual((self.config/'sym-lib-table').read_bytes(),self.symbol)

    def test_reharvest_reuses_identity_and_assets(self):
        before=self.lib.info()
        result=partsdb.import_harvest(self.lib,self.plan,'IMPORT','Test')
        self.assertEqual(result['count'],0)
        self.assertEqual(self.lib.info()['assets'],before['assets'])
        self.assertEqual(self.lib.info()['parts'],1)

    def test_critical_conflict_blocks_global_registration(self):
        p=self.lib.get(self.plan['parts'][0]['id'])
        p['conflicts'].append({'field':'Footprint','retained':'A','observed':'B'})
        with self.lib.transaction():self.lib.put(p,'Test','Conflict fixture')
        with self.assertRaisesRegex(ValueError,'conflicting'):sp.native_preview(self.lib,self.config)

    def test_global_registration_preserves_others_and_models(self):
        p=sp.native_preview(self.lib,self.config);r=sp.native_apply(self.lib,p)
        root=Path(r['destination']);text=(self.config/'sym-lib-table').read_text()
        self.assertIn('; KEEP COMMENT',text);self.assertIn('/keep/existing.kicad_sym',text)
        self.assertEqual(len(list(self.config.glob('sym-lib-table.*.bak'))),1)
        tree=parse((root/'WayriCADParts.kicad_sym').read_text())
        self.assertEqual(len(tree.nodes('symbol')),1)
        self.assertFalse(tree.nodes('symbol')[0].val().startswith('KW_'))
        fp=next((root/'WayriCADParts.pretty').glob('*.kicad_mod')).read_text()
        self.assertIn((root/'WayriCADParts.3dshapes').as_posix(),fp)
        self.assertEqual(next((root/'WayriCADParts.3dshapes').iterdir()).read_bytes(),asset_fixture.WRL)
        sp.native_apply(self.lib,sp.native_preview(self.lib,self.config))
        self.assertEqual(len(parse((self.config/'sym-lib-table').read_text()).nodes('lib')),2)

    def test_stale_tables_block(self):
        p=sp.native_preview(self.lib,self.config)
        (self.config/'sym-lib-table').write_bytes(self.symbol+b'\n; changed')
        with self.assertRaisesRegex(ValueError,'changed'):sp.native_apply(self.lib,p)
        self.assertFalse((self.config/'fp-lib-table').exists())

    def test_duplicate_nickname_not_overwritten(self):
        with self.assertRaisesRegex(ValueError,'another library'):sp.native_preview(self.lib,self.config,'Existing')

    def test_second_write_failure_restores_first(self):
        p=sp.native_preview(self.lib,self.config);original=sp._atomic
        def fail(path,raw):
            if path.name=='fp-lib-table':raise OSError('Test disk failure')
            return original(path,raw)
        with patch.object(sp,'_atomic',side_effect=fail),self.assertRaises(OSError):sp.native_apply(self.lib,p)
        self.assertEqual((self.config/'sym-lib-table').read_bytes(),self.symbol)
        self.assertFalse((self.config/'fp-lib-table').exists())

    def test_multi_instance_lock(self):
        p=sp.native_preview(self.lib,self.config)
        with sp.exclusive(self.lib.root),self.assertRaisesRegex(ValueError,'Another library'):sp.native_apply(self.lib,p)

    def test_catalogue_change_after_preview_never_publishes_unreviewed_bytes(self):
        plan=sp.native_preview(self.lib,self.config);original=sp.native_preview
        def concurrent_edit(*args,**kwargs):
            checked=original(*args,**kwargs)
            row=self.lib.db.execute('SELECT id,payload FROM parts LIMIT 1').fetchone()
            data=json.loads(row[1]);data['fields']['Description']='Concurrent catalogue edit'
            with self.lib.transaction():
                self.lib.db.execute('UPDATE parts SET payload=? WHERE id=?',(json.dumps(data),row[0]))
                self.lib.touch()
            return checked
        with patch.object(sp,'native_preview',side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError,'changed during publication'):
                sp.native_apply(self.lib,plan)
        self.assertFalse(Path(plan['destination']).exists())
        self.assertFalse((self.config/'fp-lib-table').exists())
        self.assertEqual((self.config/'sym-lib-table').read_bytes(),self.symbol)


class NewRecipients(EngFixture):
    def test_review_gate_and_real_csv_xlsx(self):
        for provider in ('aisler','pcprocess','krypton'):
            with self.subTest(provider=provider):
                c={'profiles':[provider]}
                with self.assertRaises(ValueError):ae.export(self.ws,config=c,fmt='csv',profile=provider)
                c['acknowledge_review_required']=True
                for fmt in ('csv','xlsx'):
                    raw,name,_=ae.export(self.ws,config=c,fmt=fmt,profile=provider)
                    self.assertTrue(raw);self.assertTrue(name.endswith('.'+fmt))
                    if fmt=='xlsx':
                        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn('xl/worksheets/sheet1.xml',z.namelist())


if __name__=='__main__':unittest.main()
