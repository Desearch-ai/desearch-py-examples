import csv
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import username_checker as app

METADATA = {'cost_usd': 0.0, 'usage_count': 1, 'service': 'synthetic', 'currency': 'USD'}
PROFILE = dict(METADATA, id='123', username='candidate', fullName='Synthetic Person',
               biography='Synthetic bio', avatar='https://example.test/avatar.jpg', verified=True,
               private=True, followers=17, following=4, postsCount=3, externalUrl='https://example.test')
FACEBOOK = dict(METADATA, id='456', name='Synthetic Page', url='https://www.facebook.com/NaSa',
                avatar='https://example.test/avatar.jpg', category='Science', followers=23, likes=19)
X_PROFILE = dict(METADATA, user={'name': 'Synthetic User', 'username': 'candidate',
                               'followers_count': 31, 'verified': False},
                 tweets=[{'id': '1'}, {'id': '2'}], next_cursor=None)
ERROR = dict(METADATA, detail='Resource not found')

class CheckerTests(unittest.TestCase):
    def check(self, responses, network='instagram'):
        http = Mock(side_effect=responses)
        sleep = Mock()
        call, result = app.check('candidate', network, 'secret-token', 60, http, sleep)
        return call, result, http, sleep

    def test_normalization(self):
        for text in (' @candidate ', 'https://www.instagram.com/candidate/', 'https://tiktok.com/@candidate', 'https://x.com/candidate', 'https://facebook.com/candidate?x=1'):
            self.assertEqual(app.normalize(text), 'candidate')

    def test_rules(self):
        cases = {'instagram': (['a', 'a_b.c', 'a'*30], ['.a', 'a.', 'a..b', 'a'*31, 'a-b']),
                 'tiktok': (['ab', 'a.b', 'a'*24], ['a', 'ab.', 'a'*25, 'a-b']),
                 'x': (['a', 'a_b', 'a'*15], ['a.b', 'a'*16, 'a-b']),
                 'facebook': (['a', 'nasa', 'nike', 'AB.CD', '12345', 'a'*50, '1'*51], ['', 'a'*51, 'abc_d', 'abc-d'])}
        for network, (good, bad) in cases.items():
            for handle in good:
                self.assertTrue(app.RULES[network](handle), (network, handle))
            for handle in bad:
                self.assertFalse(app.RULES[network](handle), (network, handle))
        http = Mock()
        self.assertEqual(app.check('a-b', 'x', 'secret', 1, http)[1]['status'], 'invalid')
        http.assert_not_called()

    def test_statuses(self):
        for code, status in ((200, 'found'), (404, 'not_found'), (422, 'invalid'), (429, 'could_not_check'), (500, 'could_not_check')):
            with self.subTest(code=code):
                call, result, http, _ = self.check([(code, {}, PROFILE)])
                self.assertEqual(result['status'], status)
                self.assertEqual(http.call_count, 1)
        for error in (TimeoutError('timeout'), OSError('connection failed')):
            self.assertEqual(self.check([error])[1]['status'], 'could_not_check')
        for code in (401, 403):
            with self.assertRaises(app.AuthError):
                self.check([(code, {}, {})])

    def test_retry(self):
        for final, status in ((200, 'found'), (503, 'could_not_check')):
            call, result, http, sleep = self.check([(503, {}, {}), (final, {}, PROFILE)], 'tiktok')
            self.assertEqual(result['status'], status)
            self.assertEqual(call['attempts'], 2)
            self.assertEqual(len(call['responses']), 2)
            sleep.assert_called_once_with(2)
            if final == 503:
                self.assertIn('cannot tell from an outage', result['note'])

    def test_request_headers_on_every_attempt(self):
        for network in app.NETWORKS:
            with self.subTest(network=network):
                _, _, http, _ = self.check([(503, {}, {}), (200, {}, X_PROFILE if network == 'x' else PROFILE)], network)
                self.assertEqual(http.call_count, 2)
                for request in http.call_args_list:
                    self.assertEqual(request.args[1], {
                        'Authorization': 'secret-token',
                        'User-Agent': 'desearch-username-checker/1.0',
                        'Accept': 'application/json',
                    })

    def test_auth_error_detail_is_redacted(self):
        for code in (401, 403):
            with self.subTest(code=code):
                http = Mock(return_value=(code, {}, json.dumps({'detail': 'Rejected secret-token'})))
                with self.assertRaises(app.AuthError) as raised:
                    app.check('candidate', 'instagram', 'secret-token', 60, http, Mock())
                self.assertIn(f'HTTP {code}', str(raised.exception))
                self.assertIn('Rejected [REDACTED]', str(raised.exception))
                self.assertNotIn('secret-token', str(raised.exception))
                http.assert_called_once()

    def test_nested_profiles(self):
        fixtures = [PROFILE, {'data': {'profile': PROFILE}}, {'user': PROFILE}, {'data': [{'user': PROFILE}]},
                    {'profile': {'id': '123', 'nickname': 'Synthetic', 'stats': {'followerCount': 8}}},
                    {'data': {'user': {'id': 123, 'name': 'Synthetic', 'edge_followed_by': {'count': 9}}}}]
        for fixture in fixtures:
            result = self.check([(200, {}, fixture)])[1]
            self.assertEqual(result['status'], 'found')
            self.assertNotEqual(result['followers'], '')
        for body in ({}, {'message': 'ok'}, {'data': None}, 'invalid JSON', []):
            result = self.check([(200, {}, body)], 'x')[1]
            self.assertEqual(result['status'], 'could_not_check')
            self.assertEqual(result['note'], 'empty response' if body == [] else 'unrecognized response')

    def test_x_endpoint(self):
        call, _, http, _ = self.check([(200, {}, X_PROFILE)], 'x')
        self.assertTrue(call['url'].endswith('?username=candidate'))
        self.assertNotIn('count=', call['url'])

    def test_observed_profiles(self):
        result = self.check([(200, {}, PROFILE)])[1]
        self.assertEqual(result['display_name'], 'Synthetic Person')
        self.assertEqual(result['followers'], 17)
        self.assertIs(result['verified'], True)
        self.assertIs(result['private'], True)
        self.assertEqual(result['note'], 'private account')
        public = self.check([(200, {}, dict(PROFILE, private=False, verified=False))])[1]
        self.assertIs(public['private'], False)
        self.assertIs(public['verified'], False)
        self.assertEqual(public['note'], '')
        facebook = self.check([(200, {}, FACEBOOK)], 'facebook')[1]
        self.assertEqual(facebook['display_name'], 'Synthetic Page')
        self.assertEqual(facebook['profile_url'], FACEBOOK['url'])
        self.assertEqual(facebook['note'], 'Science')
        fallback = self.check([(200, {}, dict(FACEBOOK, url=''))], 'facebook')[1]
        self.assertEqual(fallback['profile_url'], 'https://www.facebook.com/candidate')
        x = self.check([(200, {}, X_PROFILE)], 'x')[1]
        self.assertEqual(x['display_name'], 'Synthetic User')
        self.assertEqual(x['followers'], 31)
        self.assertIs(x['verified'], False)
        self.assertEqual(x['note'], '2 posts returned')
        self.assertEqual(self.check([(200, {}, dict(X_PROFILE, tweets=[]))], 'x')[1]['note'], '0 posts returned')

    def test_x_requires_user(self):
        for body in (dict(X_PROFILE, user={}), dict(X_PROFILE, user=None),
                     {k: v for k, v in X_PROFILE.items() if k != 'user'},
                     dict(PROFILE, tweets=[{'user': PROFILE}]), {'user': []}):
            with self.subTest(body=body):
                result = self.check([(200, {}, body)], 'x')[1]
                self.assertEqual(result['status'], 'could_not_check')
                self.assertEqual(result['note'], 'unrecognized response')

    def test_camel_case_names(self):
        for key in ('fullName', 'displayName', 'nickName'):
            result = self.check([(200, {}, {'id': '1', key: 'Synthetic', 'followers': 1})])[1]
            self.assertEqual(result['display_name'], 'Synthetic')

    def test_facebook_profile_id_urls(self):
        for url in ('https://www.facebook.com/profile.php?id=123456',
                    'facebook.com/profile.php?id=123456&other=value'):
            handle = app.normalize(url)
            self.assertEqual(handle, '123456')
            self.assertTrue(app.RULES['facebook'](handle))
        self.assertFalse(app.RULES['facebook'](app.normalize('facebook.com/profile.php?id=abc')))
        for handle in ('nasa', 'nike', '123456'):
            http = Mock(return_value=(200, {}, FACEBOOK))
            self.assertEqual(app.check(handle, 'facebook', 'secret', 1, http)[1]['status'], 'found')
            http.assert_called_once()

    def test_error_details(self):
        for code in (404, 422, 429, 500, 503):
            result = self.check([(code, {}, ERROR), (code, {}, ERROR)])[1]
            self.assertIn('Resource not found', result['note'])
        result = self.check([(503, {}, ERROR), (503, {}, ERROR)], 'tiktok')[1]
        self.assertIn('Resource not found', result['note'])
        self.assertIn('cannot tell from an outage', result['note'])

    def test_cost(self):
        self.assertEqual(app.cost_header({'x-desearch-cost-usd': '0.012'}), (0.012, True))
        for value in (None, 'bad', 'nan', '-1', 'inf'):
            self.assertEqual(app.cost_header({'X-Desearch-Cost-Usd': value}), (0.0, False))
        call = self.check([(503, {'X-Desearch-Cost-Usd': '.1'}, {}), (200, {'X-Desearch-Cost-Usd': '.2'}, PROFILE)])[0]
        self.assertAlmostEqual(call['cost_usd'], .3)
        self.assertTrue(call['cost_header_present'])

    def invoke(self, args, http):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = app.main(args, http=http, sleep=Mock())
        return status, stdout.getvalue(), stderr.getvalue()

    def test_dry_run(self):
        http = Mock(side_effect=AssertionError('network forbidden'))
        status, output, _ = self.invoke(['candidate', '--dry-run'], http)
        self.assertEqual(status, 0)
        self.assertIn('max calls', output)
        http.assert_not_called()

    def test_outputs_redaction_and_replay(self):
        key = 'highly-secret-key'
        body = dict(PROFILE, name=key, Authorization=key, nested={'echo': key})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DESEARCH_API_KEY': key}):
            status, output, error = self.invoke(['candidate', '--networks', 'instagram', '--out', directory, '--json'], Mock(return_value=(200, {}, body)))
            self.assertEqual(status, 0, error)
            for path in Path(directory).iterdir():
                self.assertNotIn(key, path.read_text())
            self.assertNotIn(key, output + error)
            self.assertNotIn('available', (Path(directory) / 'grid.md').read_text().lower())
            with (Path(directory) / 'results.csv').open(newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['verified'], 'True')
            self.assertEqual(row['private'], 'True')
            self.assertIn('instagram: found (private)', (Path(directory) / 'grid.md').read_text())
            raw = next(Path(directory).glob('raw-*.json'))
            http = Mock(side_effect=AssertionError('network forbidden'))
            status, _, error = self.invoke(['--from-raw', str(raw), '--out', str(Path(directory) / 'replay')], http)
            self.assertEqual(status, 0, error)
            http.assert_not_called()
        readme = (Path(app.__file__).parent / 'README.md').read_text()
        self.assertNotIn('available', readme.lower())
        self.assertNotIn('\u2014', readme)

    def test_missing_key_and_auth_abort(self):
        with patch.dict(os.environ, {'DESEARCH_API_KEY': ''}):
            status, _, error = self.invoke(['candidate'], Mock())
            self.assertEqual(status, 1)
            self.assertIn('No API key', error)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DESEARCH_API_KEY': 'secret'}):
            status, _, error = self.invoke(['candidate', '--out', directory], Mock(return_value=(401, {}, {})))
            self.assertEqual(status, 1)
            self.assertIn('Authentication failed', error)
            self.assertIn('HTTP 401', error)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stable_parallel_order(self):
        import threading
        release = threading.Event()
        def http(url, headers, timeout):
            if url.endswith('/first'):
                self.assertTrue(release.wait(2))
            else:
                release.set()
            return 200, {}, PROFILE
        calls, results = app.run(['first', 'second'], ['instagram'], 'secret', workers=2, http=http)
        self.assertEqual([r['handle'] for r in results], ['first', 'second'])
        self.assertEqual([c['handle'] for c in calls], ['first', 'second'])

if __name__ == '__main__':
    unittest.main()
