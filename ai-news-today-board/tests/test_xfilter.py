import pytest
from newsboard.xfilter import keep_post
from ai_news_board import build_board


@pytest.mark.parametrize('word', ['SHIT', 'porn', 'NsFw', 'fuck', 'xxx'])
def test_blocked_words(word):
    assert not keep_post({'text': 'AI '+word+' https://example.test', 'like_count': 90})


def test_whole_words():
    assert keep_post({'text': 'AI in Scunthorpe, an xxxlarge model', 'like_count': 10})


@pytest.mark.parametrize('field,value', [('is_reply', True), ('in_reply_to_status_id', '123'),
                                        ('in_reply_to_status_id_str', '123'), ('in_reply_to_user_id', '42'),
                                        ('reply_to', '42')])
def test_replies(field, value):
    assert not keep_post({'text': 'AI news', 'like_count': 100, field: value})


def test_engagement_and_links(monkeypatch):
    assert not keep_post({'text': 'AI news', 'url': 'https://x.com/i/status/1', 'like_count': 4})
    assert keep_post({'text': 'AI news', 'like_count': 3, 'retweet_count': 1, 'reply_count': 1})
    assert keep_post({'text': 'AI https://example.test'})
    assert keep_post({'text': 'AI', 'entities': {'urls': [{'expanded_url': 'https://example.test'}]}})
    monkeypatch.setenv('DEMO_X_MIN_ENGAGEMENT', '10')
    assert not keep_post({'text': 'AI', 'like_count': 9})
    assert keep_post({'text': 'AI', 'like_count': 2}, min_engagement=2)
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert keep_post({'text': 'NSFW', 'is_reply': True})


def test_filter_before_board(monkeypatch):
    raw = {'calls': [{'source': 'x', 'tag': 'AI', 'status': 200, 'body': [
        {'id': '1', 'text': 'NSFW AI', 'like_count': 100},
        {'id': '2', 'text': 'AI release', 'like_count': 50}]}]}
    result = build_board(raw, '2026-10-21T00:00:00+00:00')
    assert [p['url'] for p in result['x_posts']] == ['https://x.com/i/status/2']
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert len(build_board(raw, '2026-10-21T00:00:00+00:00')['x_posts']) == 2
