"""Pure shaping of public Reddit thread search results."""
import re
from urllib.parse import urlsplit

SHELL_TITLES = ('Welcome to Reddit', 'Reddit - Dive into anything',
    'Reddit - The heart of the internet', 'Log in', 'Login', 'Sign up',
    'reddit.com: log in', 'Blocked', 'Reddit', 'Please wait for verification')


def build_query(topic):
    return 'site:reddit.com ' + topic


def thread_parts(link):
    if not isinstance(link, str):
        return None
    try:
        url = urlsplit(link)
        host = url.hostname or ''
        if url.scheme not in ('http', 'https') or not (host == 'reddit.com' or host.endswith('.reddit.com')):
            return None
        match = re.match(r'^/r/([A-Za-z0-9_]{2,21})/(?i:comments)/([a-z0-9]{2,12})(?:/(?:([^/]+)(?:/.*)?)?)?$', url.path)
        return match.groups(default='') if match else None
    except ValueError:
        return None


def hide_handles(text):
    text = re.sub(r'(?<![\w/])/?u/[A-Za-z0-9_-]+', 'u/[hidden]', text, flags=re.I)
    return re.sub(r'(?<![\w@])@[A-Za-z0-9_]+', '@[hidden]', text)


def shape_threads(rows):
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts = thread_parts(row.get('link'))
        if parts is None:
            continue
        sub, ident, slug = parts
        if ident in seen:
            continue
        seen.add(ident)
        title = row.get('title') if isinstance(row.get('title'), str) else ''
        title = re.sub(r'^r/[A-Za-z0-9_]+ on Reddit:\s*', '', title.strip(), flags=re.I)
        title = re.sub(r'\s*(?:: r/[A-Za-z0-9_]+|[-|] Reddit)\s*$', '', title, flags=re.I).strip()
        rebuilt = not title or any(title.lower().startswith(t.lower()) for t in SHELL_TITLES)
        if rebuilt:
            title = ' '.join(re.sub('[_-]', ' ', slug).split())
            title = (title[:1].upper() + title[1:])[:120] if title else 'Thread in r/' + sub
        snippet = row.get('snippet') if isinstance(row.get('snippet'), str) else ''
        result.append({'subreddit': 'r/' + sub, 'title': hide_handles(title),
            'title_from_link': rebuilt, 'link': f'https://www.reddit.com/r/{sub}/comments/{ident}/' + (slug + '/' if slug else ''),
            'snippet': hide_handles(' '.join(snippet.split()))[:300], 'date': None})
        if len(result) == 10:
            break
    return result
