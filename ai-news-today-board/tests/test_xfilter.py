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


@pytest.mark.parametrize('text', [
    'THIS IS AN ACTUAL F*CKING GOLDMINE',
    'THIS IS AN ABSOLUTE F*CKING CHEATCODE',
    'f**k', 'sh!t', 'f u c k', 'f.u.c.k', 'fuuuck', 'p0rn', 'n5fw',
])
def test_masked_profanity(text):
    assert not keep_post({'text': text, 'like_count': 100})


@pytest.mark.parametrize('text', [
    'AI policy cannot save our democracy. The future is in your hands. On November 3, make it count.',
    'AI crypto morning brief: bitcoin and ETH markets rally.',
    'AI photonics stock list: NVDA AMD INTC AVGO stocks to watch.',
    'AI token promo: get in before i ape',
    'AI law changes everything. Buy $MOON today.',
    'AI models are stocks to watch, buy now',
    'A beautiful sunny morning in the garden.',
])
def test_regulation_rejects_noise(text):
    assert not keep_post({'text': text, 'like_count': 100}, tag='ai regulation', query='AI regulation')


def test_topic_and_disable(monkeypatch):
    assert keep_post({'text': 'New compliance policy governs neural model deployment', 'like_count': 20}, tag='ai regulation')
    assert keep_post({'text': 'Bitcoin crypto morning brief', 'like_count': 20}, tag='crypto')
    assert keep_post({'text': 'A shiitake harvest in Scunthorpe with an xxxlarge basket', 'like_count': 20})
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert keep_post({'text': 'NSFW crypto vote', 'is_reply': True}, tag='ai regulation')


def test_eagle_dedupe_and_truncate():
    base = 'EAGLE-4 is a new AI model release with open weights and faster inference for developers building applications. '
    posts = [{'id': str(i), 'text': base + ending, 'like_count': likes}
             for i, (ending, likes) in enumerate([
                 ('Read the report.', 20), ('Read our report today.', 100),
                 ('Read the full report.', 40), ('Read this report now.', 60)])]
    posts.append({'id': 'long', 'text': 'AI regulation policy ' + 'detailed discussion ' * 30 + 'https://example.test/report', 'like_count': 10})
    raw = {'calls': [{'source': 'x', 'tag': 'model release', 'body': posts}]}
    result = build_board(raw, '2026-10-21T00:00:00+00:00')['x_posts']
    assert len(result) == 2
    assert result[0]['url'].endswith('/1')
    assert result[0]['engagement'] == 100
    assert result[1]['title_or_text'].endswith('… https://example.test/report')
    assert len(result[1]['title_or_text']) <= 310


def test_truncation_link_positions():
    from newsboard.xfilter import truncate_text
    link = 'https://example.test/report'
    assert truncate_text('AI ' + link) == 'AI ' + link
    assert truncate_text('AI ' + link + ' text' * 100).count(link) == 1
    assert truncate_text('a' * 270 + ' ' + link).endswith('… ' + link)


def test_disabled_filter_restores_board_posts(monkeypatch):
    from ai_news_board import collect_rows
    raw = {'calls': [{'source': 'x', 'tag': 'ai regulation', 'body': [
        {'id': 'noise', 'text': 'NSFW token promo before i ape, vote now', 'like_count': 100, 'is_reply': True},
        {'id': 'quiet', 'text': 'A quiet garden', 'like_count': 1},
    ]}]}
    assert not build_board(raw, '2026-10-21T00:00:00+00:00')['x_posts']
    assert len(collect_rows(raw)[0]) == 2
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert len(build_board(raw, '2026-10-21T00:00:00+00:00')['x_posts']) == 2
