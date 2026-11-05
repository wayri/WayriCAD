"""Review lifecycle: authoritative remote snapshots, cache labels, stale source guards."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .model import anchor, attachment, markdown, note, read_markers, saved_context, scope, unchanged
from .providers import Provider
from .discussions import DiscussionProvider, node_id


def _valid_node_id(value):
    try:
        node_id(value)
        return True
    except ValueError:
        return False


def atomic_json(path, value):
    """Atomic, unique staging; private settings/cache never enter a design file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.review-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def data_home():
    base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local/share'))
    return base / 'WayriCAD' / 'review'


class ReviewSession:
    def __init__(self, settings, *, provider=None, cache_dir=None, desktop=False, context_updates=None):
        if not isinstance(settings, dict):
            raise ValueError('Review settings must be a JSON object.')
        self.settings = dict(settings)
        self.context_updates = desktop if context_updates is None else context_updates is True
        self.scope = scope(settings)
        self._desktop_auth = None
        provider_options = {}
        if desktop:
            from .desktop_auth import AUTH
            from .providers import request
            identity = self.scope.get('provider', 'github'), self.scope.get('host', 'https://github.com')
            epoch = AUTH.ticket(*identity)
            self._desktop_auth = identity, epoch

            def tokens(provider_name, origin):
                AUTH.assert_ticket(*identity, epoch)
                return AUTH.credential(provider_name, origin)

            def transport(method, url, headers, data=None):
                AUTH.assert_ticket(*identity, epoch)
                result = request(method, url, headers, data)
                AUTH.assert_ticket(*identity, epoch)
                return result

            provider_options = dict(tokens=tokens, transport=transport)
        if provider is not None:
            self.provider = provider
        elif settings.get('kind') == 'discussion':
            # The UI's host field configures GitLab only; GitHub is fixed to
            # github.com and must never inherit the GitLab field's default.
            github_settings = {key: value for key, value in settings.items() if key != 'host'}
            self.provider = DiscussionProvider(github_settings, **provider_options)
        else:
            self.provider = Provider(settings, **provider_options)
        self.path, self.digest = saved_context(settings['root'], self.scope)
        key = hashlib.sha256(json.dumps([self.scope, self.provider.kind, self.provider.number], sort_keys=True).encode()).hexdigest()
        self.cache_path = Path(cache_dir or data_home()) / (key + '.json')
        self.rows = []
        self.status = 'not synced'
        self.synced_at = None
        self.failures = 0
        self.cache_warning = None
        self.context_warning = None
        from .context_sync import ContextTracker
        self.context_tracker = ContextTracker()

    def require_authorization(self):
        if self._desktop_auth is not None:
            from .desktop_auth import AUTH
            identity, epoch = self._desktop_auth
            try:
                AUTH.assert_ticket(*identity, epoch)
            except RuntimeError:
                self.status = 'signed out'
                raise

    def cached(self):
        """Offline cache is visibly stale and cannot authorize publishing or navigation."""
        try:
            if self.cache_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Review cache exceeds 16 MiB.')
            cached = json.loads(self.cache_path.read_text(encoding='utf-8'))
            if not isinstance(cached, dict) or cached.get('scope') != self.scope or not isinstance(cached.get('rows'), list):
                raise ValueError('Cache belongs to another review.')
            rows = cached['rows']
            timestamp = cached.get('syncedAt')
            if not isinstance(timestamp, str) or len(timestamp) > 50:
                raise ValueError('Invalid cache sync timestamp.')
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if len(rows) > 5001 or any(not isinstance(r, dict) or not isinstance(r.get('id'), str)
                    or not (_valid_node_id(r['id']) if self.provider.kind == 'discussion' else r['id'].isdigit())
                    or not isinstance(r.get('body'), str) or not isinstance(r.get('author'), str)
                    or not isinstance(r.get('updatedAt', ''), str) for r in rows):
                raise ValueError('Invalid cache schema.')
            self.rows = [dict(r, anchors=[], contextStatus=[], updatedAt=r.get('updatedAt', '')) for r in rows]
            self.synced_at, self.status = timestamp, 'cached / unverified'
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, RecursionError):
            self.cache_warning = 'Local cache unavailable; fetch provider comments to continue.'
            self.rows, self.status = [], 'cache unavailable / unverified'
        return self.rows

    def draft(self, text=None, target=None, attachments=()):
        """Private pending text is distinct from provider-backed published annotations."""
        path = self.cache_path.with_suffix('.draft.json')
        if text is not None:
            if not isinstance(text, str) or len(text) > 16000:
                raise ValueError('Draft exceeds 16,000 characters.')
            target = anchor(target or self.scope)
            if scope(target) != self.scope:
                raise ValueError('Draft belongs to another design revision.')
            if len(attachments) > 4:
                raise ValueError('At most four screenshot attachments are supported.')
            atomic_json(path, dict(status='unpublished', text=text, anchor=target,
                                  attachments=[attachment(value, target) for value in attachments]))
            return
        try:
            if path.stat().st_size > 100000:
                return None
            value = json.loads(path.read_text(encoding='utf-8'))
            if (isinstance(value, dict) and value.get('status') == 'unpublished' and isinstance(value.get('text'), str)
                    and len(value['text']) <= 16000 and scope(value['anchor']) == self.scope):
                images = value.get('attachments', [])
                if not isinstance(images, list) or len(images) > 4:
                    return None
                return dict(text=value['text'], anchor=anchor(value['anchor']),
                            attachments=[attachment(image, self.scope) for image in images])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def refresh(self):
        source_verified = False
        def committed_guard():
            self.require_authorization()
            unchanged(self.path, self.digest)
        try:
            self.require_authorization()
            unchanged(self.path, self.digest)
            source_verified = True
            rows = self.provider.snapshot()
            self.require_authorization()
            source_verified = False
            unchanged(self.path, self.digest)
            source_verified = True
            for row in rows:
                # Local remoteRefs cannot invent publication: only provider readback
                # constructs this association. Invalid or foreign anchors stay unlocated.
                annotations = read_markers(row['body'], self.scope)
                row['anchors'] = [n['anchor'] for n in annotations]
                row['annotations'] = annotations
            rows = self.context_tracker.update(rows, self.provider, self.settings['root'], self.scope,
                auto_publish=self.context_updates and self.settings.get('contextSync', True) is True,
                prepublish=committed_guard)
            self.context_warning = self.context_tracker.warning
            self.require_authorization()
            source_verified = False
            unchanged(self.path, self.digest)
            source_verified = True
            # A status preflight can include a newly arrived or edited row.
            # Rebuild navigation authority from its actual provider body.
            for row in rows:
                row['annotations'] = read_markers(row['body'], self.scope)
                row['anchors'] = [n['anchor'] for n in row['annotations']]
            identifiers = {row['id'] for row in rows}
            for row in rows:
                from .model import project_markers
                relationships = row['annotations'] or project_markers(row['body'], self.scope)
                if self.provider.kind != 'discussion' and not row.get('parentId') and len(relationships) == 1:
                    reply_to = relationships[0].get('replyTo')
                    if isinstance(reply_to, str) and reply_to.isdigit() and len(reply_to) <= 200 and reply_to != row['id']:
                        row['parentId'] = reply_to
            timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
            try:
                atomic_json(self.cache_path, dict(schemaVersion=1, scope=self.scope, rows=rows, syncedAt=timestamp))
                self.cache_warning = None
            except OSError:
                self.cache_warning = 'Provider synced; local cache could not be saved.'
            self.rows, self.synced_at, self.status, self.failures = rows, timestamp, 'synced', 0
            return rows
        except Exception:
            context_only = False
            if not source_verified and self.status != 'signed out':
                # Independent diagnostics may read the conversation after the
                # source disappears; they never restore navigation/publication.
                try:
                    self.require_authorization()
                    rows = self.provider.snapshot()
                    self.require_authorization()
                    rows = self.context_tracker.update(rows, self.provider, self.settings['root'], self.scope,
                        auto_publish=self.context_updates and self.settings.get('contextSync', True) is True,
                        prepublish=self.require_authorization)
                    self.require_authorization()
                    self.rows = [dict(row, anchors=[], annotations=[]) for row in rows]
                    self.context_warning = self.context_tracker.warning
                    self.status = 'context only / saved source changed or unavailable'
                    self.synced_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    self.failures = 0
                    context_only = True
                except Exception:
                    pass
            if self.status != 'signed out' and not context_only:
                self.status = 'offline / stale'
            if not context_only:
                self.failures = min(6, self.failures + 1)
            raise

    @property
    def interval_seconds(self):
        return min(120, 8 * 2 ** self.failures)

    @property
    def participants(self):
        return sorted({r.get('author', 'unknown') for r in self.rows}, key=str.casefold)

    def publish(self, text, target, *, reply_to=None, attachments=()):
        self.require_authorization()
        if self.status != 'synced':
            raise ValueError('Refresh successfully before publishing; cached anchors are unverified.')
        unchanged(self.path, self.digest)
        if scope(target) != self.scope:
            raise ValueError('Comment anchor belongs to a different revision or file.')
        from .review_targets import verify_target
        verify_target(target, self.settings['root'])
        if reply_to is not None and str(reply_to) not in {r['id'] for r in self.rows}:
            raise ValueError('Reply target is no longer in this provider conversation.')
        # Preflight existence/permissions and resolve ambiguous prior publications
        # through fresh provider reads; POST itself is never automatically retried.
        self.refresh()
        verify_target(target, self.settings['root'])
        if reply_to is not None and str(reply_to) not in {r['id'] for r in self.rows}:
            raise ValueError('The reply target was removed remotely. Draft retained.')
        value = note(text, target, reply_to=reply_to, attachments=attachments)
        if self.provider.kind == 'discussion':
            value['threadType'] = 'discussion'
        body = markdown(value)
        self.status = 'publication pending'
        try:
            identifier = (self.provider.publish(body, reply_to=reply_to)
                          if self.provider.kind == 'discussion' else self.provider.publish(body))
        except Exception:
            self.status = 'publication uncertain / refresh required'
            raise
        self.status = 'published / refresh required'
        return identifier

    def locate(self, identifier, *, selector=None):
        """Resolve current provider anchors only; native selection never writes geometry."""
        self.require_authorization()
        if self.status != 'synced':
            raise ValueError('Refresh before locating a comment; the cache is not authoritative.')
        self.refresh()
        unchanged(self.path, self.digest)
        row = next((r for r in self.rows if r['id'] == str(identifier)), None)
        if not row or len(row.get('anchors', [])) != 1:
            raise ValueError('This comment has no unique anchor for the current file and revision.')
        target = anchor(row['anchors'][0])
        if self.path.suffix.lower() != '.kicad_pcb':
            raise ValueError('This host adapter does not expose supported live schematic selection. Open the linked revision in KiView instead.')
        if not target.get('uuid'):
            raise ValueError('Region overlay is unavailable in this host adapter. Region coordinates remain in the comment; no design markers were created.')
        if selector is None:
            from wayricad_runtime.analysis_selection import select_origin
            selector = select_origin
        result = selector(self.path, [target['uuid']], expected_sha256=self.digest, focus=True, return_details=True)
        unchanged(self.path, self.digest)
        return result
