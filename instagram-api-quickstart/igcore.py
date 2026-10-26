"""Validation and response normalization without network access."""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote


class InputError(ValueError):
    """Invalid user input."""


def validate_username(value):
    value = value.lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9._]{1,30}', value):
        raise InputError('username must contain 1-30 letters, digits, dots or underscores')
    return value


def validate_tag(value):
    value = value.lstrip('#')
    if not 1 <= len(value) <= 100 or not all(c.isalnum() or c == '_' for c in value):
        raise InputError('tag must contain 1-100 letters, digits or underscores')
    return value


def validate_shortcode(value):
    if '://' in value:
        parsed = urlparse(value)
        parts = parsed.path.strip('/').split('/')
        if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('instagram.com', 'www.instagram.com') or len(parts) != 2 or parts[0] not in ('p', 'reel', 'tv'):
            raise InputError('expected an Instagram post, reel or tv URL')
        value = unquote(parts[1])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise InputError('shortcode must contain letters, digits, hyphens or underscores')
    return value


def validate_count(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise InputError('count must be an integer from 1 to 100') from None
    if str(number) != str(value) or not 1 <= number <= 100:
        raise InputError('count must be an integer from 1 to 100')
    return number


def collapse(value):
    return ' '.join(str(value).split()) if value is not None else None


def validate_query(value):
    value = collapse(value)
    if not value or len(value) > 200:
        raise InputError('query must contain 1-200 characters')
    return value


def to_iso(value):
    if value is None or value == '':
        return None
    try:
        try:
            number = float(value)
        except (ValueError, TypeError):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromtimestamp(number / 1000 if number > 1e12 else number, timezone.utc)
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (ValueError, TypeError, OverflowError, OSError, AttributeError):
        return None


def normalize_media(item):
    stats = item.get('stats') or {}
    raw = item.get('createTime')
    caption = collapse(item.get('caption'))
    code = item.get('shortcode')
    views = next((v for v in (stats.get('viewCount'), stats.get('playCount'), item.get('viewCount'), item.get('playCount')) if v is not None), None)
    return dict(shortcode=code, url=item.get('url') or (f'https://www.instagram.com/p/{code}/' if code else None), type=item.get('mediaType'), created_at=to_iso(raw), created_raw=raw, likes=stats.get('likes', stats.get('likeCount', item.get('likeCount'))), comments=stats.get('comments', stats.get('commentCount', item.get('commentCount'))), views=views, caption=caption[:280] + '...' if caption and len(caption) > 280 else caption, hashtags=item.get('hashtags'), author=(item.get('author') or {}).get('username'))


def normalize_profile(obj):
    obj = dict(obj)
    for primary, fallback in [('followers', 'followersCount'), ('following', 'followingCount'), ('verified', 'isVerified'), ('private', 'isPrivate')]:
        if obj.get(primary) is None:
            obj[primary] = obj.get(fallback)
    return {key: obj.get(source) for key, source in [('username', 'username'), ('full_name', 'fullName'), ('followers', 'followers'), ('following', 'following'), ('posts', 'postsCount'), ('verified', 'verified'), ('private', 'private'), ('external_url', 'externalUrl')]} | {'biography': collapse(obj.get('biography'))}


def normalize_comment(obj):
    raw = obj.get('createTime')
    return dict(id=obj.get('id'), text=collapse(obj.get('text')), created_at=to_iso(raw), created_raw=raw, likes=obj.get('likes') if obj.get('likes') is not None else obj.get('likeCount'), replies=len(obj.get('replies') or []))


def normalize_search(obj):
    return {key: obj.get(key) for key in ('type', 'username', 'title', 'url', 'followers')}


def items_of(body):
    if isinstance(body, dict):
        body = next((body[k] for k in ('data', 'items', 'results') if isinstance(body.get(k), list)), [])
    return [item for item in body if isinstance(item, dict)] if isinstance(body, list) else []


def billing(headers):
    h = {k.lower(): v for k, v in headers.items()}
    def number(key, cast, default):
        try:
            return cast(h.get(key))
        except (ValueError, TypeError):
            return default
    return dict(cost_usd=number('x-desearch-cost-usd', float, 0.0), usage_count=number('x-desearch-usage-count', int, None), service=h.get('x-desearch-service'), currency=h.get('x-desearch-currency'), next_cursor=h.get('x-desearch-next-cursor'))
