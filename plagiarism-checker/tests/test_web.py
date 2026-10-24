import csv
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import plagiarism_checker as pc

TEXT = 'Quiet garden robots carefully water the colorful flowers every morning.'
PART = 'Quiet garden robots carefully water the'


class Response:
    def __init__(self, body, status=200, cost='0.001'):
        self.status_code = status
        self.body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = {'X-Desearch-Cost-Usd': cost, 'X-Desearch-Service': 'Web Crawl',
                        'X-Desearch-Usage-Count': '1'}

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def web(snippet=PART):
    return Response({'data': [{'title': 'Garden notes', 'link': 'https://garden.example/a',
                               'snippet': snippet}], 'cost_usd': .001,
                     'usage_count': 1, 'service': 'Web Search', 'currency': 'USD'})


@pytest.mark.parametrize('style', ['quoted', 'plain'])
def test_query_params(style):
    session = Session([web()])
    sentence = 'Quiet & colorful "gardens"?'
    pc.SearchClient('key', session).search(pc.build_body(sentence, style), 1, style, 'web')
    url, options = session.calls[0]
    expected = '"Quiet & colorful gardens?"' if style == 'quoted' else sentence
    assert url == 'https://api.desearch.ai/web'
    assert options['params'] == {'query': expected}
    prepared = requests.Request('GET', url, params=options['params']).prepare()
    assert parse_qs(urlsplit(prepared.url).query)['query'] == [expected]


def test_elisions():
    snippet = 'Unrelated plants... ' + TEXT + '... Extra details'
    assert pc.score_snippet(TEXT, snippet)['score'] == 1
    assert pc.score_snippet(TEXT, snippet) == max(
        [pc.score_result(TEXT, {'page_text': p}) for p in [snippet, *snippet.split('...')]],
        key=lambda r: r['score'])


def test_selection():
    def row(index, url, score):
        return dict(sentence_index=index, url=url, canonical_url=pc.canonical_url(url), snippet_score=score)
    rows = [row(1, 'http://www.a.example/', .5), row(1, 'https://a.example', .8),
            row(1, 'https://b.example', .7), row(2, 'https://c.example', .9),
            row(2, 'https://d.example', .1)]
    assert list(pc.select_candidates(rows, .4, 1, 10)) == ['https://a.example', 'https://c.example']
    assert len(pc.select_candidates(rows, .4, 3, 2)) == 2
    assert pc.select_candidates(rows, .4, 0, 10) == {}


@pytest.mark.parametrize('verify,expected', [(0, .002), (3, .005)])
def test_estimate(verify, expected):
    assert sum(pc.web_cost_parts(2, verify_pages=verify)) == pytest.approx(expected)
    assert sum(pc.web_cost_parts(8, 'both')) == pytest.approx(.021)
    assert pc.parser().parse_args([]).engine == 'web'


def run(tmp_path, monkeypatch, responses, extra=()):
    key = tmp_path / 'key'
    key.write_text('fixture-key')
    session = Session(responses)
    monkeypatch.setattr(pc.requests, 'Session', lambda: session)
    code = pc.main(['--text', TEXT, '--yes', '--key-file', str(key), '--out', str(tmp_path),
                    '--run-name', 'web', *extra])
    return code, session


def test_verify_and_replay(tmp_path, monkeypatch):
    code, session = run(tmp_path, monkeypatch, [web(), Response(TEXT, cost='0.0005')])
    assert code == 0
    assert session.calls[1][1]['params'] == {'url': 'https://garden.example/a', 'format': 'text'}
    rows = list(csv.DictReader((tmp_path / 'web-matches.csv').open()))
    assert len(rows) == 1
    row = rows[0]
    assert float(row['snippet_score']) < .6
    assert row['page_score'] == '1.0' and row['verified_on_page'] == 'yes'
    assert row['published_date'] == '' and row['rank'] == '1'
    records = [json.loads(line) for line in (tmp_path / 'web-calls.jsonl').read_text().splitlines()]
    assert sum(r['cost_usd'] for r in records) == pytest.approx(.0015)
    assert records[1]['kind'] == 'extract' and records[1]['bytes'] == len(TEXT.encode())
    original = (tmp_path / 'web-matches.csv').read_text()
    monkeypatch.setattr(pc, 'SearchClient', lambda *a, **k: pytest.fail('Network in replay'))
    assert pc.main(['--text', TEXT, '--replay', str(tmp_path / 'web-raw'), '--out', str(tmp_path), '--run-name', 'replay']) == 0
    assert (tmp_path / 'replay-matches.csv').read_text() == original
    assert 'Extract cost: $0.000500' in (tmp_path / 'replay-summary.md').read_text()


@pytest.mark.parametrize('failure,exit_code', [(Response('missing', 404), 0), (Response('unavailable', 500), 0),
                                               (requests.Timeout('timed out'), 0),
                                               (Response('credits required', 402), 2),
                                               (Response('unauthorized', 401), 2)])
def test_extract_errors(tmp_path, monkeypatch, failure, exit_code):
    code, _ = run(tmp_path, monkeypatch, [web(), failure])
    assert code == exit_code
    assert list(csv.DictReader((tmp_path / 'web-matches.csv').open())) == []
    records = [json.loads(line) for line in (tmp_path / 'web-calls.jsonl').read_text().splitlines()]
    assert 'error' in records[-1]


def test_header_cost_wins():
    session = Session([Response({'data': [], 'cost_usd': 99}, cost='0.001')])
    record, _ = pc.SearchClient('key', session).search(pc.build_body(TEXT), 1, 'quoted', 'web')
    assert record['cost_usd'] == .001


def test_query_window():
    assert pc.query_window(TEXT) == TEXT
    assert pc.query_window('the a to distinctive unusual flowers', 3) == 'distinctive unusual flowers'
    assert pc.query_window('alpha bravo cider delta', 2) == 'alpha bravo'
    assert len(pc.query_window(' '.join(['word'] * 53)).split()) == 18
    assert pc.query_window('the a bright, colorful flowers!', 3) == 'bright, colorful flowers!'


@pytest.mark.parametrize('engine', ['web', 'search'])
@pytest.mark.parametrize('style', ['quoted', 'plain', 'both'])
def test_window_requests_and_outputs(tmp_path, monkeypatch, capsys, engine, style):
    class BothSession(Session):
        def post(self, url, **kwargs):
            return self.get(url, **kwargs)

    window = 'distinctive colorful flowers'
    sentence = 'the a to of in ' + window + '.'
    styles = ['quoted', 'plain'] if style == 'both' else [style]
    body = {'data': []} if engine == 'web' else {'results': []}
    session = BothSession([Response(body) for _ in styles])
    monkeypatch.setattr(pc.requests, 'Session', lambda: session)
    key = tmp_path / 'key'
    key.write_text('fixture-key')
    assert pc.main(['--text', sentence, '--engine', engine, '--query-style', style,
                    '--max-query-words', '3', '--yes', '--key-file', str(key),
                    '--out', str(tmp_path), '--run-name', 'window']) == 0
    expected = ['"' + window + '."' if s == 'quoted' else window + '.' for s in styles]
    assert [(opts['params'] if engine == 'web' else opts['json'])['query']
            for _, opts in session.calls] == expected
    records = [json.loads(line) for line in (tmp_path / 'window-calls.jsonl').read_text().splitlines()]
    assert [r['query'] for r in records] == expected
    row, = csv.DictReader((tmp_path / 'window-sentences.csv').open())
    assert row['query_used'] == '\n'.join(expected)
    assert row['sentence'] == sentence
    assert '(window of 3 words)' in capsys.readouterr().out


def test_window_snippet_full_page_score(tmp_path, monkeypatch):
    window = pc.query_window(TEXT, 4)
    assert pc.score_snippet(TEXT, window)['score'] < 1
    code, _ = run(tmp_path, monkeypatch, [web(window), Response(window, cost='0.0005')],
                  ['--max-query-words', '4'])
    assert code == 0
    row, = csv.DictReader((tmp_path / 'web-matches.csv').open())
    assert float(row['snippet_score']) == 1
    assert float(row['page_score']) == pc.score_result(TEXT, {'page_text': window})['score'] < 1


def test_full_sentence_snippet_can_score_higher(tmp_path, monkeypatch):
    window = pc.query_window(TEXT, 4)
    snippet = 'water the colorful flowers every morning.'
    assert pc.score_snippet(TEXT, snippet)['score'] > pc.score_snippet(window, snippet)['score']
    code, _ = run(tmp_path, monkeypatch, [web(snippet)], ['--max-query-words', '4', '--verify-pages', '0'])
    assert code == 0
    row, = csv.DictReader((tmp_path / 'web-sentences.csv').open())
    assert float(row['best_score']) == pc.score_snippet(TEXT, snippet)['score']


def test_invalid_max_query_words():
    with pytest.raises(SystemExit):
        pc.main(['--text', TEXT, '--max-query-words', '0'])


@pytest.mark.parametrize('engine', ['web', 'search'])
def test_summary_engine_settings(tmp_path, engine):
    args = pc.parser().parse_args(['--engine', engine])
    path = tmp_path / 'summary.md'
    pc.write_summary(path, pc.summarize([], [], []), [], args)
    settings = json.loads(next(line[len('Settings: '):] for line in path.read_text().splitlines()
                               if line.startswith('Settings: ')))
    expected = {'mode', 'count'} if engine == 'search' else {'verify_pages', 'max_pages'}
    assert set(settings) & {'mode', 'count', 'verify_pages', 'max_pages'} == expected


def test_plan_flushed_before_requests(tmp_path, monkeypatch):
    import io

    class BufferedOutput(io.StringIO):
        flushed = ''

        def flush(self):
            self.flushed = self.getvalue()

    output = BufferedOutput()
    monkeypatch.setattr(pc.sys, 'stdout', output)
    original_get = Session.get

    def checked_get(self, url, **kwargs):
        assert 'Planned sentences:' in output.flushed
        assert TEXT[:80] in output.flushed
        assert 'estimated max cost:' in output.flushed
        return original_get(self, url, **kwargs)

    monkeypatch.setattr(Session, 'get', checked_get)
    code, session = run(tmp_path, monkeypatch, [web(), Response('missing', 404)])
    assert code == 0
    assert len(session.calls) == 2
