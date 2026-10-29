#!/usr/bin/env python3
"""Social Media Username Checker, Python 3.10+, standard library only."""
import argparse
import concurrent.futures
import csv
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

NETWORKS = ('instagram', 'tiktok', 'x', 'facebook')
# These rules are the app's approximation of each network's public rules.
RULES = {
    'instagram': lambda h: bool(re.fullmatch(r'[A-Za-z0-9._]{1,30}', h)) and not h.startswith('.') and not h.endswith('.') and '..' not in h,
    'tiktok': lambda h: bool(re.fullmatch(r'[A-Za-z0-9._]{2,24}', h)) and not h.endswith('.'),
    'x': lambda h: bool(re.fullmatch(r'[A-Za-z0-9_]{1,15}', h)),
    'facebook': lambda h: bool(re.fullmatch(r'(?:[A-Za-z0-9.]{1,50}|[0-9]+)', h)),
}
FOOTER = "No public profile found does not mean the handle is free: it can be reserved, banned, private, suspended or deactivated. Check on the network's own signup page."
LABELS = {'found': 'found', 'not_found': 'no public profile found', 'could_not_check': 'could not check', 'invalid': 'invalid'}
NAME_KEYS = ('full_name', 'fullName', 'name', 'nickname', 'nickName', 'display_name', 'displayName', 'title')
USER_KEYS = ('username', 'user_name', 'screen_name', 'uniqueId', 'unique_id', 'canonical_username')
FOLLOW_KEYS = ('followers_count', 'follower_count', 'followers', 'followerCount')

class AuthError(Exception):
    pass


def normalize(value):
    value = value.strip()
    parsed = urllib.parse.urlparse(value if '://' in value else '//' + value)
    hosts = {'instagram.com', 'tiktok.com', 'x.com', 'twitter.com', 'facebook.com'}
    if (parsed.hostname or '').lower().removeprefix('www.') in hosts:
        value = urllib.parse.unquote(parsed.path).strip('/').split('/')[0]
        if (parsed.hostname or '').lower().removeprefix('www.') == 'facebook.com' and value == 'profile.php':
            profile_id = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
            value = profile_id if re.fullmatch(r'[0-9]+', profile_id) else ''
    return value.lstrip('@').strip()


def profile_url(network, handle):
    h = urllib.parse.quote(str(handle), safe='')
    return {'instagram': f'https://www.instagram.com/{h}/', 'tiktok': f'https://www.tiktok.com/@{h}', 'x': f'https://x.com/{h}', 'facebook': f'https://www.facebook.com/{h}'}[network]


def endpoint(network, handle):
    h = urllib.parse.quote(handle, safe='')
    if network == 'x':
        return 'https://api.desearch.ai/twitter/user/posts?' + urllib.parse.urlencode({'username': handle})
    return f'https://api.desearch.ai/desearch/{network}/profile/{h}'


def parse_profile(body, network):
    def visit(obj):
        if isinstance(obj, dict):
            # Posts contain their author under a user object. Do not mistake post titles for profiles.
            keys = set(obj)
            identity = keys.intersection(USER_KEYS) or 'id' in keys
            signals = keys.intersection(NAME_KEYS + FOLLOW_KEYS + ('verified', 'edge_followed_by', 'stats'))
            if (identity and signals) or keys.intersection(NAME_KEYS) and keys.intersection(FOLLOW_KEYS + ('edge_followed_by', 'stats')):
                return obj
            for key in ('user', 'profile', 'author', 'data', 'users', 'posts', 'results'):
                if key in obj:
                    result = visit(obj[key])
                    if result is not None:
                        return result
        elif isinstance(obj, list):
            for item in obj:
                result = visit(item)
                if result is not None:
                    return result
        return None
    if network == 'x':
        if not isinstance(body, dict) or not isinstance(body.get('user'), dict) or not body['user']:
            return None
        return visit(body['user'])
    return visit(body)


def fields(profile):
    name = next((profile[k] for k in NAME_KEYS if isinstance(profile.get(k), str)), '')
    followers = next((profile[k] for k in FOLLOW_KEYS if isinstance(profile.get(k), (int, float, str)) and not isinstance(profile.get(k), bool)), '')
    if followers == '':
        for outer, inner in (('edge_followed_by', 'count'), ('stats', 'followerCount')):
            nested = profile.get(outer)
            if isinstance(nested, dict) and isinstance(nested.get(inner), (int, float, str)):
                followers = nested[inner]
                break
    username = next((profile[k] for k in USER_KEYS if isinstance(profile.get(k), str) and profile[k]), '')
    return name, followers, username


def http_get(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode('utf-8', errors='replace')


def cost_header(headers):
    import math
    value = next((v for k, v in headers.items() if k.lower() == 'x-desearch-cost-usd'), None)
    try:
        cost = float(value)
        if not math.isfinite(cost) or cost < 0:
            raise ValueError()
        return cost, True
    except (ValueError, TypeError):
        return 0.0, False


def redact(value, key):
    if isinstance(value, dict):
        return {redact(str(k), key): redact(v, key) for k, v in value.items() if str(k).lower() != 'authorization'}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str) and key:
        return value.replace(key, '[REDACTED]')
    return value


def classify(call):
    code, body, network = call['status_code'], call['body'], call['network']
    note = call.get('error') or ''
    profile = None
    if code in (401, 403):
        detail = f" Detail: {body['detail']}" if isinstance(body, dict) and 'detail' in body else ''
        raise AuthError(f'Authentication failed (HTTP {code}). Check your Desearch API key.{detail}')
    if code == 404:
        status = 'not_found'
    elif code == 422 or call.get('status') == 'invalid':
        status = 'invalid'
    elif code == 200:
        profile = parse_profile(body, network)
        status = 'found' if profile is not None else 'could_not_check'
        if profile is None:
            note = 'empty response' if network == 'x' and body == [] else 'unrecognized response'
    else:
        status = 'could_not_check'
        if code == 503 and network == 'tiktok':
            note = 'TikTok returns 503 for some missing handles; cannot tell from an outage'
        elif not note:
            note = f'HTTP {code}' if code else 'request failed'
    if code != 200 and isinstance(body, dict) and body.get('detail'):
        note = '; '.join(filter(None, (note, str(body['detail']))))
    verified = profile.get('verified', '') if profile is not None else ''
    private = profile.get('private', '') if profile is not None else ''
    verified = verified if isinstance(verified, bool) else ''
    private = private if isinstance(private, bool) else ''
    if private is True:
        note = '; '.join(filter(None, (note, 'private account')))
    if profile is not None and network == 'facebook' and profile.get('category'):
        note = '; '.join(filter(None, (note, str(profile['category']))))
    if profile is not None and network == 'x' and isinstance(body.get('tweets'), list):
        note = '; '.join(filter(None, (note, f"{len(body['tweets'])} posts returned")))
    name, followers, canonical = fields(profile) if profile is not None else ('', '', '')
    link = profile_url(network, normalize(canonical) or call['handle']) if status == 'found' else ''
    if profile is not None and network == 'facebook' and isinstance(profile.get('url'), str) and profile['url']:
        link = profile['url']
    call['status'] = status
    return dict(handle=call['handle'], network=network, status=status, label=LABELS[status], display_name=name, followers=followers,
                profile_url=link, verified=verified, private=private,
                latency_s=call['latency_s'], cost_usd=call['cost_usd'], attempts=call['attempts'], note=note)


def check(handle, network, key, timeout, http=http_get, sleep=time.sleep):
    call = dict(handle=handle, network=network, url=endpoint(network, handle), status_code=None, status='', attempts=0,
                latency_s=0.0, cost_usd=0.0, cost_header_present=False, error='', body=None, responses=[])
    if not RULES[network](handle):
        call.update(status='invalid', error='local format rule')
        return call, classify(call)
    started = time.monotonic()
    known = True
    for attempt in range(2):
        call['attempts'] += 1
        try:
            code, headers, body = http(call['url'], {
                'Authorization': key,
                'User-Agent': 'desearch-username-checker/1.0',
                'Accept': 'application/json',
            }, timeout)
            if isinstance(body, (str, bytes)):
                try:
                    body = json.loads(body)
                except (ValueError, UnicodeError):
                    pass
            cost, present = cost_header(headers)
            known = known and present
            call.update(status_code=code, body=body, cost_usd=call['cost_usd'] + cost, cost_header_present=known)
            call['responses'].append(dict(status_code=code, body=body, cost_usd=cost, cost_header_present=present))
            if code == 503 and attempt == 0:
                sleep(2)
                continue
        except AuthError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            call.update(status_code=None, error=f'{type(exc).__name__}: {exc}')
        break
    call['latency_s'] = round(time.monotonic() - started, 6)
    call = redact(call, key)
    return call, classify(call)


def run(handles, networks, key, timeout=60, workers=8, http=http_get, sleep=time.sleep):
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check, h, n, key, timeout, http, sleep) for h in handles for n in networks]
        try:
            pairs = [f.result() for f in futures]
        except AuthError:
            for future in futures:
                future.cancel()
            raise
    return [p[0] for p in pairs], [p[1] for p in pairs]


def safe(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ').replace('[', '&#91;').replace(']', '&#93;').replace('<', '&lt;').replace('>', '&gt;')


def grid(results, networks, calls, elapsed):
    handles = list(dict.fromkeys(r['handle'] for r in results))
    lines = ['| Handle | ' + ' | '.join(networks) + ' |', '| --- | ' + ' | '.join('---' for _ in networks) + ' |']
    for handle in handles:
        cells = []
        for network in networks:
            r = next((r for r in results if r['handle'] == handle and r['network'] == network), None)
            label = safe(r['label']) if r else 'could not check'
            cells.append(f"[{label}]({r['profile_url']})" if r and r['profile_url'] else label)
        lines.append('| ' + safe(handle) + ' | ' + ' | '.join(cells) + ' |')
    for handle in handles:
        lines.extend(['', f'### {safe(handle)}', ''])
        for r in results:
            if r['handle'] == handle:
                details = [r['label'] + (' (private)' if r['status'] == 'found' and r.get('private') is True else '')]
                if r['display_name']:
                    details.append(safe(r['display_name']))
                if r['followers'] != '':
                    details.append(f"followers: {safe(r['followers'])}")
                if r['profile_url']:
                    details.append(r['profile_url'])
                if r['note']:
                    details.append(safe(r['note']))
                lines.append(f"- {r['network']}: " + '; '.join(details))
    total = sum(c['attempts'] for c in calls)
    cost = sum(c['cost_usd'] for c in calls)
    unknown = any(c['attempts'] and not c['cost_header_present'] for c in calls)
    lines.extend(['', FOOTER, '', f'Total calls: {total}; total cost from headers: ${cost:.5f}; total time: {elapsed:.3f}s' + ('; some costs unknown' if unknown else '')])
    return '\n'.join(lines) + '\n'


def main(argv=None, http=http_get, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handles', nargs='*')
    parser.add_argument('--networks', default=','.join(NETWORKS))
    parser.add_argument('--out', default='out/')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--from-raw')
    parser.add_argument('--key-file')
    parser.add_argument('--json', action='store_true', help='also print structured results as JSON')
    args = parser.parse_args(argv)
    networks = list(dict.fromkeys(args.networks.split(',')))
    if any(n not in NETWORKS for n in networks) or args.timeout <= 0 or args.workers < 1:
        parser.error('Use supported networks, a positive timeout, and at least one worker.')
    if not args.handles and not args.from_raw:
        parser.error('Provide at least one handle or --from-raw FILE.')
    started = time.monotonic()
    key = ''
    try:
        handles = list(dict.fromkeys(normalize(h) for h in args.handles))
        if args.dry_run:
            planned = [endpoint(n, h) for h in handles for n in networks if RULES[n](h)]
            print('\n'.join('GET ' + url for url in planned))
            print(f'Planned calls: {len(planned)}; max calls including one 503 retry: {len(planned) * 2}')
            return 0
        if args.from_raw:
            saved = json.loads(Path(args.from_raw).read_text())
            calls = saved['calls'] if isinstance(saved, dict) else saved
            results = [classify(c) for c in calls]
            networks = list(dict.fromkeys(c['network'] for c in calls))
        else:
            key = Path(args.key_file).read_text().strip() if args.key_file else os.environ.get('DESEARCH_API_KEY', '').strip()
            if not key:
                raise ValueError('No API key. Set DESEARCH_API_KEY or use --key-file PATH.')
            calls, results = run(handles, networks, key, args.timeout, args.workers, http, sleep)
        elapsed = time.monotonic() - started
        calls, results = redact(calls, key), redact(results, key)
        output = grid(results, networks, calls, elapsed)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        (out / f'raw-{stamp}.json').write_text(json.dumps({'calls': calls, 'elapsed_s': elapsed}, indent=2) + '\n')
        with (out / 'results.csv').open('w', newline='') as stream:
            columns = 'handle,network,status,label,display_name,followers,verified,private,profile_url,latency_s,cost_usd,attempts,note'.split(',')
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(results)
        (out / 'grid.md').write_text(output)
        print(output, end='')
        if args.json:
            print(json.dumps(results, indent=2))
        print(f"calls={sum(c['attempts'] for c in calls)} cost_usd={sum(c['cost_usd'] for c in calls):.5f} elapsed_s={elapsed:.3f}", file=sys.stderr)
        return 0
    except (AuthError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Error: ' + str(redact(str(exc), key)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
