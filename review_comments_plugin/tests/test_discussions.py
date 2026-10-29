"""Real GraphQL operation contracts, complete snapshots, and publication safety."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from review_comments_plugin.discussions import DiscussionProvider

BASE = dict(repository='example/board', ref='a' * 40, file='board.kicad_pcb', number=7, kind='discussion')
URL = 'https://github.com/example/board/discussions/7'


def connection(nodes=(), *, more=False, cursor=None, total=None):
    return dict(nodes=list(nodes), totalCount=len(nodes) if total is None else total,
                pageInfo=dict(hasNextPage=more, endCursor=cursor))


def comment(identifier='DC_one', *, parent=None, replies=None, body='hello'):
    row = dict(id=identifier, body=body, author=dict(login='alice'), updatedAt='2026-10-29T00:00:00Z',
               url=URL + '#discussioncomment-' + str(sum(map(ord, identifier))),
               replyTo=dict(id=parent) if parent else None)
    if replies is not None:
        row['replies'] = replies
    return row


def root(comments=None, **changes):
    discussion = dict(id='D_root', number=7, title='Review', body='Discuss the board', author=dict(login='owner'),
                      updatedAt='2026-10-29T00:00:00Z', url=URL,
                      comments=connection() if comments is None else comments)
    discussion.update(changes)
    return dict(repository=dict(nameWithOwner='example/board', hasDiscussionsEnabled=True, discussion=discussion))


def receipt(body='posted', parent=None, **changes):
    row = dict(id='DC_new', body=body, discussion=dict(id='D_root'), replyTo=dict(id=parent) if parent else None)
    row.update(changes)
    return dict(addDiscussionComment=dict(comment=row))


def client(responses, **settings):
    calls = []
    pending = iter(responses)

    def transport(method, url, headers, data):
        payload = json.loads(data)
        calls.append(dict(method=method, url=url, headers=headers, **payload))
        value = next(pending)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, tuple) else (200, {}, dict(data=deepcopy(value)))

    provider = DiscussionProvider(dict(BASE, **settings), transport=transport, tokens=lambda *_: 'private-token')
    return provider, calls


def test_reads_root_comments_and_native_replies_with_fixed_endpoint():
    replies = connection([comment('DC_reply', parent='DC_one')])
    p, calls = client([root(connection([comment(replies=replies)]))])
    rows = p.snapshot()
    assert [r['id'] for r in rows] == ['D_root', 'DC_one', 'DC_reply']
    assert rows[0]['root'] is True and rows[-1]['parentId'] == 'DC_one'
    assert 'parentId' not in rows[1]
    assert 'private-token' not in json.dumps(rows)
    assert p.provider == 'github' and p.kind == 'discussion' and p.scope['ref'] == 'a' * 40
    assert p.web_url == URL and p.board_url == 'https://github.com/example/board/projects'
    assert calls[0]['url'] == 'https://api.github.com/graphql' and calls[0]['method'] == 'POST'
    assert calls[0]['headers']['Authorization'] == 'Bearer private-token'
    assert calls[0]['variables'] == dict(owner='example', name='board', number=7, after=None)
    assert 'discussion(number:' in calls[0]['query'] and 'replies(first:' in calls[0]['query']


def test_paginates_top_level_and_reply_connections_completely():
    first = comment(replies=connection([comment('DC_r1', parent='DC_one')], more=True, cursor='r-next', total=2))
    second = comment('DC_two', replies=connection())
    p, calls = client([
        root(connection([first], more=True, cursor='c-next', total=2)),
        dict(node=dict(id='DC_one', discussion=dict(id='D_root'), replies=connection([comment('DC_r2', parent='DC_one')], total=2))),
        root(connection([second], total=2)),
    ])
    assert [r['id'] for r in p.snapshot()] == ['D_root', 'DC_one', 'DC_r1', 'DC_r2', 'DC_two']
    assert calls[1]['variables'] == dict(id='DC_one', after='r-next')
    assert calls[2]['variables']['after'] == 'c-next'


@pytest.mark.parametrize('target,parent', [(None, None), ('D_root', None), ('DC_one', 'DC_one'), ('DC_reply', 'DC_one')])
def test_single_mutation_uses_real_reply_to_id_and_exact_body(target, parent):
    thread = comment(replies=connection([comment('DC_reply', parent='DC_one')]))
    p, calls = client([root(connection([thread])), receipt(body='posted µF', parent=parent)])
    p.snapshot()
    assert p.publish('posted µF', reply_to=target) == 'DC_new'
    writes = [c for c in calls if 'mutation ' in c['query']]
    assert len(writes) == 1
    assert 'addDiscussionComment(input: $input)' in writes[0]['query']
    expected = dict(discussionId='D_root', body='posted µF')
    if parent:
        expected['replyToId'] = parent
    assert writes[0]['variables']['input'] == expected
    with pytest.raises(ValueError, match='Refresh'):
        p.publish('again')
    assert len(calls) == 2


@pytest.mark.parametrize('settings', [dict(provider='gitlab'), dict(host='https://github.example.org'),
    dict(host='https://github.com/path'), dict(host='https://user:token@github.com'), dict(kind='issue'),
    dict(number=True), dict(number=0), dict(number=2147483648), dict(repository='a/../b'), dict(ref='main')])
def test_scope_rejection_happens_before_authentication(settings):
    def forbidden(*_):
        pytest.fail('Invalid scope must not obtain credentials or make a request')
    with pytest.raises(ValueError):
        DiscussionProvider(dict(BASE, **settings), transport=forbidden, tokens=forbidden)


@pytest.mark.parametrize('response', [
    dict(data=root(), errors=[dict(message='private-token')]), dict(errors=[dict(message='denied')]),
    dict(data=root(), errors='malformed'), dict(data=None), dict(data=root(), errors=None),
])
def test_graphql_errors_and_partial_data_never_become_snapshots(response):
    p, _ = client([(200, {}, response)])
    with pytest.raises(RuntimeError) as error:
        p.snapshot()
    assert 'private-token' not in str(error.value)
    with pytest.raises(ValueError, match='Refresh'):
        p.publish('blocked')


@pytest.mark.parametrize('change', ['disabled', 'missing_repo', 'missing_discussion', 'foreign_repository', 'foreign_url', 'foreign_number'])
def test_missing_disabled_or_foreign_conversations_fail_honestly(change):
    data = root()
    repo = data['repository']
    if change == 'disabled':
        repo['hasDiscussionsEnabled'] = False
    elif change == 'missing_repo':
        data['repository'] = None
    elif change == 'missing_discussion':
        repo['discussion'] = None
    elif change == 'foreign_repository':
        repo['nameWithOwner'] = 'other/repo'
    elif change == 'foreign_url':
        repo['discussion']['url'] = 'https://github.com/other/repo/discussions/7'
    else:
        repo['discussion']['number'] = 8
    p, _ = client([data])
    with pytest.raises(ValueError):
        p.snapshot()


@pytest.mark.parametrize('bad_page', [connection(more=True, cursor='x'), connection(total=1), connection(total=5001),
    dict(nodes=[None], totalCount=1, pageInfo=dict(hasNextPage=False)), dict(nodes=[], totalCount=0, pageInfo={})])
def test_incomplete_or_oversized_collections_are_rejected(bad_page):
    p, _ = client([root(bad_page)])
    with pytest.raises(ValueError):
        p.snapshot()


def test_repeated_cursor_duplicate_identity_and_changed_totals_fail():
    page = root(connection([comment(replies=connection())], more=True, cursor='same', total=2))
    for final in [deepcopy(page), root(connection([comment(replies=connection())], total=2)),
                  root(connection([comment('DC_two', replies=connection())], total=3))]:
        p, _ = client([page, final])
        with pytest.raises(ValueError):
            p.snapshot()


def test_failed_refresh_revokes_previous_publication_identities():
    p, calls = client([root(), RuntimeError('private-token')])
    p.snapshot()
    with pytest.raises(RuntimeError) as error:
        p.snapshot()
    assert 'private-token' not in str(error.value)
    with pytest.raises(ValueError, match='Refresh'):
        p.publish('blocked')
    assert len(calls) == 2


@pytest.mark.parametrize('response', [TimeoutError('private-token'), receipt(body='different'),
    receipt(parent='DC_elsewhere'), receipt(discussion=dict(id='D_elsewhere')), receipt(id=None),
    (200, {}, dict(data=receipt(), errors=[dict(message='failure')])), dict(addDiscussionComment=None)])
def test_ambiguous_or_wrong_receipt_never_retries(response):
    p, calls = client([root(), response])
    p.snapshot()
    with pytest.raises(RuntimeError, match='not confirmed') as error:
        p.publish('posted')
    assert 'private-token' not in str(error.value)
    assert len(calls) == 2
    with pytest.raises(ValueError, match='Refresh'):
        p.publish('posted')
    assert len(calls) == 2


def test_unknown_reply_and_invalid_body_never_mutate():
    p, calls = client([root()])
    p.snapshot()
    with pytest.raises(ValueError, match='not in this'):
        p.publish('posted', reply_to='DC_foreign')
    for body in ['', '  ', 'µ' * 32001, None]:
        with pytest.raises(ValueError):
            p.publish(body)
    assert len(calls) == 1


def test_reply_page_cannot_cross_discussions_or_hide_incomplete_results():
    first = comment(replies=connection([comment('DC_r1', parent='DC_one')], more=True, cursor='next', total=2))
    for reply_page in [dict(node=None), dict(node=dict(id='DC_one', discussion=dict(id='D_other'), replies=connection())),
                       dict(node=dict(id='DC_one', discussion=dict(id='D_root'), replies=connection(total=2)))]:
        p, _ = client([root(connection([first])), reply_page])
        with pytest.raises(ValueError):
            p.snapshot()


def test_snapshot_request_and_total_body_budgets():
    initial = root(connection([comment(replies=connection())], more=True, cursor='next', total=2))
    p, calls = client([initial])
    with patch('review_comments_plugin.discussions.MAX_REQUESTS', 1), pytest.raises(ValueError, match='too many pages'):
        p.snapshot()
    assert len(calls) == 1
    p, _ = client([root(body='x' * 1000)])
    with patch('review_comments_plugin.discussions.MAX_BODY', 512), pytest.raises(ValueError, match='snapshot limit'):
        p.snapshot()


def test_deleted_author_remains_readable_but_wrong_reply_relationship_fails():
    deleted = comment(replies=connection())
    deleted['author'] = None
    p, _ = client([root(connection([deleted]))])
    assert p.snapshot()[-1]['author'] == 'unknown'
    wrong = comment(replies=connection([comment('DC_reply', parent='DC_elsewhere')]))
    p, _ = client([root(connection([wrong]))])
    with pytest.raises(ValueError, match='another thread'):
        p.snapshot()


def test_canonical_repository_case_does_not_break_scope():
    data = root(connection([comment(replies=connection())]))
    data['repository']['nameWithOwner'] = 'Example/Board'
    data['repository']['discussion']['url'] = URL.replace('example/board', 'Example/Board')
    data['repository']['discussion']['comments']['nodes'][0]['url'] = URL.replace('example/board', 'Example/Board') + '#discussioncomment-23'
    p, _ = client([data])
    assert len(p.snapshot()) == 2


@pytest.mark.parametrize('url', ['https://github.com/other/board/discussions/7#discussioncomment-1',
    URL + '#issuecomment-1', URL + '?token=private-token#discussioncomment-1',
    'https://github.com.evil.invalid/example/board/discussions/7#discussioncomment-1'])
def test_comment_links_never_escape_selected_discussion(url):
    row = comment(replies=connection())
    row['url'] = url
    p, _ = client([root(connection([row]))])
    with pytest.raises(ValueError):
        p.snapshot()


def test_non_success_http_response_and_credential_failures_are_sanitized():
    p, _ = client([(403, {}, dict(data=root()))])
    with pytest.raises(RuntimeError):
        p.snapshot()
    def fail(*_):
        raise RuntimeError('private-token')
    p.tokens = fail
    with pytest.raises(RuntimeError) as error:
        p.snapshot()
    assert 'private-token' not in str(error.value)
