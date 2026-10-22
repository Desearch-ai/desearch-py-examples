import pytest

from newsboard.xfilter import keep_post


@pytest.mark.parametrize('text', [
    '', '   ', 'https://example.test',
    'http://example.test https://other.test t.co/abc www.example.test',
    '🔥 🚀 https://example.test !!!', 't.co/abc', 'www.example.test',
])
@pytest.mark.parametrize('lang', [None, 'en'])
def test_empty_and_link_only_dropped(text, lang):
    post = {'text': text, 'like_count': 100}
    if lang is not None:
        post['lang'] = lang
    assert not keep_post(post)


@pytest.mark.parametrize('text', [
    '最近 infra 的好消息还挺多， Google 和 Meta 合作推出了 TorchTPU 项目',
    '新しい人工知能モデルが公開されました https://example.test',
    'Новая модель искусственного интеллекта https://example.test',
    '@longenglishhandle #longenglishhashtag AI 123 🚀',
    'AI news',
])
def test_language_heuristic_drops(text):
    assert not keep_post({'text': text, 'like_count': 100})


@pytest.mark.parametrize('fields,expected', [
    ({'text': 'New model release https://example.test'}, True),
    ({'text': 'New model release', 'lang': 'zh'}, False),
    ({'text': 'AI', 'lang': 'en'}, True),
    ({'text': 'New model release', 'lang': 'und'}, True),
    ({'text': 'New model release from José and Zoë'}, True),
    ({'text': 'New model release www.example.test'}, True),
    ({'text': 'New model release t.co/abc'}, True),
    ({'text': 'abcdefgh'}, True),
    ({'text': 'abcdefg'}, False),
    ({'text': 'abcdefghijklmnopqéöü'}, True),
    ({'text': 'abcdefghijklmnopéöüß'}, False),
])
def test_language_filter(fields, expected):
    assert keep_post({'like_count': 100, **fields}) is expected


@pytest.mark.parametrize('post', [
    {}, {'text': 'https://example.test 🚀'},
    {'text': '中文', 'lang': 'zh'},
    {'text': 'NSFW', 'is_reply': True, 'lang': 'und'},
])
def test_disabled_filter_keeps_all(monkeypatch, post):
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert keep_post(post)
