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
    fake = Fake(pages=[{'users': [user(i + 1)], 'next_cursor': str(i)} for i in range(25)],
                posts=[dict(POST, retweet_count=25)])
    result = pick(fake)
    assert len(fake.calls) == 26
    assert len([p for p, _ in fake.calls if p.endswith('retweeters')]) == 25
    assert 'first 25 pages of reposters only (25 collected; more remain)' in result['notices']
    assert len(result['entrants']) == 25


@pytest.mark.parametrize('sizes', [[2, 1], [20] * 9 + [18, 18]])
def test_replayed_pages_stop_with_fresh_cursors(sizes):
    unique_pages = []
    next_id = 1
    for size in sizes:
        unique_pages.append([user(uid) for uid in range(next_id, next_id + size)])
        next_id += size
    replay = unique_pages + unique_pages + [[], [], []]
    pages = [{'users': users, 'next_cursor': str(i)} for i, users in enumerate(replay)]
    fake = Fake(pages=pages, posts=[dict(POST, retweet_count=next_id - 1)])
    result = core.collect(fake, core.validate('9000'), now=NOW)
    retweeter_calls = [params for path, params in fake.calls if path.endswith('retweeters')]
    assert len(retweeter_calls) == len(sizes) + 1
    assert len(result['reposters']) == next_id - 1
    assert not any('more remain' in notice for notice in result['notices'])
    assert result['cost_usd'] == pytest.approx((len(sizes) + 2) * 0.001)


@pytest.mark.parametrize('stop_users', [[], [user(1)]])
@pytest.mark.parametrize('reported', [0, 1, 2])
def test_empty_or_no_new_ids_stops_and_reports_shortfall(stop_users, reported):
    fake = Fake(pages=[{'users': [user(1)], 'next_cursor': 'a'},
                       {'users': stop_users, 'next_cursor': 'b'},
                       {'users': [user(2)], 'next_cursor': 'c'}],
                posts=[dict(POST, retweet_count=reported)])
    result = core.collect(fake, core.validate('9000'), now=NOW)
    assert len(fake.calls) == 3
    assert set(result['reposters']) == {'1'}
    assert 'first 25 pages of reposters only (1 collected; more remain)' not in result['notices']
    assert ('1 of 2 reposters collected; more may remain' in result['notices']) == (reported > 1)
    assert ('1 of 2 reported reposts returned; deleted, protected or uncollected accounts do not appear' in result['notices']) == (reported > 1)


def test_null_cursor():
    fake = Fake()
    pick(fake)
    assert len(fake.calls) == 2
    assert fake.calls[0] == ('/twitter/urls', {'urls': 'https://x.com/i/status/9000'})


@pytest.mark.parametrize('page_count', [1, 25])
def test_reposter_coverage_notices_are_mutually_exclusive(page_count):
    fake = Fake(pages=[{'users': [user(i + 1)], 'next_cursor': str(i)}
                       for i in range(page_count - 1)] +
                      [{'users': [user(page_count)], 'next_cursor': None}])
    result = core.collect(fake, core.validate('9000'), now=NOW)
    cap_notice = f'first 25 pages of reposters only ({page_count} collected; more remain)'
    shortfall_notice = f'{page_count} of 100 reposters collected; more may remain'
    assert (cap_notice in result['notices']) == (page_count == 25)
    assert (shortfall_notice in result['notices']) == (page_count < 25)
    assert f'{page_count} of 100 reported reposts returned; deleted, protected or uncollected accounts do not appear' in result['notices']


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


class Clock:
    def __init__(self):
        self.value = NOW.timestamp()

    def __call__(self):
        return self.value


def test_rate_windows_and_independent_ips():
    clock = Clock()
    limiter = core.RateLimiter(clock)
    assert limiter.allow('a') == (True, 0)
    assert limiter.allow('a') == (True, 0)
    assert limiter.allow('a') == (False, 600)
    assert limiter.allow('b') == (True, 0)
    clock.value += 599
    assert limiter.allow('a') == (False, 1)
    clock.value += 1
    assert limiter.allow('a') == (True, 0)
    assert len(limiter.runs['a']) == 3
    clock.value += 600
    assert limiter.allow('a')[0]
    clock.value += 600
    assert limiter.allow('a')[0]
    assert limiter.allow('a') == (False, 84600)
    clock.value = NOW.timestamp() + 86400
    assert limiter.allow('a') == (True, 0)
    assert 'b' not in limiter.runs


def cached_run(cache, fake, clock, post='9000', stamp='2026-10-23T00:00:00Z', **rules):
    options = core.validate(post, **rules)
    key = cache.key(options)
    collection = cache.get(key)
    hit = collection is not None
    now = dt.datetime.fromtimestamp(clock(), dt.timezone.utc)
    if not hit:
        collection = core.collect(fake, options, now=now)
        cache.put(key, collection)
    return core.decide(collection, options, now=now, draw_timestamp=stamp, cached=hit)


def test_cache_expiry_and_redraw_rules():
    clock = Clock()
    cache = core.CollectionCache(clock=clock)
    fake = Fake(pages=[{'users': [user(1), user(2)], 'next_cursor': None}] * 2)
    first = cached_run(cache, fake, clock)
    clock.value += 3599
    again = cached_run(cache, fake, clock)
    assert len(fake.calls) == 2
    assert again['cost_usd'] == 0.0
    assert again['seed'] == first['seed'] and again['winners'] == first['winners']
    assert 'no new API calls' in again['notices'][-1]
    other = cached_run(cache, fake, clock, stamp='2026-10-23T00:00:01Z', min_followers=101)
    assert other['seed'] != first['seed'] and other['winners'] == []
    assert len(fake.calls) == 2
    clock.value += 1
    assert cached_run(cache, fake, clock)['cost_usd'] > 0
    assert len(fake.calls) == 4


def test_cache_keys_errors_eviction_and_copy():
    clock = Clock()
    cache = core.CollectionCache(clock=clock, max_entries=2)
    keys = [cache.key(core.validate(post, **rules)) for post, rules in
            [('9000', {}), ('9001', {}), ('9000', {'must_reply': True}), ('9000', {'count': 20})]]
    assert len(set(keys)) == 4
    collection = core.collect(Fake(), core.validate('9000'), now=NOW)
    cache.put(keys[0], collection)
    copy = cache.get(keys[0]); copy['reposters'].clear()
    assert cache.get(keys[0])['reposters']
    clock.value += 1
    cache.put(keys[1], collection)
    clock.value += 1
    cache.put(keys[2], collection)
    assert cache.get(keys[0]) is None
    assert cache.get(keys[1]) is not None
    fake = Fake(posts=[])
    for _ in range(2):
        assert cached_run(cache, fake, clock, post='1999999999999999999')['error']
    assert len(fake.calls) == 2


def test_three_pages_and_missing_ids():
    fake = Fake(pages=[{'users': [user(1), {'username': 'entrant_missing'}], 'next_cursor': 'a'},
                       {'users': [user(1), user(2)], 'next_cursor': 'b'},
                       {'users': [user(3)], 'next_cursor': None}])
    result = pick(fake)
    assert [params.get('cursor') for path, params in fake.calls[1:]] == [None, 'a', 'b']
    assert [r['user_id'] for r in result['entrants']] == ['1', '2', '3']
    assert '3 of 100 reported reposts returned; deleted, protected or uncollected accounts do not appear' in result['notices']


@pytest.mark.parametrize('cursor', [None, 'remaining'])
def test_exact_page_boundary(cursor):
    pages = [{'users': [user(i + 1)], 'next_cursor': str(i)} for i in range(24)]
    pages.append({'users': [user(25)], 'next_cursor': cursor})
    fake = Fake(pages=pages, posts=[dict(POST, retweet_count=25)])
    result = pick(fake)
    assert len(fake.calls) == 26
    assert 'first 25 pages of reposters only (25 collected; more remain)' in result['notices']


def test_fake_id_guard_and_resolve_http_failure():
    fake = Fake(posts=[])
    result = core.pick(fake, '1999999999999999999', must_reply=True, now=NOW)
    assert [path for path, _ in fake.calls] == ['/twitter/urls']
    assert result['cost_usd'] == pytest.approx(0.001)
    calls = []

    def failure(path, params):
        calls.append(path)
        return 503, {}, {'x-desearch-cost-usd': '0.003'}

    with pytest.raises(RuntimeError, match='503'):
        core.pick(failure, '1999999999999999999')
    assert calls == ['/twitter/urls']


@pytest.mark.parametrize('post,rules', [('9001', {}), ('9000', {'must_reply': True}),
                                      ('9000', {'must_repost': False, 'must_reply': True}),
                                      ('9000', {'count': 20})])
def test_separate_cache_collections(post, rules):
    clock = Clock()
    cache = core.CollectionCache(clock=clock)
    cached_run(cache, Fake(), clock)
    fake = Fake()
    result = cached_run(cache, fake, clock, post=post, **rules)
    assert fake.calls and result['cost_usd'] > 0
    calls = len(fake.calls)
    assert cached_run(cache, fake, clock, post=post, **rules)['cost_usd'] == 0
    assert len(fake.calls) == calls


def test_limiter_concurrent_calls():
    from concurrent.futures import ThreadPoolExecutor
    limiter = core.RateLimiter(Clock())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(limiter.allow, ['same_ip'] * 20))
    assert sum(allowed for allowed, _ in results) == 2
    assert len(limiter.runs['same_ip']) == 2
