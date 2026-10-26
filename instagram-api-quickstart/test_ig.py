import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import pytest
import ig


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Tests must use a fake opener')
    monkeypatch.setattr(ig, 'urlopen', blocked)


class Response(io.BytesIO):
    def __init__(self, body, headers=None, code=200):
        super().__init__(json.dumps(body).encode())
        self.code = code
        self.headers = headers or {}


def setup_cli(monkeypatch, replies):
    calls = []
    def opener(request, timeout):
        calls.append(request)
        return replies.pop(0)
    monkeypatch.setenv('DESEARCH_API_KEY', 'fake-secret-key')
    monkeypatch.delenv('DESEARCH_API_KEY_FILE', raising=False)
    monkeypatch.setattr(ig, 'urlopen', opener)
    return calls


def output(capsys):
    out, err = capsys.readouterr()
    assert 'fake-secret-key' not in out + err
    return json.loads(out), err


def test_headers_and_logs(tmp_path, capsys):
    requests = []
    def opener(req, timeout):
        requests.append(req)
        assert timeout == 90
        return Response({'echo': 'fake-secret-key'}, {'X-Desearch-Cost-Usd': '0.012'})
    client = ig.Client('fake-secret-key', log_dir=tmp_path, opener=opener)
    status, body, meta = client.get('/desearch/instagram/profile/example_brand', {})
    headers = {k.lower(): v for k, v in requests[0].header_items()}
    assert headers['authorization'] == 'fake-secret-key'
    assert 'Bearer' not in headers['authorization']
    assert headers['user-agent'] == 'desearch-py-examples/instagram-api-quickstart'
    assert headers['accept'] == 'application/json'
    assert client.calls == 1 and client.cost_usd == .012
    assert body['echo'] == '<redacted>'
    for file in tmp_path.rglob('*'):
        if file.is_file():
            assert 'fake-secret-key' not in file.read_text()
    record = json.loads(next((tmp_path / 'raw').glob('*.json')).read_text())
    assert record['request']['headers']['Authorization'] == '<redacted>'
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 1
    assert 'fake-secret-key' not in ''.join(capsys.readouterr())


@pytest.mark.parametrize('raw,expected', [(b'{"detail":"missing"}', {'detail': 'missing'}), (b'not found', 'not found')])
def test_http_errors(raw, expected):
    def opener(req, timeout):
        raise HTTPError(req.full_url, 404, 'missing', {}, io.BytesIO(raw))
    status, body, meta = ig.Client('key', opener=opener).get('/desearch/instagram/media/code', {})
    assert status == 404 and body == expected and meta['status'] == 404


@pytest.mark.parametrize('error', [URLError('offline'), TimeoutError('timeout')])
def test_connection_errors(error):
    def opener(req, timeout):
        raise error
    assert ig.Client('key', opener=opener).get('/desearch/instagram/media/code', {})[0] == 0


def test_paging(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [Response([{'createTime': 1704067200}], {'x-desearch-next-cursor': 'opaque+ /', 'x-desearch-cost-usd': '.01'}), Response([{}])])
    assert ig.main(['posts', '@example_brand', '--pages', '5']) == 0
    result, err = output(capsys)
    assert len(calls) == result['pages_fetched'] == 2
    assert parse_qs(urlsplit(calls[1].full_url).query)['cursor'] == ['opaque+ /']
    assert result['next_cursor'] is None and result['cost_usd'] == .01
    assert result['items'][0]['created_at'] == '2024-01-01T00:00:00Z'
    assert len(err.splitlines()) == 2


def test_search(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [Response([{'username': 'example_brand'}], {'x-desearch-next-cursor': 'ignored'})])
    assert ig.main(['search', 'example  coffee', '--count', '2']) == 0
    result, _ = output(capsys)
    assert calls[0].method == 'POST'
    assert json.loads(calls[0].data) == {'query': 'example coffee', 'count': 2}
    assert 'cursor' not in calls[0].full_url and result['next_cursor'] is None


def test_budget(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [Response([{}], {'x-desearch-next-cursor': 'next', 'x-desearch-cost-usd': '.025'})])
    assert ig.main(['--max-cost', '.04', 'posts', 'example_brand', '--pages', '5']) == 0
    result, err = output(capsys)
    assert len(calls) == result['calls'] == 1 and 'exceed' in err


@pytest.mark.parametrize('args', [['posts', 'bad name'], ['comments', 'bad/code'], ['hashtag', '!'], ['search', ' '], ['posts', 'example_brand', '--count', '101'], ['posts', 'example_brand', '--pages', '6']])
def test_bad_input(monkeypatch, args):
    calls = setup_cli(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        ig.main(args)
    assert exc.value.code == 2 and calls == []


@pytest.mark.parametrize('authors', [False, True])
def test_comment_authors(monkeypatch, capsys, authors):
    setup_cli(monkeypatch, [Response([{'author': {'username': 'example_brand'}, 'text': ' example '}])])
    assert ig.main(['comments', 'AbC123xyz_-'] + (['--with-authors'] if authors else [])) == 0
    result, _ = output(capsys)
    assert ('author' in result['items'][0]) == authors


def test_hashtag_date(monkeypatch, capsys):
    setup_cli(monkeypatch, [Response([{'createTime': '2024-01-01T04:00:00+04:00'}])])
    ig.main(['hashtag', '#examplecoffee'])
    assert output(capsys)[0]['items'][0]['created_at'] == '2024-01-01T00:00:00Z'


def test_failure_output(monkeypatch, capsys):
    setup_cli(monkeypatch, [Response({'detail': 'missing'}, code=404)])
    assert ig.main(['media', '123456']) == 1
    result, _ = output(capsys)
    assert result == dict(error='missing', status=404, cost_usd=0.0, calls=1)


def test_key_priority(monkeypatch, tmp_path):
    explicit = tmp_path / 'explicit'
    env = tmp_path / 'env'
    explicit.write_text(' explicit-key\n')
    env.write_text(' env-key\n')
    monkeypatch.setenv('DESEARCH_API_KEY_FILE', str(env))
    monkeypatch.setenv('DESEARCH_API_KEY', 'fallback')
    assert ig.api_key(str(explicit)) == 'explicit-key'
    assert ig.api_key() == 'env-key'
    monkeypatch.delenv('DESEARCH_API_KEY_FILE')
    assert ig.api_key() == 'fallback'
    monkeypatch.delenv('DESEARCH_API_KEY')
    with pytest.raises(ig.core.InputError):
        ig.api_key()


def test_empty_page_stops(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [Response([], {'x-desearch-next-cursor': 'next'})])
    ig.main(['posts', 'example_brand', '--pages', '5'])
    assert output(capsys)[0]['returned'] == 0
    assert len(calls) == 1


def test_media_url_and_raw(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [Response({'shortcode': 'AbC123xyz_-', 'extra': 123})])
    ig.main(['--raw', 'media', 'https://www.instagram.com/reel/AbC123xyz_-/'])
    result, _ = output(capsys)
    assert calls[0].full_url.endswith('/media/AbC123xyz_-')
    assert result['item']['extra'] == 123


def test_initial_budget_stop(monkeypatch, capsys):
    calls = setup_cli(monkeypatch, [])
    ig.main(['--max-cost', '0', 'search', 'example coffee'])
    result, _ = output(capsys)
    assert result['calls'] == 0 and calls == []


@pytest.mark.parametrize('command,body,status', [
    (['profile', 'natgeo'], {'biography': 'Explore 🌎'}, 200),
    (['posts', 'natgeo'], [{'caption': 'Explore 🌎'}], 200),
    (['profile', 'natgeo'], {'detail': 'Unavailable 🌎'}, 404),
])
def test_stdout_is_indented_json(monkeypatch, capsys, command, body, status):
    setup_cli(monkeypatch, [Response(body, code=status)])
    assert ig.main(command) == (0 if status == 200 else 1)
    stdout = capsys.readouterr().out
    parsed = json.loads(stdout)
    assert stdout == json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'
    assert '\n  "' in stdout
    assert '🌎' in stdout
