#!/usr/bin/env python3
"""YouTube Creator Finder, using Desearch People Search REST endpoints.

Local quality flags: views_missing means null views; few_videos means <=1
videos; no_contact means neither email nor website; possible_brand_or_store
means a case-insensitive whole-word match for shop, store, official, retailer,
brand, inc, ltd, llc, or co. in the channel name, handle, or bio. URLs and
email addresses are removed from the bio first. Handles also match official,
shop, or store as substrings. Low_score means score <60. Flags are review hints.
Exit codes: 0 completed; 1 not confirmed; 2 API, key or input error, or task
ended not completed; 3 timeout; 4 estimate above --max-cost.
Call logs record redacted query params under params ({} when absent).
Polling and final results are deduplicated by handle, falling back to ID,
URL, or row content when no handle is present.
"""
import argparse
import calendar
from collections import Counter
import csv
from datetime import date, datetime
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

BASE = 'https://api.desearch.ai'
TASKS = '/desearch/people/tasks/'
COLUMNS = 'handle,name,channel_url,score,subscribers,videos,views,newest_matching_video,inactive,country,email,website,top_video_url,top_video_title,reasons,quality_flags'.split(',')
INACTIVE_FLAG_MONTHS = 12
TERMINAL = {'completed', 'failed', 'cancelled', 'expired'}


# https://desearch.ai/pricing (checked 2026-10-26). Observed count 5 reserved
# and billed $0.25 on 2026-10-23 and 2026-10-26.
PRICE_PER_CREATOR_USD = 0.05
MIN_BILLED_CREATORS = 3


def estimate_cost(count):
    reserved = round(count * PRICE_PER_CREATOR_USD, 4)
    return dict(reserved_usd=reserved, min_billed_usd=round(min(count, MIN_BILLED_CREATORS) * PRICE_PER_CREATOR_USD, 4), max_billed_usd=reserved)


def format_estimate(count, max_cost):
    cost = estimate_cost(count)
    return (f"Cost estimate: this search reserves ${cost['reserved_usd']:.2f} ({count} creators x $0.05). "
            f"It bills ${cost['min_billed_usd']:.2f} to ${cost['max_billed_usd']:.2f} if it finds creators (minimum 3), "
            f"$0 if it finds none; the unused part of the reservation is returned. Spend cap (--max-cost): ${max_cost:.2f}.")


def today():
    return datetime.now(ZoneInfo('Asia/Tbilisi')).date()


def months_before(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def newest_matching_video(videos):
    dates = []
    for video in videos:
        value = video.get('published_at')
        if isinstance(value, str):
            try:
                dates.append(datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value).date())
            except ValueError:
                pass
    return max(dates).isoformat() if dates else 'unknown'


def load_excludes(filename):
    if not filename:
        return []
    text = Path(filename).read_text(encoding='utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    values = [r.get('handle', '') for r in reader] if reader.fieldnames and 'handle' in reader.fieldnames else text.splitlines()
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def build_request_body(args):
    d = vars(args) if isinstance(args, argparse.Namespace) else args
    body = {'query': d['query'], 'count': d.get('count', 5)}
    if d.get('min_score') is not None:
        body['min_score'] = d['min_score']
    excludes = load_excludes(d.get('exclude_file'))
    if excludes:
        body['exclude'] = excludes
    filters = {}
    for source, target in [('min_subscribers', 'min_subscribers'), ('max_subscribers', 'max_subscribers'), ('country', 'countries'), ('require_contact', 'require_contact'), ('keyword', 'keywords'), ('exclude_keyword', 'exclude_keywords')]:
        value = d.get(source)
        if value is not None and value != [] and value is not False:
            filters[target] = value
    if filters:
        body['filters'] = filters
    return body


def quality_flags(creator, bio=''):
    flags = []
    if creator.get('views') is None:
        flags.append('views_missing')
    if isinstance(creator.get('videos'), (int, float)) and creator['videos'] <= 1:
        flags.append('few_videos')
    if not creator.get('email') and not creator.get('website'):
        flags.append('no_contact')
    bio = re.sub(r'(?i)\b(?:https?://|www\.)\S+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?', ' ', bio)
    handle = str(creator.get('handle') or '')
    text = ' '.join((str(creator.get('name') or ''), handle, bio))
    if (re.search(r'(?<!\w)(?:shop|store|official|retailer|brand|inc|ltd|llc)(?!\w)|(?<!\w)co\.(?!\w)', text, re.I)
            or re.search(r'official|shop|store', handle, re.I)):
        flags.append('possible_brand_or_store')
    if isinstance(creator.get('score'), (int, float)) and creator['score'] < 60:
        flags.append('low_score')
    return flags


def parse_creator(row, inactive_flag_months=INACTIVE_FLAG_MONTHS):
    metrics = row.get('metrics') or {}
    score = row.get('score')
    scoring = score if isinstance(score, dict) else {}
    contacts = [c for c in row.get('contacts') or [] if isinstance(c, dict)]
    links = [c for c in row.get('links') or [] if isinstance(c, dict)]
    videos = [v for v in (row.get('videos') or row.get('evidence') or []) if isinstance(v, dict) and v.get('type', 'video') == 'video']
    top = videos[0] if videos else {}
    result = dict(handle=row.get('handle'), name=row.get('name'), channel_url=row.get('url') or row.get('channel_url'), score=scoring.get('value') if isinstance(score, dict) else score,
                  subscribers=metrics.get('subscribers'), videos=metrics.get('videos'), views=metrics.get('views'), country=(row.get('attributes') or {}).get('country') or row.get('country') or row.get('location'),
                  email=next((c.get('value') for c in contacts if c.get('type') == 'email' and c.get('value')), None),
                  website=next((c.get('url') for c in links if c.get('type') == 'website' and c.get('url')), None),
                  top_video_url=top.get('url'), top_video_title=top.get('title'), reasons=' | '.join(str(x) for x in scoring.get('reasons') or []))
    if not result['website']:
        result['website'] = next((c.get('value') for c in contacts if c.get('type') == 'website'), None)
    result['newest_matching_video'] = newest_matching_video(videos)
    result['inactive'] = ('unknown' if result['newest_matching_video'] == 'unknown' else
                          str(date.fromisoformat(result['newest_matching_video']) < months_before(today(), inactive_flag_months)).lower())
    result['quality_flags'] = ' | '.join(quality_flags(result, row.get('bio') or ''))
    if result['newest_matching_video'] == 'unknown':
        result['quality_flags'] += (' | ' if result['quality_flags'] else '') + 'matching_video_date_unknown'
    return result


def summarize(task, creators, request, creation=None, max_inactive_months=None, inactive_dropped=0):
    creation = creation or {}
    duration = None
    try:
        created_at, finished_at = task.get('created_at'), task.get('finished_at')
        if created_at is not None and finished_at is not None:
            duration = (datetime.fromisoformat(finished_at.replace('Z', '+00:00')) - datetime.fromisoformat(created_at.replace('Z', '+00:00'))).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    flags = Counter(f for c in creators for f in c['quality_flags'].split(' | ') if f)
    data = {'query': task.get('query', request.get('query')), 'request': task.get('request', request), 'task_status': task.get('status'), 'completion_reason': task.get('completion_reason'), 'stop_reason': (task.get('progress') or {}).get('stop_reason'), 'coverage_limited': task.get('coverage_limited'), 'warnings': task.get('warnings', []), 'errors': task.get('errors', []), 'counts': {'downloaded': len(creators), 'result_count': task.get('result_count'), **(task.get('progress') or {})}, 'emails_count': sum(bool(c['email']) for c in creators), 'flags_counts': dict(flags), 'reserved_cost_usd': task.get('reserved_cost_usd', creation.get('reserved_cost_usd', creation.get('cost_usd'))), 'final_cost_usd': task.get('final_cost_usd'), 'refunded_usd': task.get('refunded_usd'), 'duration_seconds': duration, 'creation': creation}
    data.update(inactive_flag_months=max_inactive_months or INACTIVE_FLAG_MONTHS, inactive_flagged=sum(c['inactive'] == 'true' for c in creators), max_inactive_months=max_inactive_months, inactive_dropped=inactive_dropped, newest_matching_video_unknown=sum(c['newest_matching_video'] == 'unknown' for c in creators), note='newest_matching_video is the newest publish date among the videos that matched the search, not the channel\'s latest upload; Desearch returns no channel-level upload date. Dropped creators are still billed.')
    return '# YouTube Creator Finder\n\n' + '\n\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in data.items()) + '\n'


class APIError(Exception):
    pass


class HTTPClient:
    def __init__(self, key, session=None):
        self.key = key
        self.session = session if session is not None else requests.Session()
        self.calls = []
        self.log_path = None

    def redact(self, text):
        return text.replace(self.key, '[REDACTED]') if self.key else text

    def set_log(self, path):
        self.log_path = path
        with path.open('a', encoding='utf-8') as f:
            for call in self.calls:
                f.write(json.dumps(call, ensure_ascii=False) + '\n')

    def call(self, method, path, **kwargs):
        headers = {'Authorization': self.key, 'User-Agent': 'youtube-creator-finder/1.0', **kwargs.pop('headers', {})}
        start = time.monotonic()
        try:
            response = self.session.request(method, BASE + path, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            self.record(method, path, None, start, {}, {'error': self.redact(str(exc))}, kwargs.get('params') or {})
            raise APIError(self.redact(f'Network error: {exc}')) from None
        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]
        cost = {k: v for k, v in response.headers.items() if k.lower().startswith('x-desearch-')}
        self.record(method, path, response.status_code, start, cost, body, kwargs.get('params') or {})
        if response.status_code >= 400:
            raise APIError(self.redact(f'API HTTP {response.status_code}: {json.dumps(body, ensure_ascii=False)}'))
        return response, body

    def record(self, method, path, status, start, cost, body, params):
        call = json.loads(self.redact(json.dumps(dict(time=datetime.now(ZoneInfo('Asia/Tbilisi')).isoformat(), method=method, path=path, params=params, status=status, elapsed_ms=round((time.monotonic()-start)*1000, 2), cost_headers=cost, response_body=body))))
        self.calls.append(call)
        if self.log_path:
            with self.log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(call, ensure_ascii=False) + '\n')

    def results(self, task_id):
        cursor = None
        seen = set()
        while True:
            params = {'limit': 100}
            if cursor is not None:
                params['cursor'] = cursor
            _, page = self.call('GET', TASKS + task_id + '/results', params=params)
            yield from page.get('results', [])
            following = page.get('next_cursor')
            if page.get('has_more') is False or not following:
                break
            if following in seen:
                raise APIError('API returned a repeated results cursor')
            seen.add(following)
            cursor = following


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--query', required=True)
    p.add_argument('--count', type=int, default=5, choices=range(5, 201), metavar='5..200')
    for name in ['min-score', 'min-subscribers', 'max-subscribers']:
        p.add_argument('--' + name, type=int)
    for name in ['country', 'keyword', 'exclude-keyword']:
        p.add_argument('--' + name, action='append')
    for name in ['require-contact', 'dry-run', 'cancel-on-timeout']:
        p.add_argument('--' + name, action='store_true')
    for name in ['exclude-file', 'idempotency-key', 'task-id']:
        p.add_argument('--' + name)
    p.add_argument('--max-cost', type=float, default=0.25, help='maximum reservation in USD, greater than zero (default: 0.25)')
    p.add_argument('--yes', action='store_true', help='start the paid search without asking')
    p.add_argument('--max-inactive-months', type=int, default=None, help='optional: drops creators whose newest matching video is older than N calendar months; without it they are only flagged (inactive=true) using 12 months; 0 = flag only, same as not passing it')
    p.add_argument('--poll-seconds', type=float, default=5)
    p.add_argument('--max-wait', type=float, default=600)
    p.add_argument('--out', default='output/')
    p.add_argument('--key-file', default=os.environ.get('DESEARCH_KEY_FILE', '~/.desearch_api_key'))
    return p


def main(argv=None, session=None):
    p = parser()
    args = p.parse_args(argv)
    if args.poll_seconds < 0 or args.max_wait < 0:
        p.error('poll-seconds and max-wait must be nonnegative')
    if args.min_score is not None and not 0 <= args.min_score <= 100:
        p.error('min-score must be 0..100')
    if any(v is not None and v < 0 for v in [args.min_subscribers, args.max_subscribers]):
        p.error('subscriber limits must be nonnegative')
    if args.min_subscribers is not None and args.max_subscribers is not None and args.min_subscribers > args.max_subscribers:
        p.error('min-subscribers must not exceed max-subscribers')
    if not math.isfinite(args.max_cost) or args.max_cost <= 0:
        p.error('max-cost must be greater than zero')
    if args.max_inactive_months is not None and args.max_inactive_months < 0:
        p.error('max-inactive-months must be nonnegative')
    client = None
    try:
        body = build_request_body(args)
        estimate = estimate_cost(args.count)
        if not args.task_id:
            print(format_estimate(args.count, args.max_cost), file=sys.stderr)
            if estimate['reserved_usd'] > args.max_cost:
                if args.dry_run:
                    print('Note: a real run would be refused by the spend cap --max-cost.', file=sys.stderr)
                else:
                    print(f"Error: the estimate (${estimate['reserved_usd']:.2f} reserved for count {args.count}) is above your spend cap --max-cost ${args.max_cost:.2f}. Lower --count or raise --max-cost. Nothing was sent.", file=sys.stderr)
                    return 4
            if not args.dry_run and not args.yes:
                if not sys.stdin.isatty():
                    print('Error: this search costs money and needs confirmation. Run it in a terminal to confirm, or pass --yes to start it without asking. Nothing was sent.', file=sys.stderr)
                    return 1
                print('Start this paid search? [y/N] ', end='', file=sys.stderr, flush=True)
                try:
                    answer = input()
                except EOFError:
                    answer = ''
                if answer.strip().lower() not in ('y', 'yes'):
                    print('Cancelled. Nothing was sent.', file=sys.stderr)
                    return 1
        if args.dry_run:
            print(json.dumps(body, indent=2))
            return 0
        key = Path(args.key_file).expanduser().read_text().strip()
        if not key:
            raise APIError('Key file is empty')
        client = HTTPClient(key, session)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        creation = {}
        start = time.monotonic()
        if args.task_id:
            task_id = quote(args.task_id, safe='')
            client.set_log(out / f'{task_id}-calls.jsonl')
            _, task = client.call('GET', TASKS + task_id)
        else:
            headers = {'Idempotency-Key': args.idempotency_key} if args.idempotency_key else {}
            try:
                response, task = client.call('POST', '/desearch/people/search/youtube', json=body, headers=headers)
            except APIError:
                client.set_log(out / 'create-error-calls.jsonl')
                raise
            reserved = task.get('reserved_cost_usd', task.get('cost_usd'))
            if isinstance(reserved, (int, float)) and abs(reserved - estimate['reserved_usd']) > 0.0001:
                print(client.redact(f"Warning: the API reserved ${reserved:.2f}, the estimate was ${estimate['reserved_usd']:.2f}; check https://desearch.ai/pricing."), file=sys.stderr)
            task_id = quote(str(task['task_id']), safe='')
            client.set_log(out / f'{task_id}-calls.jsonl')
            creation = {'status_code': response.status_code, 'cost_usd': task.get('cost_usd'), 'reserved_cost_usd': task.get('reserved_cost_usd', task.get('cost_usd')), 'cost_header': response.headers.get('X-Desearch-Cost-Usd')}
            print(client.redact(f'Task {task_id}: {json.dumps(creation)}'), file=sys.stderr)
        creators, seen = [], set()
        inactive_dropped = 0
        flag_months = args.max_inactive_months or INACTIVE_FLAG_MONTHS
        cutoff = months_before(today(), flag_months)
        inactive_path = out / f'{task_id}-inactive.csv'
        inactive_path.unlink(missing_ok=True)
        def save_summary():
            (out / f'{task_id}-summary.md').write_text(client.redact(summarize(task, creators, body, creation, args.max_inactive_months, inactive_dropped)), encoding='utf-8')
        with (out / f'{task_id}-creators.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            while True:
                progress = task.get('progress') or {}
                print(client.redact(f"Task {task_id}: {task.get('status')} qualified={progress.get('qualified')} candidates_found={progress.get('candidates_found')} stop_reason={progress.get('stop_reason')}"), file=sys.stderr)
                for row in client.results(task_id):
                    identity = row.get('handle') or row.get('id') or row.get('url') or json.dumps(row, sort_keys=True)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    creator = json.loads(client.redact(json.dumps(parse_creator(row, flag_months))))
                    if args.max_inactive_months and creator['inactive'] == 'true':
                        with inactive_path.open('a' if inactive_dropped else 'w', newline='', encoding='utf-8') as inactive:
                            inactive_writer = csv.DictWriter(inactive, fieldnames=COLUMNS)
                            if not inactive_dropped:
                                inactive_writer.writeheader()
                            inactive_writer.writerow(creator)
                        inactive_dropped += 1
                        continue
                    creators.append(creator)
                    writer.writerow(creator)
                    f.flush()
                    print(json.dumps(creator, ensure_ascii=False), flush=True)
                if task.get('status') in TERMINAL:
                    break
                remaining = args.max_wait - (time.monotonic() - start)
                if remaining <= 0:
                    if args.cancel_on_timeout:
                        _, task = client.call('POST', TASKS + task_id + '/cancel')
                    save_summary()
                    print(f'Timeout: task {task_id}', file=sys.stderr)
                    return 3
                time.sleep(min(args.poll_seconds, remaining))
                _, task = client.call('GET', TASKS + task_id)
        unknown = sum(c['newest_matching_video'] == 'unknown' for c in creators)
        if args.max_inactive_months:
            print(f'Inactivity filter (--max-inactive-months {args.max_inactive_months}): dropped {inactive_dropped} of {len(seen)} creators with no matching video since {cutoff}' + (f' (see {inactive_path.name})' if inactive_dropped else '') + f'; {unknown} with unknown matching video date kept.', file=sys.stderr)
        else:
            flagged = sum(c['inactive'] == 'true' for c in creators)
            print(f'Inactive flag: {flagged} of {len(seen)} creators have no matching video since {cutoff} (inactive=true, kept); {unknown} unknown. Pass --max-inactive-months N to drop them.', file=sys.stderr)
        save_summary()
        response, _ = client.call('GET', TASKS + task_id + '/export', params={'format': 'csv'})
        (out / f'{task_id}-export.csv').write_bytes(response.content)
        return 0 if task.get('status') == 'completed' else 2
    except (APIError, OSError, ValueError, KeyError) as exc:
        message = str(exc)
        print('Error: ' + (client.redact(message) if client else message), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
