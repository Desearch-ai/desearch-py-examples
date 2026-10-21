import pytest

from newsboard.xfilter import LINK, keep_post, prepare_posts, truncate_text


def test_many_links_keep_readable_text():
    links = [f'https://t.co/link{i:06d}' for i in range(12)]
    text = 'New AI research with detailed results. ' * 10 + ' '.join(links)
    assert len(text) > 300
    result = truncate_text(text)
    assert result.startswith('New AI research')
    assert result.endswith('… ' + links[0])
    assert LINK.findall(result) == links[:1]
    assert len(result) <= 280


@pytest.mark.parametrize('disabled', ['0', '1'])
def test_link_only_posts_dropped(monkeypatch, disabled):
    monkeypatch.setenv('DEMO_X_FILTER', disabled)
    text = ' '.join(f'https://t.co/link{i:06d}' for i in range(20))
    assert truncate_text(text) == ''
    assert prepare_posts([{'title_or_text': text}]) == []
    if disabled == '0':
        assert keep_post({'text': text})


@pytest.mark.parametrize('text', ['', '123 !!! https://t.co/example', '🔥 🚀'])
def test_display_without_letters_dropped(text):
    assert prepare_posts([{'title_or_text': text}]) == []


def test_short_post_unchanged():
    text = 'New AI research results https://t.co/example'
    assert truncate_text(text) == text
    assert prepare_posts([{'title_or_text': text}]) == [{'title_or_text': text}]


def test_long_post_with_one_link():
    link = 'https://t.co/example'
    result = truncate_text('Detailed AI research results. ' * 20 + link)
    assert result.startswith('Detailed AI research results.')
    assert result.endswith('… ' + link)
    assert len(result) <= 280


def test_oversized_link_leaves_room_for_text():
    result = truncate_text('Readable research details ' + 'https://example.test/' + 'a' * 300)
    assert result.startswith('Readable research details')
    assert result.endswith('…')
    assert not LINK.findall(result)
    assert len(result) <= 280
