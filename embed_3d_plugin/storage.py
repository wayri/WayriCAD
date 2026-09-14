"""Backup-first, per-file atomic writes and conservative rollback/restore.

Multi-file batches cannot be crash-atomic on ordinary filesystems. A durable
journal and immutable originals are created before the first target is changed.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
from .codec import sha256
from .core import Plan, verify_sources


def job_directory(parent: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = parent/'.embed_3d_plugin-backups'/(stamp+'-'+uuid.uuid4().hex[:8])
    dest.mkdir(parents=True, exist_ok=False)
    return dest


def atomic_write(path: Path, data: bytes, mode: int | None = None):
    """Stage next to the destination to keep os.replace on the same filesystem."""
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.embed_3d_plugin-tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path, obj):
    atomic_write(path, (json.dumps(obj, indent=2, ensure_ascii=False)+'\n').encode('utf-8'))


def embed_files(plans: list[Plan], backup_parent: Path, validator=None) -> Path:
    chosen = [p for p in plans if p.actionable]
    if not chosen:
        raise ValueError('No checked models are ready to embed')
    paths = [p.source_path for p in chosen]
    if any(p is None for p in paths) or len(set(paths)) != len(paths):
        raise ValueError('Each footprint must have a unique source file')
    verify_sources(chosen)
    outputs = [(p, p.build().encode('utf-8')) for p in chosen]
    if validator:
        for plan, data in outputs:
            validator(plan, data.decode('utf-8'))
    job = job_directory(backup_parent)
    journal = {'format': 'embed_3d_plugin-backup-v1', 'status': 'prepared', 'files': [],
               'plans': [p.manifest() for p in chosen]}
    for index, (plan, new) in enumerate(outputs):
        path = plan.source_path
        original = plan.original.encode('utf-8')
        backup = job/('%04d_' % index + path.name)
        atomic_write(backup, original)
        journal['files'].append({'target': str(path.resolve()), 'backup': backup.name,
                                 'before_sha256': sha256(original), 'after_sha256': sha256(new),
                                 'mode': stat.S_IMODE(path.stat().st_mode), 'written': False})
    write_json(job/'manifest.json', journal)
    completed = []
    try:
        # Recheck after potentially slow native validation and backup creation.
        verify_sources(chosen)
        for (plan, new), item in zip(outputs, journal['files']):
            path = plan.source_path
            if sha256(path.read_bytes()) != item['before_sha256']:
                raise ValueError('Footprint changed before write: '+str(path))
            completed.append(item)  # A failure can happen after os.replace; track attempts.
            atomic_write(path, new, item['mode'])
            if path.read_bytes() != new:
                raise OSError('Read-back verification failed: '+str(path))
            item['written'] = True
            write_json(job/'manifest.json', journal)
        journal['status'] = 'complete'
        write_json(job/'manifest.json', journal)
    except Exception as exc:
        errors = []
        for item in reversed(completed):
            path = Path(item['target'])
            try:
                current = sha256(path.read_bytes())
                if current == item['before_sha256']:
                    continue
                if current != item['after_sha256']:
                    raise ValueError('File was modified again; manual restore required: '+str(path))
                atomic_write(path, (job/item['backup']).read_bytes(), item['mode'])
                item['written'] = False
            except Exception as rollback_error:
                errors.append(str(rollback_error))
        journal['status'] = 'rollback-needed' if errors else 'rolled-back'
        journal['error'], journal['rollback_errors'] = str(exc), errors
        try:
            write_json(job/'manifest.json', journal)
        except OSError:
            pass
        raise RuntimeError('%s\nBackups: %s%s' % (exc, job, '\n'+'\n'.join(errors) if errors else '')) from exc
    return job


def restore_files(manifest_path: Path) -> int:
    """Restore only files that still match this job's output; never overwrite later work."""
    job = manifest_path.parent
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    if data.get('format') != 'embed_3d_plugin-backup-v1':
        raise ValueError('Not a WayriCAD Embed3D library-file backup manifest')
    ready = []
    for item in data['files']:
        backup_name = item['backup']
        if Path(backup_name).name != backup_name:
            raise ValueError('Invalid backup filename')
        original = (job/backup_name).read_bytes()
        if sha256(original) != item['before_sha256']:
            raise ValueError('Backup checksum mismatch: '+backup_name)
        path = Path(item['target'])
        current = sha256(path.read_bytes())
        if current == item['before_sha256']:
            continue
        if current != item['after_sha256']:
            raise ValueError('Later edits detected; refusing to overwrite '+str(path))
        ready.append((path, original, item))
    for path, original, item in ready:
        if sha256(path.read_bytes()) != item['after_sha256']:
            raise ValueError('File changed during restore: '+str(path))
        atomic_write(path, original, item.get('mode'))
    data['status'] = 'restored'
    write_json(manifest_path, data)
    return len(ready)
