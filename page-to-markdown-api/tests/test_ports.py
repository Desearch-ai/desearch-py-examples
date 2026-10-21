import json
import socket
from unittest.mock import Mock

import pytest
from pagemd.service import Converter
from pagemd.guards import RateLimiter
from pagemd.urlguard import validate_url, URLValidationError


PORT_MESSAGE = 'Only standard web ports are allowed (http on 80, https on 443).'


@pytest.mark.parametrize('url,expected,port', [
    ('http://example.com/a', 'http://example.com/a', 80),
    ('https://example.com/a', 'https://example.com/a', 443),
    ('http://example.com:80/a', 'http://example.com/a', 80),
    ('https://example.com:443/a', 'https://example.com/a', 443),
    ('HTTPS://Example.COM:443/a?q=1#x', 'https://example.com/a?q=1', 443),
])
def test_allowed_ports_are_normalized(url, expected, port):
    resolver = Mock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
    ])
    assert validate_url(url, resolver) == expected
    resolver.assert_called_once_with('example.com', port, type=socket.SOCK_STREAM)


@pytest.mark.parametrize('scheme', ['http', 'https'])
@pytest.mark.parametrize('port', ['8080', '22', '8443', '0', '-1', '65536', '999999', 'bad', '80.0', ''])
def test_nonstandard_or_malformed_ports_rejected_before_dns(scheme, port):
    assert_port_rejected(f'{scheme}://example.com:{port}/a')


@pytest.mark.parametrize('url', ['http://example.com:443/a', 'https://example.com:80/a'])
def test_swapped_default_ports_rejected_before_dns(url):
    assert_port_rejected(url)


def assert_port_rejected(url):
    resolver = Mock(side_effect=AssertionError('Resolver must not be called'))
    with pytest.raises(URLValidationError) as exc:
        validate_url(url, resolver)
    assert str(exc.value) == PORT_MESSAGE
    resolver.assert_not_called()


def test_converter_returns_invalid_with_saved_sample_without_client_call():
    client = Mock()
    resolver = Mock(side_effect=AssertionError('Resolver must not be called'))
    converter = Converter(client=client, resolver=resolver, live=True, limiter=RateLimiter())
    status, headers, text = converter.handle({'url': 'https://example.com:8080/a'}, 'ip')
    body = json.loads(text)
    assert status == 400 and body['status'] == 'invalid'
    assert body['message'] == body['error'] == PORT_MESSAGE
    assert body['markdown'] == converter.sample['markdown']
    assert body['sample'] == '/sample.json'
    assert headers['Cache-Control'] == 'no-store'
    resolver.assert_not_called()
    client.extract.assert_not_called()
