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
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.validation' / 'multi-instance' / str(time.time_ns())
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
    args = parser.parse_args()
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
        for index, folder in enumerate(('one', 'two'), 1):
            socket_root = BASE / 'temp' / folder if args.separate_temp else BASE / 'temp'
            socket_root.mkdir(parents=True, exist_ok=True)
            process_env = dict(env, TEMP=str(socket_root), TMP=str(socket_root))
            board = BASE / folder / ('fixture_' + folder + '.kicad_pcb')
            code = "import pcbnew,sys; b=pcbnew.BOARD(); b.SetFileName(sys.argv[1]); pcbnew.SaveBoard(sys.argv[1],b)"
            subprocess.run([str(NATIVE / 'python.exe'), '-c', code, str(board)], env=env,
                           capture_output=True, check=True, timeout=15)
            board.with_suffix('.kicad_pro').write_text('{}')
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
            deadline, last = time.monotonic() + 35, ''
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
                raise RuntimeError(f'Editor {index} failed within35s: ' + last)
            assert digest == hashlib.sha256(board.read_bytes()).hexdigest()
        # Fresh connections with each captured token must keep their project
        # identity while both owned editors are still alive.
        for index, (socket, token, board) in enumerate(instances):
            for _ in range(5):
                client = KiCad(socket_path=socket, kicad_token=token, timeout_ms=1000)
                assert context.saved_board(client) == board.resolve()
            report['instances'][index]['concurrent_reconnections'] = 5
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
