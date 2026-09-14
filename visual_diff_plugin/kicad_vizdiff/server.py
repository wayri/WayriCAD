"""Development GitHub App/extension service. Public repositories only in v0.1."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit

from .github import api, download_snapshot, installation_token, public_commit, repository_name, verify_webhook
from .git import VizError, run, safe_path
from .render import DEFAULT_LAYERS, find_kicad, pair_pages, render


class Jobs:
    def __init__(self, executable):
        self.executable = executable
        self.version = run([executable, 'version']).decode().strip()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.items = {}
        self.lock = threading.Lock()
        self.seen_deliveries = {}

    def submit(self, request):
        repo = repository_name(request.get('repository'))
        path = request.get('file')
        if not isinstance(path, str) or Path(path).suffix not in ('.kicad_sch', '.kicad_pcb'):
            raise VizError('file must be a repository-relative KiCad schematic or PCB path.')
        safe_path(Path(tempfile.gettempdir()), path)
        if request.get('base') is not None and not isinstance(request['base'], str):
            raise VizError('base must be a Git revision string.')
        if not isinstance(request.get('head'), str):
            raise VizError('head must be a Git revision string.')
        old_file = request.get('oldFile', path)
        if not isinstance(old_file, str):
            raise VizError('oldFile must be a path.')
        safe_path(Path(tempfile.gettempdir()), old_file)
        layers = request.get('layers', DEFAULT_LAYERS)
        if not isinstance(layers, str) or len(layers) > 1000:
            raise VizError('Invalid layer selection.')
        with self.lock:
            cutoff = time.time() - 3600
            self.items = {k: v for k, v in self.items.items() if v['created'] > cutoff or v['status'] in ('queued', 'rendering')}
            if len(self.items) >= 40:
                raise VizError('Preview capacity reached. Retry after reports expire (one hour).')
            job = secrets.token_urlsafe(24)
            self.items[job] = {'status': 'queued', 'created': time.time()}
        self.pool.submit(self.render, job, repo, path, old_file, request.get('base'), request['head'], layers)
        return job

    def render(self, job, repo, path, old_file, base, head, layers):
        self.items[job]['status'] = 'rendering'
        try:
            head_sha = public_commit(repo, head)
            base_sha = public_commit(repo, base) if base else None
            with tempfile.TemporaryDirectory(prefix='kicad-github-') as temp:
                temp = Path(temp)
                before = {}
                if base_sha:
                    download_snapshot(repo, base_sha, temp / 'base')
                    before = render(temp / 'base', old_file, temp / 'old-svg', self.executable, layers)
                download_snapshot(repo, head_sha, temp / 'head')
                after = render(temp / 'head', path, temp / 'new-svg', self.executable, layers)
                if not before and not after:
                    raise VizError('The KiCad file was not found at these revisions.')
                pages = pair_pages(before, after)
                self.items[job]['report'] = {'file': path, 'oldFile': old_file, 'repository': repo,
                    'base': base_sha, 'head': head_sha, 'mode': 'diff' if base else 'view',
                    'kicad': self.version, 'theme': 'KiCad default', 'pages': pages}
            self.items[job]['status'] = 'complete'
        except Exception as exc:
            self.items[job].update(status='failed', error=str(exc))


class Handler(BaseHTTPRequestHandler):
    server_version = 'WayriCADVisualDiff/3.0'

    def log_message(self, format, *args):
        pass  # Avoid logging report capability URLs and credentials.

    def respond(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def authenticated(self):
        key = self.server.api_key
        return not key or secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + key)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self.respond(200, {'status': 'ok', 'kicad': self.server.jobs.version, 'privateRepositories': False})
        if not self.authenticated():
            return self.respond(401, {'error': 'Service API key required.'})
        if path.startswith('/api/jobs/'):
            job = self.server.jobs.items.get(path.removeprefix('/api/jobs/'))
            if job:
                return self.respond(200, dict(job))
        self.respond(404, {'error': 'Not found.'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024 * 1024:
                return self.respond(413, {'error': 'Request body must be between 1 byte and 1 MiB.'})
            raw = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path == '/api/github/webhook':
                if not verify_webhook(os.environ.get('GITHUB_WEBHOOK_SECRET', ''), raw, self.headers.get('X-Hub-Signature-256')):
                    return self.respond(401, {'error': 'Invalid webhook signature.'})
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise VizError('Expected a JSON object.')
                delivery = self.headers.get('X-GitHub-Delivery', '')
                if not delivery:
                    raise VizError('Missing webhook delivery ID.')
                with self.server.jobs.lock:
                    now = time.time()
                    seen = self.server.jobs.seen_deliveries
                    self.server.jobs.seen_deliveries = {k: v for k, v in seen.items() if now-v < 86400}
                    if delivery in self.server.jobs.seen_deliveries:
                        return self.respond(202, {'status': 'duplicate'})
                    if len(self.server.jobs.seen_deliveries) >= 10000:
                        raise VizError('Webhook capacity reached.')
                    self.server.jobs.seen_deliveries[delivery] = now
                if self.headers.get('X-GitHub-Event') == 'pull_request' and payload.get('action') in ('opened', 'synchronize', 'reopened'):
                    if payload.get('repository', {}).get('private', True):
                        return self.respond(202, {'status': 'skipped', 'reason': 'Private repositories are not enabled in v0.1.'})
                    self.server.webhooks.submit(self.server.process_pr, payload)
                return self.respond(202, {'status': 'accepted'})
            if path != '/api/jobs':
                return self.respond(404, {'error': 'Not found.'})
            if not self.authenticated():
                return self.respond(401, {'error': 'Service API key required.'})
            if self.headers.get_content_type() != 'application/json':
                return self.respond(415, {'error': 'Use application/json.'})
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise VizError('Expected a JSON object.')
            return self.respond(202, {'id': self.server.jobs.submit(payload)})
        except (ValueError, VizError, TypeError, KeyError) as exc:
            self.respond(400, {'error': str(exc)})


class Server(ThreadingHTTPServer):
    def process_pr(self, payload):
        """Post links to the GitHub file views enhanced by the companion extension."""
        try:
            repo = repository_name(payload['repository']['full_name'])
            pr = payload['pull_request']
            number = int(pr['number'])
            # Commit refs/pull/N/head are available in the base repo, including public forks.
            changes = []
            for page in range(1, 31):
                batch = api(f'/repos/{repo}/pulls/{number}/files?per_page=100&page={page}')
                changes.extend(batch)
                if len(batch) < 100:
                    break
            designs = [f for f in changes if Path(f['filename']).suffix in ('.kicad_sch', '.kicad_pcb')]
            if not designs:
                return
            token = installation_token(os.environ['GITHUB_APP_ID'], os.environ['GITHUB_PRIVATE_KEY_PATH'], payload['installation']['id'])
            summary = (f'Found {len(designs)} KiCad design file(s). Open **Files changed** with the KiCad Visual Review browser extension for native page previews and visual comparison. '
                       'The extension renders on demand. Page borders and title blocks are preserved.\n\n'
                       f'[Open visual review](https://github.com/{repo}/pull/{number}/files)')
            api(f'/repos/{repo}/check-runs', token, {'name': 'KiCad visual review', 'head_sha': pr['head']['sha'],
                'status': 'completed', 'conclusion': 'neutral', 'details_url': f'https://github.com/{repo}/pull/{number}/files',
                'output': {'title': f'{len(designs)} KiCad design files available for visual review', 'summary': summary}})
        except Exception as exc:
            print(f'GitHub App event failed: {type(exc).__name__}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='GitHub App and browser extension rendering service (public repository preview).')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--kicad-cli')
    args = parser.parse_args()
    key = os.environ.get('VIZDIFF_API_KEY', '')
    if args.host not in ('127.0.0.1', 'localhost', '::1') and len(key) < 24:
        parser.error('Set VIZDIFF_API_KEY (at least 24 characters) before binding to a network interface.')
    server = Server((args.host, args.port), Handler)
    server.api_key = key
    server.jobs = Jobs(find_kicad(args.kicad_cli))
    server.webhooks = ThreadPoolExecutor(max_workers=1)
    print(f'WayriCAD GitHub preview service: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.jobs.pool.shutdown(wait=False, cancel_futures=True)
        server.webhooks.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
