#!/usr/bin/env python3
"""Small Desearch Instagram CLI."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import igcore as core


class Client:
    def __init__(self, api_key, base_url='https://api.desearch.ai', timeout=90, log_dir=None, opener=None):
        self.key, self.base_url, self.timeout = api_key, base_url.rstrip('/'), timeout
        self.log_dir = Path(log_dir) if log_dir else None
        self.opener = opener or urlopen
        self.calls, self.cost_usd = 0, 0.0

    def get(self, path, params=None):
        return self._call('GET', path, params=params)

    def post(self, path, json_body):
        return self._call('POST', path, json_body=json_body)

    def _call(self, method, path, params=None, json_body=None):
        path = '/'.join(quote(part, safe='%') for part in path.split('/'))
        if params:
            path += '?' + urlencode(params)
        url = self.base_url + path
        headers = {'Authorization': self.key, 'User-Agent': 'desearch-py-examples/instagram-api-quickstart', 'Accept': 'application/json'}
        data = None
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(json_body).encode()
        request = Request(url, data=data, headers=headers, method=method)
        start = time.monotonic()
        response_headers = {}
        try:
            try:
                response = self.opener(request, timeout=self.timeout)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.code
                response_headers = dict(response.headers.items())
                raw = response.read().decode('utf-8', errors='replace')
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw
        except (URLError, TimeoutError, OSError) as exc:
            status, body = 0, str(exc)
        try:
            tz = ZoneInfo('Asia/Tbilisi')
        except ZoneInfoNotFoundError:
            tz = timezone.utc
        meta = dict(method=method, path=path, status=status, latency_s=round(time.monotonic() - start, 3), time=datetime.now(tz).isoformat(), **core.billing(response_headers))
        self.calls += 1
        self.cost_usd += meta['cost_usd']
        n = len(core.items_of(body)) if isinstance(body, list) or core.items_of(body) else int(isinstance(body, dict))
        line = f"[{meta['time']}] {status} {path.split('?')[0]} {meta['latency_s']:.3f}s items={n} cost=${meta['cost_usd']:.6f} next_cursor={'yes' if meta['next_cursor'] else 'no'}"
        def redact(value):
            return value.replace(self.key, '<redacted>') if self.key else value
        print(redact(line), file=sys.stderr)
        if self.log_dir:
            (self.log_dir / 'raw').mkdir(parents=True, exist_ok=True)
            with (self.log_dir / 'calls.jsonl').open('a') as file:
                file.write(redact(json.dumps(meta)) + '\n')
            command = 'posts' if path.split('?')[0].endswith('/posts') else path.split('?')[0].split('/')[3]
            record = dict(meta=meta, request=dict(method=method, url=url, headers=headers | {'Authorization': '<redacted>'}, json=json_body), response=dict(status=status, headers=response_headers, body=body))
            (self.log_dir / 'raw' / f'{self.calls:03d}-{command}.json').write_text(redact(json.dumps(record, ensure_ascii=False)), encoding='utf-8')
        # Response content can echo credentials, so sanitize it before exposing it.
        body = json.loads(redact(json.dumps(body)))
        return status, body, meta


def api_key(key_file=None):
    path = key_file or os.environ.get('DESEARCH_API_KEY_FILE')
    try:
        key = Path(path).read_text().strip() if path else os.environ.get('DESEARCH_API_KEY', '').strip()
    except OSError as exc:
        raise core.InputError(f'cannot read API key file: {exc.strerror}') from None
    if not key:
        raise core.InputError('provide --key-file, DESEARCH_API_KEY_FILE or DESEARCH_API_KEY')
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file')
    parser.add_argument('--log-dir')
    parser.add_argument('--raw', action='store_true')
    parser.add_argument('--max-cost', type=float, default=0.10)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('profile', 'posts', 'media', 'comments', 'hashtag', 'search'):
        sub = subs.add_parser(command)
        sub.add_argument('target')
        if command in ('posts', 'comments', 'hashtag', 'search'):
            sub.add_argument('--count', default='10')
        if command in ('posts', 'comments', 'hashtag'):
            sub.add_argument('--pages', type=int, default=1)
            sub.add_argument('--cursor')
        if command == 'comments':
            sub.add_argument('--with-authors', action='store_true')
    args = parser.parse_args(argv)
    try:
        validators = dict(profile=core.validate_username, posts=core.validate_username, media=core.validate_shortcode, comments=core.validate_shortcode, hashtag=core.validate_tag, search=core.validate_query)
        target = validators[args.command](args.target)
        count = core.validate_count(args.count) if hasattr(args, 'count') else None
        pages = getattr(args, 'pages', 1)
        if not 1 <= pages <= 5:
            raise core.InputError('pages must be from 1 to 5')
        if not math.isfinite(args.max_cost) or args.max_cost < 0:
            raise core.InputError('max-cost must be a finite nonnegative number')
        key = api_key(args.key_file)
    except core.InputError as exc:
        parser.error(str(exc))
    client = Client(key, log_dir=args.log_dir)
    command = args.command
    segment = quote(target, safe='')
    path = '/desearch/instagram/' + (f'profile/{segment}/posts' if command == 'posts' else f'{command}/{segment}')
    if command == 'search':
        path = '/desearch/instagram/search'
    items, cursor, fetched = [], getattr(args, 'cursor', None), 0
    for _ in range(pages):
        if count is not None and client.cost_usd + count * 0.00207 > args.max_cost:
            print('Stopped paging: estimated next call would exceed --max-cost', file=sys.stderr)
            break
        params = {'count': count} if count else {}
        if cursor and command != 'search':
            params['cursor'] = cursor
        status, body, meta = client.post(path, {'query': target, 'count': count}) if command == 'search' else client.get(path, params)
        if status != 200:
            print(json.dumps(dict(error=body.get('detail', body) if isinstance(body, dict) else body, status=status, cost_usd=round(client.cost_usd, 6), calls=client.calls), indent=2, ensure_ascii=False))
            return 1
        fetched += 1
        if count is None:
            normalizer = core.normalize_profile if command == 'profile' else core.normalize_media
            print(json.dumps(dict(command=command, target=target, cost_usd=round(client.cost_usd, 6), calls=client.calls, item=body if args.raw else normalizer(body)), indent=2, ensure_ascii=False))
            return 0
        page = core.items_of(body)
        for obj in page:
            if args.raw:
                item = dict(obj)
                if command == 'comments' and not args.with_authors:
                    for field in ('author', 'username', 'avatar'):
                        item.pop(field, None)
            else:
                normalizer = core.normalize_comment if command == 'comments' else core.normalize_search if command == 'search' else core.normalize_media
                item = normalizer(obj)
            if command == 'comments' and args.with_authors:
                item['author'] = (obj.get('author') or {}).get('username')
            items.append(item)
        cursor = meta['next_cursor'] if command != 'search' else None
        if not cursor or not page:
            break
    print(json.dumps(dict(command=command, target=target, count_requested=count, pages_fetched=fetched, returned=len(items), next_cursor=cursor, cost_usd=round(client.cost_usd, 6), calls=client.calls, items=items), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
