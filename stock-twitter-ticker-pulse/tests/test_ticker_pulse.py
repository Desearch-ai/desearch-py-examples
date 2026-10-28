"""Offline behavior checks using synthetic posts and mocked HTTP responses."""
import ast
import contextlib
import copy
import csv
from datetime import date
import io
import json
import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import ticker_pulse as app

POSTS = json.loads((Path(__file__).parent / 'fixtures/posts.json').read_text())
KEY = 'synthetic_private_key'
DAY = date(2026, 10, 28)
PLANNED = {'ticker': 'NVDA', 'sort': 'Latest', 'params': {'query': '$NVDA'}}


def response(posts=None, headers=None):
    value = io.BytesIO(json.dumps(POSTS if posts is None else posts).encode())
    value.status = 200
    value.headers = {'X-Desearch-Cost-Usd': '0.003'} if headers is None else headers
    return value


def call(sort='Latest', posts=None):
    return dict(ticker='NVDA', sort=sort, posts=copy.deepcopy(POSTS if posts is None else posts),
                status=200, cost_header='0.003', error='', latency_s=0)


class PulseTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.enter = stack.enter_context
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.stderr = io.StringIO()
        self.stdout = io.StringIO()
        self.enter(contextlib.redirect_stderr(self.stderr))
        self.enter(contextlib.redirect_stdout(self.stdout))
        self.enter(patch.dict(os.environ, {'DESEARCH_API_KEY': KEY}))
        self.opener = self.enter(patch('urllib.request.urlopen', side_effect=lambda *a, **k: response()))

    def run_app(self, *options):
        return app.main(['NVDA', '--out', str(self.out), *options], today=DAY)

    def read(self, prefix, suffix):
        return (self.out / f'{prefix}-{DAY}.{suffix}').read_text()

    def stats(self, posts=None):
        return app.ticker_stats('NVDA', [call(posts=posts), call('Top', posts)], 5)

    def test_normalize_case(self):
        self.assertEqual(app.normalize_tickers(['nvda', '$TsLa']), ['NVDA', 'TSLA'])

    def test_normalize_deduplicates(self):
        self.assertEqual(app.normalize_tickers(['NVDA', 'nvda']), ['NVDA'])

    def test_invalid_tickers(self):
        for ticker in ['A1', '$$ABC', 'TOOLONG', '']:
            with self.subTest(ticker=ticker), self.assertRaises(ValueError):
                app.normalize_tickers([ticker])

    def test_watchlist_limit(self):
        with self.assertRaises(ValueError):
            app.normalize_tickers(['A', 'B'], 1)

    def test_plain_post_off_topic(self):
        self.assertEqual(app.spam_reasons({'text': 'ordinary text'}, 'NVDA'), ['off_topic'])

    def test_clean_post(self):
        self.assertEqual(app.spam_reasons(POSTS[0], 'NVDA'), [])

    def test_invite_text(self):
        for link in app.INVITE_LINKS:
            self.assertIn('invite_link', app.spam_reasons({'text': '$NVDA ' + link}, 'NVDA'))

    def test_invite_entity(self):
        for link in app.INVITE_LINKS:
            post = {'text': '$NVDA', 'entities': {'urls': [{'expanded_url': 'https://' + link}]}}
            self.assertIn('invite_link', app.spam_reasons(post, 'NVDA'))

    def test_group_phrases(self):
        for phrase in app.GROUP_PHRASES:
            self.assertIn('group_pitch', app.spam_reasons({'text': '$NVDA ' + phrase.upper()}, 'NVDA'))

    def test_distinct_entity_and_text_tags(self):
        post = {'text': '$nvda $AMD $amd', 'entities': {'symbols': [{'text': 'TSLA'}]}}
        self.assertEqual(app.cashtags(post), {'NVDA', 'AMD', 'TSLA'})

    def test_threshold_includes_current_ticker(self):
        self.assertIn('watchlist_spam', app.spam_reasons({'text': '$NVDA $AMD'}, 'NVDA', 2))

    def test_repeated_tags_count_once(self):
        self.assertNotIn('watchlist_spam', app.spam_reasons({'text': '$NVDA $nvda'}, 'NVDA', 2))

    def test_current_ticker_case_insensitive(self):
        self.assertNotIn('off_topic', app.spam_reasons({'text': '$NvDa'}, 'nvda'))

    def test_entity_ticker_match(self):
        self.assertNotIn('off_topic', app.spam_reasons({'entities': {'symbols': [{'text': 'NVDA'}]}}, 'NVDA'))

    def test_money_not_cashtags(self):
        self.assertEqual(app.cashtags({'text': '$100 $5B $NVDA'}), {'NVDA'})

    def test_embedded_dollar_not_cashtag(self):
        self.assertEqual(app.cashtags({'text': 'a$AMD 1$TSLA ($NVDA)'}), {'NVDA'})

    def test_merge_deduplicates(self):
        self.assertEqual(self.stats()['unique'], 3)

    def test_merge_preserves_sorts(self):
        self.assertEqual(self.stats()['posts'][0]['sorts'], {'Latest', 'Top'})

    def test_spam_counts(self):
        self.assertEqual((self.stats()['kept'], self.stats()['spam_dropped']), (2, 1))

    def test_filter_groups_and_unique_shares(self):
        posts = [dict(POSTS[0], id='kept'),
                 dict(POSTS[0], id='word', text='Tesla is growing'),
                 dict(POSTS[0], id='both', text='Join our community about Tesla'),
                 dict(POSTS[0], id='spam', text='$NVDA free group')]
        stats = self.stats(posts)
        self.assertEqual((stats['unique'], stats['kept']), (4, 1))
        self.assertEqual((stats['spam_dropped'], stats['spam_share']), (2, 50.0))
        self.assertEqual((stats['off_topic'], stats['off_topic_share']), (1, 25.0))
        self.assertEqual([p['filter_group'] for p in stats['posts']],
                         ['kept', 'off_topic', 'spam', 'spam'])
        self.assertEqual(stats['posts'][2]['spam_reasons'], ['group_pitch', 'off_topic'])
        rows = [app.post_row('NVDA', p) for p in stats['posts']]
        self.assertEqual([r['filter_group'] for r in rows], ['kept', 'off_topic', 'spam', 'spam'])
        row = app.board_row(stats)
        self.assertEqual([row[k] for k in ('spam_dropped', 'spam_share', 'off_topic', 'off_topic_share')],
                         [2, 50.0, 1, 25.0])

    def test_real_group_pitch_without_cashtag_threshold(self):
        text = ("$NVDA Our group has been discussing US and Indian stocks. "
                "That's exactly why I built this community")
        self.assertEqual(app.spam_reasons({'text': text}, 'NVDA'), ['group_pitch'])
        for phrase in ('our group', 'this community', 'join our community',
                       'join my community', 'free group'):
            with self.subTest(phrase=phrase):
                self.assertEqual(app.spam_reasons({'text': '$NVDA ' + phrase}, 'NVDA'),
                                 ['group_pitch'])

    def test_top_window_and_like_bounds_only_kept_top(self):
        top = [dict(POSTS[0], id='old', created_at='Mon Oct 26 10:00:00 +0000 2026', like_count=50),
               dict(POSTS[0], id='new', created_at='Tue Oct 27 12:00:00 +0000 2026', like_count=150),
               dict(POSTS[0], id='bad_date', created_at='invalid', like_count=75),
               dict(POSTS[0], id='dropped', text='Tesla', like_count=9999,
                    created_at='Sun Oct 25 00:00:00 +0000 2026')]
        latest = [dict(POSTS[0], id='latest', like_count=1)]
        stats = app.ticker_stats('NVDA', [call(posts=latest), call('Top', top)], 5)
        self.assertEqual(stats['top_oldest'], '2026-10-26T10:00:00+00:00')
        self.assertEqual(stats['top_newest'], '2026-10-27T12:00:00+00:00')
        self.assertEqual((stats['top_min_likes'], stats['top_max_likes']), (50, 150))
        empty = app.ticker_stats('NVDA', [call(posts=latest)], 5)
        self.assertEqual([empty[k] for k in ('top_oldest', 'top_newest', 'top_min_likes', 'top_max_likes')],
                         ['', '', '', ''])

    def test_report_filter_columns_and_top_details(self):
        self.run_app()
        text = self.read('board', 'md')
        self.assertIn('| Spam | Off-topic | Kept |', text)
        self.assertIn('Top window (UTC):', text)
        self.assertIn('Top likes among kept posts: min ', text)
        self.assertIn('Spam reasons:', text)
        self.assertIn('Off-topic reasons:', text)
        rows = list(csv.DictReader(io.StringIO(self.read('posts', 'csv'))))
        self.assertEqual([r['filter_group'] for r in rows], ['kept', 'kept', 'spam'])
        board = next(csv.DictReader(io.StringIO(self.read('board', 'csv'))))
        self.assertEqual((board['spam_dropped'], board['off_topic']), ('1', '0'))

    def test_latest_span(self):
        self.assertEqual(self.stats()['span_hours'], 2.0)

    def test_most_liked(self):
        self.assertEqual(self.stats()['most_liked']['id'], 'fake_1')

    def test_most_viewed(self):
        self.assertEqual(self.stats()['most_viewed']['id'], 'fake_2')

    def test_co_mentions(self):
        self.assertEqual(self.stats()['co_mentions'], [('AMD', 2)])

    def test_keyword_counts(self):
        self.assertEqual((self.stats()['bullish'], self.stats()['bearish']), (3, 2))

    def test_keyword_tilt_empty(self):
        self.assertEqual(app.keyword_tilt([]), (0, 0, 'no keywords'))

    def test_invalid_date_kept(self):
        post = dict(POSTS[0], created_at='invalid')
        self.assertEqual(self.stats([post])['kept'], 1)

    def test_invalid_date_no_span(self):
        self.assertEqual(self.stats([dict(POSTS[0], created_at='invalid')])['span_hours'], '')

    def test_invalid_costs(self):
        for value in [None, '', 'bad', 'nan', '-1', 'inf']:
            self.assertIsNone(app.cost_value(value))

    def test_valid_cost(self):
        self.assertEqual(app.cost_value('0.003'), .003)

    def test_unknown_cost_log(self):
        self.opener.side_effect = lambda *a, **k: response(headers={})
        self.run_app()
        self.assertIn('cost_usd=unknown', self.stderr.getvalue())

    def test_default_timeout(self):
        self.run_app('--latest-only')
        self.assertEqual(self.opener.call_args.kwargs['timeout'], 60)

    def test_custom_timeout(self):
        self.run_app('--timeout', '4.5', '--latest-only')
        self.assertEqual(self.opener.call_args.kwargs['timeout'], 4.5)

    def test_timeout_no_retry(self):
        self.opener.side_effect = TimeoutError()
        self.assertEqual(self.run_app('--latest-only'), 1)
        self.opener.assert_called_once()
        self.assertEqual(json.loads(self.read('raw', 'json'))['calls'][0]['error'], 'timeout')

    def test_failures_after_headers(self):
        failures = [socket.timeout(), TimeoutError(), OSError('read failed'),
                    ValueError('parse failed'), urllib.error.URLError(TimeoutError())]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                reply = response(headers={'X-Desearch-Cost-Usd': '0.003',
                                          'X-Desearch-Usage-Count': '20'})
                reply.read = lambda: (_ for _ in ()).throw(failure)
                self.opener.side_effect = [reply]
                self.stderr.seek(0)
                self.stderr.truncate()
                self.assertEqual(self.run_app('--latest-only'), 1)
                recorded = json.loads(self.read('raw', 'json'))['calls'][0]
                expected = ('timeout after headers' if isinstance(
                    failure, (TimeoutError, socket.timeout, urllib.error.URLError))
                    else 'body read failed after headers')
                self.assertEqual(recorded['error'], expected)
                self.assertEqual(recorded['status'], 200)
                self.assertEqual(recorded['cost_header'], '0.003')
                self.assertEqual(recorded['usage_count'], '20')
                self.assertIn(' error=' + expected.replace(' ', '_'), self.stderr.getvalue())
                board = self.read('board', 'md')
                self.assertIn('Latest: error (' + expected + ')', board)
                self.assertNotIn('Latest: 0', board)
                self.assertIn('Call error (Latest): ' + expected, board)
                self.assertIn('Some failed calls still carried a cost header; see the calls table.', board)
                self.assertIn('| 200 | 0 | 0.003 |', board)
                row = next(csv.DictReader(io.StringIO(self.read('board', 'csv'))))
                self.assertEqual(row['span_hours'], '')
                self.assertNotIn('\u2014', board)

    def test_parse_failure_after_headers(self):
        reply = response()
        reply.read = lambda: b'invalid json'
        self.opener.side_effect = [reply]
        self.assertEqual(app.fetch_call(PLANNED, KEY)['error'], 'body read failed after headers')

    def test_failed_latest_suppresses_span(self):
        failed = dict(call(), error='timeout after headers')
        self.assertEqual(app.ticker_stats('NVDA', [failed, call('Top')], 5)['span_hours'], '')

    def test_unbilled_failure_has_no_billing_note(self):
        self.opener.side_effect = TimeoutError()
        self.run_app('--latest-only')
        recorded = json.loads(self.read('raw', 'json'))['calls'][0]
        self.assertEqual((recorded['status'], recorded['error']), (0, 'timeout'))
        self.assertIn(' error=timeout', self.stderr.getvalue())
        self.assertNotIn('Some failed calls still carried', self.read('board', 'md'))

    def test_success_has_no_error_log_or_billing_note(self):
        self.run_app('--latest-only')
        self.assertNotIn(' error=', self.stderr.getvalue())
        self.assertNotIn('Some failed calls still carried', self.read('board', 'md'))

    def test_wrapped_timeout(self):
        self.opener.side_effect = urllib.error.URLError(TimeoutError())
        self.assertEqual(app.fetch_call(PLANNED, KEY)['error'], 'timeout')

    def test_http_body_redacted_and_limited(self):
        body = ('hello\n  ' + KEY + ' ' + 'z' * 300).encode()
        self.opener.side_effect = urllib.error.HTTPError(app.API_URL, 503, '', {}, io.BytesIO(body))
        error = app.fetch_call(PLANNED, KEY)['error']
        self.assertEqual(error, 'HTTP 503: ' + ('hello [REDACTED] ' + 'z' * 300)[:200])

    def test_http_without_body(self):
        self.opener.side_effect = urllib.error.HTTPError(app.API_URL, 503, '', {}, None)
        self.assertEqual(app.fetch_call(PLANNED, KEY)['error'], 'HTTP 503')

    def test_failure_continues(self):
        self.opener.side_effect = [TimeoutError(), response()]
        self.assertEqual(self.run_app(), 0)
        self.assertEqual(self.opener.call_count, 2)

    def test_request_headers(self):
        self.run_app('--latest-only')
        request = self.opener.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), KEY)
        self.assertEqual(request.get_header('User-agent'), app.USER_AGENT)

    def test_request_parameters(self):
        self.run_app()
        params = [urllib.parse.parse_qs(urllib.parse.urlsplit(c.args[0].full_url).query)
                  for c in self.opener.call_args_list]
        self.assertEqual(params[0], dict(query=['$NVDA'], sort=['Latest'], count=['20'], lang=['en']))
        self.assertEqual(params[1], dict(query=['$NVDA'], sort=['Top'], count=['20'], lang=['en'],
                                         start_date=['2026-10-25'], min_likes=['50']))

    def test_total_stderr(self):
        self.run_app()
        self.assertIn('total_cost_usd=0.0060 calls=2 unknown_cost_calls=0', self.stderr.getvalue())
        self.assertEqual(self.stderr.getvalue().splitlines()[-1], str(self.out.resolve()))

    def test_unknown_total(self):
        self.opener.side_effect = lambda *a, **k: response(headers={})
        self.run_app('--latest-only')
        self.assertIn('total_cost_usd=0.0000 calls=1 unknown_cost_calls=1', self.stderr.getvalue())

    def test_payload_key_redaction(self):
        self.opener.side_effect = lambda *a, **k: response([dict(POSTS[0], text='$NVDA ' + KEY)])
        self.run_app()
        for path in self.out.iterdir():
            self.assertNotIn(KEY, path.read_text())

    def test_board_disclaimer(self):
        self.run_app()
        self.assertIn('not all mentions. Keyword tilt is a rough word count, not a signal. Not investment advice.', self.read('board', 'md'))
        self.assertNotIn('\u2014', self.read('board', 'md'))

    def test_replay_no_calls_or_raw(self):
        self.run_app()
        self.opener.reset_mock()
        target = self.out / 'replay'
        self.assertEqual(app.main(['--from-raw', str(self.out / f'raw-{DAY}.json'), '--out', str(target)]), 0)
        self.opener.assert_not_called()
        self.assertFalse(list(target.glob('raw*')))
        text = (target / f'board-{DAY}.md').read_text()
        self.assertIn('Original run cost: $0.0060', text)
        self.assertIn('Total spend this run: $0.0000 (0 calls)', text)
        self.assertEqual(self.read('board', 'md').split('Total spend this run:')[0].rstrip(),
                         text.split('Original run cost:')[0].rstrip())

    def anonymized_run(self):
        posts = copy.deepcopy(POSTS)
        for index, post in enumerate(posts):
            username = post['user']['username']
            host = 'x.com' if index == 0 else 'twitter.com'
            post['url'] = f'https://{host}/{username}/status/{index}'
            post['text'] += f' @{username}'
        self.opener.side_effect = lambda *a, **k: response(posts)
        self.run_app('--anonymize')

    def test_anonymized_markdown(self):
        self.anonymized_run()
        text = self.read('board', 'md')
        for post in POSTS:
            self.assertNotIn(post['user']['username'], text)
        self.assertIn('https://x.com/account-1/status/0', text)
        self.assertIn('https://twitter.com/account-2/status/1', text)

    def test_anonymized_csv(self):
        self.anonymized_run()
        for path in self.out.glob('*.csv'):
            for post in POSTS:
                self.assertNotIn(post['user']['username'], path.read_text())
        rows = list(csv.DictReader(io.StringIO(self.read('posts', 'csv'))))
        self.assertEqual([r['username'] for r in rows], ['account-1', 'account-2', 'account-3'])

    def test_anonymize_preserves_raw(self):
        self.anonymized_run()
        raw = json.loads(self.read('raw', 'json'))
        self.assertEqual(raw['calls'][0]['posts'][0]['user']['username'], POSTS[0]['user']['username'])
        self.assertNotIn('account-1', self.read('raw', 'json'))

    def test_anonymize_username_matching_sort(self):
        post = dict(POSTS[0], id='top', text='$NVDA Top pick, bullish @Top',
                    url='https://x.com/Top/status/1', user={'username': 'Top'})
        raw = {'date': str(DAY), 'params': {'count': 20, 'max_cashtags': 5}, 'tickers': ['NVDA'],
               'calls': [call(posts=[post]), call('Top', [post])]}
        original = copy.deepcopy(raw)
        result = app.anonymized(raw)
        self.assertEqual(raw, original)
        self.assertEqual([c['sort'] for c in result['calls']], ['Latest', 'Top'])
        self.assertEqual(result['calls'][1]['posts'][0]['user']['username'], 'account-1')
        self.opener.side_effect = lambda *a, **k: response([post])
        self.run_app('--anonymize')
        board = self.read('board', 'md')
        self.assertIn('Latest: 1; Top: 1', board)
        self.assertIn('Top window (UTC): 2026-10-27T05:20:09+00:00', board)
        self.assertIn('Top likes among kept posts: min 80, max 80', board)
        self.assertIn('| NVDA | Top | 200 |', board)
        self.assertIn('@account-1](https://x.com/account-1/status/1)', board)
        costs = list(csv.DictReader(io.StringIO(self.read('costs', 'csv'))))
        self.assertEqual([r['sort'] for r in costs], ['Latest', 'Top'])
        rows = list(csv.DictReader(io.StringIO(self.read('posts', 'csv'))))
        self.assertEqual([(r['username'], r['sorts']) for r in rows], [('account-1', 'Latest;Top')])
        board_row = next(csv.DictReader(io.StringIO(self.read('board', 'csv'))))
        self.assertEqual((board_row['returned_top'], board_row['top_username']), ('1', 'account-1'))

    def test_anonymize_username_matching_ticker(self):
        post = dict(POSTS[0], id='nv', text='$NVDA bullish @nvda', url='https://x.com/nvda/status/1',
                    user={'username': 'nvda'}, entities={'symbols': [{'text': 'NVDA'}]})
        raw = {'date': str(DAY), 'params': {'count': 20, 'max_cashtags': 5}, 'tickers': ['NVDA'],
               'calls': [call(posts=[post])]}
        result = app.anonymized(raw)
        self.assertEqual(result['tickers'], ['NVDA'])
        self.assertEqual(result['calls'][0]['ticker'], 'NVDA')
        anonymous = result['calls'][0]['posts'][0]
        self.assertEqual(anonymous['entities']['symbols'], [{'text': 'NVDA'}])
        self.assertEqual(app.spam_reasons(anonymous, 'NVDA'), [])
        self.opener.side_effect = lambda *a, **k: response([post])
        self.run_app('--anonymize', '--latest-only')
        rows = list(csv.DictReader(io.StringIO(self.read('posts', 'csv'))))
        self.assertEqual([(r['ticker'], r['username'], r['filter_group'], r['cashtags']) for r in rows],
                         [('NVDA', 'account-1', 'kept', 'NVDA')])
        self.assertIn('$NVDA bullish @account-1', rows[0]['text'])
        board = self.read('board', 'md')
        self.assertIn('## NVDA', board)
        self.assertIn('| NVDA | Latest: 1 |', board)
        self.assertIn('@account-1](https://x.com/account-1/status/1)', board)
        for name in ('posts-%s.csv', 'board-%s.md', 'board-%s.csv'):
            self.assertNotIn('nvda', (self.out / (name % DAY)).read_text())
            self.assertNotIn('$account', (self.out / (name % DAY)).read_text())

    def assert_raw_error(self, path, message):
        with self.assertRaises(SystemExit) as error:
            app.main(['--from-raw', str(path), '--out', str(self.out / 'replay')])
        self.assertEqual(error.exception.code, 2)
        self.assertIn(message, self.stderr.getvalue())
        self.assertNotIn(KEY, self.stderr.getvalue())

    def test_from_raw_missing_file(self):
        self.assert_raw_error(self.out / 'missing.json', 'FileNotFoundError')

    def test_from_raw_invalid_json(self):
        path = self.out / 'bad.json'
        path.write_text('{not json')
        self.assert_raw_error(path, 'JSONDecodeError')

    def test_from_raw_empty_tickers(self):
        path = self.out / 'empty.json'
        path.write_text(json.dumps({'date': str(DAY), 'params': {}, 'tickers': [], 'calls': []}))
        self.assert_raw_error(path, 'Raw file has no tickers to render.')

    def test_from_raw_missing_tickers(self):
        path = self.out / 'nokey.json'
        path.write_text(json.dumps({'date': str(DAY), 'params': {}, 'calls': []}))
        self.assert_raw_error(path, 'Raw file has no tickers to render.')

    def test_watchlist_comments(self):
        watchlist = self.out / 'watchlist'
        watchlist.write_text('# comment\n$nvda # note\nTSLA\nnvda\n')
        self.run_app('--watchlist', str(watchlist), '--latest-only')
        self.assertEqual(self.opener.call_count, 2)

    def test_key_file_precedence(self):
        keyfile = self.out / 'key'
        keyfile.write_text('  file_key\n')
        self.run_app('--key-file', str(keyfile), '--latest-only')
        self.assertEqual(self.opener.call_args.args[0].get_header('Authorization'), 'file_key')

    def test_dry_run_omits_empty_language(self):
        self.assertEqual(self.run_app('--dry-run', '--lang', ''), 0)
        self.opener.assert_not_called()
        self.assertNotIn('"lang"', self.stdout.getvalue())

    def test_invalid_cli(self):
        for options in [['A1'], ['A', 'B', '--max-tickers', '1'], ['NVDA', '--count', '101'],
                        ['NVDA', '--timeout', '0'], ['NVDA', '--timeout', 'nan']]:
            with self.subTest(options=options), self.assertRaises(SystemExit) as error:
                app.main(options)
            self.assertEqual(error.exception.code, 2)

    def test_python_310_syntax(self):
        ast.parse(Path(app.__file__).read_text(), feature_version=(3, 10))


if __name__ == '__main__':
    unittest.main()
