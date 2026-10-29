"""GitHub Discussions: complete bounded GraphQL reads and single-shot replies.

Schema: https://docs.github.com/en/graphql/reference/discussions
Credentials and HTTPS transport use the same private CLI boundary as issue reviews.
"""
from __future__ import annotations

import json
import re

from .model import host, scope
from .providers import MAX_BODY, credential, request

MAX_COMMENTS = 5000
MAX_REQUESTS = 100
PAGE_SIZE = 100

_FIELDS = 'id body author { login } updatedAt url replyTo { id }'
_PAGE = 'totalCount pageInfo { hasNextPage endCursor }'
_READ = '''query ReviewDiscussion($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    nameWithOwner hasDiscussionsEnabled
    discussion(number: $number) {
      id number title body author { login } updatedAt url
      comments(first: 100, after: $after) {
        ''' + _PAGE + ''' nodes { ''' + _FIELDS + '''
          replies(first: 100) { ''' + _PAGE + ' nodes { ' + _FIELDS + ''' } }
        }
      }
    }
  }
}'''
_REPLIES = '''query ReviewDiscussionReplies($id: ID!, $after: String) {
  node(id: $id) { ... on DiscussionComment {
    id discussion { id }
    replies(first: 100, after: $after) { ''' + _PAGE + ' nodes { ' + _FIELDS + ''' } }
  } }
}'''
_PUBLISH = '''mutation ReviewDiscussionComment($input: AddDiscussionCommentInput!) {
  addDiscussionComment(input: $input) {
    comment { id body discussion { id } replyTo { id } }
  }
}'''


def node_id(value):
    """Node IDs are opaque strings, distinct from issue REST numeric identities."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_+/=-]{1,256}', value):
        raise ValueError('GitHub returned an invalid Discussion node identity.')
    return value


class DiscussionProvider:
    """One existing GitHub Discussion, independently scoped from issue reviews."""

    provider = 'github'
    kind = 'discussion'
    origin = 'https://github.com'

    def __init__(self, settings, *, transport=request, tokens=credential):
        self.scope = scope(settings)
        if self.scope.get('provider', 'github') != 'github':
            raise ValueError('GitHub Discussions require a GitHub repository.')
        if host(settings.get('host', self.origin)) != self.origin:
            raise ValueError('GitHub Discussions currently support github.com only.')
        if settings.get('kind', self.kind) != self.kind:
            raise ValueError('Choose a GitHub Discussion conversation.')
        self.number = settings.get('number')
        if type(self.number) is not int or not 1 <= self.number <= 2147483647:
            raise ValueError('Choose a positive GitHub Discussion number.')
        self.repository = self.scope['repository']
        self.transport, self.tokens = transport, tokens
        self._discussion = None
        self._parents = {}

    @property
    def web_url(self):
        return self.origin + '/' + self.repository + '/discussions/' + str(self.number)

    @property
    def board_url(self):
        return self.origin + '/' + self.repository + '/projects'

    def boards(self):
        return {'url': self.board_url, 'boards': [], 'mode': 'provider-browser'}

    def _call(self, query, variables):
        try:
            token = self.tokens(self.provider, self.origin)
            if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
                raise ValueError('Invalid credential')
            headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                       'Accept': 'application/vnd.github+json', 'User-Agent': 'WayriCAD-Review/0.1'}
            status, _, result = self.transport('POST', 'https://api.github.com/graphql', headers,
                                              json.dumps(dict(query=query, variables=variables)).encode())
        except Exception:
            # Transport diagnostics are not trusted to omit tokens/request bodies.
            raise RuntimeError('GitHub Discussion request failed. Check login, permissions and connectivity.') from None
        if (status != 200 or not isinstance(result, dict) or result.get('errors')
                or ('errors' in result and not isinstance(result['errors'], list))
                or not isinstance(result.get('data'), dict)):
            raise RuntimeError('GitHub Discussion GraphQL request failed or returned partial data. Check access and refresh.')
        return result['data']

    def _row(self, value, *, root=False, parent=None):
        if not isinstance(value, dict):
            raise ValueError('GitHub returned an incomplete Discussion record.')
        identifier = node_id(value.get('id'))
        body, updated, url = value.get('body'), value.get('updatedAt'), value.get('url')
        if not isinstance(body, str) or not isinstance(updated, str) or not updated:
            raise ValueError('GitHub returned incomplete Discussion text or timestamps.')
        # GitHub repository names are case-insensitive; API URLs use canonical case.
        if (not isinstance(url, str) or (url.casefold() != self.web_url.casefold() if root else
                not re.fullmatch(re.escape(self.web_url) + r'#discussioncomment-[0-9]+', url, re.IGNORECASE))):
            raise ValueError('GitHub returned a Discussion URL outside the selected conversation.')
        if not root:
            if 'replyTo' not in value:
                raise ValueError('GitHub returned an incomplete Discussion reply relationship.')
            relation = value['replyTo']
            if parent is None:
                if relation is not None:
                    raise ValueError('GitHub returned a reply as a top-level Discussion comment.')
            elif not isinstance(relation, dict) or relation.get('id') != parent:
                raise ValueError('GitHub returned a Discussion reply in another thread.')
        author = value.get('author')
        if author is None:
            login = 'unknown'
        elif (not isinstance(author, dict) or not isinstance(author.get('login'), str)
                or not 1 <= len(author['login']) <= 200):
            raise ValueError('GitHub returned an incomplete Discussion author.')
        else:
            login = author['login']
        result = dict(id=identifier, root=root, body=body, author=login, updatedAt=updated, url=url)
        if parent is not None:
            result['parentId'] = parent
        return result

    @staticmethod
    def _page(value, seen, expected=None):
        if not isinstance(value, dict):
            raise ValueError('GitHub returned an incomplete Discussion comment collection.')
        total, rows, page = value.get('totalCount'), value.get('nodes'), value.get('pageInfo')
        if (type(total) is not int or total < 0 or total > MAX_COMMENTS
                or not isinstance(rows, list) or len(rows) > PAGE_SIZE
                or not isinstance(page, dict) or type(page.get('hasNextPage')) is not bool):
            raise ValueError('Discussion is incomplete or exceeds the 5,000-comment limit. Cache was not replaced.')
        if expected is not None and total != expected:
            raise ValueError('Discussion changed during pagination. Refresh for a complete snapshot.')
        cursor = page.get('endCursor')
        if page['hasNextPage']:
            if (not rows or not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024
                    or cursor in seen or any(ord(c) < 32 for c in cursor)):
                raise ValueError('GitHub returned an invalid or repeated Discussion page cursor.')
            seen.add(cursor)
        return rows, cursor if page['hasNextPage'] else None, total

    def snapshot(self):
        """Replace publication identities only after every comment/reply page succeeds."""
        self._discussion, self._parents = None, {}
        rows, identities, parents = [], set(), {}
        requests, body_size = 0, 0

        def read(query, variables):
            nonlocal requests
            requests += 1
            if requests > MAX_REQUESTS:
                raise ValueError('Discussion requires too many pages. Choose a smaller conversation; cache was not replaced.')
            return self._call(query, variables)

        def add(value, *, root=False, parent=None):
            nonlocal body_size
            row = self._row(value, root=root, parent=parent)
            if row['id'] in identities:
                raise ValueError('Discussion changed during pagination or contains duplicate identities. Refresh again.')
            identities.add(row['id'])
            body_size += len(json.dumps(row, ensure_ascii=True).encode())
            if len(rows) >= MAX_COMMENTS + 1 or body_size > MAX_BODY:
                raise ValueError('Discussion exceeds the 5,000-comment or 8 MiB snapshot limit. Cache was not replaced.')
            rows.append(row)
            if not root:
                parents[row['id']] = parent
            return row['id']

        owner, name = self.repository.split('/')
        cursor, total, count, discussion_id = None, None, 0, None
        seen = set()
        while True:
            data = read(_READ, dict(owner=owner, name=name, number=self.number, after=cursor))
            repo = data.get('repository')
            if not isinstance(repo, dict):
                raise ValueError('GitHub repository is missing or inaccessible.')
            if not isinstance(repo.get('nameWithOwner'), str) or repo['nameWithOwner'].casefold() != self.repository.casefold():
                raise ValueError('GitHub returned a different repository. Check repository settings.')
            if repo.get('hasDiscussionsEnabled') is not True:
                raise ValueError('GitHub Discussions are disabled or unavailable in this repository.')
            root = repo.get('discussion')
            if not isinstance(root, dict) or type(root.get('number')) is not int or root['number'] != self.number:
                raise ValueError('GitHub Discussion is missing or inaccessible. Choose an existing Discussion number.')
            if discussion_id is None:
                discussion_id = add(root, root=True)
            elif (root.get('id') != discussion_id or not isinstance(root.get('url'), str)
                    or root['url'].casefold() != self.web_url.casefold()):
                raise ValueError('GitHub Discussion identity changed during pagination. Refresh again.')
            comments, cursor, total = self._page(root.get('comments'), seen, total)
            count += len(comments)
            for comment in comments:
                identifier = add(comment)
                replies, reply_cursor, reply_total = self._page(comment.get('replies'), set())
                reply_count, reply_seen = 0, {reply_cursor} if reply_cursor else set()
                while True:
                    for reply in replies:
                        add(reply, parent=identifier)
                    reply_count += len(replies)
                    if reply_cursor is None:
                        break
                    data = read(_REPLIES, dict(id=identifier, after=reply_cursor))
                    node = data.get('node')
                    if (not isinstance(node, dict) or node.get('id') != identifier
                            or not isinstance(node.get('discussion'), dict)
                            or node['discussion'].get('id') != discussion_id):
                        raise ValueError('GitHub Discussion reply target changed or disappeared. Refresh again.')
                    replies, reply_cursor, reply_total = self._page(node.get('replies'), reply_seen, reply_total)
                if reply_count != reply_total:
                    raise ValueError('GitHub returned an incomplete Discussion reply collection. Refresh again.')
            if cursor is None:
                break
        if count != total:
            raise ValueError('GitHub returned an incomplete Discussion comment collection. Refresh again.')
        self._discussion, self._parents = discussion_id, parents
        return rows

    def publish(self, body, reply_to=None):
        """One mutation, never retried; replies target their native top-level thread."""
        if not isinstance(body, str) or not body.strip() or len(body.encode()) > 64000:
            raise ValueError('Comment is empty or exceeds 64 KiB.')
        if self._discussion is None:
            raise ValueError('Refresh the complete GitHub Discussion before publishing.')
        if reply_to is not None and reply_to != self._discussion and reply_to not in self._parents:
            raise ValueError('Reply target is not in this GitHub Discussion. Refresh before posting.')
        parent = None
        if reply_to is not None and reply_to != self._discussion:
            parent = self._parents[reply_to] or reply_to
        discussion_id = self._discussion
        payload = dict(discussionId=discussion_id, body=body)
        if parent is not None:
            payload['replyToId'] = parent
        # Even a successful receipt requires a new read before another write.
        self._discussion, self._parents = None, {}
        try:
            data = self._call(_PUBLISH, dict(input=payload))
            result = data.get('addDiscussionComment')
            row = result.get('comment') if isinstance(result, dict) else None
            if (not isinstance(row, dict) or row.get('body') != body
                    or not isinstance(row.get('discussion'), dict) or row['discussion'].get('id') != discussion_id
                    or 'replyTo' not in row):
                raise ValueError('Incomplete publication receipt')
            returned_parent = row['replyTo']
            if returned_parent != (dict(id=parent) if parent is not None else None):
                raise ValueError('Incorrect reply receipt')
            return node_id(row.get('id'))
        except Exception:
            raise RuntimeError('Discussion publication was not confirmed. Refresh the provider thread and check for your comment before retrying; the draft has been retained.') from None
