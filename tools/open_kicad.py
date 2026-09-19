"""Open a PCB with a private Windows IPC namespace and the user's usual settings."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def editor_path(override=None):
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise ValueError('PCB Editor executable does not exist: ' + str(path))
        return path
    found = shutil.which('pcbnew')
    if found:
        return Path(found)
    candidates = []
    if sys.platform == 'win32':
        root = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'KiCad'
        candidates = [root / version / 'bin/pcbnew.exe' for version in ('10.0', '11.0', '9.0')]
    elif sys.platform == 'darwin':
        candidates = [Path('/Applications/KiCad/KiCad.app/Contents/Applications/pcbnew.app/Contents/MacOS/pcbnew'),
                      Path('/Applications/KiCad/pcbnew.app/Contents/MacOS/pcbnew')]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError('Cannot locate PCB Editor. Supply --pcbnew with its executable path.')


def launch_environment(original, private_temp=None):
    env = dict(original)
    # A new editor must not inherit the launching plugin's connection identity.
    for name in ('KICAD_API_SOCKET', 'KICAD_API_TOKEN'):
        env.pop(name, None)
    if private_temp is not None:
        env.update(TEMP=str(private_temp), TMP=str(private_temp))
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board', type=Path, help='Saved .kicad_pcb to open.')
    parser.add_argument('--pcbnew', type=Path, help='Override the PCB Editor executable path.')
    args = parser.parse_args(argv)
    board = args.board.expanduser().resolve()
    if board.suffix.lower() != '.kicad_pcb' or not board.is_file():
        parser.error('Provide an existing .kicad_pcb file.')
    try:
        executable = editor_path(args.pcbnew)
    except ValueError as exc:
        parser.error(str(exc))
    private_temp = Path(tempfile.mkdtemp(prefix='wayricad-kicad-')).resolve() if sys.platform == 'win32' else None
    process = None
    try:
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == 'win32' else {}
        process = subprocess.Popen([str(executable), str(board)],
                                   env=launch_environment(os.environ, private_temp), **options)
        print('Opened PCB Editor. This helper waits until that editor closes.', flush=True)
        return process.wait()
    except KeyboardInterrupt:
        print('Helper interrupted; the editor remains open. Its temporary directory is retained.', file=sys.stderr)
        return 130
    finally:
        # Never remove a namespace while its editor is still alive, and never
        # traverse a substituted symlink. Only our freshly created folder qualifies.
        if private_temp is not None and (process is None or process.poll() is not None):
            if not private_temp.is_symlink() and private_temp.resolve() == private_temp:
                try:
                    shutil.rmtree(private_temp)
                except OSError:
                    print('Temporary files remain at ' + str(private_temp), file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
