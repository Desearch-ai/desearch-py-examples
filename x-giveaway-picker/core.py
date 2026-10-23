"""Network-free giveaway collection orchestration and entry rules.

fetch(path, params) is injected and returns (HTTP status, JSON body, headers).
"""
import csv
import datetime as dt
import io
import random
import re

MAX_RETWEETER_PAGES = 25
CSV_FIELDS = ['user_id', 'username', 'followers', 'account_created_at',
              'reposted', 'replied', 'tags', 'eligible', 'reason']


def clean_post(value):
    value = str(value or '').strip()
    if re.fullmatch(r'[0-9]+', value):
        return f'https://x.com/i/status/{value}'
    if not re.fullmatch(r'https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,15}/status/[0-9]+/?(?:\?[^#\s]*)?', value, re.I):
        raise ValueError('Enter an X post URL or numeric post id.')
    return value


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


def pick(fetch, post, *, now=None, draw_timestamp=None, **rules):
    options = validate(post, **rules)  # Validate everything before the first billed request.
    now = now or dt.datetime.now(dt.timezone.utc)
    now = now.replace(tzinfo=dt.timezone.utc) if now.tzinfo is None else now.astimezone(dt.timezone.utc)
    stamp = parse_time(draw_timestamp) if draw_timestamp is not None else now
    if stamp is None:
        raise ValueError('Invalid draw timestamp.')
    notices, cost = [], 0.0

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
            raise RuntimeError(f'Desearch returned HTTP {status}')
        return body

    posts = request('/twitter/urls', {'urls': options['url']})
    if not posts:
        return dict(error='post not found or not public', entrants=[], winners=[], notices=[], cost_usd=cost)
    source = posts[0]
    post_id, author = str(source['id']), source.get('user') or {}
    reposters, replies = {}, []
    if options['must_repost']:
        cursor, seen = None, set()
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
                except Exception:
                    body = None
            if body is None:
                notices.append('reposter collection stopped early after a failed page and retry')
                break
            for user in body['users']:
                if user.get('id') is not None:
                    reposters.setdefault(str(user['id']), user)
            cursor = body.get('next_cursor')
            if cursor is None:
                break
            if page + 1 == MAX_RETWEETER_PAGES:
                notices.append('first 500 reposters only')
                break
            if cursor in seen:
                notices.append('reposter collection stopped early: repeated cursor')
                break
            seen.add(cursor)
    if options['must_reply']:
        try:
            body = request('/twitter/replies/post', {'post_id': post_id, 'count': options['count']})
            replies = body if isinstance(body, list) else body.get('tweets', body.get('replies', []))
        except Exception:
            notices.append('reply collection stopped early')
        notices.append(f"from the latest ~{len(replies)} replies the API returned (post shows {source.get('reply_count', 0)} replies)")
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
            reasons.append('must reply')
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
    return dict(entrants=rows, winners=draw([r for r in rows if r['eligible']], options['winners'], seed),
                seed=seed, notices=notices, coverage=coverage, cost_usd=cost,
                returned_reposters=len(reposters), reported_reposts=source.get('retweet_count', 0))


def to_csv(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
