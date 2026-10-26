"""Network-free giveaway collection orchestration and entry rules.

fetch(path, params) is injected and returns (HTTP status, JSON body, headers).
"""
import copy
import csv
import datetime as dt
import io
import math
import random
import re
import threading
import time
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_RETWEETER_PAGES = 25
CSV_FIELDS = ['user_id', 'username', 'followers', 'account_created_at',
              'reposted', 'replied', 'tags', 'eligible', 'reason']


class APIError(RuntimeError):
    def __init__(self, status, body=None):
        self.status = status
        self.detail = str(body.get('detail', '')) if isinstance(body, dict) else ''
        detail = self.detail or 'No detail provided'
        if status == 403 and body is None:
            message = "Desearch refused the request at the edge (HTTP 403). This is not a key problem; check the client's User-Agent and network."
        elif status in (401, 403):
            message = f'Desearch refused the API key (HTTP {status}). Check the key at console.desearch.ai.'
        elif status == 402:
            message = f'Desearch returned HTTP 402 (payment required): {detail}'
        elif status == 429:
            message = 'Desearch rate limited this request (HTTP 429). Wait and try again.'
        elif 500 <= status < 600:
            message = f'Desearch had a server error (HTTP {status}): {detail}'
        else:
            message = f'Desearch returned HTTP {status}: {detail}'
        super().__init__(message)


def local_time(value):
    stamp = parse_time(value)
    name = os.environ.get('GIVEAWAY_TZ')
    try:
        zone = ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    local = stamp.astimezone(zone)
    label = name if zone else local.tzname()
    offset = local.strftime('%z')
    return f"{local:%Y-%m-%d %H:%M} ({label}, UTC{offset[:3]}:{offset[3:]})"


def clean_post(value):
    value = str(value or '').strip()
    if re.fullmatch(r'[0-9]+', value):
        return f'https://x.com/i/status/{value}'
    if not re.match(r'https?://', value, re.I):
        value = 'https://' + value
    if not re.fullmatch(r'https?://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,15}/status/[0-9]+/?(?:\?[^#\s]*)?', value, re.I):
        raise ValueError('Enter an X post URL or numeric post id.')
    return re.sub(r'^http://', 'https://', value, flags=re.I)


def integer(value, name, minimum, maximum=None):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError(f'{name} must be an integer.')
    value = int(value)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name} is out of range.')
    return value


def validate(post, winners=1, min_tags=0, min_account_age_days=None,
             min_followers=None, must_repost=True, must_reply=False, count=50):
    url = clean_post(post)
    if not isinstance(must_repost, bool) or not isinstance(must_reply, bool) or not (must_repost or must_reply):
        raise ValueError('Select at least one entry mode.')
    return dict(url=url, winners=integer(winners, 'winners', 1, 10),
                min_tags=integer(min_tags, 'min_tags', 0, 5),
                min_account_age_days=None if min_account_age_days in (None, '') else integer(min_account_age_days, 'min_account_age_days', 0),
                min_followers=None if min_followers in (None, '') else integer(min_followers, 'min_followers', 0),
                must_repost=must_repost, must_reply=must_reply, count=integer(count, 'count', 1, 100))


def parse_time(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        try:
            parsed = dt.datetime.strptime(value, '%a %b %d %H:%M:%S %z %Y')
        except (ValueError, TypeError):
            return None
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)


def draw(entrants, number, seed):
    integer(number, 'winners', 1, 10)
    ordered = sorted(entrants, key=lambda row: row['user_id'])
    return random.Random(seed).sample(ordered, min(number, len(ordered)))


def post_id(value):
    return re.search(r'/status/([0-9]+)', clean_post(value)).group(1)


def draw_time(value, now):
    stamp = parse_time(value) if value is not None else now
    if stamp is None:
        raise ValueError('Invalid draw timestamp.')
    return stamp


def collect(fetch, options, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    now = now.replace(tzinfo=dt.timezone.utc) if now.tzinfo is None else now.astimezone(dt.timezone.utc)
    notices, cost = [], 0.0
    failed_parts = []

    def request(path, params):
        nonlocal cost
        status, body, headers = fetch(path, params)
        for key, value in headers.items():
            if key.lower() == 'x-desearch-cost-usd':
                try:
                    cost += float(value)
                except (ValueError, TypeError):
                    pass
        if status != 200:
            raise APIError(status, body)
        return body

    posts = request('/twitter/urls', {'urls': options['url']})
    if not posts:
        return dict(error='post not found or not public', source=None, reposters={}, replies=[],
                    notices=[], cost_usd=cost, collected_at=now.isoformat())
    source = posts[0]
    post_id = str(source['id'])
    reposters, replies = {}, []
    if options['must_repost']:
        cursor, seen = None, set()
        cap_with_new_ids = False
        for page in range(MAX_RETWEETER_PAGES):
            params = {'id': post_id}
            if cursor is not None:
                params['cursor'] = cursor
            body = None
            for attempt in range(2):
                try:
                    body = request('/twitter/post/retweeters', params)
                    if not isinstance(body, dict) or not isinstance(body.get('users'), list):
                        raise ValueError('Invalid retweeter response')
                    break
                except Exception as error:
                    failure_message = str(error)
                    body = None
            if body is None:
                failed_parts.append('reposters')
                notices.append('reposter collection stopped early after a failed page and retry' + (': ' + failure_message if failure_message else ''))
                break
            previous_count = len(reposters)
            for user in body['users']:
                if user.get('id') is not None:
                    reposters.setdefault(str(user['id']), user)
            if len(reposters) == previous_count:
                break
            cap_with_new_ids = page + 1 == MAX_RETWEETER_PAGES
            cursor = body.get('next_cursor')
            if cursor is None or cap_with_new_ids:
                break
            if cursor in seen:
                notices.append('reposter collection stopped early: repeated cursor')
                break
            seen.add(cursor)
        if cap_with_new_ids:
            notices.append(f'first 25 pages of reposters only ({len(reposters)} collected; more remain)')
        elif len(reposters) < source.get('retweet_count', 0):
            notices.append(f"{len(reposters)} of {source['retweet_count']} reposters collected; more may remain")
    if options['must_reply']:
        try:
            body = request('/twitter/replies/post', {'post_id': post_id, 'count': options['count']})
            replies = body if isinstance(body, list) else body.get('tweets', body.get('replies', []))
        except APIError as error:
            if error.status == 503 and (source.get('reply_count', 0) == 0 or
                    re.search(r'no replies|replies.*not found', error.detail, re.I)):
                notices.append('The post has no replies the API could find: ' + error.detail)
            else:
                failed_parts.append('replies')
                notices.append(f'reply collection failed (HTTP {error.status}): {error.detail or "No detail provided"}')
        except Exception as error:
            failed_parts.append('replies')
            notices.append('reply collection failed: ' + str(error))
        notices.append(f"from the latest ~{len(replies)} replies the API returned (post shows {source.get('reply_count', 0)} replies)")
    if options['must_repost'] and len(reposters) < source.get('retweet_count', 0):
        notices.append(f"{len(reposters)} of {source['retweet_count']} reported reposts returned; deleted, protected or uncollected accounts do not appear")
    return dict(source=source, reposters=reposters, replies=replies,
                notices=notices, failed_parts=failed_parts, cost_usd=cost, collected_at=now.isoformat(),
                reply_coverage=reply_coverage(replies, source))


def decide(collection, options, *, now=None, draw_timestamp=None, cached=False, perform_draw=True):
    now = now or parse_time(collection['collected_at'])
    now = now.replace(tzinfo=dt.timezone.utc) if now.tzinfo is None else now.astimezone(dt.timezone.utc)
    stamp = draw_time(draw_timestamp, now)
    if collection.get('error'):
        return dict(error=collection['error'], entrants=[], winners=[],
                    notices=list(collection['notices']), cost_usd=collection['cost_usd'])
    source = collection['source']
    post_id, author = str(source['id']), source.get('user') or {}
    reposters, replies = collection['reposters'], collection['replies']
    notices = list(collection['notices'])
    cost = 0.0 if cached else collection['cost_usd']
    if cached:
        collected = local_time(collection['collected_at'])
        notices.append(f'reused the list collected at {collected}; no new API calls')
    users = dict(reposters)
    reply_tags = {}
    for reply in replies:
        user = reply.get('user') or {}
        if user.get('id') is None:
            continue
        uid = str(user['id'])
        users.setdefault(uid, user)
        tags = {m.lower() for m in re.findall(r'(?<![\w@])@([A-Za-z0-9_]{1,15})\b', reply.get('text') or '')}
        tags.discard(str(author.get('username', '')).lower().lstrip('@'))
        # A single reply must meet the tag requirement; do not combine replies.
        reply_tags[uid] = max(reply_tags.get(uid, 0), len(tags))
    rows = []
    for uid, user in sorted(users.items()):
        reasons = []
        reposted, replied = uid in reposters, uid in reply_tags
        created = parse_time(user.get('created_at'))
        if uid == str(author.get('id')) or (user.get('username') and str(user['username']).lower() == str(author.get('username', '')).lower()):
            reasons.append('post author')
        if options['must_repost'] and not reposted:
            reasons.append('must repost')
        if options['must_reply'] and not replied:
            reasons.append('reply not returned')
        if options['must_reply'] and reply_tags.get(uid, 0) < options['min_tags']:
            reasons.append('not enough tags')
        if options['min_account_age_days'] is not None and (created is None or (now - created).total_seconds() < options['min_account_age_days'] * 86400):
            reasons.append('account too new or age unknown')
        followers = user.get('followers_count')
        if options['min_followers'] is not None and (followers is None or followers < options['min_followers']):
            reasons.append('not enough followers or unknown')
        rows.append(dict(user_id=uid, username=user.get('username', ''), followers=followers,
                         account_created_at=user.get('created_at', ''), reposted=reposted, replied=replied,
                         tags=reply_tags.get(uid, 0), eligible=not reasons, reason='; '.join(reasons)))
    seed = f"{post_id}:{stamp.isoformat().replace('+00:00', 'Z')}"
    coverage = f"Picked from {len(reposters)} reposts and {len(replies)} replies the API returned (post shows {source.get('retweet_count', 0)} reposts, {source.get('reply_count', 0)} replies)."
    eligible = [r for r in rows if r['eligible']]
    winners = draw(eligible, options['winners'], seed) if perform_draw else []
    message = ''
    if not eligible:
        message = 'No accounts met the rules, so no winners were drawn.'
    elif len(eligible) < options['winners'] and perform_draw:
        message = f"Only {len(eligible)} accounts met the rules, so {len(winners)} winners were drawn instead of {options['winners']}."
    exclusions = {}
    for row in rows:
        for reason in filter(None, row['reason'].split('; ')):
            exclusions[reason] = exclusions.get(reason, 0) + 1
    rules = dict(options, entry_mode='both' if options['must_repost'] and options['must_reply'] else 'reply' if options['must_reply'] else 'repost', draw_timestamp=stamp.isoformat().replace('+00:00', 'Z'))
    return dict(entrants=rows, winners=winners, drawn=perform_draw,
                rules=rules, counts=dict(entrants=len(rows), eligible=len(eligible), winners_requested=options['winners'], winners_drawn=len(winners)),
                message=message, exclusions=exclusions, reply_coverage=reply_coverage(replies, source),
                partial_reply_warning=partial_reply_warning(collection, options),
                seed=seed, notices=notices, coverage=coverage, cost_usd=cost,
                returned_reposters=len(reposters), reported_reposts=source.get('retweet_count', 0))


def reply_coverage(replies, source):
    return dict(returned=len(replies), reported=source.get('reply_count', 0),
                unique_authors=len({str(r['user']['id']) for r in replies if (r.get('user') or {}).get('id') is not None}))


def partial_reply_warning(collection, options):
    coverage = reply_coverage(collection['replies'], collection.get('source') or {})
    if options['must_reply'] and coverage['returned'] < coverage['reported']:
        return (f"Only {coverage['returned']} of {coverage['reported']} replies came back from the API. "
                "People whose reply was not returned are marked 'reply not returned' and cannot win. Consider repost-only mode.")
    return ''


def pick(fetch, post, *, now=None, draw_timestamp=None, **rules):
    options = validate(post, **rules)
    now = now or dt.datetime.now(dt.timezone.utc)
    draw_time(draw_timestamp, now)
    return decide(collect(fetch, options, now=now), options, now=now,
                  draw_timestamp=draw_timestamp)


class RateLimiter:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.runs = {}

    def allow(self, ip):
        with self.lock:
            now = self.clock()
            self.runs = {key: [t for t in times if now - t < 86400]
                         for key, times in self.runs.items() if times and now - times[-1] < 86400}
            times = self.runs.get(ip, [])
            recent = [t for t in times if now - t < 600]
            waits = []
            if len(recent) >= 2:
                waits.append(recent[-2] + 600 - now)
            if len(times) >= 5:
                waits.append(times[-5] + 86400 - now)
            if waits:
                return False, max(1, math.ceil(max(waits)))
            self.runs.setdefault(ip, []).append(now)
            return True, 0


class CollectionCache:
    def __init__(self, ttl=3600, clock=time.time, max_entries=100):
        if ttl <= 0 or max_entries < 1:
            raise ValueError('Cache bounds must be positive.')
        self.ttl, self.clock, self.max_entries = ttl, clock, max_entries
        self.lock = threading.Lock()
        self.entries = {}

    @staticmethod
    def key(options):
        return (post_id(options['url']), options['must_repost'], options['must_reply'], options['count'])

    def get(self, key):
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if now - v[0] < self.ttl}
            entry = self.entries.get(key)
            return copy.deepcopy(entry[1]) if entry else None

    def put(self, key, collection):
        if collection.get('error') or collection.get('failed_parts'):
            return
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if now - v[0] < self.ttl}
            self.entries.pop(key, None)
            if len(self.entries) >= self.max_entries:
                del self.entries[min(self.entries, key=lambda k: self.entries[k][0])]
            self.entries[key] = (now, copy.deepcopy(collection))

    @staticmethod
    def needed(options):
        pid = post_id(options['url'])
        return [(pid, 'post')] + ([(pid, 'reposters')] if options['must_repost'] else []) + ([(pid, 'replies', options['count'])] if options['must_reply'] else [])

    def snapshot(self, options):
        return {key: self.get(key) for key in self.needed(options)}

    def collect(self, fetch, options, parts, now):
        """Replay cached responses through the same collector, billing only new fetches.

        Store all pages of a part together so incomplete failures cannot become hits.
        Replaying keeps each part's pagination and notices identical on a redraw.
        """
        records = {}
        reused = []
        def wrapped(path, params):
            kind = {'/twitter/urls': 'post', '/twitter/post/retweeters': 'reposters', '/twitter/replies/post': 'replies'}[path]
            key = next(k for k in parts if k[1] == kind)
            part = parts[key]
            if part is not None:
                index = records.get(key, 0)
                records[key] = index + 1
                if index == 0:
                    reused.append(part['collected_at'])
                status, body, _ = part['responses'][index]
                return status, copy.deepcopy(body), {}
            response = fetch(path, params)
            records.setdefault(key, []).append(copy.deepcopy(response))
            return response
        collection = collect(wrapped, options, now=now)
        if not collection.get('error'):
            for key, responses in records.items():
                if parts[key] is None and key[1] not in collection.get('failed_parts', []):
                    self.put(key, dict(responses=responses, collected_at=now.isoformat()))
        for stamp in sorted(set(reused)):
            collection['notices'].append(f'reused the list collected at {local_time(stamp)}; no new API calls for cached parts')
        return collection


def to_csv(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
