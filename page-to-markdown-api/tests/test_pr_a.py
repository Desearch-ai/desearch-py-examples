"""Validation, free limits metadata, and demo error regressions."""
import importlib.util
import io
import json
from pathlib import Path
import re
import socket
from unittest.mock import Mock

import pytest

from pagemd.guards import RateLimiter
from pagemd.service import Converter
from pagemd.urlguard import URLUnreachableError, URLValidationError, validate_url
from test_demo import dns, make, response

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', [socket.gaierror(), socket.timeout(), OSError('resolver failed')])
def test_resolver_failures_are_unreachable(failure):
    resolver = Mock(side_effect=failure)
    with pytest.raises(URLUnreachableError):
        validate_url('https://example.com', resolver)
    c = make()
    c.resolver = resolver
    for _ in range(8):
        code, body = response(c)
        assert code == 502 and body['status'] == 'unreachable'
        assert body['error'].startswith("Couldn't reach this site")
    assert not c.limiter.hits and c._client.calls == 0
    c.resolver = dns
    assert response(c)[0] == 200


@pytest.mark.parametrize('address,expected', [
    ('198.18.0.0', 502), ('198.19.255.255', 502),
    ('10.0.0.1', 400), ('192.168.1.1', 400), ('172.16.1.1', 400),
    ('127.0.0.1', 400), ('169.254.169.254', 400), ('fe80::1', 400),
    ('fd00::1', 400), ('::1', 400), ('::ffff:8.8.8.8', 400),
])
def test_dns_answer_classification_and_no_limit_charge(address, expected):
    resolver = Mock(return_value=dns('', 443) + [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', (address, 443))])
    with pytest.raises(URLValidationError) as error:
        validate_url('https://example.com', resolver)
    assert isinstance(error.value, URLUnreachableError) == (expected == 502)
    c = make(limiter=RateLimiter(per_ip=1, per_ip_day=1, global_window=1))
    c.resolver = resolver
    for _ in range(8):
        assert response(c)[0] == expected
    assert not c.limiter.hits and c._client.calls == 0
    c.resolver = dns
    assert response(c)[0] == 200
    assert response(c)[0] == 429


def test_benchmark_precedes_other_non_global_answers():
    resolver = Mock(return_value=[(2, 1, 6, '', (ip, 443))
                                  for ip in ('10.0.0.1', '198.18.1.1')])
    with pytest.raises(URLUnreachableError):
        validate_url('https://example.com', resolver)


@pytest.mark.parametrize('url', ['ftp://example.com', 'http://169.254.169.254/',
    'http://127.0.0.1/', 'https://example.com:8080', 'https://example.com/file.pdf'])
def test_invalid_bursts_preserve_all_limits(url):
    c = make(limiter=RateLimiter(per_ip=1, per_ip_day=1, global_window=1))
    for _ in range(8):
        assert response(c, url)[0] == 400
    assert not c.limiter.hits and c._client.calls == 0
    assert response(c)[0] == 200
    assert response(c)[0] == 429


@pytest.mark.parametrize('mode', ['cache', 'cap', 'paused', 'client'])
def test_valid_request_calls_limiter_once_before_downstream(mode):
    c = make()
    events = []
    c.limiter.allow = Mock(side_effect=lambda ip: events.append('limit') or True)
    c.cache.get = Mock(side_effect=lambda url: events.append('cache') or (
        {'status': 'ok'} if mode == 'cache' else None))
    c.cap.ok = Mock(side_effect=lambda: events.append('cap') or mode != 'cap')
    c._client.extract = Mock(side_effect=lambda url: events.append('client') or (
        200, 'hello', {'cost': 0, 'cost_known': True}))
    c.live = mode != 'paused'
    response(c)
    c.limiter.allow.assert_called_once_with('ip')
    assert events == {'cache': ['limit', 'cache'], 'cap': ['limit', 'cache', 'cap'],
                      'paused': ['limit'], 'client': ['limit', 'cache', 'cap', 'client']}[mode]


@pytest.mark.parametrize('entrypoint', ['local', 'vercel'])
def test_limits_endpoint_uses_env_without_work(monkeypatch, entrypoint):
    import app
    monkeypatch.setenv('DEMO_PER_IP_10MIN', '7')
    monkeypatch.setenv('DEMO_PER_IP_DAY', '23')
    monkeypatch.setenv('DEMO_STATE', 'memory')
    c = Converter(client=Mock(), resolver=Mock())
    assert c.limiter.per_ip == 7 and c.limiter.per_ip_day == 23
    c.limiter.allow = Mock(side_effect=AssertionError('limiter called'))
    c.cap.ok = Mock(side_effect=AssertionError('cap called'))
    c.cache.get = Mock(side_effect=AssertionError('cache called'))
    c._memory_refused = True  # Metadata remains available even when state is unavailable.
    if entrypoint == 'local':
        handler = app.make_handler(c)
    else:
        spec = importlib.util.spec_from_file_location('pr_a_convert', ROOT / 'api/convert.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, 'CONVERTER', c)
        handler = module.handler
    h = handler.__new__(handler)
    h.path = '/api/convert?limits=1'
    h.headers = {}
    h.client_address = ('ip', 123)
    h.wfile = io.BytesIO()
    h.send_response = Mock()
    h.send_header = Mock()
    h.end_headers = Mock()
    h.do_GET()
    h.send_response.assert_called_once_with(200)
    assert json.loads(h.wfile.getvalue()) == {'limits': {'per_10min': 7, 'per_day': 23}}
    c.resolver.assert_not_called()
    c._client.extract.assert_not_called()
    c.limiter.allow.assert_not_called()


def test_demo_hides_and_clears_errors_and_restores_success():
    text = (ROOT / 'public/index.html').read_text()
    assert re.search(r'<section id="result">.*?id="title".*?id="copy".*?id="download".*?id="markdown".*?</section>', text, re.S)
    error = re.search(r'function showError\(message\) \{(.*?)\n\}', text, re.S).group(1)
    for statement in ("$('result').hidden = true", "markdown = ''", "$('markdown').textContent = ''", "$('title').textContent = ''"):
        assert statement in error
    assert "if (!r.ok || !['ok', 'empty'].includes(d.status)) {showError(" in text
    assert "else render(d)" in text
    assert re.search(r'catch \(_\) \{showError\(', text)
    assert "$('result').hidden = false" in text
    assert 'if (!submitted) render(sample)' in text
    assert 'submitted = true' in text
    assert 'render(sample,' not in text


def test_demo_fetches_limits_without_hardcoded_numbers():
    text = (ROOT / 'public/index.html').read_text()
    assert '<p id="limits" hidden></p>' in text
    assert "fetch('/api/convert?limits=1')" in text
    assert '${d.limits.per_10min}' in text and '${d.limits.per_day}' in text
    assert ".catch(() => {$('limits').hidden = true;})" in text
    assert '\u2014' not in text and '\u2013' not in text
