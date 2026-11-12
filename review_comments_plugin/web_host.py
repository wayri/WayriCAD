"""Ephemeral, read-only loopback host for the internal Review web canvas."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
from types import MappingProxyType
from urllib.parse import unquote_to_bytes, urlsplit

from .web_assets import asset_manifest, discover_assets, verify_assets, verify_module_closure, _is_link


_MIME = {
    '.html': 'text/html; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.wasm': 'application/wasm',
    '.txt': 'text/plain; charset=utf-8',
    '.md': 'text/plain; charset=utf-8',
}
_CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "worker-src 'self' blob:; frame-src 'none'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'")
_WEB_FILES = ('index.html', 'bridge.mjs', 'style.css')
_MAX_WEB_FILE = 256 * 1024
_MAX_TOTAL = 4 * 1024 * 1024


def _mime(name: str) -> str:
    if name.rsplit('/', 1)[-1].endswith('LICENSE'):
        return 'text/plain; charset=utf-8'
    return _MIME.get(Path(name).suffix.lower(), 'application/octet-stream')


def _read_file(path: Path, root: Path, limit: int) -> bytes:
    if _is_link(root) or not root.is_dir():
        raise ValueError('Review web assets need a real directory.')
    for part in path.relative_to(root).parts:
        root = root / part
        if _is_link(root):
            raise ValueError('Review web assets cannot be symlinks.')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Review web asset is missing or exceeds its size bound: ' + path.name)
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Review web asset changed while being read: ' + path.name)
    return data


def _snapshot(viewer_root: Path, web_root: Path) -> dict[str, bytes]:
    paths = discover_assets(viewer_root, include_3d=True, linked_models=True)
    # Discovery rejects a linked selected root and linked asset children.
    # Use its canonical root for relative checks, including macOS /var aliases.
    viewer_root = viewer_root.resolve(strict=True)
    if _is_link(web_root):
        raise ValueError('Review web assets need a real directory.')
    web_root = web_root.resolve(strict=True)
    manifest = asset_manifest(viewer_root, include_3d=True, linked_models=True)
    by_name = {record.path: record for record in manifest}
    files = {}
    total = 0
    for name, path in paths.items():
        data = _read_file(path, viewer_root, by_name[name].bytes)
        if len(data) != by_name[name].bytes or hashlib.sha256(data).hexdigest() != by_name[name].sha256:
            raise ValueError('KiView source changed while preparing the Review web host.')
        files['vendor/' + name] = data
        total += len(data)
    # A host-owned entry keeps unmodified upstream URLs and legacy preloads
    # separate from the bridge. The published full ESM needs no preloads.
    imports = ("import './extension/repo-models.js';\nimport './extension/embedded-models.js';\n"
               if 'extension/repo-models.js' in paths else '')
    entry = (imports + "export {KiCadViewer} from './web-library/kicad-viewer.mjs';\n").encode('utf-8')
    files['vendor/review-viewer.mjs'] = entry
    total += len(entry)
    for name in _WEB_FILES:
        path = web_root / name
        data = _read_file(path, web_root, _MAX_WEB_FILE)
        files[name] = data
        total += len(data)
    if total > _MAX_TOTAL:
        raise ValueError('Review web asset snapshot exceeds its size bound.')
    verify_module_closure({name.removeprefix('vendor/'): data for name, data in files.items()
                           if name.startswith('vendor/')})
    verify_assets(viewer_root, manifest)
    for name in _WEB_FILES:
        path = web_root / name
        if _read_file(path, web_root, _MAX_WEB_FILE) != files[name]:
            raise ValueError('Review web assets changed while preparing the host.')
    return files


def _route(target: str, token: str) -> str | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    try:
        decoded = unquote_to_bytes(parsed.path).decode('utf-8', errors='strict')
    except UnicodeError:
        return None
    if not decoded.startswith('/' + token + '/'):
        return None
    relative = decoded[len(token) + 2:]
    if (not relative or '%' in relative or '\\' in relative or '\x00' in relative or
            any(part in ('', '.', '..') for part in relative.split('/'))):
        return None
    return relative


class ReviewWebHost:
    """Serve an immutable KiView/bridge snapshot from a random local URL.

    Source paths are explicit and are never copied, exposed in URLs, or read by
    request handlers. Close the host when its wxWebView is destroyed.
    """

    def __init__(self, viewer_root: str | Path, web_root: str | Path | None = None):
        viewer = Path(viewer_root).expanduser().absolute()
        web = (Path(web_root).expanduser().absolute() if web_root is not None else
               Path(__file__).with_name('web'))
        self._files = MappingProxyType(_snapshot(viewer, web))
        self._token = secrets.token_urlsafe(16)
        self._closed = False
        host = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self._serve(head=False)

            def do_HEAD(self):
                self._serve(head=True)

            def do_POST(self):
                self.send_error(405)

            def _serve(self, *, head: bool):
                if self.headers.get('Host') != host.origin.removeprefix('http://'):
                    self.send_error(403)
                    return
                name = _route(self.path, host._token)
                data = host._files.get(name) if name is not None else None
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', _mime(name))
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', _CSP)
                self.end_headers()
                if not head:
                    self.wfile.write(data)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False

        self._server = Server(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self._server.server_port}'
        self.url = f'{self.origin}/{self._token}/index.html'
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name='WayriCAD Review web host', daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self) -> 'ReviewWebHost':
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
