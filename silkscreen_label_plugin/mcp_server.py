"""Optional, read-only MCP tools for saved-board silk review.

Install the official ``mcp`` Python SDK separately to run the stdio server.
KiCad's native Python is launched only for an explicitly requested board tool.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

MAX_TIMEOUT_SECONDS = 1800
MAX_SETTINGS_BYTES = 64 * 1024


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class ReadOnlyTools:
    """Validated read-only board operations scoped to one required project root."""

    def __init__(self, project_root, *, timeout=1800, worker=None):
        try:
            root = Path(project_root).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError('Allowed project root must be an existing directory.') from exc
        if not root.is_dir():
            raise ValueError('Allowed project root must be an existing directory.')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f'Timeout must be greater than zero and at most {MAX_TIMEOUT_SECONDS} seconds.')
        self.root = root
        self.timeout = float(timeout)
        self._worker = worker

    def settings(self):
        from .placement import DEFAULTS
        return {'status': 'SETTINGS', 'settings': dict(DEFAULTS), 'units': 'mm and degrees',
                'writes_board': False, 'can_apply': False}

    def _board_path(self, supplied):
        if not isinstance(supplied, str) or not supplied.strip():
            raise ValueError('board_path must be a nonempty path string.')
        candidate = Path(supplied).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        board = candidate.resolve(strict=True)
        if not _inside(board, self.root) or not board.is_file():
            raise ValueError('Board must be a saved PCB inside the allowed project root.')
        if board.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose a saved .kicad_pcb file.')
        for suffix in ('.kicad_pro', '.kicad_dru'):
            sidecar = board.with_suffix(suffix)
            resolved = sidecar.resolve(strict=False)
            if not _inside(resolved, self.root):
                raise ValueError('Project rules or settings resolve outside the allowed project root.')
        return board

    @staticmethod
    def _safe_settings(settings):
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise ValueError('settings must be a JSON object.')
        try:
            encoded = json.dumps(settings, allow_nan=False, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('settings must contain finite JSON values only.') from exc
        if len(encoded.encode('utf-8')) > MAX_SETTINGS_BYTES:
            raise ValueError('settings exceeds the 64 KiB limit.')
        return settings

    def preview_board(self, board_path, settings=None):
        return self._board_operation(board_path, 'preview', settings)

    def audit_generated(self, board_path):
        return self._board_operation(board_path, 'audit-generated', {})

    def _board_operation(self, supplied, operation, settings):
        try:
            if operation == 'preview':
                settings = self._safe_settings(settings)
            board = self._board_path(supplied)
            request = {'board': str(board), 'operation': operation, 'settings': settings,
                       'refs': [], 'include_report_geometry': False}
            if self._worker is not None:
                result = self._worker(request)
                if not isinstance(result, dict):
                    raise RuntimeError('Native worker returned an invalid result.')
                return {**result, 'writes_board': False, 'can_apply': False}
            return self._run_native_worker(request)
        except subprocess.TimeoutExpired:
            return {'status': 'ERROR', 'error': 'Native KiCad operation timed out.',
                    'writes_board': False, 'can_apply': False}
        except OSError:
            return {'status': 'ERROR', 'error': 'Board access failed inside the allowed project root.',
                    'writes_board': False, 'can_apply': False}
        except ValueError as exc:
            return {'status': 'ERROR', 'error': str(exc),
                    'writes_board': False, 'can_apply': False}
        except Exception:
            return {'status': 'ERROR', 'error': 'Native KiCad operation failed; verify the saved board and KiCad runtime.',
                    'writes_board': False, 'can_apply': False}

    def _run_native_worker(self, request):
        from wayricad_runtime.runtime_setup import native_python
        native = native_python()
        if not native:
            raise RuntimeError('KiCad native Python is unavailable; configure WAYRICAD_KICAD_PYTHON.')
        worker = Path(__file__).with_name('cli_worker.py').resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix='wayricad-silk-mcp-') as directory:
            request_path = Path(directory) / 'request.json'
            result_path = Path(directory) / 'result.json'
            request_path.write_text(json.dumps(request, allow_nan=False), encoding='utf-8')
            process = subprocess.Popen(
                [str(native), str(worker), str(request_path), str(result_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + self.timeout
            try:
                from anyio.from_thread import check_cancelled
            except ImportError:
                check_cancelled = lambda: None
            try:
                while process.poll() is None:
                    try:
                        check_cancelled()
                    except RuntimeError:
                        # Direct, non-SDK invocation has no AnyIO worker token.
                        check_cancelled = lambda: None
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(process.args, self.timeout)
                    time.sleep(.05)
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
            if not result_path.is_file():
                raise RuntimeError('Native KiCad worker did not return a result.')
            try:
                result = json.loads(result_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError('Native KiCad worker returned invalid JSON.') from exc
            if process.returncode or not isinstance(result, dict):
                raise RuntimeError('Native KiCad worker failed.')
            if result.get('status') == 'ERROR':
                raise RuntimeError('Native KiCad operation failed; verify the saved board and KiCad runtime.')
            result['writes_board'] = False
            result['can_apply'] = False
            return result


def create_server(project_root, *, timeout=1800, worker=None):
    """Build a server with the official optional MCP SDK, scoped at startup."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError('MCP support requires the optional official Python SDK: pip install "mcp>=2,<3".') from exc
    tools = ReadOnlyTools(project_root, timeout=timeout, worker=worker)
    server = MCPServer('WayriCAD Silkscreen Review', instructions=(
        'Read-only saved-board preview and generated-object audit. The server never applies, saves, or cleans up a board.'))

    @server.tool()
    def get_settings() -> dict:
        """Return the current planner settings and units. No board is opened."""
        return tools.settings()

    @server.tool()
    def preview_board(board_path: str, settings: dict | None = None) -> dict:
        """Preview labels on a saved KiCad PCB inside the configured project root."""
        return tools.preview_board(board_path, settings)

    @server.tool()
    def audit_generated(board_path: str) -> dict:
        """Audit managed generated objects on a saved KiCad PCB without changing it."""
        return tools.audit_generated(board_path)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True, help='Required allowed project root for every board operation.')
    parser.add_argument('--timeout', type=float, default=1800, help='Maximum native operation time in seconds (1..1800).')
    args = parser.parse_args(argv)
    server = create_server(args.project_root, timeout=args.timeout)
    server.run()


if __name__ == '__main__':
    raise SystemExit(main())
