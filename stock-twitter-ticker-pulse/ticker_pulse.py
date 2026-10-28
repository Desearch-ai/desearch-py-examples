"""Build a small, sampled public X stock ticker board using only the stdlib."""
import argparse
import socket
import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
API_URL = 'https://api.desearch.ai/twitter'
USER_AGENT = 'desearch-stock-ticker-pulse/0.1'
GROUP_PHRASES = ('join my group', 'join our group', 'join my whatsapp',
    'join the group', 'whatsapp group', 'telegram group', 'telegram channel',
    'our group', 'this community', 'join our community', 'join my community', 'free group',
    'free signals', 'dm me for', 'link in bio', 'join us on telegram', 'join us on whatsapp')
INVITE_LINKS = ('chat.whatsapp.com',
    'wa.me/', 't.me/', 'telegram.me', 'discord.gg', 'discord.com/invite')
BULLISH = 'bullish buy buying long calls breakout moon rally beat upgrade undervalued rip'.split()
BEARISH = 'bearish sell selling short puts dump crash miss downgrade overvalued drop bagholder'.split()
CASHTAG = re.compile('(?<![A-Za-z0-9])\\$([A-Za-z]{1,6})\\b')


def normalize_tickers(values, maximum=10):
    """Validate and deduplicate ticker symbols in input order."""
    result = []
    for value in values:
        ticker = value.strip().removeprefix('$').upper()
        if not re.fullmatch('[A-Z]{1,6}', ticker):
            raise ValueError('Invalid ticker: expected 1 to 6 letters, optionally prefixed with $.')
        if ticker not in result:
            result.append(ticker)
    if len(result) > maximum:
        raise ValueError('Watchlist exceeds --max-tickers.')
    return result


def cashtags(post):
    """Collect distinct cashtags from entities and post text."""
    symbols = (post.get('entities') or {}).get('symbols') or []
    entity_tags = {
        symbol['text'].upper().lstrip('$') for symbol in symbols if symbol.get('text') }
    text_tags = {tag.upper() for tag in CASHTAG.findall(post.get('text') or '')}
    return entity_tags | text_tags


def spam_reasons(post, ticker, max_cashtags=5):
    """List matching spam rules and the off-topic rule."""
    text = (post.get('text') or '').lower()
    urls = (post.get('entities') or {}).get('urls') or []
    searchable = text + ' ' + ' '.join((str(u.get('expanded_url') or '').lower() for u in urls))
    tags = cashtags(post)
    reasons = []
    if any((link in searchable for link in INVITE_LINKS)):
        reasons.append('invite_link')
    if any((phrase in text for phrase in GROUP_PHRASES)):
        reasons.append('group_pitch')
    if len(tags) >= max_cashtags:
        reasons.append('watchlist_spam')
    if ticker.upper() not in tags:
        reasons.append('off_topic')
    return reasons


def filter_group(reasons):
    """Assign one group, with spam taking precedence over off-topic."""
    if any(reason in ('invite_link', 'group_pitch', 'watchlist_spam') for reason in reasons):
        return 'spam'
    return 'off_topic' if 'off_topic' in reasons else 'kept'


def parse_date(value):
    """Parse an X timestamp as UTC, returning None for invalid dates."""
    try:
        return datetime.strptime(value, '%a %b %d %H:%M:%S %z %Y').astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def cost_value(value):
    """Accept only finite, nonnegative cost values."""
    try:
        number = float(value)
        return number if number >= 0 and number < float('inf') else None
    except (TypeError, ValueError):
        return None


def plan_calls(tickers, args, today):
    """Build one request per selected ticker and sort."""
    calls = []
    for ticker in tickers:
        for sort in ('Latest', 'Top'):
            if args.latest_only and sort == 'Top' or (args.top_only and sort == 'Latest'):
                continue
            params = dict(query='$' + ticker, sort=sort, count=args.count)
            if args.lang:
                params['lang'] = args.lang
            if sort == 'Top':
                params.update(start_date=(today - timedelta(days=args.days)).isoformat(),
                    min_likes=args.min_likes)
            calls.append(dict(ticker=ticker, sort=sort, params=params))
    return calls


def fetch_call(planned, key, timeout=60):
    """Fetch once and retain safe errors, timing, and billing metadata."""
    call = dict(
        planned,
        status=0,
        cost_header=None,
        posts=[],
        error='',
    )
    headers_received = False
    started = time.monotonic()
    request = urllib.request.Request(API_URL + '?' + urllib.parse.urlencode(planned['params']),
        headers={'Authorization': key, 'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers_received = True
            call['status'] = response.status
            call['cost_header'] = response.headers.get('X-Desearch-Cost-Usd')
            call['usage_count'] = response.headers.get('X-Desearch-Usage-Count')
            payload = json.load(response)
            if not isinstance(payload, list):
                raise ValueError('Expected a JSON array')
            call['posts'] = payload
    except urllib.error.HTTPError as exc:
        call['status'] = exc.code
        call['cost_header'] = exc.headers.get('X-Desearch-Cost-Usd') if exc.headers else None
        call['usage_count'] = exc.headers.get('X-Desearch-Usage-Count') if exc.headers else None
        try:
            body = exc.read().decode('utf-8', errors='replace')
            snippet = ' '.join(body.replace(key, '[REDACTED]').split())[:200]
            call['error'] = f'HTTP {exc.code}' + (': ' + snippet if snippet else '')
        except (TimeoutError, socket.timeout):
            call['error'] = 'timeout after headers'
        except Exception:
            call['error'] = 'body read failed after headers'
    except (TimeoutError, socket.timeout):
        call['error'] = 'timeout after headers' if headers_received else 'timeout'
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            call['error'] = 'timeout after headers' if headers_received else 'timeout'
        else:
            call['error'] = ('body read failed after headers' if headers_received
                             else 'Request or response processing failed')
    except Exception:
        call['error'] = ('body read failed after headers' if headers_received
                             else 'Request or response processing failed')
    call['latency_s'] = round(time.monotonic() - started, 2)
    cost = cost_value(call['cost_header'])
    print( f"ticker={call['ticker']} sort={call['sort']} "
        f"status={call['status']} posts={len(call['posts'])} "
        f"cost_usd={(cost if cost is not None else 'unknown')} "
        f"latency_s={call['latency_s']:.2f}"
        + (" error=" + call['error'].replace(" ", "_") if call['error'] else ""),
        file=sys.stderr)
    return call


def merge_posts(calls):
    """Merge post IDs and retain every source sort and returned count."""
    merged = {}
    returned = Counter()
    for call in calls:
        returned[call['sort']] += len(call.get('posts', []))
        for post in call.get('posts', []):
            identity = str(post.get('id', ''))
            if identity not in merged:
                merged[identity] = dict(post, sorts=set())
            merged[identity]['sorts'].add(call['sort'])
    return (list(merged.values()), returned)


def keyword_tilt(kept):
    """Count bullish and bearish words in the retained sample."""
    words = Counter(re.findall('\\b\\w+\\b', ' '.join((p.get('text') or '' for p in kept)).lower()))
    bull, bear = (sum((words[w] for w in BULLISH)), sum((words[w] for w in BEARISH)))
    if bull + bear == 0:
        tilt = 'no keywords'
    elif bull > bear:
        tilt = 'more bullish words'
    elif bear > bull:
        tilt = 'more bearish words'
    else:
        tilt = 'even'
    return (bull, bear, tilt)


def ticker_stats(ticker, calls, threshold):
    """Summarize deduplicated posts after applying spam rules."""
    posts, returned = merge_posts(calls)
    for post in posts:
        post['spam_reasons'] = spam_reasons(post, ticker, threshold)
        post['filter_group'] = filter_group(post['spam_reasons'])
    kept = [p for p in posts if not p['spam_reasons']]
    dates = [parse_date(p.get('created_at')) for p in kept if 'Latest' in p['sorts']]
    dates = [d for d in dates if d is not None]
    if any(c['sort'] == 'Latest' and c.get('error') for c in calls):
        dates = []
    bull, bear, tilt = keyword_tilt(kept)
    co = Counter((tag for p in kept for tag in cashtags(p) if tag != ticker))
    viewed = [p for p in kept if p.get('view_count') is not None]
    dropped = sum(p['filter_group'] == 'spam' for p in posts)
    off_topic = sum(p['filter_group'] == 'off_topic' for p in posts)
    top = [p for p in kept if 'Top' in p['sorts']]
    top_dates = [d for p in top if (d := parse_date(p.get('created_at'))) is not None]
    top_likes = [p.get('like_count') or 0 for p in top]
    return dict(
        ticker=ticker,
        returned=dict(returned),
        unique=len(posts),
        spam_dropped=dropped,
        spam_share=round(100 * dropped / len(posts), 1) if posts else 0,
        off_topic=off_topic,
        off_topic_share=round(100 * off_topic / len(posts), 1) if posts else 0,
        kept=len(kept),
        top_oldest=min(top_dates).isoformat() if top_dates else '',
        top_newest=max(top_dates).isoformat() if top_dates else '',
        top_min_likes=min(top_likes) if top_likes else '',
        top_max_likes=max(top_likes) if top_likes else '',
        oldest=min(dates).isoformat() if dates else '',
        newest=max(dates).isoformat() if dates else '',
        span_hours=round((max(dates) - min(dates)).total_seconds() / 3600, 1) if dates else '',
        most_liked=max(kept, key=lambda p: p.get('like_count') or 0, default=None),
        most_viewed=max(viewed, key=lambda p: p['view_count'], default=None),
        co_mentions=sorted(co.items(), key=lambda pair: (-pair[1], pair[0]))[:5],
        bullish=bull,
        bearish=bear,
        tilt=tilt,
        reasons=dict(Counter((r for p in posts for r in p['spam_reasons']))),
        posts=posts,
    )


def write_csv(path, fields, rows):
    """Write UTF-8 CSV with the requested column order."""
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def anonymized(raw):
    """Copy report data and replace account names in all report strings."""
    labels = {}

    def label(username):
        """Assign a stable label on first appearance."""
        identity = username.lower()
        if identity not in labels:
            labels[identity] = f'account-{len(labels) + 1}'
        return labels[identity]
    url_pattern = re.compile('(https?://(?:www\\.)?(?:x|twitter)\\.com/)([A-Za-z0-9_]+)(/status/)',
        re.IGNORECASE)
    for call in raw['calls']:
        for post in call.get('posts', []):
            username = (post.get('user') or {}).get('username', '')
            if username:
                label(username)
            for match in url_pattern.finditer(post.get('url') or ''):
                label(match.group(2))
            for match in re.finditer('@([A-Za-z0-9_]+)', post.get('text') or ''):
                label(match.group(1))

    def replace(value):
        """Replace names and post URL accounts recursively on a copy."""
        if isinstance(value, str):
            value = url_pattern.sub(lambda match: match[1] + label(match[2]) + match[3], value)
            if labels:
                names = '|'.join((re.escape(name) for name in sorted(labels,
                    key=len, reverse=True)))
                pattern = '(?<![A-Za-z0-9_])(' + names + ')(?![A-Za-z0-9_])'
                value = re.sub(pattern, lambda match: labels[match[1].lower()], value, flags=re.I)
            return value
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value
    return replace(raw)


def board_row(s):
    """Build a ticker summary CSV row."""
    liked, viewed = (s['most_liked'], s['most_viewed'])
    likes = liked.get('like_count') or 0 if liked else ''
    fields = (
        'ticker', 'unique', 'spam_dropped', 'spam_share', 'off_topic', 'off_topic_share', 'kept', 'oldest',
        'newest', 'span_hours', 'bullish', 'bearish', 'tilt',
    )
    row = {field: s[field] for field in fields}
    row.update(
        returned_latest=s['returned'].get('Latest', 0),
        returned_top=s['returned'].get('Top', 0),
        top_likes=likes,
        top_username=(liked.get('user') or {}).get('username', '') if liked else '',
        top_url=liked.get('url', '') if liked else '',
        top_views=viewed['view_count'] if viewed else '',
        top_views_url=viewed.get('url', '') if viewed else '',
        co_mentions=json.dumps(s['co_mentions']),
        spam_reasons=json.dumps(s['reasons']),
    )
    return row


def post_row(ticker, p):
    """Build a CSV row including spam flags and normalized post text."""
    parsed = parse_date(p.get('created_at'))
    return dict(
        ticker=ticker,
        id=p.get('id', ''),
        created_at_utc=parsed.isoformat() if parsed else '',
        username=(p.get('user') or {}).get('username', ''),
        likes=p.get('like_count', 0),
        views=p.get('view_count'),
        retweets=p.get('retweet_count', 0),
        replies=p.get('reply_count', 0),
        is_retweet=str(bool(p.get('is_retweet'))).lower(),
        sorts=';'.join(sorted(p['sorts'])),
        kept=str(not p['spam_reasons']).lower(),
        filter_group=p['filter_group'],
        spam_reasons=';'.join(p['spam_reasons']),
        cashtags=';'.join(sorted(cashtags(p))),
        url=p.get('url', ''),
        text=' '.join((p.get('text') or '').split()),
    )


def render_markdown(lines):
    """Join report lines with a final newline and normalize em dashes."""
    return '\n'.join(lines).replace('\u2014', ',') + '\n'


def render(raw, out, replay=False, anonymize=False):
    """Write the board, posts, and costs as Markdown and CSV."""
    if anonymize:
        raw = anonymized(raw)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    date, calls = (raw['date'], raw['calls'])
    stats = []
    for ticker in raw['tickers']:
        ticker_calls = [call for call in calls if call['ticker'] == ticker]
        stats.append(ticker_stats(ticker, ticker_calls, raw['params']['max_cashtags']))
    original_cost = sum((cost_value(c.get('cost_header')) or 0 for c in calls))
    total, n = (0, 0) if replay else (original_cost, len(calls))
    lines = [f'# Stock Twitter Ticker Pulse, {date}',
        '', 'Made by Desearch ([https://desearch.ai](https://desearch.ai))',
        '', f"Counts come from the latest {raw['params']['count']} public X posts "
        "Desearch returned per ticker, not all mentions. Keyword tilt is a rough word count, "
        "not a signal. Not investment advice.", '',
        '| Ticker | Returned | Spam | Off-topic | Kept | Latest span (h) | Top post likes | Tilt |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    board_rows, post_rows = ([], [])
    for s in stats:
        liked, viewed = (s['most_liked'], s['most_viewed'])
        ticker_calls = [c for c in calls if c['ticker'] == s['ticker']]
        returned = '; '.join(
            f"{c['sort']}: error ({c['error']})" if c.get('error')
            else f"{c['sort']}: {len(c.get('posts', []))}" for c in ticker_calls)
        likes = liked.get('like_count') or 0 if liked else ''
        lines.append( f"| {s['ticker']} | {returned} | "
            f"{s['spam_dropped']} ({s['spam_share']}%) | {s['off_topic']} ({s['off_topic_share']}%) | {s['kept']} | "
            f"{s['span_hours']} | {likes} | {s['tilt']} |")
        row = board_row(s)
        board_rows.append(row)
        for p in s['posts']:
            post_rows.append(post_row(s['ticker'], p))
    for s in stats:
        lines += ['', '## ' + s['ticker']]
        for label, p, field in [('Most-liked',
            s['most_liked'], 'like_count'), ('Most-viewed', s['most_viewed'], 'view_count')]:
            if p:
                username = (p.get('user') or {}).get('username', '')
                lines.append(
                    f"{label}: [{p.get(field) or 0}, @{username}]({p.get('url', '')})" )
            else:
                lines.append(label + ': none')
        lines += [f"Latest UTC window: {s['oldest'] or 'unknown'} to {s['newest'] or 'unknown'}",
            f"Top window (UTC): {s['top_oldest'] or 'unknown'} to {s['top_newest'] or 'unknown'}",
            f"Top likes among kept posts: min {s['top_min_likes'] if s['top_min_likes'] != '' else 'unknown'}, "
            f"max {s['top_max_likes'] if s['top_max_likes'] != '' else 'unknown'}",
            f"Spam: {s['spam_dropped']} ({s['spam_share']}% of unique); "
            f"Off-topic: {s['off_topic']} ({s['off_topic_share']}% of unique)",
            'Co-mentioned cashtags: ' + (', '.join((f'${t}: {c}' for t,
                c in s['co_mentions'])) or 'none'),
            f"Keyword tilt: {s['bullish']} bullish, {s['bearish']} bearish, {s['tilt']} "
            "(rough word count, not a signal).",
            'Spam reasons: ' + (', '.join((f'{r}: {c}' for r,
                c in s['reasons'].items() if r != 'off_topic')) or 'none'),
            f"Off-topic reasons: off_topic: {s['reasons'].get('off_topic', 0)}"]
        for call in calls:
            if call['ticker'] == s['ticker'] and call.get('error'):
                lines.append(f"Call error ({call['sort']}): {call['error']}")
    if replay:
        lines += ['', f'Original run cost: ${original_cost:.4f} ({len(calls)} calls)']
    if any((cost_value(c.get('cost_header')) is None for c in calls)):
        lines += ['', 'Unknown costs are counted as 0 in totals.']
    lines += ['', f'Total spend this run: ${total:.4f} ({n} calls)',
        '', '| Ticker | Sort | Status | Posts | Cost USD | Latency (s) | Error |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    cost_rows = []
    for c in calls:
        value = cost_value(c.get('cost_header'))
        row = dict(
            ticker=c['ticker'],
            sort=c['sort'],
            status=c['status'],
            posts=len(c.get('posts', [])),
            cost_usd=value if value is not None else 'unknown',
            latency_s=c.get('latency_s', 0),
            error=c.get('error', ''),
        )
        cost_rows.append(row)
        lines.append('| ' + ' | '.join((str(v).replace('|',
            '\\|').replace('\n', ' ') for v in row.values())) + ' |')
    if any(c.get('error') and c.get('cost_header') is not None for c in calls):
        lines += ['', 'Some failed calls still carried a cost header; see the calls table.']
    (out / f'board-{date}.md').write_text(render_markdown(lines), encoding='utf-8')
    write_csv(out / f'board-{date}.csv', list(board_rows[0]), board_rows)
    write_csv(out / f'posts-{date}.csv',
        ['ticker', 'id', 'created_at_utc', 'username', 'likes', 'views', 'retweets', 'replies',
            'is_retweet', 'sorts', 'kept', 'filter_group', 'spam_reasons', 'cashtags', 'url', 'text'], post_rows)
    write_csv(out / f'costs-{date}.csv', list(cost_rows[0]) if cost_rows else ['ticker',
        'sort', 'status', 'posts', 'cost_usd', 'latency_s', 'error'], cost_rows)


def main(argv=None, today=None):
    """Validate options, fetch or replay data, and write reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tickers', nargs='*')
    defaults = [
        ('max-tickers', 10),
        ('count', 20),
        ('days', 3),
        ('min-likes', 50),
        ('max-cashtags', 5),
    ]
    for name, default in defaults:
        parser.add_argument('--' + name, type=int, default=default)
    parser.add_argument('--lang', default='en')
    parser.add_argument('--watchlist')
    parser.add_argument('--out', default='output')
    parser.add_argument('--from-raw')
    parser.add_argument('--key-file')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--anonymize', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--latest-only', action='store_true')
    group.add_argument('--top-only', action='store_true')
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float('inf'):
        parser.error('timeout must be positive and finite.')
    invalid = (
        not 1 <= args.count <= 100
        or args.days < 0
        or args.min_likes < 0
        or args.max_tickers < 1
        or args.max_cashtags < 1
    )
    if invalid:
        parser.error(
            'count must be 1..100; days/min-likes nonnegative; '
            'max-tickers/max-cashtags positive.'
        )
    if args.from_raw:
        try:
            raw = json.loads(Path(args.from_raw).read_text(encoding='utf-8'))
            render(raw, args.out, replay=True, anonymize=args.anonymize)
        except Exception:
            parser.error('Could not render raw file.')
        return 0
    values = list(args.tickers)
    try:
        if args.watchlist:
            contents = Path(args.watchlist).read_text(encoding='utf-8')
            for line in contents.splitlines():
                ticker = line.split('#', 1)[0].strip()
                if ticker:
                    values.append(ticker)
        tickers = normalize_tickers(values, args.max_tickers)
    except (ValueError, OSError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else 'Could not read watchlist.')
    if not tickers:
        parser.error('Provide at least one ticker or --watchlist.')
    today = today or datetime.now(timezone.utc).date()
    planned = plan_calls(tickers, args, today)
    if args.dry_run:
        for call in planned:
            print(json.dumps(call))
        return 0
    try:
        if args.key_file:
            key = Path(args.key_file).read_text(encoding='utf-8').strip()
        else:
            key = os.environ.get('DESEARCH_API_KEY', '').strip()
    except OSError:
        parser.error('Could not read key file.')
    if not key:
        parser.error('Set DESEARCH_API_KEY or provide --key-file.')
    calls = [fetch_call(call, key, args.timeout) for call in planned]
    raw = {
        'date': today.isoformat(),
        'params': {
            'count': args.count,
            'lang': args.lang,
            'days': args.days,
            'min_likes': args.min_likes,
            'max_cashtags': args.max_cashtags,
        },
        'tickers': tickers,
        'calls': calls,
    }

    def redact(value):
        """Remove credential echoes recursively before saving data."""
        if isinstance(value, str):
            return value.replace(key, '[REDACTED]')
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {redact(k): redact(v) for k, v in value.items()}
        return value
    raw = redact(raw)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f'raw-{today.isoformat()}.json').write_text(json.dumps(raw, indent=2), encoding='utf-8')
    render(raw, out, anonymize=args.anonymize)
    total = sum((cost_value(call.get('cost_header')) or 0 for call in calls))
    unknown = sum((cost_value(call.get('cost_header')) is None for call in calls))
    print(f'total_cost_usd={total:.4f} calls={len(calls)} unknown_cost_calls={unknown}',
        file=sys.stderr)
    print(str(out.resolve()), file=sys.stderr)
    return 0 if any((c['status'] == 200 and (not c.get('error')) for c in calls)) else 1
if __name__ == '__main__':
    sys.exit(main())
