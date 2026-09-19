"""Resolve only the KiCad instance that launched this action."""
from pathlib import Path
import os


def connect(*, timeout_ms=5000):
    from kipy import KiCad
    socket = os.environ.get('KICAD_API_SOCKET', '').strip()
    token = os.environ.get('KICAD_API_TOKEN', '')
    if not socket or not token:
        raise RuntimeError('No originating KiCad connection. Launch this action from the PCB Editor toolbar, or supply a saved board to the standalone CLI.')
    # Never enumerate sockets or fall back to another running editor.
    return KiCad(socket_path=socket, kicad_token=token, timeout_ms=timeout_ms)


def saved_board(client=None):
    client = client if client is not None else connect()
    board = client.get_board()
    document = getattr(board, 'document', None)
    name = getattr(document, 'board_filename', '') or getattr(board, 'name', '')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Save the originating PCB before opening this tool.')
    path = Path(name)
    if not path.is_absolute():
        project = board.get_project()
        directory = getattr(project, 'path', '')
        if not isinstance(directory, str) or not directory:
            raise ValueError('KiCad did not provide this board’s project directory. Save the PCB and reopen the action.')
        directory = Path(directory)
        if directory.suffix.lower() in ('.kicad_pro', '.pro'):
            directory = directory.parent
        if not directory.is_absolute():
            raise ValueError('KiCad returned a relative project directory; refusing to use the plugin working directory.')
        path = directory / path
    if path.suffix.lower() != '.kicad_pcb' or not path.is_file():
        raise ValueError('The originating PCB is not saved on disk. Save it in KiCad and reopen this action: ' + str(path))
    return path.resolve()


def redact_error(error):
    text = str(error)
    token = os.environ.get('KICAD_API_TOKEN', '')
    return text.replace(token, '[redacted]') if token else text
