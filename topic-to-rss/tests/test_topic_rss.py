from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import topic_rss as app

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/search_response.json').read_text())


class Tests(unittest.TestCase):
    def response(self, *args, **kwargs):
        return io.BytesIO(json.dumps(FIXTURE).encode())

    def test_request(self):
        expected = dict(query='bittensor', mode='balanced', count=20, start_date='2026-10-16', end_date='2026-10-23', highlights=True)
        self.assertEqual(app.build_request_body('bittensor', 7, 20, date(2026, 10, 23)), expected)
        with patch('urllib.request.urlopen', side_effect=self.response) as opening:
            results, meta = app.fetch_results('bittensor', 'secret', today=date(2026, 10, 23), no_cache=True)
        request = opening.call_args.args[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers['authorization'], 'secret')
        self.assertEqual(headers['user-agent'], 'desearch-topic-to-rss/0.1')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.full_url, app.API_URL)
        self.assertEqual(json.loads(request.data), expected)
        self.assertEqual(results, FIXTURE['results'])
        self.assertEqual(meta['cost_usd'], .01)
        self.assertGreaterEqual(meta['latency_s'], 0)
        for count in (10, 15):
            self.assertEqual(app.build_request_body('x', count=count)['count'], count)
        with self.assertRaises(ValueError):
            app.build_request_body('x', count=12)

    def test_normalize(self):
        def row(url, title, published):
            return dict(url=url, title=title, published_date=published)
        rows = [row('https://EXAMPLE.com/a/?utm_source=x&keep=1#f', 'Story | Site', '2026-10-20'),
                row('https://example.com/a?keep=1', 'Other', '2026-10-22'),
                row('https://other.test/copy', 'STORY - Site', '2026-10-23'),
                row('https://example.com/new', 'New', '2026-10-21'),
                row('https://example.com/no', 'No', None),
                row('https://example.com/bad', 'Bad', '2026-02-30')]
        items = app.normalize(rows)
        self.assertEqual([x['title'] for x in items], ['New', 'Story | Site'])
        self.assertEqual(items[1]['url'], 'https://example.com/a?keep=1')
        self.assertEqual(len(app.normalize(FIXTURE['results'])), 6)

    def test_unwrap_translate_query(self):
        for host in ('translate.google.com', 'www.translate.google.org', 'translate.google.co.uk'):
            for path in ('/translate', '/website'):
                with self.subTest(host=host, path=path):
                    self.assertEqual(app.unwrap_translate_url(
                        f'https://{host}{path}?hl=en&u=https://example.org/a'),
                        'https://example.org/a')
        for query in ('', '?u=', '?u=relative', '?u=ftp://example.org/a'):
            with self.subTest(query=query):
                self.assertIsNone(app.unwrap_translate_url(
                    'https://translate.google.com/translate' + query))

    def test_unwrap_translate_host(self):
        self.assertEqual(app.unwrap_translate_url(
            'https://my--site-example-org.translate.goog/a?keep=1&_x_tr_sl=auto&empty=&_x_tr_tl=en&keep=2#part'),
            'https://my-site.example.org/a?keep=1&empty=&keep=2')
        self.assertEqual(app.unwrap_translate_url(
            'https://www-example-org.translate.goog/a'), 'https://www.example.org/a')
        self.assertIsNone(app.unwrap_translate_url('https://example.translate.goog/a'))

    def test_normalize_drops_missing_translate_target(self):
        self.assertEqual(app.normalize([dict(
            url='https://translate.google.com/translate?hl=en',
            title='A page', published_date='2026-10-23')]), [])

    def test_normalize_deduplicates_translate_copy(self):
        for translated in ('https://translate.google.com/translate?u=https://example.org/a/',
                           'https://example-org.translate.goog/a/?_x_tr_sl=auto'):
            with self.subTest(translated=translated):
                items = app.normalize([
                    dict(url=translated, title='First page', published_date='2026-10-20'),
                    dict(url='https://example.org/a', title='Second page', published_date='2026-10-23')])
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]['url'], 'https://example.org/a')
                self.assertEqual(items[0]['title'], 'First page')

    def test_unwrap_normal_url(self):
        url = 'https://example.com/a/?keep=1#part'
        self.assertEqual(app.unwrap_translate_url(url), url)

    def test_rss(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        root = ET.fromstring(app.build_rss('bittensor', app.normalize(FIXTURE['results']), now, self_url='https://example.com/feed'))
        self.assertEqual(root.attrib['version'], '2.0')
        self.assertEqual(root.findtext('channel/title'), 'Desearch: bittensor')
        self.assertEqual(root.findtext('channel/link'), 'https://desearch.ai')
        self.assertEqual(parsedate_to_datetime(root.findtext('channel/lastBuildDate')), now)
        items = root.findall('channel/item')
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0].findtext('pubDate'), 'Thu, 22 Oct 2026 00:00:00 +0000')
        for item in items:
            self.assertIsNotNone(parsedate_to_datetime(item.findtext('pubDate')).tzinfo)
            self.assertEqual(item.find('guid').attrib['isPermaLink'], 'true')
        self.assertIsNotNone(root.find('channel/{http://www.w3.org/2005/Atom}link'))

    def test_escaping(self):
        text = 'A & <B>\x00\x01\x0b\ud800\ufffe'
        item = dict(title=text, url='https://example.com/?a=1&b=2', published_date='2026-10-23', highlights=[text + 'x' * 600])
        xml = app.build_rss(text, [item])
        root = ET.fromstring(xml)
        self.assertIn('&amp;', xml)
        self.assertIn('&lt;B&gt;', xml)
        self.assertEqual(root.findtext('channel/item/title'), 'A & <B>')
        self.assertEqual(len(root.findtext('channel/item/description')), 500)
        self.assertEqual(root.findtext('channel/item/link'), item['url'])

    def test_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=self.response) as opening:
            kwargs = dict(cache_dir=directory, today=date(2026, 10, 23))
            first, _ = app.fetch_results('x', 'secret', **kwargs)
            second, meta = app.fetch_results('x', 'secret', **kwargs)
            self.assertEqual(first, second)
            self.assertEqual(opening.call_count, 1)
            self.assertTrue(meta['cache_hit'])
            self.assertEqual(meta['cost_usd'], 0)
            path = next(Path(directory).glob('*.json'))
            cached = json.loads(path.read_text())
            cached['saved_at'] -= app.CACHE_TTL + 1
            path.write_text(json.dumps(cached))
            app.fetch_results('x', 'secret', **kwargs)
            app.fetch_results('x', 'secret', no_cache=True, **kwargs)
            self.assertEqual(opening.call_count, 3)

    def test_errors(self):
        with patch('urllib.request.urlopen') as opening:
            with self.assertRaisesRegex(ValueError, 'DESEARCH_API_KEY'):
                app.fetch_results('x', None)
            opening.assert_not_called()
        error = urllib.error.HTTPError(app.API_URL, 403, 'Forbidden', {}, None)
        with patch('urllib.request.urlopen', side_effect=error) as opening:
            with self.assertRaisesRegex(RuntimeError, 'HTTP error 403') as caught:
                app.fetch_results('x', 'private-key', no_cache=True)
            self.assertNotIn('private-key', str(caught.exception))
            self.assertEqual(opening.call_count, 1)

    def test_server(self):
        class Connection:
            def __init__(self, path):
                self.request = io.BytesIO(f'GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n'.encode())
                self.output = bytearray()

            def makefile(self, *args, **kwargs):
                return self.request

            def sendall(self, data):
                self.output.extend(data)

        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'DESEARCH_API_KEY': 'secret'}):
            handler = app.make_handler(cache_dir=directory)
            for path in ('/feed', '/feed?topic=', '/feed?topic=%20', '/feed?topic=' + 'x' * 201):
                connection = Connection(path)
                handler(connection, ('127.0.0.1', 12345), object())
                self.assertTrue(bytes(connection.output).startswith(b'HTTP/1.0 400'))
            with patch('urllib.request.urlopen', side_effect=self.response) as opening:
                connection = Connection('/feed?topic=bittensor')
                handler(connection, ('127.0.0.1', 12345), object())
                headers, body = bytes(connection.output).split(b'\r\n\r\n', 1)
                self.assertTrue(headers.startswith(b'HTTP/1.0 200'))
                self.assertIn(b'Content-Type: application/rss+xml', headers)
                self.assertEqual(len(ET.fromstring(body).findall('channel/item')), 6)
                self.assertEqual(opening.call_count, 1)


if __name__ == '__main__':
    unittest.main()
