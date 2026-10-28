"""Run custody and subprocess lifecycle, independent of the native widgets."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from .backend import atomic_json
from .model import config_digest, source_identity, validate_config


class StudySession:
    def __init__(self, board):
        self.board = Path(board).resolve()
        self.review = None
        self.process = None
        self.run_dir = None
        self.log = None

    def preview(self, config, region=None):
        self.review = {'config': validate_config(config), 'source': source_identity(self.board)}
        self.review['config_sha256'] = config_digest(self.review['config'])
        if self.review['config']['mode'] == 'pcb_region':
            from .region_backend import region_digest, validate_region
            validate_region(region, self.review['config'])
            if region['source'] != self.review['source']:
                raise ValueError('Region source differs from the current saved board; reload its rule areas.')
            self.review.update(region=region, region_sha256=region_digest(region))
        return self.review

    def start(self, config, python, output, *, solver_environment=None):
        if self.process is not None and self.process.poll() is None:
            raise ValueError('A simulation is already running.')
        if not self.review or self.review['config_sha256'] != config_digest(config):
            raise ValueError('Preview the current setup before running.')
        if source_identity(self.board) != self.review['source']:
            raise ValueError('PCB changed since preview. Preview again.')
        if solver_environment is not None and (not isinstance(solver_environment, dict) or set(solver_environment)-{'EMERGE_PARDISO_PATH'}):
            raise ValueError('Only a verified solver-library hint may be supplied.')
        executable = Path(python).expanduser().resolve(strict=True)
        output = Path(output).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(output).free < 1024**3:
            raise ValueError('Less than 1 GiB free in the run destination. Choose another drive or free space.')
        self.run_dir = output/uuid.uuid4().hex
        self.run_dir.mkdir()
        atomic_json(self.run_dir/'request.json', self.review)
        atomic_json(self.run_dir/'status.json', {'status': 'running'})
        self.log = (self.run_dir/'solver.log').open('wb')
        try:
            self.process = subprocess.Popen(
                [str(executable), '-I', str(Path(__file__).with_name('__main__.py')),
                 '--worker', str(self.run_dir/'request.json')],
                cwd=self.run_dir, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                env={**os.environ, **(solver_environment or {})},
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as exc:
            self.log.close()
            atomic_json(self.run_dir/'status.json', {'status': 'failed', 'error': str(exc)})
            raise

    def log_tail(self):
        if self.run_dir is None:
            return ''
        with (self.run_dir/'solver.log').open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-8192))
            return stream.read().decode('utf-8', errors='replace')

    def collect(self):
        if self.process is None or self.process.poll() is None:
            return None
        self.log.close()
        exit_code = self.process.returncode
        self.process = None
        status = json.loads((self.run_dir/'status.json').read_text(encoding='utf-8'))
        if exit_code or status['status'] != 'completed':
            raise RuntimeError(status.get('error', f'Solver exited with code {exit_code}. See solver.log.'))
        result = json.loads((self.run_dir/'result.json').read_text(encoding='utf-8'))
        if (result['config_sha256'] != self.review['config_sha256'] or
                result['source'] != self.review['source'] or
                source_identity(self.board) != result['source']):
            raise ValueError('Result does not match the reviewed setup and current source PCB.')
        if self.review.get('region_sha256') and result.get('region_sha256') != self.review['region_sha256']:
            raise ValueError('Result does not match the reviewed rule-area geometry.')
        return result

    def cancel(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.log.close()
            self.process = None
            atomic_json(self.run_dir/'status.json', {'status': 'cancelled'})
