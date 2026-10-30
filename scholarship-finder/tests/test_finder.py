import csv
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import scholarship_finder as sf
from fixtures import SEARCH, WEB, EXTRACT

TODAY = dt.date(2026, 10, 30)


def rows(text, url='https://aid.example/award', title='Award'):
    return sf.extract_rows(dict(url=url, title=title, highlights=[text]), 'search', TODAY)


def response(body, headers=None, status=200):
    obj = unittest.mock.MagicMock()
    obj.status = status
    obj.headers = headers or {}
    obj.read.return_value = (body if isinstance(body, str) else json.dumps(body)).encode()
    obj.__enter__.return_value = obj
    return obj


def call(path, body, status=200, params=None):
    return dict(path=path, response_body=body, status=status, params=params or {}, cost_usd=0.001)


class Parsing(unittest.TestCase):
    def test_full_month(self): self.assertEqual(sf.dates('November 13, 2026')[0][0], dt.date(2026, 11, 13))
    def test_short_month(self): self.assertEqual(sf.dates('Nov 13, 2026')[0][0], dt.date(2026, 11, 13))
    def test_no_space_comma(self): self.assertEqual(rows('by noon on November 13,2026')[0]['flags'], ['no publish date'])
    def test_no_space_keyword(self): self.assertNotIn('unclear if deadline', rows('DeadlineFebruary 12, 2027')[0]['flags'])
    def test_february(self): self.assertEqual(rows('due February 12, 2027')[0]['deadline'], '2027-02-12')
    def test_day_first(self): self.assertEqual(rows('due 13 November 2026')[0]['deadline'], '2026-11-13')
    def test_iso(self): self.assertEqual(rows('due 2026-11-13')[0]['deadline'], '2026-11-13')
    def test_us(self): self.assertEqual(rows('due 11/13/2026')[0]['deadline'], '2026-11-13')
    def test_yearless(self): self.assertEqual(sf.dates('due November 13 and 11/13 and 1/5/27'), [])
    def test_academic_year(self): self.assertEqual(sf.dates('2026-27 and 2026-2027'), [])
    def test_invalid(self): self.assertEqual(sf.dates('February 30, 2027'), [])
    def test_past(self): self.assertEqual(rows('deadline October 29, 2026'), [])
    def test_today(self): self.assertEqual(len(rows('due October 30, 2026')), 1)
    def test_far_future(self): self.assertEqual(rows('deadline October 31, 2028'), [])
    def test_two_year_boundary(self): self.assertEqual(len(rows('due October 30, 2028')), 1)
    def test_keyword_distance(self): self.assertIn('unclear if deadline', rows('deadline ' + 'x'*81 + ' November 13, 2026')[0]['flags'])
    def test_date_mentioned(self): self.assertIn('unclear if deadline', rows('Published November 13, 2026')[0]['flags'])
    def test_keywords(self):
        for word in ['deadline', 'due', 'apply by', 'applications close', 'closes', 'by noon on', 'submit by', 'until']:
            with self.subTest(word=word): self.assertNotIn('unclear if deadline', rows(word+' November 13, 2026')[0]['flags'])
    def test_amount(self): self.assertEqual(rows('Up to $10,000 due November 13, 2026')[0]['amount'], 'Up to $10,000')
    def test_decimal_amount(self): self.assertEqual(rows('$2,500.00 due November 13, 2026')[0]['amount'], '$2,500.00')
    def test_distant_amount(self): self.assertEqual(rows('$5,000. '+ 'Details '*40 + 'due November 13, 2026')[0]['amount'], 'not stated')
    def test_name(self): self.assertEqual(rows('The $5,000 Jean Andrews Nursing Scholarship deadline November 13, 2026')[0]['name'], 'Jean Andrews Nursing Scholarship')
    def test_fallback_title(self): self.assertEqual(rows('deadline November 13, 2026')[0]['name'], 'Award')
    def test_domain_aggregator(self): self.assertTrue(sf.is_aggregator('https://www.bold.org/x', ''))
    def test_false_domain(self): self.assertFalse(sf.is_aggregator('https://notbold.org', ''))
    def test_text_aggregator(self): self.assertTrue(sf.is_aggregator('https://aid.example', 'due November 13, 2026; due December 1, 2026; due January 1, 2027'))
    def test_multiple_names(self):
        result = rows('The Alpha Scholarship deadline November 13, 2026. The Beta Scholarship due January 1, 2027.')
        self.assertEqual([r['name'] for r in result], ['Alpha Scholarship', 'Beta Scholarship'])
    def test_old_dates(self): self.assertIn('mixed old dates', rows('Archived November 13, 2024. Deadline November 13, 2026')[0]['flags'])
    def test_publish_date(self):
        result = sf.extract_rows(dict(url='https://aid.example', published_date='2026-01-01', highlights=['due November 13, 2026']), 'search', TODAY)
        self.assertNotIn('no publish date', result[0]['flags'])
    def test_dedupe(self):
        a = rows('due November 13, 2026')[0]
        b = dict(a, url='https://www.aid.example/award/?utm_source=test#x', endpoints=['web'])
        merged = sf.dedupe([a,b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['endpoints'], ['search', 'web'])
    def test_application_windows(self):
        for separator in ('-', '\u2013', 'to', 'through'):
            for start in ('September 8, 2026', 'November 8, 2026'):
                with self.subTest(separator=separator, start=start):
                    result = rows(f'{start} {separator} January 11, 2027')
                    self.assertEqual([r['deadline'] for r in result], ['2027-01-11'])
                    self.assertNotIn('unclear if deadline', result[0]['flags'])
                    self.assertEqual(result[0]['confidence'], 'snippet only')
        self.assertEqual(len(rows('November 8, 2026. January 11, 2027')), 2)
        self.assertEqual(rows('November 8, 2026 to January 11, 2029'), [])

    def test_negated_uab_date(self):
        text = (Path(__file__).parent / 'fixtures' / 'uab.txt').read_text()
        result = rows(text, title='SON Scholarship Applications')
        self.assertEqual(result[0]['deadline'], '')
        self.assertIn('date negated by source', result[0]['flags'])

    def test_negating_context(self):
        for phrase in ('is NOT the deadline', 'is not valid', 'is no longer valid',
                       'does not apply', 'is a placeholder', 'is system-generated'):
            with self.subTest(phrase=phrase):
                result = rows('March 15, 2027 ' + phrase)
                self.assertEqual(result[0]['deadline'], '')
        result = rows('March 15, 2027 is NOT the deadline. Deadline April 1, 2027.')
        self.assertEqual([r['deadline'] for r in result], ['2027-04-01'])

    def test_ui_name_fallback(self):
        for phrase in ('Award Winner Save', 'Save', 'Apply', 'Share', 'Login'):
            result = rows(phrase + ' Scholarship due November 13, 2026', title='Nursing awards')
            self.assertEqual(result[0]['name'], 'Nursing awards')
            self.assertFalse(result[0]['specific_name'])

    def test_extract_negation(self):
        calls = [call('/search', SEARCH), call('/web/extract',
            'February 12, 2027 is NOT the deadline.', params={'url': 'https://aid.example/award'})]
        result = sf.rebuild(calls, TODAY)
        self.assertEqual(result[0]['deadline'], '')
        self.assertIn('date negated by source', result[0]['flags'])

    def test_sort(self): self.assertEqual(sf.dedupe(rows('due February 12, 2027; due November 13, 2026'))[0]['deadline'], '2026-11-13')

    def test_dash_normalization(self):
        self.assertEqual(rows('due November 13, 2026', title='Awards \u2014 Grants \u2013 Aid')[0]['name'], 'Awards - Grants - Aid')
        self.assertEqual(rows('Alpha\u2013Beta Scholarship due November 13, 2026')[0]['name'], 'Alpha-Beta Scholarship')

    def test_cross_page_dedupe(self):
        first = rows('Alpha Scholarship $5,000 due November 13, 2026')[0]
        second = dict(first, url='https://www.aid.example/other', endpoints=['web'])
        third = dict(first, url='https://aid.example/third')
        merged = sf.dedupe([first, second, second, third])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['url'], first['url'])
        self.assertIn('also on 2 more pages', merged[0]['flags'])
        self.assertEqual(merged[0]['endpoints'], ['search', 'web'])
        self.assertIn('also on 1 more page', sf.dedupe([first, second])[0]['flags'])
        for other in [dict(second, amount='$6,000'), dict(second, deadline='2027-01-01'),
                      dict(second, name='Beta Scholarship'), dict(second, url='https://other.example/a')]:
            self.assertEqual(len(sf.dedupe([first, other])), 2)
        fallback = rows('due November 13, 2026', title='Alpha Scholarship')[0]
        self.assertEqual(len(sf.dedupe([fallback, dict(fallback, url=second['url'])])), 2)


class HTTP(unittest.TestCase):
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_body_cost_and_headers(self, http):
        http.return_value = response(SEARCH, {'X-Desearch-Cost-Usd': '99'})
        client = sf.Client('secret')
        client.request('POST', '/search', {'query':'nursing', 'count':10, 'highlights':True})
        self.assertEqual(client.calls[0]['cost_usd'], .012)
        req = http.call_args.args[0]
        self.assertEqual(req.get_header('User-agent'), 'desearch-scholarship-finder/0.1')
        self.assertEqual(req.get_header('Authorization'), 'secret')
        self.assertEqual(json.loads(req.data)['count'], 10)
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_extract_header_cost(self, http):
        http.return_value = response(EXTRACT, {'X-Desearch-Cost-Usd': '.0005', 'X-Desearch-Usage-Count':'1'})
        client = sf.Client('secret')
        self.assertEqual(client.request('GET', '/web/extract', {'url':'https://aid.example','format':'text'}), EXTRACT)
        self.assertEqual(client.calls[0]['cost_usd'], .0005)
        self.assertIn('format=text', http.call_args.args[0].full_url)
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_503_unavailable(self, http):
        for status in (503, 500, 422):
            with self.subTest(status=status):
                http.side_effect = urllib.error.HTTPError('https://api.desearch.ai/web', status,
                    'unavailable', {'X-Desearch-Cost-Usd': '.004'},
                    io.BytesIO(b'{"cost_usd": 0.003}'))
                client = sf.Client('secret')
                with self.assertRaises(sf.SourceError):
                    client.request('GET', '/web', {'query': 'nursing'})
                self.assertEqual(client.calls[0]['cost_usd'], .003)
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_authentication(self, http):
        for status in (401,403):
            http.side_effect = urllib.error.HTTPError('url',status,'secret',{},io.BytesIO(b'secret'))
            with self.assertRaisesRegex(sf.AuthenticationError, '^Authentication failed$'): sf.Client('secret').request('GET','/web',{})
    @patch('scholarship_finder.time.sleep')
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_retry(self, http, sleep):
        for status in (429,500,503):
            http.side_effect = [urllib.error.HTTPError('url',status,'error',{},io.BytesIO(b'{}')), response(SEARCH)]
            client = sf.Client('secret')
            client.request('POST','/search',{})
            self.assertEqual(len(client.calls), 2)
        self.assertEqual(sleep.call_args.args, (2,))
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_redaction(self, http):
        http.return_value = response({'results':[], 'echo':'secret', 'Authorization':'secret'})
        client = sf.Client('secret')
        client.request('POST','/search',{})
        self.assertNotIn('secret', json.dumps(client.calls))
    def test_cost_sum(self): self.assertEqual(sf.cost_line([{'cost_usd':.012}, {'cost_usd':.001}, {'cost_usd':.0005}]), 'calls: 3, cost: $0.01350')
    def test_confidence(self):
        for body, status, expected in [(EXTRACT,200,'confirmed on page'), ('No dates',200,'date not found on page'), ('error',500,'extract failed')]:
            calls = [call('/search',SEARCH), call('/web/extract',body,status,{'url':'https://aid.example/award'})]
            self.assertEqual(sf.rebuild(calls,TODAY)[0]['confidence'],expected)
    def test_snippet_only(self): self.assertEqual(sf.rebuild([call('/search',SEARCH)],TODAY)[0]['confidence'],'snippet only')


class CLI(unittest.TestCase):
    def run_cli(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = sf.main(args)
        return code, out.getvalue(), err.getvalue()
    @patch('scholarship_finder.urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
    def test_dry_run(self, http):
        code, out, err = self.run_cli(['--field','nursing','--level','undergraduate','--year','2027','--dry-run'])
        self.assertEqual(code,0)
        self.assertIn('POST /search',out)
        self.assertIn('cost: $0.00000',err)
        http.assert_not_called()
    @patch('scholarship_finder.urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
    def test_replay(self, http):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)/'saved.json'
            raw.write_text(json.dumps({'query':'test query','requests':[call('/search',SEARCH), call('/web',WEB), call('/web/extract',EXTRACT,params={'url':'https://aid.example/award'})]}))
            dest = Path(directory)/'out'
            code,out,err = self.run_cli(['--from-raw',str(raw),'--out',str(dest),'--today','2026-10-30'])
            self.assertEqual(code,0)
            self.assertIn('confirmed on page',out)
            self.assertIn(sf.DISCLAIMER,(dest/'results.md').read_text())
            self.assertIn('[source]',(dest/'results.md').read_text())
            self.assertIn('https://aid.example/award',(dest/'results.csv').read_text())
            http.assert_not_called()
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_full_mocked_run(self,http):
        http.side_effect = [response(SEARCH),response(WEB),response(EXTRACT,{'X-Desearch-Cost-Usd':'.0005'})]
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory)/'key'
            key.write_text('supersecret')
            code,out,err = self.run_cli(['--field','nursing','--level','undergraduate','--year','2027','--today','2026-10-30','--key-file',str(key),'--out',directory])
            self.assertEqual(code,0)
            self.assertIn('calls: 3, cost: $0.01350',err)
            self.assertNotIn('supersecret',''.join(p.read_text() for p in Path(directory).glob('raw-*.json')))
    @patch('scholarship_finder.time.sleep')
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_source_failure_continues(self,http,sleep):
        http.side_effect = [response({},status=500),response({},status=500),response(WEB)]
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory)/'key'; key.write_text('secret')
            code,out,err = self.run_cli(['--field','nursing','--level','undergraduate','--year','2027','--today','2026-10-30','--key-file',str(key),'--out',directory,'--verify','0'])
            self.assertEqual(code,0)
            self.assertIn('/search unavailable',err)
    @patch('scholarship_finder.time.sleep')
    @patch('scholarship_finder.urllib.request.urlopen')
    def test_503_sources_and_cost(self, http, sleep):
        for all_failed in (True, False):
            with self.subTest(all_failed=all_failed), tempfile.TemporaryDirectory() as directory:
                def failure(body, headers=None):
                    return urllib.error.HTTPError('url', 503, 'unavailable', headers or {},
                                                  io.BytesIO(json.dumps(body).encode()))
                http.side_effect = ([failure({'cost_usd': .002}), failure({'cost_usd': .003})]
                                    if all_failed else [response(SEARCH)]) + [failure({}, {'X-Desearch-Cost-Usd': '.004'})]
                key = Path(directory) / 'key'
                key.write_text('secret')
                code, out, err = self.run_cli(['--field', 'nursing', '--level', 'undergraduate',
                    '--year', '2027', '--today', '2026-10-30', '--key-file', str(key),
                    '--out', directory, '--verify', '0'])
                self.assertEqual(code, 2 if all_failed else 0)
                self.assertIn('/web unavailable', err)
                self.assertIn('cost: $0.00900' if all_failed else 'cost: $0.01600', err)
                record = json.loads(next(Path(directory).glob('raw-*.json')).read_text())
                self.assertEqual(record['requests'][-1]['cost_usd'], .004)
                if all_failed:
                    self.assertIn('All sources failed: /search, /web', err)
                    self.assertNotIn('No open dated candidates', out)

    @patch('scholarship_finder.urllib.request.urlopen')
    def test_js_retry_and_no_js(self, http):
        for no_js, retry_body in [(False, EXTRACT), (True, None), (False, None)]:
            with self.subTest(no_js=no_js, retry_body=retry_body), tempfile.TemporaryDirectory() as directory:
                error = {'error_code': 'js_required', 'detail': 'Retry with js=true. secret'}
                http.side_effect = [response(SEARCH), response(error, status=422)]
                if not no_js:
                    http.side_effect = [response(SEARCH), response(error, status=422),
                                        response(retry_body if retry_body else error, status=200 if retry_body else 422)]
                key = Path(directory)/'key'
                key.write_text('secret')
                args = ['--field', 'nursing', '--level', 'undergraduate', '--year', '2027',
                        '--today', '2026-10-30', '--key-file', str(key), '--out', directory, '--no-web']
                if no_js: args.append('--no-js')
                code, out, err = self.run_cli(args)
                self.assertEqual(code, 0)
                self.assertIn('js_required', err)
                self.assertIn('Retry with js=true.', err)
                self.assertNotIn('secret', err)
                record = json.loads(next(Path(directory).glob('raw-*.json')).read_text())
                extracts = [c for c in record['requests'] if c['path'] == '/web/extract']
                self.assertEqual(len(extracts), 1 if no_js else 2)
                self.assertNotIn('js', extracts[0]['params'])
                self.assertNotIn('wait', extracts[0]['params'])
                self.assertEqual(http.call_args_list[1].kwargs['timeout'], 30)
                if not no_js:
                    self.assertEqual(extracts[1]['params']['js'], 'true')
                    self.assertEqual(extracts[1]['params']['wait'], 3000)
                    self.assertGreaterEqual(http.call_args.kwargs['timeout'], 45)
                    self.assertIn('wait=3000', http.call_args.args[0].full_url)
                    self.assertIn('js=true', http.call_args.args[0].full_url)
                expected = 'confirmed on page (js)' if retry_body else 'extract failed'
                self.assertIn(expected, out)
                self.assertEqual(sf.rebuild(record['requests'], TODAY)[0]['confidence'], expected)

    @patch('scholarship_finder.urllib.request.urlopen')
    def test_evidence_url_and_window(self, http):
        fixtures = Path(__file__).parent / 'fixtures'
        sources = json.loads((fixtures / 'sources.json').read_text())
        url = 'https://www.fnsna.org/2027-undergraduate-scholarship-application'
        probe = (fixtures / 'extract.txt').read_text()
        http.side_effect = [response(c['response_body']) for c in sources] + [response(probe)] * 20
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'key'
            key.write_text('secret')
            code, out, err = self.run_cli(['--field', 'nursing', '--level', 'undergraduate',
                '--year', '2027', '--today', '2026-10-30', '--key-file', str(key),
                '--out', directory, '--verify', '20', '--limit', '0'])
            self.assertEqual(code, 0)
            saved = json.loads(next(Path(directory).glob('raw-*.json')).read_text())
            extracts = [c for c in saved['requests'] if c['path'] == '/web/extract']
            self.assertIn(url, [c['params']['url'] for c in extracts])
            data = list(csv.DictReader(io.StringIO((Path(directory) / 'results.csv').read_text())))
            award = [r for r in data if 'fnsna.org' in r['url'] and r['deadline'] == '2027-01-11']
            self.assertTrue(award)
            self.assertTrue(all(r['url'] == url for r in award))
            self.assertTrue(all('unclear if deadline' not in r['flags'] for r in award))
            self.assertIn(url, out)
            self.assertIn('[source](<' + url + '>)', (Path(directory) / 'results.md').read_text())
        for ordered in (sources, list(reversed(sources))):
            rebuilt = sf.rebuild(ordered, dt.date(2026, 9, 1))
            self.assertFalse(any(r['deadline'] == '2026-09-08' and 'fnsna.org' in r['url']
                                 for r in rebuilt if 'unclear if deadline' not in r['flags']))
            self.assertTrue(all(r['url'] == url for r in rebuilt if 'fnsna.org' in r['url']))

    @patch('scholarship_finder.urllib.request.urlopen')
    def test_verify_unique_urls_and_aggregator_preference(self, http):
        results = []
        for url, text in [
            ('https://scholarshipsclosingsoon.com/a', 'due November 1, 2026'),
            ('https://scholarships360.org/a', 'due November 2, 2026'),
            ('https://usascholarships.net/a', 'due November 3, 2026'),
            ('https://list.example/a', 'due November 4, 2026; due November 5, 2026; due November 6, 2026'),
            ('https://aid.example/a', 'due December 1, 2026; due January 1, 2027'),
            ('https://www.aid.example/a/?utm_source=test#x', 'due February 1, 2027'),
        ]:
            results.append(dict(url=url, title='Award', highlights=[text]))
        http.side_effect = [response({'results': results})] + [response('No dates')] * 5
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory)/'key'
            key.write_text('secret')
            code, out, err = self.run_cli(['--field', 'nursing', '--level', 'undergraduate', '--year', '2027',
                '--today', '2026-10-30', '--key-file', str(key), '--out', directory, '--no-web', '--verify', '20'])
            self.assertEqual(code, 0)
            record = json.loads(next(Path(directory).glob('raw-*.json')).read_text())
            urls = [c['params']['url'] for c in record['requests'] if c['path'] == '/web/extract']
            self.assertEqual(urls[0], 'https://aid.example/a')
            self.assertEqual(len(urls), 5)
            self.assertEqual(len({sf.normalized_url(u) for u in urls}), 5)

    def test_aggregator_snippet_and_extracted_text(self):
        text = 'due November 1, 2026; due December 1, 2026; due January 1, 2027'
        self.assertTrue(sf.extract_rows(dict(url='https://list.example', snippet=text), 'web', TODAY)[0]['aggregator'])
        calls = [call('/search', SEARCH), call('/web/extract', text, params={'url': 'https://aid.example/award'})]
        self.assertTrue(sf.rebuild(calls, TODAY)[0]['aggregator'])
        for domain in ('scholarshipsclosingsoon.com', 'scholarships360.org', 'usascholarships.net'):
            self.assertTrue(sf.is_aggregator('https://www.' + domain + '/a', ''))
            self.assertFalse(sf.is_aggregator('https://not' + domain + '/a', ''))

    def test_plain_table_alignment(self):
        data = rows('due November 13, 2026', url='https://aid.example/short')
        data += rows('due December 1, 2026', url='https://aid.example/much-longer-url')
        data[0]['endpoints'] = ['search', 'web']
        data[1]['flags'] = []
        lines = sf.table(data).splitlines()
        for label, values in [('Name', ['Award', 'Award']), ('Amount', ['not stated', 'not stated']),
                              ('Deadline', ['2026-11-13', '2026-12-01']),
                              ('Confidence', ['snippet only', 'snippet only']),
                              ('Endpoint', ['search, web', 'search']),
                              ('Source URL', [r['url'] for r in data])]:
            for line, value in zip(lines[1:], values):
                self.assertEqual(line.index(value), lines[0].index(label))
        self.assertEqual(lines[1].index('no publish date'), lines[0].index('Flags'))
        self.assertTrue(lines[0].endswith('Source URL'))


    @patch('scholarship_finder.urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
    def test_display_options_and_raw_names(self, http):
        items = [dict(url=f'https://aid.example/{i}', title=f'Award {i:02d} \u2014 Grants \u2013 Aid',
                      highlights=[('Published ' if i == 0 else 'due ') + 'November 13, 2026'])
                 for i in reversed(range(20))]
        record = {'query': 'test', 'requests': [call('/search', {'results': items})]}
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / 'input.json'
            raw.write_text(json.dumps(record))
            dest = Path(directory) / 'out'
            base = ['--from-raw', str(raw), '--out', str(dest), '--today', '2026-10-30']
            for options, count, total in [([], 15, 20), (['--limit', '2'], 2, 20),
                                          (['--limit', '0'], 20, 20),
                                          (['--hide-unclear', '--limit', '2'], 2, 19)]:
                code, out, err = self.run_cli(base + options)
                self.assertEqual(code, 0)
                md = (dest / 'results.md').read_text()
                csv_text = (dest / 'results.csv').read_text()
                self.assertIn(f'showing {count} of {total} rows', out)
                self.assertIn(f'showing {count} of {total} rows', md)
                self.assertEqual(len(list(csv.DictReader(io.StringIO(csv_text)))), total)
                self.assertEqual(len([line for line in md.splitlines() if line.startswith('| Award')]), count)
                self.assertIn('Award 01 - Grants - Aid' if options and '--hide-unclear' in options else 'Award 00 - Grants - Aid', out)
                for text in (out, md, csv_text):
                    self.assertNotIn('\u2014', text)
                    self.assertNotIn('\u2013', text)
                saved = json.loads(next(dest.glob('raw-*.json')).read_text())
                self.assertEqual(saved['requests'], record['requests'])
            http.assert_not_called()

    def test_negative_limit(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sf.main(['--limit', '-1'])

    def test_count_validation(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): sf.parser().parse_args(['--count','11'])


if __name__ == '__main__': unittest.main()
