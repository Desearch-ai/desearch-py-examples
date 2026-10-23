"""Fully offline tests. No credentials or filesystem credential lookup."""
import datetime as dt
import importlib.util
import pathlib
import pytest

# Use a unique module name so neighboring examples' core modules cannot collide.
spec = importlib.util.spec_from_file_location('giveaway_core', pathlib.Path(__file__).with_name('core.py'))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
NOW = dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc)
POST = {'id': '9000', 'user': {'id': '0', 'username': 'demo_brand'}, 'retweet_count': 100, 'reply_count': 90}


def user(uid, **extra):
    return dict(id=str(uid), username=f'entrant_{uid:02}', followers_count=100,
                created_at='Wed Oct 10 20:19:24 +0000 2018', **extra)


class Fake:
    def __init__(self, pages=None, replies=None, posts=None):
        self.pages = list(pages or [{'users': [user(1)], 'next_cursor': None}])
        self.replies = replies or []
        self.posts = [POST] if posts is None else posts
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if path == '/twitter/urls':
            body = self.posts
        elif path == '/twitter/post/retweeters':
            body = self.pages.pop(0)
            if isinstance(body, Exception):
                raise body
        else:
            body = self.replies
        return 200, body, {'X-Desearch-Cost-Usd': '0.001'}


def pick(fake=None, **rules):
    return core.pick(fake or Fake(), '9000', now=NOW, **rules)


@pytest.mark.parametrize('raw', ['https://x.com/demo_brand/status/123', 'http://www.twitter.com/demo_brand/status/123/?s=1', '123'])
def test_valid_url(raw):
    assert '/status/123' in core.clean_post(raw)
    if raw == '123':
        assert core.clean_post(raw) == 'https://x.com/i/status/123'


@pytest.mark.parametrize('raw', ['https://other.com/demo_brand/status/123', 'https://x.com/demo_brand', 'https://x.com/demo_brand/status/abc', 'abc', 'https://x.com.evil/demo/status/1', 'https://x.com/demo/status/1/extra'])
def test_invalid_url(raw):
    fake = Fake()
    with pytest.raises(ValueError):
        core.pick(fake, raw)
    assert fake.calls == []


def test_not_found():
    fake = Fake(posts=[])
    result = pick(fake, must_reply=True)
    assert result['error'] == 'post not found or not public'
    assert [path for path, _ in fake.calls] == ['/twitter/urls']


def test_page_cap():
    fake = Fake(pages=[{'users': [user(1)], 'next_cursor': str(i)} for i in range(25)])
    result = pick(fake)
    assert len(fake.calls) == 26
    assert len([p for p, _ in fake.calls if p.endswith('retweeters')]) == 25
    assert 'first 500 reposters only' in result['notices']
    assert len(result['entrants']) == 1


def test_null_cursor():
    fake = Fake()
    pick(fake)
    assert len(fake.calls) == 2
    assert fake.calls[0] == ('/twitter/urls', {'urls': 'https://x.com/i/status/9000'})


def test_repeat_and_dedupe():
    fake = Fake(pages=[{'users': [user(1)], 'next_cursor': 'a'}, {'users': [user(1), user(2)], 'next_cursor': 'a'}])
    result = pick(fake)
    assert len(fake.calls) == 3 and len(result['entrants']) == 2
    assert fake.calls[-1][1]['cursor'] == 'a'
    assert 'repeated cursor' in result['notices'][0]


def test_retry_then_partial():
    fake = Fake(pages=[{'users': [user(1)], 'next_cursor': 'a'}, OSError(), OSError()])
    result = pick(fake)
    assert len(fake.calls) == 4 and len(result['entrants']) == 1
    assert 'collection stopped early' in result['notices'][0]
    assert fake.calls[-1] == fake.calls[-2]


def test_retry_recovers():
    fake = Fake(pages=[OSError(), {'users': [user(1)], 'next_cursor': None}])
    assert len(pick(fake)['winners']) == 1
    assert len(fake.calls) == 3


def test_reply_notice_and_author_tags():
    replies = [{'user': POST['user'], 'text': '@entrant_01 @entrant_02'},
               {'user': user(1), 'text': '@demo_brand @entrant_02 @ENTRANT_02'},
               {'user': user(2), 'text': '@entrant_01 @entrant_03'}]
    fake = Fake(replies=replies)
    result = pick(fake, must_repost=False, must_reply=True, min_tags=2)
    assert 'from the latest ~3 replies the API returned (post shows 90 replies)' in result['notices']
    assert [r['user_id'] for r in result['winners']] == ['2']
    assert result['entrants'][0]['reason'] == 'post author'
    assert result['entrants'][1]['tags'] == 1
    assert len(fake.calls) == 2 and fake.calls[-1][1] == {'post_id': '9000', 'count': 50}


def test_tags_not_combined():
    fake = Fake(replies=[{'user': user(1), 'text': '@entrant_02'}, {'user': user(1), 'text': '@entrant_03'}])
    assert not pick(fake, must_reply=True, min_tags=2)['winners']


def test_age_followers_and_author():
    young = user(2); young['created_at'] = '2026-10-22T00:00:00Z'
    low = user(3); low['followers_count'] = 1
    unknown = user(4); unknown['created_at'] = 'unknown'
    fake = Fake(pages=[{'users': [POST['user'], user(1), young, low, unknown], 'next_cursor': None}])
    result = pick(fake, min_account_age_days=30, min_followers=10)
    assert [r['user_id'] for r in result['winners']] == ['1']
    assert core.parse_time('2018-10-10T20:19:24Z') == core.parse_time(user(1)['created_at'])


def test_intersection():
    fake = Fake(pages=[{'users': [user(1), user(2)], 'next_cursor': None}],
                replies=[{'user': user(2), 'text': ''}, {'user': user(3), 'text': ''}])
    result = pick(fake, must_reply=True)
    assert [r['user_id'] for r in result['winners']] == ['2']
    assert len(result['entrants']) == 3


def test_seeded_draw():
    rows = [{'user_id': str(i)} for i in range(20)]
    assert core.draw(rows, 3, 'same') == core.draw(list(reversed(rows)), 3, 'same')
    assert any(core.draw(rows, 3, str(i)) != core.draw(rows, 3, 'same') for i in range(10))
    assert pick()['seed'] == '9000:2026-10-23T00:00:00Z'
    assert len(core.draw(rows[:1], 10, 'seed')) == 1


@pytest.mark.parametrize('rules', [{'winners': 0}, {'winners': 11}, {'winners': 1.5}, {'min_tags': 6}, {'min_tags': -1}, {'min_followers': -1}, {'min_account_age_days': -1}, {'must_repost': False}, {'count': 0}, {'count': 101}])
def test_validation_before_calls(rules):
    fake = Fake()
    with pytest.raises(ValueError):
        pick(fake, **rules)
    assert fake.calls == []


def test_coverage_csv_and_cost():
    result = pick()
    assert result['coverage'] == 'Picked from 1 reposts and 0 replies the API returned (post shows 100 reposts, 90 replies).'
    assert result['returned_reposters'] == 1 and result['reported_reposts'] == 100
    assert result['cost_usd'] == pytest.approx(0.002)
    assert core.to_csv(result['entrants']).splitlines()[0] == 'user_id,username,followers,account_created_at,reposted,replied,tags,eligible,reason'
