"""Launch two disposable Windows PCB editors and verify originating IPC context.

Uses private configuration, projects and temporary socket namespace. Stops only
processes started here; never discovers or connects to an existing user editor.
"""
import ctypes
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.gettempdir()) / 'WayriCAD-validation' / 'multi-instance' / str(time.time_ns())
NATIVE = Path('C:/Program Files/KiCad/10.0/bin')


def owned_windows(pid):
    """Record own process dialog captions to diagnose first-run modal blockers."""
    output = []
    user = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    @callback
    def inspect(hwnd, unused):
        process_id = ctypes.c_ulong()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid:
            text = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, text, 512)
            if text.value:
                output.append(text.value)
                if text.value == 'KiCad Setup':
                    @callback
                    def child_caption(child, unused):
                        caption = ctypes.create_unicode_buffer(512)
                        user.GetWindowTextW(child, caption, 512)
                        if caption.value: output.append('  ' + caption.value)
                        return True
                    user.EnumChildWindows(hwnd, child_caption, 0)
        return True
    user.EnumWindows(inspect, 0)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--separate-temp', action='store_true', help='Use a separate IPC namespace per owned editor to test the Windows collision workaround.')
    parser.add_argument('--single-editor', action='store_true',
                        help='Use one disposable PCB Editor for plugin checks; skips the two-editor token isolation check.')
    parser.add_argument('--plugin-smoke', action='store_true', help='Run installed-release Pin Extractor and Fanout windows on disposable footprints.')
    parser.add_argument('--extract-copies', type=int, choices=(1, 2), default=2,
                        help='Number of concurrent Pin Extractor windows for plugin smoke (default: 2).')
    parser.add_argument('--skip-extract', action='store_true',
                        help='Skip the Pin Extractor window when isolating other plugin failures.')
    parser.add_argument('--runtime-python', type=Path, help='Prepared native KiCad Python environment for plugin UI checks.')
    parser.add_argument('--extra-plugin-smoke', action='store_true',
                        help='Open additional direct IPC plugin first windows from disposable ZIPs.')
    parser.add_argument('--extra-plugin-id', choices=('embed-3d', 'harness-workbench', 'heater-designer',
                        'manufacturing-readiness', 'planar-magnetics', 'protocol-constraint-composer'),
                        help='Limit additional first-window smoke to one named plugin.')
    parser.add_argument('--runtime-python-heavy', type=Path,
                        help='Prepared KiCad runtime with scientific dependencies for Planar Magnetics.')
    parser.add_argument('--archive-dir', type=Path, default=ROOT/'releases',
                        help='PCM ZIP source for plugin UI checks; defaults to published releases.')
    parser.add_argument('--board-source', type=Path,
                        help='Copy a saved PCB into the disposable editor for additional first-window checks.')
    parser.add_argument('--overlay-webview-fix', action='store_true', help='Overlay current Pin/WebView source into test payload; results are not release-archive validation.')
    args = parser.parse_args()
    if args.board_source and (not args.board_source.is_file() or not args.single_editor):
        parser.error('--board-source requires an existing board and --single-editor.')
    if args.plugin_smoke and (not args.runtime_python or not args.runtime_python.is_file()):
        parser.error('--plugin-smoke requires --runtime-python pointing to a prepared native environment.')
    if args.extra_plugin_smoke and not args.plugin_smoke:
        parser.error('--extra-plugin-smoke requires --plugin-smoke.')
    if args.extra_plugin_smoke and (not args.runtime_python_heavy or not args.runtime_python_heavy.is_file()):
        parser.error('--extra-plugin-smoke requires --runtime-python-heavy.')
    if args.extra_plugin_id and not args.extra_plugin_smoke:
        parser.error('--extra-plugin-id requires --extra-plugin-smoke.')
    if args.extra_plugin_smoke:
        # Plugin-only validation needs one originating editor. Starting a
        # second visible editor after the UI workers can trigger a KiCad open
        # confirmation unrelated to plugin behavior.
        args.single_editor = True
    if sys.platform != 'win32':
        raise RuntimeError('This live validation harness targets the local Windows KiCad installation.')
    for name in ('config', 'config/10.0', 'temp', 'documents', 'cache', 'one', 'two'):
        (BASE / name).mkdir(parents=True, exist_ok=True)
    settings = {'meta': {'version': 6},
                'do_not_show_again': {'data_collection_prompt': True, 'update_check_prompt': True},
                'api': {'enable_server': True,
                'interpreter_path': str(NATIVE / 'pythonw.exe')}}
    for directory in (BASE / 'config', BASE / 'config/10.0'):
        (directory / 'kicad_common.json').write_text(json.dumps(settings))
        (directory / 'pcbnew.json').write_text(json.dumps({'meta': {'version': 5}}))
        (directory / 'fp-lib-table').write_text('(fp_lib_table (version 7))')
        (directory / 'sym-lib-table').write_text('(sym_lib_table (version 7))')
        (directory / 'design-block-lib-table').write_text('(design_block_lib_table (version 1))')
        (directory / 'kicad_advanced').write_text('EnableAPILogging=1\n')
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'KICAD_API_SOCKET', 'KICAD_API_TOKEN'):
        env.pop(key, None)
    env.update(KICAD_CONFIG_HOME=str(BASE / 'config'), KICAD_DOCUMENTS_HOME=str(BASE / 'documents'),
               KICAD_CACHE_HOME=str(BASE / 'cache'), TEMP=str(BASE / 'temp'), TMP=str(BASE / 'temp'))
    sys.path[:0] = [str(ROOT / '.build-tools'), str(ROOT)]
    from kipy import KiCad
    from wayricad_runtime import context
    processes, handles, instances = [], [], []
    report = {'status': 'starting', 'live_ipc_verified': False, 'instances': [],
              'separate_temp_namespaces': args.separate_temp}
    try:
        folders = ('one',) if args.single_editor else ('one', 'two')
        for index, folder in enumerate(folders, 1):
            socket_root = BASE / 'temp' / folder if args.separate_temp else BASE / 'temp'
            socket_root.mkdir(parents=True, exist_ok=True)
            process_env = dict(env, TEMP=str(socket_root), TMP=str(socket_root))
            board = BASE / folder / (args.board_source.name if args.board_source else 'fixture_' + folder + '.kicad_pcb')
            code = """import pcbnew,sys
b=pcbnew.BOARD();b.SetFileName(sys.argv[1])
n=pcbnew.NETINFO_ITEM(b,'SIGNAL');b.Add(n)
for index,ref in enumerate(('J1','U1')):
 f=pcbnew.FOOTPRINT(b);f.SetReference(ref);f.SetValue('Fixture');b.Add(f)
 for number in (1,2):
  p=pcbnew.PAD(f);p.SetNumber(str(number));p.SetAttribute(pcbnew.PAD_ATTRIB_SMD);p.SetShape(pcbnew.PAD_SHAPE_RECT);p.SetSize(pcbnew.VECTOR2I(1000000,1000000));p.SetPosition(pcbnew.VECTOR2I(10000000+index*10000000,number*2000000));ls=pcbnew.LSET();ls.AddLayer(pcbnew.F_Cu);p.SetLayerSet(ls);p.SetNet(n);f.Add(p)
for a,z in (((0,0),(40,0)),((40,0),(40,40)),((40,40),(0,40)),((0,40),(0,0))):
 s=pcbnew.PCB_SHAPE(b);s.SetShape(pcbnew.SHAPE_T_SEGMENT);s.SetLayer(pcbnew.Edge_Cuts);s.SetStart(pcbnew.VECTOR2I(a[0]*1000000,a[1]*1000000));s.SetEnd(pcbnew.VECTOR2I(z[0]*1000000,z[1]*1000000));b.Add(s)
pcbnew.SaveBoard(sys.argv[1],b)
"""
            if args.board_source:
                shutil.copy2(args.board_source, board)
                source_project = args.board_source.with_suffix('.kicad_pro')
                if source_project.is_file():
                    shutil.copy2(source_project, board.with_suffix('.kicad_pro'))
            else:
                subprocess.run([str(NATIVE / 'python.exe'), '-c', code, str(board)], env=env,
                               capture_output=True, check=True, timeout=15)
                board.with_suffix('.kicad_pro').write_text(json.dumps({'board':{'design_settings':{'rules':{'min_clearance':.2}}}}))
            digest = hashlib.sha256(board.read_bytes()).hexdigest()
            handle = (BASE / (folder + '-editor.log')).open('w')
            handles.append(handle)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen([str(NATIVE / 'pcbnew.exe'), str(board)], env=process_env,
                                       cwd=BASE, startupinfo=startup, stdout=handle, stderr=handle)
            processes.append(process)
            item = {'pid': process.pid, 'board': str(board), 'connected': False}
            report['instances'].append(item)
            deadline, last = time.monotonic() + (90 if args.board_source else 35), ''
            while time.monotonic() < deadline and process.poll() is None:
                # Both candidates belong exclusively to our private namespace.
                names = ('api.sock', f'api-{process.pid}.sock')
                for name in names:
                    socket = 'ipc://' + str(socket_root / 'kicad' / name)
                    try:
                        client = KiCad(socket_path=socket, kicad_token='', timeout_ms=300)
                        version = client.get_version()
                        resolved = context.saved_board(client)
                        if resolved != board.resolve():
                            raise RuntimeError('Owned socket returned an unexpected board.')
                        token = client._client._kicad_token
                        if not token:
                            raise RuntimeError('KiCad response has no instance token.')
                        old_socket, old_token = os.environ.get('KICAD_API_SOCKET'), os.environ.get('KICAD_API_TOKEN')
                        try:
                            os.environ.update(KICAD_API_SOCKET=socket, KICAD_API_TOKEN=token)
                            assert context.saved_board() == board.resolve()
                        finally:
                            for key, value in (('KICAD_API_SOCKET', old_socket), ('KICAD_API_TOKEN', old_token)):
                                if value is None: os.environ.pop(key, None)
                                else: os.environ[key] = value
                        item.update(connected=True, version=str(version), exact_token_context=True,
                                    canonical_board_name=client.get_board().name,
                                    project_path=str(client.get_board().get_project().path), socket=socket)
                        instances.append((socket, token, board))
                        break
                    except Exception as exc:
                        last = type(exc).__name__ + ': ' + str(exc)
                        item.setdefault('connection_errors', {})[name] = last
                if item['connected']:
                    break
                time.sleep(.25)
            if not item['connected']:
                item['owned_window_captions'] = owned_windows(process.pid)
                raise RuntimeError(f'Editor {index} did not become ready: ' + last)
            assert digest == hashlib.sha256(board.read_bytes()).hexdigest()
            if args.plugin_smoke and index==1:
                import zipfile
                version=json.loads((ROOT/'extract_pins_plugin/metadata.json').read_text())['versions'][0]['version']
                if not args.board_source:
                    client.get_board().add_to_selection(client.get_board().get_footprints())
                report['plugin_smoke']=[]
                for short in (() if args.board_source else ('fanout-generator','extract-pins')):
                    if short == 'extract-pins' and args.skip_extract:
                        continue
                    archive=args.archive_dir/('WayriCAD-'+short+'-'+version+'-PCM.zip')
                    target=BASE/short
                    with zipfile.ZipFile(archive) as z:z.extractall(target)
                    if args.overlay_webview_fix and short=='extract-pins':
                        for relative in ('plugin_dialog_v2.py', 'native_visual.py'):
                            (target/'plugins'/relative).write_bytes((ROOT/'extract_pins_plugin'/relative).read_bytes())
                        (target/'plugins/wayricad_runtime/local_webview.py').write_bytes((ROOT/'wayricad_runtime/local_webview.py').read_bytes())
                    python=args.runtime_python.resolve()
                    run_env=dict(process_env,KICAD_API_SOCKET=socket,KICAD_API_TOKEN=token,WAYRICAD_KICAD_PYTHON=str(python))
                    # The IPC endpoint is explicit; browser child-process caches
                    # should use the usual short Windows temp root, not this
                    # deeply nested validation artifact directory.
                    for key in ('TEMP','TMP'):
                        if key in os.environ:run_env[key]=os.environ[key]
                    workers=[]
                    try:
                        for copy in range(args.extract_copies if short=='extract-pins' else 1):
                            output=BASE/(short+'-'+str(copy)+'-ui.json')
                            command=[str(python),'-I',str(ROOT/'tools/validate_plugin_window_worker.py'),str(target/'plugins'),str(output)]
                            log_path=output.with_suffix('.log');log=log_path.open('w')
                            workers.append((subprocess.Popen(command,env=run_env,stdout=log,stderr=log,text=True),output,log))
                        for worker,output,log in workers:
                            try:worker.wait(timeout=45)
                            except subprocess.TimeoutExpired:
                                log.flush()
                                report['plugin_smoke'].append({'plugin':short,'status':'timeout','windows':owned_windows(worker.pid),'stderr':output.with_suffix('.log').read_text(errors='replace')})
                                raise
                            log.flush();stderr=output.with_suffix('.log').read_text(errors='replace')
                            record=json.loads(output.read_text()) if output.exists() else {'status':'failed','stderr':stderr}
                            record.update(plugin=short,stderr=stderr,source_overlay=bool(args.overlay_webview_fix and short=='extract-pins'))
                            record['base_archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
                            if (worker.returncode or 'failed with error' in stderr.lower()
                                    or 'wxAssertionError' in stderr or 'C++ assertion' in stderr):
                                record['status']='failed'
                            report['plugin_smoke'].append(record)
                    finally:
                        for worker,output,log in workers:
                            if worker.poll() is None:worker.terminate();worker.wait(timeout=5)
                            log.close()
                assert digest == hashlib.sha256(board.read_bytes()).hexdigest(), 'Plugin altered the fixture file.'
                assert all(r['status']=='passed' for r in report['plugin_smoke']), 'A plugin UI check failed; inspect plugin_smoke results.'
                if args.extra_plugin_smoke:
                    report['plugin_open_smoke'] = []
                    for short in ((args.extra_plugin_id,) if args.extra_plugin_id else
                                  ('embed-3d', 'harness-workbench', 'heater-designer',
                                   'manufacturing-readiness', 'planar-magnetics',
                                   'protocol-constraint-composer')):
                        archive = args.archive_dir / ('WayriCAD-'+short+'-'+version+'-PCM.zip')
                        target = BASE / short
                        with zipfile.ZipFile(archive) as z:
                            manifest = json.loads(z.read('plugins/plugin.json'))
                            z.extractall(target)
                        entrypoint = manifest['actions'][0]['entrypoint']
                        runtime = (args.runtime_python_heavy if short == 'planar-magnetics'
                                   else args.runtime_python).resolve()
                        output = BASE / (short+'-open.json')
                        command = [str(runtime), '-I', str(ROOT/'tools/validate_plugin_open_worker.py'),
                                   str(target/'plugins'), entrypoint, str(output)]
                        run_env = dict(process_env, KICAD_API_SOCKET=socket, KICAD_API_TOKEN=token,
                                       WAYRICAD_KICAD_PYTHON=str(runtime))
                        log_path = output.with_suffix('.log')
                        with log_path.open('w') as log:
                            worker = subprocess.Popen(command, env=run_env, stdout=log, stderr=log)
                            try:
                                worker.wait(timeout=75 if args.board_source else 25)
                            except subprocess.TimeoutExpired:
                                subprocess.run(['taskkill', '/PID', str(worker.pid), '/T', '/F'],
                                               capture_output=True, timeout=8, check=False)
                                worker.wait(timeout=5)
                        record = json.loads(output.read_text()) if output.exists() else {'status': 'failed'}
                        record.update(plugin=short, returncode=worker.returncode,
                                      stderr=log_path.read_text(errors='replace'))
                        if worker.returncode or record.get('errors'):
                            record['status'] = 'failed'
                        report['plugin_open_smoke'].append(record)
                    assert digest == hashlib.sha256(board.read_bytes()).hexdigest(), 'Plugin altered the fixture file.'
                    assert all(r['status']=='passed' for r in report['plugin_open_smoke']), 'An additional plugin UI check failed.'
        # Fresh connections with each captured token must keep their project
        # identity while both owned editors are still alive.
        for index, (socket, token, board) in enumerate(instances):
            for _ in range(5):
                client = KiCad(socket_path=socket, kicad_token=token, timeout_ms=1000)
                assert context.saved_board(client) == board.resolve()
            report['instances'][index]['concurrent_reconnections'] = 5
            if args.single_editor:
                continue
            other_token = instances[1 - index][1]
            assert other_token != token, 'Owned editors unexpectedly share an instance token.'
            rejected = False
            wrong_client = KiCad(socket_path=socket, kicad_token=other_token, timeout_ms=1000)
            try:
                context.saved_board(wrong_client)
            except Exception as exc:
                from kipy.errors import ApiError
                if not isinstance(exc, ApiError):
                    raise AssertionError('Wrong-token probe failed without a KiCad API rejection.') from exc
                rejected = True
            assert rejected, 'KiCad accepted a token from another editor.'
            assert wrong_client._client._kicad_token == other_token, 'Client silently adopted another instance token.'
            report['instances'][index]['foreign_token_rejected'] = True
            report['instances'][index]['foreign_token_not_replaced'] = True
        report.update(status='passed', live_ipc_verified=True, concurrent_editors=len(processes))
    except Exception as exc:
        report.update(status='failed', error=str(exc), traceback=traceback.format_exc())
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
        report['owned_processes_stopped'] = all(p.poll() is not None for p in processes)
        (BASE / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    return 0 if report['live_ipc_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
