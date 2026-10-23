import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import youtube_creator_finder as app

FIX = Path(__file__).parent / 'fixtures'
RESULTS = json.loads((FIX / 'sample-results.json').read_text())
TASK = json.loads((FIX / 'sample-task.json').read_text())


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code = body, status
        self.headers = headers or {}
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        if isinstance(self.body, str):
            raise ValueError()
        return self.body


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert self.responses, 'Unexpected HTTP call'
        return self.responses.pop(0)


@pytest.fixture
def cli(tmp_path):
    key = tmp_path / 'secret.key'
    key.write_text('  secret-credential-123\n')
    return ['--query', 'coffee creators', '--key-file', str(key), '--out', str(tmp_path / 'out')]


def test_minimal_body():
    assert app.build_request_body({'query': 'coffee'}) == {'query': 'coffee', 'count': 5}


def test_filters_omitted():
    assert 'filters' not in app.build_request_body(app.parser().parse_args(['--query', 'coffee']))


def test_all_body_fields():
    args = app.parser().parse_args(['--query', 'coffee', '--count', '10', '--min-score', '0', '--min-subscribers', '0', '--max-subscribers', '90', '--country', 'US', '--country', 'GE', '--require-contact', '--keyword', 'gear', '--exclude-keyword', 'store'])
    assert app.build_request_body(args) == {'query': 'coffee', 'count': 10, 'min_score': 0, 'filters': {'min_subscribers': 0, 'max_subscribers': 90, 'countries': ['US', 'GE'], 'require_contact': True, 'keywords': ['gear'], 'exclude_keywords': ['store']}}


@pytest.mark.parametrize('contents', ['alice\nbob\nalice\n\n', 'handle,name\nalice,A\nbob,B\nalice,C\n'])
def test_excludes(tmp_path, contents):
    p = tmp_path / 'exclude'
    p.write_text(contents)
    assert app.load_excludes(p) == ['alice', 'bob']
    assert app.build_request_body({'query': 'coffee', 'exclude_file': p})['exclude'] == ['alice', 'bob']


@pytest.mark.parametrize('row', RESULTS['results'], ids=lambda r: r['handle'])
def test_parse_sample(row):
    parsed = app.parse_creator(row)
    assert set(parsed) == set(app.COLUMNS)
    assert parsed['handle'] == row['handle']
    assert parsed['score'] == row['score']['value']
    assert parsed['subscribers'] == row['metrics']['subscribers']
    assert parsed['top_video_url'] == row['evidence'][0]['url']
    assert parsed['country'] == row['attributes']['country']
    assert parsed['reasons'] == ' | '.join(row['score']['reasons'])


def test_missing_fields():
    assert app.parse_creator({})['quality_flags'] == 'views_missing | no_contact'


@pytest.mark.parametrize('changes,flag', [({'views': None}, 'views_missing'), ({'videos': 1}, 'few_videos'), ({'email': '', 'website': ''}, 'no_contact'), ({'name': 'Official coffee'}, 'possible_brand_or_store'), ({'score': 59}, 'low_score')])
def test_each_flag(changes, flag):
    row = dict(views=5, videos=2, email='contact@example.com', website='', name='Alice', score=60)
    row.update(changes)
    assert app.quality_flags(row) == [flag]


@pytest.mark.parametrize('term', ['shop', 'STORE', 'Official', 'retailer', 'brand', 'co.', 'inc', 'ltd', 'llc'])
def test_brand_terms(term):
    assert 'possible_brand_or_store' in app.quality_flags({'name': term})


def test_word_boundaries():
    assert 'possible_brand_or_store' not in app.quality_flags({'name': 'Brandon shopping stored incident'})


def test_paging():
    session = Session(Response({'results': RESULTS['results'][:2], 'next_cursor': 'abc', 'has_more': True}), Response({'results': RESULTS['results'][2:], 'next_cursor': '5', 'has_more': False}))
    client = app.HTTPClient('key', session)
    assert len(list(client.results('task'))) == 5
    assert session.calls[1][2]['params'] == {'limit': 100, 'cursor': 'abc'}
    assert client.calls[1]['params'] == {'limit': 100, 'cursor': 'abc'}
    assert session.calls[0][2]['headers']['Authorization'] == 'key'
    assert session.calls[0][2]['headers']['User-Agent'] == 'youtube-creator-finder/1.0'


@pytest.mark.parametrize('status', [200, 202])
def test_create_and_replay(cli, tmp_path, status, capsys):
    task = dict(TASK, cost_usd=.25)
    s = Session(Response(task, status, {'X-Desearch-Cost-Usd': '0.25'}), Response(RESULTS), Response('handle\nAlice\n'))
    assert app.main(cli + ['--idempotency-key', 'unique'], s) == 0
    assert s.calls[0][2]['headers']['Idempotency-Key'] == 'unique'
    out = tmp_path / 'out'
    assert (out / f'{TASK["task_id"]}-export.csv').read_bytes() == b'handle\nAlice\n'
    summary = (out / f'{TASK["task_id"]}-summary.md').read_text()
    assert f'"status_code": {status}' in summary
    assert '121.203018' in summary
    logs = [json.loads(x) for x in next(out.glob('*calls.jsonl')).read_text().splitlines()]
    assert len(logs) == 3
    assert [entry['params'] for entry in logs] == [{}, {'limit': 100}, {'format': 'csv'}]
    assert logs[0]['status'] == status
    assert logs[0]['time'].endswith('+04:00')
    assert 'secret-credential-123' not in json.dumps(logs)
    assert len(capsys.readouterr().out.splitlines()) == 5


@pytest.mark.parametrize('status', [401, 402, 422, 429, 500])
def test_api_error(cli, tmp_path, capsys, status):
    s = Session(Response({'detail': 'bad secret-credential-123'}, status))
    assert app.main(cli, s) == 2
    captured = capsys.readouterr()
    assert str(status) in captured.err
    assert 'bad' in captured.err
    assert 'secret-credential-123' not in captured.out + captured.err
    assert 'secret-credential-123' not in next((tmp_path / 'out').glob('*calls.jsonl')).read_text()


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout(cli, capsys, cancel):
    running = dict(TASK, status='running')
    s = Session(Response(running, 202), Response({'results': [], 'has_more': False}), *([Response(dict(TASK, status='cancelled'))] if cancel else []))
    assert app.main(cli + ['--max-wait', '0'] + (['--cancel-on-timeout'] if cancel else []), s) == 3
    assert TASK['task_id'] in capsys.readouterr().err
    assert any('/cancel' in c[1] for c in s.calls) == cancel


def test_dry_run_no_key(capsys):
    assert app.main(['--query', 'coffee', '--dry-run', '--key-file', '/missing'], Session()) == 0
    assert json.loads(capsys.readouterr().out) == {'query': 'coffee', 'count': 5}


def test_api_key_env_ignored(monkeypatch, capsys):
    monkeypatch.setenv('DESEARCH_API_KEY', 'forbidden-env-secret')
    s = Session()
    assert app.main(['--query', 'coffee', '--key-file', '/missing'], s) == 2
    assert not s.calls
    assert 'forbidden-env-secret' not in str(capsys.readouterr())


def test_key_file_env(cli, monkeypatch):
    monkeypatch.setenv('DESEARCH_KEY_FILE', cli[3])
    assert app.parser().parse_args(['--query', 'coffee']).key_file == cli[3]


def test_poll_stream_dedup_resume(cli, capsys, monkeypatch):
    monkeypatch.setattr(app.time, 'sleep', lambda _: None)
    final = copy.deepcopy(RESULTS)
    for index, row in enumerate(final['results']):
        row['id'] = f'final-{index}'
    final['results'].append(copy.deepcopy(final['results'][0]))
    s = Session(Response(dict(TASK, status='running')), Response(RESULTS), Response(TASK), Response(final), Response('csv'))
    assert app.main(cli + ['--task-id', TASK['task_id'], '--poll-seconds', '0'], s) == 0
    assert len(capsys.readouterr().out.splitlines()) == 5
    assert all(c[0] == 'GET' for c in s.calls)


def test_summary():
    rows = [app.parse_creator(r) for r in RESULTS['results']]
    summary = app.summarize(TASK, rows, TASK['request'])
    for term in ['count_reached', 'reserved_cost_usd: 0.25', 'emails_count: 0', 'duration_seconds: 121.203018']:
        assert term in summary


@pytest.mark.parametrize('intermediate', [('queued', 'running'), ('pausing', 'paused')])
def test_poll_until_completed(cli, tmp_path, monkeypatch, intermediate):
    monkeypatch.setattr(app.time, 'sleep', lambda _: None)
    summaries = []
    summarize = app.summarize

    def track_summary(task, *args):
        summaries.append(task['status'])
        return summarize(task, *args)

    monkeypatch.setattr(app, 'summarize', track_summary)
    empty = Response({'results': [], 'has_more': False})
    s = Session(
        Response(dict(TASK, status=intermediate[0], created_at=None, finished_at=None), 202), empty,
        Response(dict(TASK, status=intermediate[1], finished_at=None)), empty,
        Response(TASK), Response(RESULTS), Response('csv'),
    )
    assert app.main(cli + ['--poll-seconds', '0'], s) == 0
    assert not s.responses
    assert summaries == ['completed']
    summary = next((tmp_path / 'out').glob('*-summary.md')).read_text()
    assert 'task_status: "completed"' in summary


@pytest.mark.parametrize('field', ['created_at', 'finished_at'])
@pytest.mark.parametrize('missing', [False, True])
def test_summary_missing_timestamps(field, missing):
    task = dict(TASK)
    if missing:
        task.pop(field)
    else:
        task[field] = None
    assert 'duration_seconds: null' in app.summarize(task, [], TASK['request'])


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled', 'expired'])
def test_terminal_statuses(cli, status):
    s = Session(Response(dict(TASK, status=status, finished_at=None)),
                Response({'results': [], 'has_more': False}), Response('csv'))
    assert app.main(cli, s) == (0 if status == 'completed' else 2)
    assert not s.responses


@pytest.mark.parametrize('count', ['4', '201'])
def test_count_validation(count):
    with pytest.raises(SystemExit) as e:
        app.main(['--query', 'coffee', '--count', count, '--dry-run'])
    assert e.value.code == 2


def test_echoed_key_redacted_from_results(cli, tmp_path, capsys):
    row = copy.deepcopy(RESULTS['results'][0])
    row['name'] = 'secret-credential-123'
    s = Session(Response(TASK, 202), Response({'results': [row], 'has_more': False}), Response('handle\nAlice\n'))
    assert app.main(cli, s) == 0
    captured = capsys.readouterr()
    assert 'secret-credential-123' not in captured.out + captured.err
    for path in (tmp_path / 'out').iterdir():
        assert 'secret-credential-123' not in path.read_text()


def test_fixtures_are_neutral():
    from urllib.parse import urlsplit

    def check(value):
        if isinstance(value, dict):
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, str):
            assert '@' not in value
            if value.startswith(('http://', 'https://')):
                assert urlsplit(value).hostname == 'example.com'

    assert {path.name for path in FIX.glob('*.json')} == {'sample-results.json', 'sample-task.json'}
    check(RESULTS)
    check(TASK)
    assert len(RESULTS['results']) == 5
    assert all(row['name'].startswith('Example Channel ') for row in RESULTS['results'])


@pytest.mark.parametrize('bio', ['Contact alice@example.com', 'https://example.com/shop www.example.com/store', 'shop@example.com official@example.com example.com/store'])
def test_bio_addresses_do_not_flag(bio):
    assert 'possible_brand_or_store' not in app.quality_flags({'name': 'Alice'}, bio)


@pytest.mark.parametrize('handle', ['XOfficial', 'MySHOPChannel', 'bookstore'])
def test_handle_brand_substrings(handle):
    assert 'possible_brand_or_store' in app.quality_flags({'handle': handle})


def test_contact_fields_do_not_flag():
    assert 'possible_brand_or_store' not in app.quality_flags({'name': 'example.com', 'email': 'shop@example.com', 'website': 'https://example.com/official'})


@pytest.mark.parametrize('term', ['shop', 'STORE', 'Official', 'retailer', 'brand', 'inc', 'ltd', 'llc', 'co.'])
def test_bio_brand_words(term):
    assert 'possible_brand_or_store' in app.quality_flags({}, f'https://example.com {term}')
