"""Deterministic, offline coverage for demo extraction failures."""
import json
import socket
import urllib.error

from pagemd.client import Client

import pytest

from pagemd.guards import DailyCap, RateLimiter, TTLCache
from pagemd.service import Converter, FAST_404_SECONDS


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeClient:
    def __init__(self, clock, status, body, elapsed, failure=None, known=True):
        self.clock, self.status, self.body = clock, status, body
        self.elapsed, self.failure, self.known = elapsed, failure, known
        self.calls = 0

    def extract(self, url):
        self.calls += 1
        self.clock.now += self.elapsed
        if self.failure:
            raise self.failure
        return self.status, self.body, {'cost': .002, 'cost_known': self.known}


def dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]


def make(status=200, body=None, elapsed=0, failure=None, known=True):
    clock = FakeClock()
    client = FakeClient(clock, status, body, elapsed, failure, known)
    service = Converter(client=client, resolver=dns, live=True, clock=clock,
                        limiter=RateLimiter(), cap=DailyCap(), cache=TTLCache())
    service.fallback_cost = .0005
    return service, client


def response(service):
    code, _, raw = service.handle({'url': 'https://example.com/page'}, 'test')
    return code, json.loads(raw)


@pytest.mark.parametrize('upstream,elapsed,payload,failure,known,code,status,message,cost', [
    (404, 2.999, {}, None, True, 404, 'not_found',
     'Page not found. Check the link and try again.', 0),
    (404, FAST_404_SECONDS, {}, None, True, 504, 'timed_out',
     'Timed out fetching this page. Try again or use another link.', 0),
    (599, 0, {}, None, False, 504, 'timed_out',
     'Timed out fetching this page. Try again or use another link.', .0005),
    (200, 4, {}, TimeoutError(), True, 504, 'timed_out',
     'Timed out fetching this page. Try again or use another link.', .0005),
    (200, 0, {}, OSError('connection failed'), True, 502, 'unreachable',
     "Couldn't reach this site. Check the link and try again.", 0),
    (504, 0, {}, None, True, 504, 'timed_out',
     'Timed out fetching this page. Try again or use another link.', .002),
    (408, 0, {}, None, True, 504, 'timed_out',
     'Timed out fetching this page. Try again or use another link.', .002),
    (500, 0, {'error': {'detail': 'Access denied by site'}}, None, True, 502, 'blocked',
     'The site blocked us from reading this page. Try another link.', .002),
    (404, 0, {'data': {'message': 'Site blocked access with CAPTCHA'}}, None, True, 502, 'blocked',
     'The site blocked us from reading this page. Try another link.', 0),
    (404, 4, {'error': 'robots restriction'}, None, True, 502, 'blocked',
     'The site blocked us from reading this page. Try another link.', 0),
])
def test_errors(upstream, elapsed, payload, failure, known, code, status, message, cost):
    service, client = make(upstream, payload, elapsed, failure, known)
    actual_code, body = response(service)
    assert (actual_code, body['status'], body['message']) == (code, status, message)
    assert body['error'] == message
    assert body['cost_usd_this_request'] == 0
    assert service.cap.spent == cost
    assert client.calls == 1
    assert not service.cache.d
    # A second request must make a new Extract call.
    response(service)
    assert client.calls == 2
    assert service.cap.spent == pytest.approx(cost * 2)


@pytest.mark.parametrize('payload', [
    {'html': ''}, {'data': {'html': '<html><body></body></html>'}},
    {'html': '<html><head><script>window.__INITIAL_STATE__ = {"site":"x.com"};</script></head><body><div id="react-root"></div></body></html>'},
    None, {}, [], 42, {'content': None}, {'data': None},
    {'html': '<p>Just a few words</p>'},
])
def test_empty(payload):
    service, client = make(body=payload)
    code, body = response(service)
    assert code == 200
    assert body['status'] == 'empty'
    assert body['message'] == 'This page looks empty (JavaScript-heavy). Try another link.'
    assert body['words'] < 20
    assert body['cost_usd_this_request'] == .002
    assert service.cap.spent == .002
    assert client.calls == 1


@pytest.mark.parametrize('payload', [
    '<html>blocked captcha robots</html>',
    {'html': 'blocked captcha robots'},
    {'data': {'content': 'access denied'}},
    {'detail': 'The page could not be fetched'},
])
def test_page_content_is_not_api_block_report(payload):
    service, client = make(500, payload)
    code, body = response(service)
    assert code == 502 and body['status'] == 'error'
    assert client.calls == 1


@pytest.mark.parametrize('status', [401, 402, 403])
def test_paused_precedes_block_report(status):
    service, client = make(status, {'error': 'blocked'})
    code, body = response(service)
    assert code == 503 and body['status'] == 'paused'
    assert service.cap.spent == body['cost_usd_this_request'] == 0
    assert client.calls == 1


def test_error_cost_exhausts_cap_before_next_extract():
    service, client = make(504, {})
    service.cap.cap = .002
    assert response(service)[0] == 504
    assert service.cap.spent == .002
    code, body = response(service)
    assert code == 503 and body['status'] == 'paused'
    assert body['cost_usd_this_request'] == 0
    assert client.calls == 1


CONNECTION_FAILURES = [
    socket.gaierror('name or service not known'),
    ConnectionRefusedError('connection refused'),
    ConnectionResetError('connection reset'),
    OSError('connection failed'),
    urllib.error.URLError(socket.gaierror('getaddrinfo failed')),
    urllib.error.URLError(ConnectionRefusedError()),
    urllib.error.URLError('connection failed'),
]
TIMEOUTS = [TimeoutError(), socket.timeout(), urllib.error.URLError(TimeoutError())]


@pytest.mark.parametrize('failure,status',
                         [(e, 598) for e in CONNECTION_FAILURES] + [(e, 599) for e in TIMEOUTS])
def test_client_connection_failures(failure, status):
    calls = []

    def opener(req, timeout):
        calls.append((req, timeout))
        raise failure

    assert Client('offline-test-key', opener=opener).extract('https://example.com') == (
        status, '', {'cost': 0, 'cost_known': False})
    assert len(calls) == 1


@pytest.mark.parametrize('failure', CONNECTION_FAILURES + TIMEOUTS)
def test_service_connection_failures(failure):
    service, client = make(failure=failure)
    code, body = response(service)
    timeout = failure in TIMEOUTS
    assert (code, body['status']) == ((504, 'timed_out') if timeout else (502, 'unreachable'))
    assert service.cap.spent == (.0005 if timeout else 0)
    assert body['cost_usd_this_request'] == 0
    assert client.calls == 1


@pytest.mark.parametrize('message', [
    'Name or service not known', 'nodename nor servname provided', 'getaddrinfo failed',
    'ENOTFOUND', 'ERR_NAME_NOT_RESOLVED', 'DNS failure', 'Could not resolve host',
    'Connection refused', 'ECONNREFUSED', 'ERR_CONNECTION_REFUSED',
    'Failed to establish a new connection',
])
@pytest.mark.parametrize('as_dict', [False, True])
def test_api_unreachable_body(message, as_dict):
    payload = {'error': {'details': [message]}} if as_dict else message
    service, client = make(504, payload, known=True)
    code, body = response(service)
    assert (code, body['status'], body['message']) == (
        502, 'unreachable', "Couldn't reach this site. Check the link and try again.")
    assert body['error'] == body['message']
    assert service.cap.spent == body['cost_usd_this_request'] == 0
    assert not service.cache.d
    assert client.calls == 1


def test_status_598_is_unreachable():
    service, client = make(598, {}, known=True)
    code, body = response(service)
    assert (code, body['status']) == (502, 'unreachable')
    assert service.cap.spent == body['cost_usd_this_request'] == 0
    assert client.calls == 1


def test_blocked_precedes_unreachable():
    service, client = make(598, {'error': 'blocked, DNS failure'})
    code, body = response(service)
    assert (code, body['status']) == (502, 'blocked')
    assert client.calls == 1


@pytest.mark.parametrize('addresses', [None, [], [
    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443)),
]])
def test_validation_dns_failure_and_private_addresses(addresses):
    service, client = make()

    def resolver(*args, **kwargs):
        if addresses is None:
            raise socket.gaierror('name or service not known')
        return addresses

    service.resolver = resolver
    code, body = response(service)
    if addresses:
        assert (code, body['status']) == (400, 'invalid')
    else:
        assert (code, body['status'], body['message']) == (
            502, 'unreachable', "Couldn't reach this site. Check the link and try again.")
    assert service.cap.spent == body['cost_usd_this_request'] == 0
    assert client.calls == 0


def test_successful_content_is_not_unreachable():
    service, client = make(200, {'html': '<p>DNS connection refused</p>'})
    code, body = response(service)
    assert code == 200
    assert body['status'] == 'empty'
    assert client.calls == 1
