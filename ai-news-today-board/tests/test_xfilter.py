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
    assert not keep_post({'text': 'AI model news', 'url': 'https://x.com/i/status/1', 'like_count': 4})
    assert keep_post({'text': 'AI model news', 'like_count': 3, 'retweet_count': 1, 'reply_count': 1})
    assert keep_post({'text': 'AI model news https://example.test'})
    assert keep_post({'text': 'AI model news', 'entities': {'urls': [{'expanded_url': 'https://example.test'}]}})
    monkeypatch.setenv('DEMO_X_MIN_ENGAGEMENT', '10')
    assert not keep_post({'text': 'AI model news', 'like_count': 9})
    assert keep_post({'text': 'AI model news', 'like_count': 2}, min_engagement=2)
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
    'AI token airdrop promo: get in before i ape',
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
    assert len(result[1]['title_or_text']) <= 280


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


@pytest.mark.parametrize('text', ['fck', 'b*tch', '****', '***', 'f*ck', 'F*CKING'])
def test_additional_masked_profanity(text):
    from newsboard.xfilter import has_profanity
    assert has_profanity(text)
    assert not keep_post({'text': 'AI ' + text, 'like_count': 50}, tag='ai')


def test_normal_profanity_guard():
    from newsboard.xfilter import has_profanity
    assert not has_profanity('A normal AI model with tokens and useful results')


@pytest.mark.parametrize('text', [
    'New LLM with 1M tokens context window', 'Claude cuts cost per token',
    'AI eth benchmark results', 'AI ape benchmark results',
])
def test_ambiguous_crypto_words_kept(text):
    assert keep_post({'text': text, 'like_count': 50}, tag='ai')


@pytest.mark.parametrize('context', ['coin', 'crypto', 'blockchain', '$SOL', 'airdrop',
                                     'memecoin', 'wallet', 'defi', 'nft', 'pump'])
@pytest.mark.parametrize('word', ['token', 'tokens', 'ape', 'eth'])
def test_crypto_context_dropped(context, word):
    assert not keep_post({'text': f'AI {word} {context}', 'like_count': 50}, tag='ai')


def test_ape_airdrop_dropped():
    assert not keep_post({'text': 'Ape into this token airdrop now', 'like_count': 50})


@pytest.mark.parametrize('name', ['Donald Trump', 'Gavin Newsom', 'Scott Wiener',
    'Biden', 'Harris', 'Vance', 'Pelosi', 'Schumer', 'McConnell', 'DeSantis',
    'Obama', 'Macron', 'Starmer', 'Sunak', 'Scholz', 'Merz', 'Meloni',
    'von der Leyen', 'Orban', 'Sanchez', 'the Politico bill', 'Andrii',
    'Matt Buechele', 'Jane Smith', '@someone'])
def test_politicians_and_people_dropped(name):
    assert not keep_post({'text': f'AI update from {name}', 'like_count': 50}, tag='ai')


@pytest.mark.parametrize('term', ['election', 'senator', 'governor', 'congress',
    'bill sponsor', 'bill sponsored', 'legislation sponsor', 'campaign', 'vote',
    'partisan', 'GOP', 'Democrats', 'Republicans', 'politics'])
def test_politics_dropped_even_when_requested(term):
    assert not keep_post({'text': f'AI {term} update', 'like_count': 50}, tag=f'ai {term}')


@pytest.mark.parametrize('name', ['OpenAI', 'Google DeepMind', 'Claude', 'Llama 4',
    'Anthropic', 'Meta AI', 'Hugging Face', 'Mistral AI', 'Microsoft', 'Nvidia',
    'GitHub', 'EU AI Act', '@OpenAI'])
def test_organization_allowlist(name):
    assert keep_post({'text': f'{name} releases AI model weights', 'like_count': 50}, tag='ai')


@pytest.mark.parametrize('prefix', [250, 278])
def test_all_urls_preserved_within_hard_limit(prefix):
    from newsboard.xfilter import truncate_text, LINK
    links = ['https://one.test/a', 'https://two.test/report']
    text = links[0] + ' ' + 'x' * (prefix - len(links[0]) - 1) + ' ' + links[1] + ' trailing' * 30
    result = truncate_text(text)
    assert len(result) <= 280
    assert LINK.findall(result) == links


def test_url_starting_at_279_is_not_cut():
    from newsboard.xfilter import truncate_text, LINK
    link = 'https://example.test/report'
    result = truncate_text('x' * 278 + ' ' + link)
    assert len(result) <= 280
    assert LINK.findall(result) == [link]


def test_urls_exhaust_budget():
    from newsboard.xfilter import truncate_text
    first = 'https://example.test/' + 'a' * 140
    second = 'https://example.test/' + 'b' * 140
    assert truncate_text('AI ' + first + ' ' + second) == first


@pytest.mark.parametrize('text', ['x' * 280, 'x' * 281, 'AI details ' * 100])
def test_hard_limit_and_ellipsis(text):
    from newsboard.xfilter import truncate_text
    result = truncate_text(text)
    assert len(result) <= 280
    if len(text) > 280:
        assert result.endswith('…')
    else:
        assert result == text


def test_public_sample_passes_filter(monkeypatch):
    import json
    from pathlib import Path
    from newsboard.xfilter import has_profanity, relevant, politics_or_person
    monkeypatch.setenv('DEMO_X_FILTER', '1')
    board = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())
    assert board['x_posts']
    for post in board['x_posts']:
        text = post['title_or_text']
        assert len(text) <= 280
        assert not has_profanity(text)
        assert relevant(text, tag=post['tag'])
        assert not politics_or_person(text)
        assert keep_post({'text': text, 'like_count': post['likes'],
                          'retweet_count': post['reposts'], 'reply_count': post['replies']}, tag=post['tag'])


@pytest.mark.parametrize('term', [
    'launchpad', 'market maker', 'market makers', 'supply-controlled',
    'presale', 'pre-sale', 'tokenomics', 'mint', 'minting', 'minted',
    'token launch', 'liquidity pool', 'TGE', 'whitelist',
])
def test_strong_crypto_terms_drop_on_their_own(term):
    assert not keep_post({'text': f'AI {term} available soon', 'like_count': 50}, tag='ai')


def test_orbio_launchpad_dropped():
    text = ('You can now launch supply-controlled AI agents paired with ORBIO, funded by the people '
            'who want them and backed by AI market makers from day one. Launching them straight '
            'from the Orbio launchpad, soon.')
    assert not keep_post({'text': text, 'like_count': 50}, tag='ai')


@pytest.mark.parametrize('phrase', ['mint condition', 'mint green', 'token', 'tokens', 'eth'])
def test_non_crypto_uses_kept(phrase):
    assert keep_post({'text': f'AI {phrase} research update', 'like_count': 50}, tag='ai')


@pytest.mark.parametrize('encoded,decoded', [
    ('AI &amp;amp; models &lt;3 &gt;2 &quot;new&quot; &#39;release&#39;',
     'AI & models <3 >2 "new" \'release\''),
    ('AI &#x26;amp; models', 'AI & models'),
])
def test_entities_decoded_for_display(encoded, decoded):
    from ai_news_board import collect_rows
    raw = {'calls': [{'source': 'x', 'tag': 'ai', 'body': [
        {'id': '1', 'text': encoded, 'like_count': 50}]}]}
    assert collect_rows(raw)[0][0]['title_or_text'] == decoded
    assert build_board(raw, '2026-10-21T00:00:00+00:00')['x_posts'][0]['title_or_text'] == decoded


@pytest.mark.parametrize('text', ['AI cr&#121;pto', 'AI sh&#105;t', 'AI &#64;someone'])
def test_entities_decoded_before_filter(text):
    assert not keep_post({'text': text, 'like_count': 50}, tag='ai')


def test_entities_decoded_before_dedupe_and_truncation():
    from newsboard.xfilter import prepare_posts, truncate_text
    posts = [
        {'title_or_text': 'AI &#109;odel &#114;elease', 'engagement': 50},
        {'title_or_text': 'AI model release', 'engagement': 10},
    ]
    assert prepare_posts(posts) == [{'title_or_text': 'AI model release', 'engagement': 50}]
    assert truncate_text('AI ' + '&amp;amp;' * 270) == 'AI ' + '&' * 270
    assert len(truncate_text('AI ' + '&amp;amp;' * 400)) <= 280


def test_public_sample_entities_and_length():
    import json
    from pathlib import Path
    from newsboard.xfilter import LINK
    board = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())
    assert board['x_posts']
    for post in board['x_posts']:
        text = post['title_or_text']
        assert not any(entity in text for entity in ('&amp;', '&lt;', '&gt;', '&quot;', '&#'))
        assert len(text) <= 280 or LINK.fullmatch(text)
