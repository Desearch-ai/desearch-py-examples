import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
import requests
import plagiarism_checker as pc

SENTENCE = 'Garden tools are high-level, general-purpose instruments for careful seasonal planting.'
SECOND = 'Colorful flowers attract numerous helpful insects throughout sunny summer afternoons.'
KEY = 'test-secret-credential-7562'


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.headers = {'X-Desearch-Test': 'fixture', 'Authorization': KEY}
        self.text = json.dumps(body)

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def response():
    return json.loads((Path(__file__).parent / 'fixtures/search.json').read_text())


@pytest.fixture
def runner(tmp_path, monkeypatch, response):
    key = tmp_path / 'access.key'
    key.write_text('  '+KEY+'\n')
    session = FakeSession([FakeResponse(response) for _ in range(10)])
    monkeypatch.setattr(pc.requests, 'Session', lambda: session)
    monkeypatch.setattr(pc.sys, 'stdin', io.StringIO(''))
    def run(extra=(), text=SENTENCE):
        return pc.main(['--engine', 'search', '--text', text, '--key-file', str(key), '--out', str(tmp_path/'out'), '--run-name', 'trial', *extra])
    return run, session, tmp_path


def test_split_title():
    assert pc.split_sentences('Garden notes\nOne sentence here.\nAnother here! What next?') == ['One sentence here.', 'Another here!', 'What next?']


def test_single_line_retained():
    assert pc.split_sentences('Words without punctuation') == ['Words without punctuation']


def test_newlines_collapsed():
    assert pc.split_sentences('Notes\nSome sentence\nwith another line.') == ['Some sentence with another line.']


def test_pick_limit_order():
    sentences = ['Short one.', SECOND, SENTENCE]
    selected = pc.pick_sentences(sentences, 2)
    assert [i for i,s in selected] == [2,3]
    assert len(pc.pick_sentences(sentences, 1)) == 1


def test_min_words():
    assert pc.pick_sentences(['Very short.'], min_words=8) == []
    assert pc.pick_sentences(['Very short.'], min_words=2) == [(1,'Very short.')]


@pytest.mark.parametrize('style,multiplier', [('quoted',1),('plain',1),('both',2)])
@pytest.mark.parametrize('count', [10,15,20])
def test_estimate(style, multiplier, count):
    assert pc.estimate_cost(8,count,0.0005,style) == pytest.approx(8*count*.0005*multiplier)


def test_quoted():
    assert pc.build_body('A "quoted" sentence.') == dict(query='"A quoted sentence."',mode='balanced',count=10,page_text=True,highlights=True)


def test_plain():
    assert pc.build_body('A "quoted" sentence.', 'plain', 'fast',20)['query'] == 'A "quoted" sentence.'


def test_query_limit():
    with pytest.raises(ValueError):
        pc.build_body('x'*2000)


def test_normalize():
    assert pc.normalize('HIGH-level,general-purpose') == 'high level general purpose'
    assert pc.normalize('\u201cWide\u201d\u2014range Ａ') == 'wide range a'


def test_exact(response):
    result = pc.score_result(SENTENCE, response['results'][0])
    assert result['score'] == 1 and result['exact']
    assert result['containment'] == 1
    assert result['longest_run_share'] == 1
    assert result['longest_run_words'] == len(pc.normalize(SENTENCE).split())
    assert 'high-level,general-purpose' in result['evidence_snippet']


def test_fallback(response):
    assert pc.score_result(SENTENCE, response['results'][2])['exact']


def test_partial():
    result = pc.score_result(SENTENCE, {'page_text':'Garden tools are high level devices for growing green plants.'})
    assert 0 < result['score'] < 1
    assert not result['exact']
    assert result['longest_run_words'] == 5


def test_no_overlap():
    assert pc.score_result(SENTENCE, {'page_text':'Ocean currents travel across deep water.'})['score'] == 0


def test_two_words():
    assert pc.score_result('garden tools', {'page_text':'These garden tools work.'})['containment'] == 1


@pytest.mark.parametrize('url,expected', [
    ('https://web.archive.org/web/20261001/https://www.garden.example/guide/?utm_source=x#top','https://garden.example/guide'),
    ('https://garden-example.translate.goog/guide/?_x_tr_sl=en&_x_tr_tl=fr','https://garden.example/guide'),
    ('https://my--garden-example.translate.goog/a/?_x_tr_sl=en&keep=1','https://my-garden.example/a?keep=1'),
    ('https://WWW.GARDEN.EXAMPLE/path/?utm_campaign=a&keep=b#section','https://garden.example/path?keep=b'),
])
def test_canonical(url, expected):
    assert pc.canonical_url(url) == expected


def test_group(response):
    matches = [dict(r,sentence_index=1,score=.7+i*.1) for i,r in enumerate(response['results'])]
    grouped = pc.group_matches(matches)
    assert len(grouped) == 1
    assert grouped[0]['score'] == pytest.approx(.9)
    assert len(grouped[0]['mirror_urls']) == 3


def test_budget(runner):
    run, session, _ = runner
    assert run(['--yes','--max-cost','0']) == 4
    assert not session.calls


@pytest.mark.parametrize('answer,expected,calls', [('n\n',1,0),('y\n',0,1),('YES\n',0,1)])
def test_confirm(runner, monkeypatch, answer, expected, calls):
    run, session, _ = runner
    monkeypatch.setattr(pc.sys, 'stdin', Terminal(answer))
    assert run() == expected
    assert len(session.calls) == calls


def test_non_tty(runner,capsys):
    run, session, _ = runner
    assert run() == 1
    assert '--yes' in capsys.readouterr().err
    assert not session.calls


def test_dry_run(runner):
    run, session, _ = runner
    assert run(['--dry-run','--key-file','/missing/key']) == 0
    assert not session.calls


def test_fingerprint(runner):
    run, session, _ = runner
    assert run(['--yes','--expect-fingerprint','0000000000000000']) == 2
    assert not session.calls


def test_correct_fingerprint(runner):
    run, session, _ = runner
    assert run(['--yes','--expect-fingerprint',hashlib.sha256(KEY.encode()).hexdigest()[:8]]) == 0
    assert len(session.calls) == 1


def test_env_ignored(runner,monkeypatch):
    run, session, _ = runner
    monkeypatch.setenv('DESEARCH_API_KEY','wrong-environment-key')
    assert run(['--yes']) == 0
    assert session.calls[0][1]['headers']['Authorization'] == KEY
    assert run(['--yes','--key-file','/missing/key']) == 2
    assert len(session.calls) == 1


def test_outputs(runner,capsys):
    run, session, root = runner
    assert run(['--yes']) == 0
    out = root/'out'
    with (out/'trial-matches.csv').open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == pc.MATCH_COLUMNS
        assert len(list(reader)) == 3
    with (out/'trial-sentences.csv').open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == pc.SENTENCE_COLUMNS
        assert list(reader)[0]['found_online'] == 'yes'
    summary = (out/'trial-summary.md').read_text()
    assert summary.startswith('# Matching sources found on the web')
    assert '1 of 1 sampled sentences' in summary
    assert 'does not say who wrote it first' in summary
    assert 'Mirror URLs for' in summary
    assert '$0.005000' in summary
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    for path in out.rglob('*'):
        if path.is_file():
            assert KEY not in path.read_text()
    call = json.loads((out/'trial-calls.jsonl').read_text())
    assert call['desearch_headers'] == {'X-Desearch-Test':'fixture'}
    assert call['time'].endswith('+04:00')
    assert session.calls[0][0] == 'https://api.desearch.ai/search'
    assert session.calls[0][1]['headers']['User-Agent'] == 'desearch-plagiarism-checker/1.0'


def test_no_matches(runner,capsys):
    run, session, root = runner
    session.responses = [FakeResponse(dict(results=[],cost_usd=.002))]
    assert run(['--yes']) == 0
    assert pc.NO_MATCH in capsys.readouterr().out.splitlines()
    assert pc.NO_MATCH in (root/'out/trial-summary.md').read_text().splitlines()


@pytest.mark.parametrize('status,expected,calls', [(422,0,2),(429,0,2),(500,0,2),(401,2,1),(402,2,1)])
def test_http_errors(runner,status,expected,calls,capsys):
    run, session, root = runner
    session.responses[0] = FakeResponse({'detail':'fixture failure'}, status)
    assert run(['--yes'], SENTENCE+' '+SECOND) == expected
    assert len(session.calls) == calls
    records = [json.loads(line) for line in (root/'out/trial-calls.jsonl').read_text().splitlines()]
    assert records[0]['http_status'] == status
    assert 'fixture failure' in capsys.readouterr().err


def test_timeout(runner):
    run, session, root = runner
    session.responses[0] = requests.Timeout('fixture timeout')
    assert run(['--yes'], SENTENCE+' '+SECOND) == 0
    assert len(session.calls) == 2
    records = [json.loads(line) for line in (root/'out/trial-calls.jsonl').read_text().splitlines()]
    assert records[0]['http_status'] is None
    assert 'timeout' in records[0]['error']


def test_slow(runner,monkeypatch,capsys):
    run, _, root = runner
    ticks = iter([0,21])
    monkeypatch.setattr(pc.time,'monotonic', lambda: next(ticks))
    assert run(['--yes']) == 0
    assert 'slow response' in capsys.readouterr().err
    assert '21.00 s' in (root/'out/trial-summary.md').read_text()


def test_cost_sum(runner):
    run, session, root = runner
    session.responses = [FakeResponse({'results':[], 'cost_usd':.003}), FakeResponse({'results':[], 'cost_usd':.007})]
    assert run(['--yes','--query-style','both']) == 0
    summary = (root/'out/trial-summary.md').read_text()
    assert 'Total cost: $0.010000' in summary
    assert 'Empty-result calls: 2; their cost: $0.010000' in summary


def test_threshold(runner):
    run, session, root = runner
    body = {'results':[dict(url='https://garden.example',page_text='Garden tools are high level devices for growing green plants.')], 'cost_usd':0}
    session.responses = [FakeResponse(body)]
    assert run(['--yes','--threshold','0.9']) == 0
    assert list(csv.DictReader((root/'out/trial-matches.csv').open())) == []
    session.responses = [FakeResponse(body)]
    assert run(['--yes','--threshold','0.1','--run-name','low']) == 0
    assert len(list(csv.DictReader((root/'out/low-matches.csv').open()))) == 1


def test_secret_echo_redacted(runner,capsys):
    run, session, root = runner
    session.responses = [FakeResponse({'detail':KEY},422)]
    assert run(['--yes']) == 0
    captured = capsys.readouterr()
    assert KEY not in captured.out+captured.err
    for path in (root/'out').rglob('*'):
        if path.is_file():
            assert KEY not in path.read_text()


def test_disallowed_wording(runner):
    run, _, root = runner
    assert run(['--yes']) == 0
    forbidden = ['plagiarism'+'-free','plagiarism'+' free','100%'+' original','original content'+' guaranteed','no'+' plagiarism','AI'+' detected']
    paths = [Path(pc.__file__),Path('README.md')] + [p for p in (root/'out').rglob('*') if p.is_file()]
    for path in paths:
        data = path.read_text()
        assert '\u2014' not in data
        for phrase in forbidden:
            assert phrase.lower() not in data.lower()


def test_stdin_input(runner,monkeypatch):
    _, session, root = runner
    monkeypatch.setattr(pc.sys,'stdin',io.StringIO('Garden title\n'+SENTENCE))
    assert pc.main(['--engine', 'search', '-','--yes','--key-file',str(root/'access.key'),'--out',str(root/'out')]) == 0
    assert len(session.calls) == 1


def test_file_input(runner):
    _, session, root = runner
    path = root/'essay.txt'
    path.write_text(SENTENCE)
    assert pc.main(['--engine', 'search', str(path),'--yes','--key-file',str(root/'access.key'),'--out',str(root/'out')]) == 0
    assert len(session.calls) == 1


@pytest.mark.parametrize('host', ['translate.google.com', 'translate.googleusercontent.com'])
def test_translate_wrapper(host):
    assert pc.canonical_url('https://' + host + '/translate?hl=fr&u=http%3A%2F%2Fwww.garden.example%2Fguide%2F%3Futm_source%3Dx') == 'https://garden.example/guide'


def test_http_group_and_representative():
    urls = ['https://web.archive.org/web/20261001/http://garden.example/a',
            'http://garden.example/a', 'https://garden.example/a']
    rows = [dict(sentence_index=1, url=u, score=1-i*.1) for i,u in enumerate(urls)]
    group, = pc.group_matches(rows)
    assert group['canonical_url'] == 'https://garden.example/a'
    assert group['url'] == urls[1]
    assert group['score'] == 1
    assert pc.group_matches(rows[:1])[0]['url'] == urls[0]


@pytest.mark.parametrize('partial,status', [('0.2','partial'), ('0.4','none')])
def test_below_threshold_reporting(runner, partial, status):
    run, session, root = runner
    url = 'http://www.garden.example/a/'
    result = dict(url=url, page_text='Garden tools are high level devices for growing green plants.')
    score = pc.score_result(SENTENCE, result)['score']
    session.responses = [FakeResponse(dict(results=[dict(url='https://empty.example', page_text='Ocean waves.'), result]))]
    assert run(['--yes', '--threshold', '0.9', '--partial-threshold', partial]) == 0
    row, = csv.DictReader((root/'out/trial-sentences.csv').open())
    assert float(row['best_score']) == score
    assert row['best_url'] == url
    assert row['best_canonical_url'] == 'https://garden.example/a'
    assert row['overlap'] == status
    assert row['found_online'] == 'no'
    assert list(csv.DictReader((root/'out/trial-matches.csv').open())) == []
    report = (root/'out/trial-summary.md').read_text()
    assert f'{score:.3f}' in report and url in report
    assert ('1 sampled sentences have partial overlap (score between 0.2 and 0.9); check them by hand.' in report) == (status == 'partial')
    assert 'Mirror URLs for' not in report


def test_source_order_and_mirror_lines(tmp_path):
    def row(index, url, score):
        return dict(sentence_index=index, url=url, canonical_url=pc.canonical_url(url), score=score, title='Source', published_date=None)
    archive = 'https://web.archive.org/web/20261001/http://b.example'
    rows = [row(1, archive, .9), row(1, 'http://b.example', .7),
            row(1, 'https://a.example', .9), row(1, 'https://z.example', .6),
            row(2, 'https://z.example', .6), row(1, 'https://c.example', .8)]
    sampled = [(1, SENTENCE), (2, SECOND)]
    summary = pc.summarize(sampled, rows, [])
    assert [r['url'] for r in summary['sources']] == ['https://z.example', 'https://a.example', 'https://b.example', 'https://c.example']
    args = pc.parser().parse_args(['--text', SENTENCE])
    path = tmp_path/'summary.md'
    pc.write_summary(path, summary, sampled, args)
    report = path.read_text()
    mirror_lines = [line for line in report.splitlines() if line.startswith('Mirror URLs for')]
    assert mirror_lines == ['Mirror URLs for http://b.example: ' + archive]
    assert '| Best score | Mirror count |' in report
    assert '| http://b.example | Source |  | 1 | 0.900 | 1 |' in report


def test_replay_offline_and_same_sampling(runner, monkeypatch, capsys):
    run, session, root = runner
    text = 'Short sentence. ' + SENTENCE + ' ' + SECOND
    options = ['--max-sentences','1','--query-style','both']
    assert run(['--yes', *options], text) == 0
    original = (root/'out/trial-sentences.csv').read_text()
    matches = (root/'out/trial-matches.csv').read_text()
    capsys.readouterr()
    def forbidden(*args, **kwargs):
        pytest.fail('Replay attempted a search or client construction')
    monkeypatch.setattr(pc, 'SearchClient', forbidden)
    monkeypatch.setattr(pc.requests.sessions.Session, 'request', forbidden)
    (root/'access.key').unlink()
    assert run(['--replay',str(root/'out/trial-raw'), '--run-name','replay', '--max-cost','0', *options], text) == 0
    assert (root/'out/replay-sentences.csv').read_text() == original
    assert (root/'out/replay-matches.csv').read_text() == matches
    assert not (root/'out/replay-calls.jsonl').exists()
    assert not (root/'out/replay-raw').exists()
    report = (root/'out/replay-summary.md').read_text()
    stdout = capsys.readouterr().out
    for output in [report, stdout]:
        assert 'Replay of saved responses, no new searches, cost $0' in output
        assert 'cost of the original run: $0.010000' in output
    settings = json.loads(next(line.removeprefix('Settings: ') for line in report.splitlines() if line.startswith('Settings: ')))
    assert set(settings) == set('input max_sentences min_words query_style mode count threshold partial_threshold run_name engine'.split())
    assert settings['input'] == 'inline text'


@pytest.mark.parametrize('value', ['-0.1', '1.1', 'nan', 'inf'])
def test_invalid_partial_threshold(value):
    with pytest.raises(SystemExit):
        pc.main(['--engine', 'search', '--text', SENTENCE, '--partial-threshold', value])


def test_replay_missing_response(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, 'SearchClient', lambda *a, **k: pytest.fail('Unexpected client'))
    assert pc.main(['--engine', 'search', '--text', SENTENCE, '--replay', str(tmp_path), '--out',str(tmp_path/'out')]) == 2
    assert not list((tmp_path/'out').glob('*calls.jsonl'))
