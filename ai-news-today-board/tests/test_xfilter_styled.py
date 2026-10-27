import pytest

from newsboard.xfilter import keep_post


STYLED_POSTS = [
    'AI model 𝐛𝐨𝐥𝐝 release',
    'AI model 𝑖𝑡𝑎𝑙𝑖𝑐 release',
    'AI model 𝟏𝟐𝟑 release',
    'AI model ＡＩ release',
    'AI model ａｉ release',
    'AI model １２３ release',
    'AI model &amp;#x1D400; release',
]
EMPTY_LIST_POSTS = [
    f'AI model release\n{marker} {content}\n- faster inference'
    for marker in ('-', '*', '•', '·', '1.', '2)')
    for content in ('', '@someone', '@OpenAI', '@OpenAI @github', '… 🚀')
]


@pytest.mark.parametrize('text', STYLED_POSTS)
def test_styled_unicode_dropped(text):
    assert not keep_post({'text': text, 'lang': 'en', 'like_count': 100})


@pytest.mark.parametrize('text', [
    'AI model release 🚀 with café results, “better” inference…',
    'AI model release\n- faster inference\n* open weights\n• useful tools\n· better results\n1. new benchmarks\n2) efficient training',
    'AI model release\n- @OpenAI releases weights\n2) @github hosts code',
    'AI model release\n- 123\n\ncontact ai@example.test',
])
def test_normal_posts_kept(text):
    assert keep_post({'text': text, 'like_count': 100})


@pytest.mark.parametrize('text', EMPTY_LIST_POSTS)
def test_empty_list_items_dropped(text):
    assert not keep_post({'text': text, 'like_count': 100})


@pytest.mark.parametrize('text', STYLED_POSTS + EMPTY_LIST_POSTS)
def test_filter_off_keeps_posts(monkeypatch, text):
    monkeypatch.setenv('DEMO_X_FILTER', '0')
    assert keep_post({'text': text})
