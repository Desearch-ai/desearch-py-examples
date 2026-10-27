import pytest
import igcore as c


@pytest.mark.parametrize('fn,value,expected', [
    (c.validate_username, '@example_brand', 'example_brand'),
    (c.validate_tag, '#examplecoffee', 'examplecoffee'),
    (c.validate_tag, '#ყავა', 'ყავა'),
    (c.validate_shortcode, 'AbC123xyz_-', 'AbC123xyz_-'),
    *[(c.validate_shortcode, f'https://www.instagram.com/{kind}/AbC123xyz_-/?x=1', 'AbC123xyz_-') for kind in ('p', 'reel', 'tv')],
    (c.validate_count, '100', 100),
    (c.validate_query, ' example  coffee\n shop ', 'example coffee shop'),
])
def test_valid(fn, value, expected):
    assert fn(value) == expected


@pytest.mark.parametrize('fn,value', [
    (c.validate_username, ''), (c.validate_username, 'x' * 31),
    (c.validate_username, 'bad name'), (c.validate_tag, 'bad-tag'),
    (c.validate_tag, 'x' * 101), (c.validate_shortcode, 'bad/code'),
    (c.validate_shortcode, 'https://evil.example/p/code/'),
    (c.validate_count, 0), (c.validate_count, 101),
    (c.validate_count, 'abc'), (c.validate_query, '   '),
    (c.validate_query, 'x' * 201),
])
def test_invalid(fn, value):
    with pytest.raises(c.InputError):
        fn(value)


@pytest.mark.parametrize('value', [1704067200, 1704067200000, '1704067200', '2024-01-01T00:00:00Z', '2024-01-01T04:00:00+04:00'])
def test_dates(value):
    assert c.to_iso(value) == '2024-01-01T00:00:00Z'


@pytest.mark.parametrize('value', [None, '', 'garbage', float('inf')])
def test_bad_dates(value):
    assert c.to_iso(value) is None


def test_normalizers():
    media = c.normalize_media({'shortcode': 'AbC123xyz_-', 'stats': None, 'author': None, 'caption': 'x ' * 200})
    assert media['url'] == 'https://www.instagram.com/p/AbC123xyz_-/'
    assert len(media['caption']) == 283
    assert media['likes'] is None and media['author'] is None
    assert c.normalize_media({})['created_raw'] is None
    assert c.normalize_profile({})['followers'] is None
    assert c.normalize_profile({'biography': ' a\n b '})['biography'] == 'a b'
    comment = c.normalize_comment({'author': {'username': 'example_brand'}, 'replies': [{}, {}]})
    assert comment['replies'] == 2 and 'author' not in comment
    assert c.normalize_comment({})['replies'] == 0
    assert c.normalize_search({}) == dict.fromkeys(['type', 'username', 'title', 'url', 'followers'])


@pytest.mark.parametrize('body', [[{}, 1], {'data': [{}]}, {'items': [{}]}, {'results': [{}]}])
def test_items(body):
    assert c.items_of(body) == [{}]


def test_empty_and_billing():
    assert c.items_of(None) == []
    assert c.items_of({'data': None}) == []
    assert c.billing({}) == dict(cost_usd=0.0, usage_count=None, service=None, currency=None, next_cursor=None)
    assert c.billing({'X-DESEARCH-COST-USD': '.02', 'X-Desearch-Usage-Count': '2', 'X-Desearch-Next-Cursor': 'opaque+ /', 'X-Desearch-Service': 'instagram', 'X-Desearch-Currency': 'USD'}) == dict(cost_usd=.02, usage_count=2, service='instagram', currency='USD', next_cursor='opaque+ /')


def test_profile_live_fields():
    profile = c.normalize_profile(dict(id='1', username='natgeo', fullName='National Geographic', biography='Explore', avatar='avatar.jpg', verified=True, private=False, followers=268283644, following=195, postsCount=32115, externalUrl='https://example.com'))
    assert list(profile) == ['username', 'full_name', 'followers', 'following', 'posts', 'verified', 'private', 'external_url', 'biography']
    assert profile['followers'] == 268283644
    assert profile['following'] == 195
    assert profile['posts'] == 32115
    assert profile['verified'] is True
    assert profile['private'] is False


@pytest.mark.parametrize('primary,fallback,value,old', [
    ('followers', 'followersCount', 0, 12),
    ('following', 'followingCount', 0, 34),
    ('verified', 'isVerified', False, True),
    ('private', 'isPrivate', False, True),
])
def test_profile_fallback(primary, fallback, value, old):
    assert c.normalize_profile({fallback: old})[primary] == old
    assert c.normalize_profile({primary: None, fallback: old})[primary] == old
    result = c.normalize_profile({primary: value, fallback: old})[primary]
    assert result == value and type(result) is type(value)


@pytest.mark.parametrize('fields,expected', [
    ({'likes': 7}, 7), ({'likes': 0}, 0),
    ({'likeCount': 9}, 9), ({'likes': None, 'likeCount': 9}, 9),
    ({'likes': 0, 'likeCount': 9}, 0), ({'likes': 7, 'likeCount': 9}, 7),
])
def test_comment_likes(fields, expected):
    assert c.normalize_comment(fields)['likes'] == expected
