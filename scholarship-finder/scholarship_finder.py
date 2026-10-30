#!/usr/bin/env python3
"""Find source-stated scholarship dates using Desearch. Python 3.10+."""
import argparse
import calendar
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DISCLAIMER = 'Deadlines and amounts are as stated by the source page. Check the official page before applying.'
AGGREGATORS = {'scholarships.com', 'bold.org', 'fastweb.com', 'scholarshipowl.com', 'niche.com', 'collegescholarships.org', 'unigo.com', 'scholarshipsclosingsoon.com', 'scholarships360.org', 'usascholarships.net'}
MONTHS = {name.lower(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
MONTH = '|'.join(sorted(MONTHS, key=len, reverse=True))
DATE_RE = re.compile(rf'(?P<md>(?:{MONTH})\.?\s+\d{{1,2}},?\s*\d{{4}})|(?P<dm>\d{{1,2}}\s+(?:{MONTH})\.?\s+\d{{4}})|(?P<iso>\b\d{{4}}-\d{{2}}-\d{{2}}\b)|(?P<us>\b\d{{1,2}}/\d{{1,2}}/\d{{4}}\b)', re.I)
KEYWORD = re.compile(r'deadline|\bdue\b|apply by|applications close|\bcloses\b|by noon on|submit by|\buntil\b', re.I)
AMOUNT = re.compile(r'(?:up to\s*)?\$\s*\d[\d,]*(?:\.\d{2})?', re.I)


def dates(text):
    """Return (date, start, end) for explicit, valid four-digit-year dates."""
    found = []
    for m in DATE_RE.finditer(text):
        parts = re.findall(r'[A-Za-z]+|\d+', m.group())
        try:
            if m.lastgroup == 'md': month, day, year = MONTHS[parts[0].lower()], int(parts[1]), int(parts[2])
            elif m.lastgroup == 'dm': day, month, year = int(parts[0]), MONTHS[parts[1].lower()], int(parts[2])
            elif m.lastgroup == 'iso': year, month, day = map(int, parts)
            else: month, day, year = map(int, parts)
            found.append((dt.date(year, month, day), m.start(), m.end()))
        except (ValueError, KeyError):
            pass
    return found


def sentence_window(text, start, end):
    # Decimal points inside amounts and abbreviated months are not sentence breaks.
    boundaries = list(re.finditer(r'[!?\n]|\.(?=\s+[A-Z]|$)', text))
    left = max([m.end() for m in boundaries if m.end() <= start] + [0])
    right = min([m.start() for m in boundaries if m.start() >= end] + [len(text)])
    return text[max(left, start - 150):min(right, end + 150)], max(left, start - 150)


def date_negated(text, start, end):
    window, _ = sentence_window(text, start, end)
    return bool(re.search(r"\bnot\b|\bno longer\b|\bdoes not\b|system-generated|\bplaceholder\b", window, re.I))


def normalize_name(value):
    return value.replace("\u2014", "-").replace("\u2013", "-")


def derive_name(text, title):
    pattern = r'(?:(?:The|the)\s+)?(?:\$[\d,]+(?:\.\d{2})?\s+)?([A-Z][\w&\'-]*(?:\s+(?:[A-Z][\w&\'-]*|of|the|and|in|for|&)){0,10}\s+Scholarship)\b'
    names = list(re.finditer(pattern, text))
    for match in names:
        name = match.group(1)
        if not re.fullmatch(r'(?:(?:Award Winner|Save|Apply|Share|Login)\s+)+Scholarship', name, re.I):
            return name
    return title


def normalized_url(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or '').lower().removeprefix('www.')
    query = urllib.parse.urlencode(sorted((k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith('utm_')))
    return urllib.parse.urlunsplit((p.scheme.lower(), host + (f':{p.port}' if p.port else ''), p.path.rstrip('/'), query, ''))


def is_aggregator(url, text):
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    return any(host == d or host.endswith('.' + d) for d in AGGREGATORS) or len({d for d, s, e in dates(text) if KEYWORD.search(text[max(0, s-80):s])}) >= 3


def extract_rows(item, endpoint, today):
    url = item.get('url') or item.get('link') or ''
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'): return []
    text = '\n'.join(item.get('highlights') or []) if endpoint == 'search' else item.get('snippet', '')
    title = item.get('title') or url
    parsed = dates(text)
    flags = []
    if not item.get('published_date'): flags.append('no publish date')
    if any(d.year <= today.year - 2 for d, _, _ in parsed): flags.append('mixed old dates')
    limit = today.replace(year=today.year + 2, day=min(today.day, calendar.monthrange(today.year + 2, today.month)[1]))
    # Only the closing date of an explicit application window is a candidate.
    range_starts, range_ends = set(), set()
    for first, second in zip(parsed, parsed[1:]):
        if first[0] <= second[0] and re.fullmatch(r'\s*(?:-|\u2013|to|through)\s*', text[first[2]:second[1]], re.I):
            range_starts.add(first[1])
            range_ends.add(second[1])
    rows = []
    negated = False
    for date, start, end in parsed:
        if start in range_starts: continue
        if not today <= date <= limit: continue
        if date_negated(text, start, end):
            negated = True
            continue
        window, offset = sentence_window(text, start, end)
        name = derive_name(normalize_name(window), None)
        specific_name = name is not None
        name = name if specific_name else normalize_name(title)
        amounts = list(AMOUNT.finditer(window))
        amount = min(amounts, key=lambda m: abs(offset + m.start() - start)).group() if amounts else 'not stated'
        rowflags = flags.copy()
        if start not in range_ends and not KEYWORD.search(text[max(0, start-80):start]): rowflags.append('unclear if deadline')
        rows.append(dict(name=name, specific_name=specific_name, amount=amount, deadline=date.isoformat(), confidence='snippet only', url=url, endpoints=[endpoint], flags=rowflags, aggregator=is_aggregator(url, text)))
    if negated and not rows:
        rows.append(dict(name=normalize_name(title), specific_name=False, amount='not stated', deadline='', confidence='snippet only', url=url, endpoints=[endpoint], flags=flags + ['date negated by source'], aggregator=is_aggregator(url, text)))
    return rows


def dedupe(rows):
    merged = {}
    for row in rows:
        row = dict(row, name=normalize_name(row['name']))
        key = (normalized_url(row['url']), row['deadline'], ' '.join(row['name'].lower().split()))
        if key not in merged: merged[key] = dict(row, endpoints=list(row['endpoints']), flags=list(row['flags']))
        else:
            old = merged[key]
            old['aggregator'] = old['aggregator'] or row['aggregator']
            old['endpoints'] = sorted(set(old['endpoints'] + row['endpoints']))
            old['flags'] = sorted(set(old['flags'] + row['flags']))
            if old['amount'] == 'not stated': old['amount'] = row['amount']
    # Preserve URL-level merging for fallback titles, then merge named awards
    # across pages on the same host, retaining the first encountered URL.
    awards = {}
    result = []
    for row in merged.values():
        if not row.get('specific_name'):
            result.append(row)
            continue
        host = urllib.parse.urlsplit(normalized_url(row['url'])).hostname
        key = (host, ' '.join(row['name'].casefold().split()), row['deadline'], row['amount'])
        if key not in awards:
            awards[key] = (row, {normalized_url(row['url'])})
            result.append(row)
        else:
            old, urls = awards[key]
            urls.add(normalized_url(row['url']))
            old['endpoints'] = sorted(set(old['endpoints'] + row['endpoints']))
            old['flags'] = sorted(set(old['flags'] + row['flags']))
            old['aggregator'] = old['aggregator'] or row['aggregator']
    for row, urls in awards.values():
        if len(urls) > 1:
            row['flags'].append(f'also on {len(urls) - 1} more page' + ('s' if len(urls) > 2 else ''))
    return sorted(result, key=lambda r: (r['deadline'], r['name'], r['url']))


class AuthenticationError(Exception): pass
class SourceError(Exception): pass


class Client:
    def __init__(self, key, timeout=30, no_js=False):
        self.key, self.timeout, self.calls = key, timeout, []
        self.no_js = no_js

    def clean(self, value):
        if isinstance(value, dict): return {k: ('[REDACTED]' if k.lower() == 'authorization' else self.clean(v)) for k, v in value.items()}
        if isinstance(value, list): return [self.clean(v) for v in value]
        if isinstance(value, str) and self.key: return value.replace(self.key, '[REDACTED]')
        return value

    def request(self, method, path, params):
        attempts = 2 if path == '/search' or (path == '/web/extract' and not self.no_js) else 1
        for attempt in range(attempts):
            url = 'https://api.desearch.ai' + path
            data = None
            if method == 'GET': url += '?' + urllib.parse.urlencode(params)
            else: data = json.dumps(params).encode()
            req = urllib.request.Request(url, data=data, method=method, headers={'Authorization': self.key, 'User-Agent': 'desearch-scholarship-finder/0.1', 'Content-Type': 'application/json'})
            start = time.monotonic()
            status, headers, body = 0, {}, ''
            try:
                timeout = max(self.timeout, 45) if path == '/web/extract' and attempt and params.get('js') == 'true' else self.timeout
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    status, headers, body = response.status, dict(response.headers), response.read().decode('utf-8', errors='replace')
            except urllib.error.HTTPError as exc:
                status, headers, body = exc.code, dict(exc.headers or {}), exc.read().decode('utf-8', errors='replace')
            except (OSError, urllib.error.URLError):
                body = 'Transport failed'
            try: payload = json.loads(body) if path != '/web/extract' or not 200 <= status < 300 else body
            except ValueError: payload = body
            lower = {k.lower(): v for k, v in headers.items()}
            obj = payload if isinstance(payload, dict) else {}
            cost = obj.get('cost_usd', lower.get('x-desearch-cost-usd', 0))
            usage = obj.get('usage_count', lower.get('x-desearch-usage-count'))
            self.calls.append(self.clean(dict(method=method, path=path, params=params, status=status, latency_seconds=round(time.monotonic()-start, 6), cost_usd=float(cost or 0), usage_count=usage, response_body=payload)))
            if status in (401, 403): raise AuthenticationError('Authentication failed')
            if 200 <= status < 300:
                if path != '/web/extract' and not isinstance(payload, dict): raise SourceError(path + ': invalid JSON response')
                return payload
            if path == '/web/extract':
                message = self.clean(f"{path}: request failed (status {status}); error_code: {obj.get('error_code', 'unknown')}; detail: {obj.get('detail', body)}")
                print(message, file=sys.stderr)
                if obj.get('error_code') == 'js_required' and attempt + 1 < attempts and params.get('js') != 'true':
                    params = dict(params, js='true', wait=3000)
                    continue
                raise SourceError(message)
            if attempt + 1 < attempts and (status == 429 or status >= 500):
                time.sleep(2)
                continue
            raise SourceError(f'{path}: request failed (status {status})')


def rebuild(calls, today):
    rows = []
    extracts = {}
    # Retain source strings verbatim, using normalized URLs only as lookup keys.
    web_urls = {}
    for call in calls:
        if call['path'] == '/web' and 200 <= call['status'] < 300:
            for item in call['response_body'].get('data', []):
                url = item.get('url') or item.get('link') or ''
                if urllib.parse.urlsplit(url).scheme in ('http', 'https'):
                    web_urls.setdefault(normalized_url(url), url)
    for call in calls:
        if call['path'] == '/web/extract': extracts[normalized_url(call['params']['url'])] = call
        if not 200 <= call['status'] < 300: continue
        body = call['response_body']
        if call['path'] == '/search':
            for item in body.get('results', []): rows.extend(extract_rows(item, 'search', today))
        elif call['path'] == '/web':
            for item in body.get('data', []): rows.extend(extract_rows(item, 'web', today))
    for row in rows:
        row['url'] = web_urls.get(normalized_url(row['url']), row['url'])
    rows = dedupe(rows)
    for row in rows:
        call = extracts.get(normalized_url(row['url']))
        if call:
            if 200 <= call['status'] < 300:
                row['aggregator'] = row['aggregator'] or is_aggregator(row['url'], str(call['response_body']))
            if not 200 <= call['status'] < 300: row['confidence'] = 'extract failed'
            elif row['deadline'] and any(d.isoformat() == row['deadline'] and date_negated(str(call['response_body']), start, end) for d, start, end in dates(str(call['response_body']))):
                row['deadline'] = ''
                row['flags'].append('date negated by source')
                row['confidence'] = 'date negated by source'
            elif row['deadline'] and row['deadline'] in {d.isoformat() for d, _, _ in dates(str(call['response_body']))}: row['confidence'] = 'confirmed on page (js)' if call['params'].get('js') == 'true' else 'confirmed on page'
            else: row['confidence'] = 'date not found on page'
    return rows


def cost_line(calls):
    return f"calls: {len(calls)}, cost: ${sum(c.get('cost_usd', 0) for c in calls):.5f}"


def table(rows):
    columns = [('name', 'Name', 44), ('amount', 'Amount', 20), ('deadline', 'Deadline', 10),
               ('confidence', 'Confidence', 24), ('endpoints', 'Endpoint', None),
               ('flags', 'Flags', None), ('url', 'Source URL', None)]
    values = [{k: ' '.join((', '.join(r[k]) if isinstance(r[k], list) else str(r[k])).split())
               for k, _, _ in columns} for r in rows]
    widths = {k: width or max([len(label)] + [len(r[k]) for r in values])
              for k, label, width in columns}
    def render(row):
        return '  '.join((row[k][:widths[k]-3] + '...' if len(row[k]) > widths[k] else row[k]).ljust(widths[k])
                         for k, _, _ in columns).rstrip()
    lines = [render({k: label for k, label, _ in columns})]
    lines.extend(render(row) for row in values)
    if not rows: lines.append('No open dated candidates found.')
    return '\n'.join(lines)


def save(out, rows, record, limit=15):
    out.mkdir(parents=True, exist_ok=True)
    fields = ['name', 'amount', 'deadline', 'confidence', 'url', 'endpoints', 'flags']
    with (out / 'results.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in rows: writer.writerow({k: ', '.join(r[k]) if isinstance(r[k], list) else r[k] for k in fields})
    shown = rows[:limit] if limit else rows
    def esc(value): return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    md = [DISCLAIMER, '', f"Query: {esc(record['query'])}", f"Run time: {record['run_time']}", 'Endpoints used: ' + ', '.join(sorted({c['path'] for c in record['requests']})), cost_line(record['requests']), f'showing {len(shown)} of {len(rows)} rows', '', '| Name | Amount | Deadline | Confidence | Source URL | Endpoint | Flags |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in shown:
        url = r['url']
        md.append('| ' + ' | '.join([esc(r[k]) for k in fields[:4]] + [f'[source](<{url}>)', esc(', '.join(r['endpoints'])), esc(', '.join(r['flags']))]) + ' |')
    (out / 'results.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    (out / f'raw-{stamp}.json').write_text(json.dumps(record, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--field')
    p.add_argument('--level')
    p.add_argument('--year', type=int)
    p.add_argument('--count', type=int, choices=[10, 15, 20], default=10)
    p.add_argument('--limit', type=int, default=15, help='Maximum displayed rows; 0 shows all')
    p.add_argument('--hide-unclear', action='store_true', help='Drop rows with an empty deadline or flagged unclear if deadline or date negated by source')
    p.add_argument('--out', type=Path, default=Path('./out'))
    p.add_argument('--key-file', type=Path, default=Path('~/.desearch_api_key').expanduser())
    p.add_argument('--no-web', action='store_true')
    p.add_argument('--no-js', action='store_true', help='Disable js_required extraction retries')
    p.add_argument('--verify', type=int, default=3)
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--today', type=dt.date.fromisoformat, default=dt.date.today())
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--from-raw', type=Path)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.limit < 0: p.error('limit must be nonnegative')
    if args.verify < 0 or args.timeout <= 0: p.error('verify must be nonnegative and timeout must be positive')
    if not args.from_raw and not all((args.field, args.level, args.year)): p.error('--field, --level and --year are required')
    query = f'{args.field} {args.level} scholarships {args.year} application deadline'
    webquery = f'{args.field} {args.level} scholarships {args.year} deadline'
    if len(query) > 2000: p.error('query exceeds 2000 characters')
    if args.dry_run:
        print('POST /search ' + json.dumps(dict(query=query, count=args.count, highlights=True)))
        if not args.no_web: print('GET /web ' + json.dumps(dict(query=webquery)))
        print(f'GET /web/extract?url=<candidate URL>&format=text for up to {args.verify} candidate pages, preferring non-aggregators')
        if not args.no_js: print('Each js_required response may trigger one retry with js=true&wait=3000 and a timeout of at least 45 seconds (separate billing tier).')
        print(cost_line([]), file=sys.stderr)
        return 0
    client = None
    saved = False
    try:
        if args.from_raw:
            record = json.loads(args.from_raw.read_text(encoding='utf-8'))
            calls = record['requests']
            query = record.get('query', '')
        else:
            key = args.key_file.read_text().strip() if args.key_file.exists() else os.environ.get('DESEARCH_API_KEY', '').strip()
            if not key: raise SourceError('No API key found')
            client = Client(key, args.timeout, no_js=args.no_js)
            success = 0
            failed = []
            plans = [('POST', '/search', dict(query=query, count=args.count, highlights=True))]
            if not args.no_web: plans.append(('GET', '/web', dict(query=webquery)))
            for method, path, params in plans:
                try:
                    client.request(method, path, params)
                    success += 1
                except SourceError as exc:
                    failed.append(path)
                    print(f'{path} unavailable: {exc}', file=sys.stderr)
            if not success:
                print('All sources failed: ' + ', '.join(failed), file=sys.stderr)
                return 2
            rows = rebuild(client.calls, args.today)
            urls = []
            for row in sorted(rows, key=lambda r: (r['aggregator'], r['deadline'])):
                if row['deadline'] and normalized_url(row['url']) not in {normalized_url(u) for u in urls}: urls.append(row['url'])
            for url in urls[:args.verify]:
                try: client.request('GET', '/web/extract', dict(url=url, format='text'))
                except SourceError: pass
            calls = client.calls
        rows = rebuild(calls, args.today)
        if client: rows = client.clean(rows)
        record = dict(query=query, run_time=dt.datetime.now().astimezone().isoformat(), today=args.today.isoformat(), requests=calls)
        if client: record = client.clean(record)
        if args.hide_unclear:
            rows = [r for r in rows if r['deadline'] and
                    not any(flag in r['flags'] for flag in ('unclear if deadline', 'date negated by source'))]
        save(args.out, rows, record, args.limit)
        saved = True
        shown = rows[:args.limit] if args.limit else rows
        print(DISCLAIMER + f'\n\nshowing {len(shown)} of {len(rows)} rows\n\n' + table(shown))
        if not client: print(cost_line(calls), file=sys.stderr)
        return 0
    except AuthenticationError:
        print('Authentication failed', file=sys.stderr)
        return 1
    except (SourceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(client.clean(str(exc)) if client else str(exc), file=sys.stderr)
        return 1
    finally:
        if client:
            if client.calls and not saved:
                try:
                    save(args.out, [], client.clean(dict(query=query, run_time=dt.datetime.now().astimezone().isoformat(), today=args.today.isoformat(), requests=client.calls)))
                except OSError:
                    print('Could not save request log', file=sys.stderr)
            print(cost_line(client.calls), file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
