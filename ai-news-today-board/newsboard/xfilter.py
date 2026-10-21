"""Small display filter. Tune WORDS or DEMO_X_MIN_ENGAGEMENT as needed."""
import os
import re

WORDS = ("fuck", "shit", "porn", "pornography", "nsfw", "xxx")
BLOCKED = re.compile(r"\b(?:" + "|".join(map(re.escape, WORDS)) + r")\b", re.I)
LINK = re.compile(r"https?://\S+", re.I)


def keep_post(post, min_engagement=None):
    if os.environ.get("DEMO_X_FILTER", "1") == "0":
        return True
    text = str(post.get("text") or "")
    if BLOCKED.search(text):
        return False
    if any(post.get(k) for k in ("in_reply_to_status_id", "in_reply_to_status_id_str", "in_reply_to_user_id", "is_reply", "reply_to")):
        return False
    if min_engagement is None:
        try:
            min_engagement = int(os.environ.get("DEMO_X_MIN_ENGAGEMENT", "5"))
        except ValueError:
            min_engagement = 5
    engagement = sum(v if isinstance(v, int) and v > 0 else 0 for v in
                     (post.get("like_count"), post.get("retweet_count"), post.get("reply_count")))
    has_link = LINK.search(text) or (post.get("entities") or {}).get("urls")
    return bool(has_link) or engagement >= min_engagement
