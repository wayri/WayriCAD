"""Authenticated loopback-only offline UI; no remote binding or CDN dependencies."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from .native import Project, BASE
from .engine import Workspace
from .exporters import export, release, table
from .writeback import compile_plan, apply_plan
from .compat import capabilities
from . import catalog, enforcement, bulkedit, evidence, intelligence, search, actions, automation, analytics, analytics_exports

ROOT=Path(__file__).resolve().parent.parent
from .runtime_info import runtime_info

class Application:
    def __init__(self,project=None,demo=False,auto_link=False,analytics_demo=False,engineering_demo=False):
        self.token=secrets.token_urlsafe(32);self.lock=threading.RLock();self.workspace=None
        self.demo_directory=None;self.compat=None;self.startup_note=None;self.ui_mode='none';self.desktop_host=None
        from .bridge import SelectionService
        self.link=SelectionService()
        if engineering_demo:
            self.open_demo(True)
            from .engineering_demo import prepare
            prepare(self)
        elif demo or analytics_demo:self.open_demo(analytics_demo)
        elif project:self.workspace=Workspace(Project(project))
        if auto_link and not (demo or analytics_demo or engineering_demo) and os.environ.get('KICAD_API_SOCKET'):
            try:
                if self.workspace is None:self.workspace=Workspace(Project(self.link.call('discover')['project']))
                self.link.call('connect',self.workspace.project)
                self.startup_note='Saved PCB project discovered/linked from KiCad launch context. Schematic relay and focus remain host-unverified.'
            except Exception as exc:self.startup_note='Automatic live link unavailable: '+str(exc)
    def open_demo(self,analytics_demo=False):
        directory=Path(tempfile.mkdtemp(prefix='wayricad-bom-demo-')).resolve()
        shutil.copytree(ROOT/'examples'/('analytics' if analytics_demo else ''),directory,dirs_exist_ok=True)
        self.demo_directory=directory;self.workspace=Workspace(Project(directory/'BOM_Demo.kicad_pro'))
        if analytics_demo:
            analytics.configure(self.workspace,automation.load_json(directory/'analytics-config.json'));self.workspace.save()
    def current(self):
        if self.workspace is None:raise ValueError('Open a KiCad project first.')
        return self.workspace
    def state(self,variant=BASE):
        if not self.workspace:return {'project':None,'version':'3.0.0','ui_mode':self.ui_mode,'startup_note':self.startup_note,'runtime':runtime_info(self)}
        result=self.workspace.public(variant);result['runtime']=runtime_info(self);result['ui_mode']=self.ui_mode;result['startup_note']=self.startup_note;result['demo']=bool(self.demo_directory and self.workspace.project.root.parent==self.demo_directory)
        return result

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def server_close(self):
        try:
            self.app.link.close()
            if hasattr(self.app,'engineering_tasks'):self.app.engineering_tasks.stop()
        finally:super().server_close()
    def __init__(self,app,port=0):
        self.app=app
        super().__init__(('127.0.0.1',port),Handler)
        self.origin=f'http://127.0.0.1:{self.server_port}'
        self.url=self.origin+'/#token='+app.token

class Handler(BaseHTTPRequestHandler):
    server_version='WayriCADBOM/3.0.0'
    def log_message(self,fmt,*args):
        # URLs/token fragments are deliberately never written to an access log.
        pass
    def headers_common(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
    def respond(self,data,status=200,content_type='application/json; charset=utf-8',name=None):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode('utf-8')
        compressed=False
        if len(data)>8192 and 'gzip' in self.headers.get('Accept-Encoding','') and not name:
            import gzip
            data=gzip.compress(data,compresslevel=4);compressed=True
        self.send_response(status);self.headers_common();self.send_header('Content-Type',content_type)
        self.send_header('Vary','Accept-Encoding')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Length',str(len(data)))
        if name:
            from urllib.parse import quote
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name))
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def validate(self,auth=True):
        expected=f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host')!=expected:
            self.respond({'error':'Invalid local Host header.'},403);return False
        origin=self.headers.get('Origin')
        if origin and origin!=self.server.origin:
            self.respond({'error':'Cross-origin access denied.'},403);return False
        if auth and not hmac.compare_digest(self.headers.get('X-Bom-Token',''),self.server.app.token):
            self.respond({'error':'Session authorization required. Use the launcher URL.'},401);return False
        return True
    def do_GET(self):
        url=urlsplit(self.path);path=url.path
        if not self.validate(path.startswith('/api/')):return
        try:
            if path=='/api/state':
                variant=parse_qs(url.query).get('variant',[BASE])[0]
                with self.server.app.lock:data=self.server.app.state(variant)
                self.respond(data);return
            if path=='/api/compat':
                app=self.server.app
                if app.compat is None:app.compat=capabilities()
                self.respond(app.compat);return
            files={'/':'index.html','/app.js':'app.js','/workbench.js':'workbench.js','/intelligence.js':'intelligence.js','/automation.js':'automation.js','/engineering.js':'engineering.js','/assets.js':'assets.js','/analytics.js':'analytics.js','/style.css':'style.css','/studio8.js':'studio8.js','/library8.js':'library8.js','/nativefirst.js':'nativefirst.js','/vendors.js':'vendors.js','/assemblers.js':'assemblers.js'}
            if path not in files:self.respond({'error':'Not found.'},404);return
            file=ROOT/'web'/files[path]
            self.respond(file.read_bytes(),content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        except (ValueError,KeyError,OSError) as exc:self.respond({'error':str(exc)},400)
        except Exception:
            traceback.print_exc();self.respond({'error':'Unexpected internal error. See launcher console; no operation was assumed successful.'},500)
    def do_POST(self):
        if not self.validate():return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=20*1024*1024:raise ValueError('Request must contain JSON and be smaller than 20 MiB.')
            if self.headers.get_content_type()!='application/json':raise ValueError('JSON content type required.')
            body=automation.strict_loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(body,dict):raise ValueError('JSON object required.')
            with self.server.app.lock:
                result=self.dispatch(urlsplit(self.path).path,body)
            if isinstance(result,tuple):self.respond(result[0],content_type=result[2],name=result[1])
            else:self.respond(result)
        except (ValueError,KeyError,TypeError,OSError) as exc:self.respond({'error':str(exc)},400)
        except Exception:
            traceback.print_exc();self.respond({'error':'Unexpected internal error. Review source/backups before proceeding; see launcher console.'},500)
    def do_OPTIONS(self):self.respond({'error':'Cross-origin API use is not permitted.'},403)
    def dispatch(self,path,b):
        app=self.server.app;variant=b.get('variant',BASE)
        if path=='/api/browse':
            if app.desktop_host:return {'path':app.desktop_host.pick_project()}
            command=[sys.executable,str(ROOT/'entrypoint.py'),'--pick']
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            if result.returncode:raise ValueError('Native file picker unavailable. Paste the absolute project path instead.')
            return {'path':result.stdout.strip()}
        if path=='/api/open':
            if app.workspace and app.workspace.dirty and b.get('discard') is not True:raise ValueError('Save your workspace first, or confirm discarding pending changes.')
            app.link.call('close')
            if b.get('demo'):app.open_demo()
            else:app.workspace=Workspace(Project(b['path']))
            return app.state()
        if path=='/api/quit':
            if app.workspace and app.workspace.dirty and b.get('discard') is not True:raise ValueError('Save changes or confirm discarding before quitting.')
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return {'ok':True}
        if path=='/api/link/diagnostic':
            from .bridge import diagnostic
            return diagnostic()
        if path=='/api/link/poll':
            try:return app.link.call('poll')
            except Exception as exc:
                app.link.call('close');return {'connected':False,'ids':[],'error':str(exc)}
        if path=='/api/link/disconnect':return app.link.call('close')
        if path=='/api/link/mapping':return app.link.call('mapping_report')
        if path.startswith('/api/engineering/'):
            from .engineering import dispatch
            return dispatch(app,path[len('/api/engineering/'):],b)
        if path.startswith('/api/library/'):
            from .librarymaker import dispatch
            return dispatch(app,path[len('/api/library/'):],b)
        if path=='/api/runtime/diagnostic':
            from .runtime_info import diagnostic
            return diagnostic(app)
        if path=='/api/native-bom/status':
            from .nativebom import status
            return status()
        if path=='/api/assemblers/profiles':
            from .assembler_export import profiles
            return profiles(b.get('config'))
        ws=app.current()
        if path.startswith('/api/assemblers/'):
            from . import assembler_export as ae
            op=path.rsplit('/',1)[-1]
            if op=='config':return {'config':ae.configuration(ws),'profiles':ae.profiles(ae.configuration(ws))}
            if op=='settings':return ae.configure(ws,b['config'])
            if op=='preview':return ae.preview(ws,variant,b.get('config'))
            if op=='export':return ae.export(ws,variant,b.get('config'),b.get('format','zip'),b.get('profile'),b.get('fingerprint'))
            raise ValueError('Unknown assembler export operation.')
        if path.startswith('/api/bom-format/'):
            from . import nativefirst as nf
            op=path.rsplit('/',1)[-1]
            if op=='context':return nf.context(ws)
            if op=='configure':return nf.configure_export(ws,b['settings'])
            if op=='select':return nf.select(ws,b.get('mode','native'),b.get('preset'),b.get('format_preset'),b.get('custom_template'))
            if op=='customize':return nf.customize(ws,b['name'],b.get('merge') is True)
            if op=='reverse-preview':return nf.reverse_preview(ws,b['template'])
            if op=='reverse-apply':return nf.reverse_apply(ws,b['template'],b['fingerprint'],b.get('confirmation'),b.get('acknowledge') is True)
            if op in ('preview','export'):
                from .nativebom import generate
                result=generate(ws,nf.inherited_options(ws,variant),b.get('acknowledge_saved') is True)
                if op=='export':return result['data'],result['filename'],'text/csv; charset=utf-8'
                return {'text':result['data'][:200000].decode('utf-8-sig',errors='replace'),'truncated':len(result['data'])>200000,'command':result['command'],'notice':result['notice']}
            raise ValueError('Unknown BOM-format operation.')
        if path.startswith('/api/vendors/'):
            from . import vendor_export as ve
            op=path.rsplit('/',1)[-1]
            if op=='config':return {'config':ve.configuration(ws),'profiles':ve.profiles(ve.configuration(ws))}
            if op=='settings':return ve.configure(ws,b['config'])
            if op=='preview':return ve.preview(ws,variant,b.get('config'))
            if op=='export':
                return ve.export(ws,variant,b.get('config'),b.get('format','zip'),b.get('vendor'),b.get('allow_partial') is True,b.get('fingerprint'))
            raise ValueError('Unknown vendor export operation.')
        if path=='/api/fields/inventory':
            from .field_registry import inventory
            return inventory(ws,variant)
        if path=='/api/fields/adopt':
            from .field_registry import adopt
            return adopt(ws,variant,b.get('preset_id'),b.get('all_fields') is True)
        if path=='/api/fields/import-preset':
            from .field_registry import import_template
            return import_template(ws,b['preset_id'],b['name'],b.get('format_id'))
        if path in ('/api/native-bom/preview','/api/native-bom/export'):
            from .nativebom import generate
            from .nativefirst import inherited_options
            result=generate(ws,b['config'] if 'config' in b else inherited_options(ws,variant),b.get('acknowledge_saved') is True)
            if path.endswith('/export'):return result['data'],result['filename'],'text/csv; charset=utf-8'
            return {'text':result['data'][:200000].decode('utf-8-sig',errors='replace'),'truncated':len(result['data'])>200000,'command':result['command'],'notice':result['notice']}
        if path=='/api/analytics/validate':return {'config':analytics.validate_config(b['config'])}
        if path=='/api/analytics/settings':return analytics.configure(ws,b['settings'])
        if path=='/api/analytics/run':return analytics.run(ws,variant,b.get('config'))
        if path=='/api/analytics/export':return analytics_exports.render(analytics.run(ws,variant,b.get('config')),b.get('format','json'),b.get('table','summary'))
        if path=='/api/threshold':return analytics.threshold(ws,variant,b['field'],b['condition'],b.get('unit'),b.get('query',''),b.get('rows') is True)
        if path=='/api/query':return search.run(ws,variant,b.get('query',''),b.get('case_sensitive') is True)
        if path=='/api/filter/save':return search.save_filter(ws,b['name'],b.get('record'),b.get('remove') is True)
        if path=='/api/filter/export':return automation.json_bytes(search.bundle(ws)),'WayriCAD_Search_Filters.json','application/json'
        if path=='/api/filter/import':return search.import_filters(ws,b['payload'],b.get('replace') is True)
        if path=='/api/bulk/preview':return actions.preview(ws,variant,b['recipe'])
        if path=='/api/bulk/apply':return actions.apply(ws,variant,b['recipe'],b['fingerprint'],b.get('confirmation'),b.get('acknowledge_loss') is True)
        if path=='/api/link/connect':return app.link.call('connect',ws.project,b.get('options'))
        if path=='/api/link/select':return app.link.call('select',b['ids'],b.get('focus') is True,b.get('allow_partial') is True)
        if path=='/api/jobset/bundle':return automation.jobset_bundle(ws,b['directory'],python=b.get('python'),platform=b.get('platform'),config=b.get('config'))
        if path=='/api/grid/preview':return bulkedit.preview(ws,variant,b['entries'])
        if path=='/api/grid/apply':return bulkedit.apply(ws,variant,b['entries'],b['fingerprint'],b.get('confirmation'),b.get('acknowledge_loss') is True)
        if path=='/api/grid/paste':
            plan=ws.csv_preview(b['text'],variant)
            if plan['unmatched']:raise ValueError('Unmatched references: '+', '.join(plan['unmatched']))
            entries=[{'ids':[c['id']],'changes':c['changes']} for c in plan['changes']]
            return {'entries':entries,'count':len(entries)}
        if path=='/api/grouping':return bulkedit.groups(ws,variant,b.get('fields',[]),b.get('raw') is True)
        if path=='/api/grouping/settings':
            fields=b.get('fields',[]);raw=b.get('raw') is True
            bulkedit.groups(ws,variant,fields,raw)
            from .nativefirst import preferences,context
            current_view=context(ws)['view'] if preferences(ws)['mode']=='native' else ws.state['view']
            ws.commit('Change presentation grouping',lambda:ws.state.update(grouping={'fields':fields,'raw':raw},view=current_view,bom_preferences=dict(preferences(ws),mode='custom')))
            return {'ok':True}
        if path=='/api/evidence/inspect':return evidence.table_info(b['payload'])[1]
        if path=='/api/evidence/preview':return evidence.preview(ws,b['payload'])
        if path=='/api/evidence/apply':return evidence.apply(ws,b['payload'],b['fingerprint'],b.get('confirmation'),b.get('reviewed'))
        if path=='/api/evidence/remove':evidence.remove(ws,b['ids']);return {'ok':True}
        if path=='/api/health/settings':return intelligence.configure(ws,b['settings'])
        if path=='/api/health/run':return intelligence.run(ws,variant)
        if path=='/api/analyzer/run':return intelligence.analyze(ws,variant)
        if path=='/api/supplier/request':return intelligence.supplier_request(ws,variant,b.get('supplier','DigiKey'))
        if path=='/api/health/export':
            if b.get('kind','health') not in ('health','analysis'):raise ValueError('Unknown report kind.')
            report=intelligence.run(ws,variant) if b.get('kind','health')=='health' else intelligence.analyze(ws,variant)
            data=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
            return data,'WayriCAD_'+b.get('kind','health')+'_report.json','application/json; charset=utf-8'
        if path=='/api/view':return catalog.set_view(ws,b['view'],b.get('preset')) or {'ok':True}
        if path=='/api/field/profile':catalog.save_profile(ws,b['profile']);return {'ok':True}
        if path=='/api/catalog/manage':catalog.manage(ws,b['section'],b['operation'],b['old'],b.get('new'));return {'ok':True}
        if path=='/api/catalog/export':
            payload=catalog.bundle(ws,b.get('section'),b.get('name'))
            data=(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            return data,'WayriCAD_BOM_Templates.json','application/json; charset=utf-8'
        if path=='/api/catalog/import/preview':return catalog.import_preview(ws,b['text'],b.get('policy','keep_both'))
        if path=='/api/catalog/import/apply':return catalog.import_apply(ws,b['text'],b.get('policy','keep_both'))
        if path=='/api/field/enforce/preview':return enforcement.preview(ws,b['profile'],b.get('options'))
        if path=='/api/field/enforce/apply':return enforcement.apply(ws,b['fingerprint'],b.get('confirmation'),b.get('acknowledge_loss') is True)
        if path=='/api/edit':count=ws.edit(b['ids'],variant,b['changes']);return {'affected':count}
        if path=='/api/population':return {'affected':ws.set_population(b['ids'],variant,b['state'])}
        if path=='/api/variant/add':return {'name':ws.new_variant(b['name'],b.get('parent',BASE),b.get('description',''))}
        if path=='/api/variant/remove':ws.remove_variant(b['name'])
        elif path=='/api/variables':ws.set_variables(b['scope'],b['values'],variant)
        elif path=='/api/settings':ws.settings(b['settings'])
        elif path=='/api/template':ws.template(b['template'])
        elif path=='/api/aliases':ws.set_aliases(b['aliases'])
        elif path=='/api/save':return {'path':ws.save()}
        elif path=='/api/undo':ws.undo()
        elif path=='/api/redo':ws.redo()
        elif path=='/api/rebase':ws.acknowledge_sources(b.get('confirmation'))
        elif path=='/api/reload':
            if ws.dirty and b.get('discard') is not True:raise ValueError('Save the workspace or confirm discarding changes before reopening.')
            app.link.call('close');app.workspace=Workspace(Project(ws.project.pro_path if ws.project.pro_path.exists() else ws.project.root));return app.state(variant)
        elif path=='/api/compare':return {'changes':ws.compare(b.get('left',BASE),b.get('right',variant))}
        elif path=='/api/matrix':
            names=[BASE]+list(ws.state['variants'])
            return {'variants':names,'rows':{v:[{'id':r['id'],'reference':r['ref'],'state':r['fields']['Assembly'],'in_bom':r['flags']['in_bom'],'in_pos_files':r['flags']['in_pos_files'],'inherited':r['inherited']} for r in ws.rows(v)] for v in names}}
        elif path=='/api/baseline':ws.snapshot(variant)
        elif path=='/api/baseline/diff':return {'changes':ws.baseline_diff(variant)}
        elif path=='/api/alternate':ws.alternate(b['mpn'],b['record'])
        elif path=='/api/import/preview':return ws.csv_preview(b['text'],variant)
        elif path=='/api/import/apply':return {'affected':ws.csv_apply(b['text'],variant)}
        elif path=='/api/export/preview':
            if not b.get('template'):raise ValueError('Choose an explicit custom template or use the inherited Native BOM preview.')
            return table(ws,variant,b['template'])
        elif path=='/api/export':
            if not b.get('template'):raise ValueError('Choose an explicit custom template or use the inherited Native BOM export.')
            return export(ws,variant,b['template'],b.get('format','csv'),b.get('draft') is True)
        elif path=='/api/release':
            if not b.get('template'):raise ValueError('A multi-variant release requires an explicit custom template.')
            return release(ws,b.get('variants'),b['template'],b.get('draft') is True)
        elif path=='/api/native/preview':return compile_plan(ws)
        elif path=='/api/native/apply':
            app.link.call('close')
            app.workspace,backup=apply_plan(ws,b.get('fingerprint'),b.get('confirmation'),b.get('editors_closed'))
            return {'backup':backup,'message':'Native files updated and round-trip verified by the adapter. Reopen in KiCad and update PCB from schematic.'}
        else:raise ValueError('Unknown operation: '+path)
        return {'ok':True}
