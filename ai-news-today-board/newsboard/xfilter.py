"""Offline display filtering and compact X post presentation."""
import os
import re

WORDS = ("fuck", "fucking", "fucker", "fucked", "shit", "porn", "pornography", "nsfw", "xxx")
LINK = re.compile(r"https?://\S+", re.I)
LEET = str.maketrans({"@": "a", "$": "s", "0": "o", "1": "i", "3": "e", "!": "i", "4": "a", "5": "s", "7": "t"})
SYNONYMS = {
    "ai": "ai artificial intelligence llm llms gpt openai anthropic claude gemini llama neural machine learning generative chatgpt",
    "regulation": "regulation regulations regulate regulated law laws act policy bill compliance governance",
    "model": "model models release released launch launches weights benchmark inference",
    "llm": "llm llms language model models weights",
    "funding": "funding funded investment raised round financing",
    "agents": "agent agents agentic automation autonomous",
}
NOISE = (
    r"november\s+3|vote|voting|election|make\s+it\s+count|globalist|democrat|republican",
    r"crypto|bitcoin|btc|eth|token|tokens|memecoin|ape|airdrop",
    r"stock\s+list|stocks\s+to\s+watch|buy\s+now",
)


def normalise(text):
    return " ".join(re.findall(r"[a-z0-9]+", LINK.sub("", text.lower())))


def has_profanity(text):
    text = LINK.sub("", text.lower()).translate(LEET)
    text = re.sub(r"(?<![a-z*])(?:[a-z*][\s._-]+){2,}[a-z*](?![a-z*])",
                  lambda m: re.sub(r"[\s._-]+", "", m.group()), text)
    for token in re.findall(r"[a-z*]+", text):
        if not re.search(r"[a-z]", token):
            continue
        if token == "xxx":
            return True
        token = re.sub(r"(.)\1+", r"\1", token)
        for word in WORDS:
            if word == "xxx":
                continue
            word = re.sub(r"(.)\1+", r"\1", word)
            # A mask can replace one or more letters, including a vowel pair.
            pattern = "".join("[a-z]+" if c == "*" else re.escape(c) for c in token)
            if re.fullmatch(pattern, word):
                return True
    return False


def relevant(text, tag=None, query=None):
    context = normalise(" ".join(filter(None, (tag, query))))
    plain = LINK.sub("", text.lower())
    for pattern in NOISE:
        if re.search(r"\b(?:" + pattern + r")\b", plain) and not re.search(r"\b(?:" + pattern + r")\b", context):
            return False
    if re.search(r"\$[A-Za-z][A-Za-z0-9]*\b", plain) and not re.search(r"\b(stock|stocks|ticker|crypto|token)\b", context):
        return False
    if len(re.findall(r"\b[A-Z]{2,5}\b", LINK.sub("", text))) >= 4 and re.search(r"\bstocks?\b", plain) and not re.search(r"\bstocks?\b", context):
        return False
    if not context:
        return True
    terms = set(context.split())
    for term in tuple(terms):
        terms.update(SYNONYMS.get(term, "").split())
    return bool(terms.intersection(normalise(text).split()))


def keep_post(post, min_engagement=None, tag=None, query=None, topic=None):
    if os.environ.get("DEMO_X_FILTER", "1") == "0":
        return True
    text = str(post.get("text") or "")
    if has_profanity(text) or not relevant(text, tag or topic, query):
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


def truncate_text(text, limit=280):
    if len(text) <= limit:
        return text
    first_link = LINK.search(text)
    short = text[:limit - 1].rstrip()
    # Remove a partial URL before appending the intact first link.
    if first_link and first_link.end() > len(short):
        if first_link.start() < len(short):
            short = short[:first_link.start()].rstrip()
        return short + "… " + first_link.group()
    return short + "…"


def prepare_posts(posts, threshold=0.5):
    """Keep strongest representatives before truncating their display text."""
    kept, shingles = [], []
    for post in sorted(posts, key=lambda p: p.get("engagement", 0), reverse=True):
        words = normalise(post["title_or_text"]).split()
        current = set(zip(words, words[1:], words[2:])) if len(words) >= 3 else {tuple(words)}
        if any(len(current & other) / len(current | other) >= threshold for other in shingles if current | other):
            continue
        shingles.append(current)
        kept.append({**post, "title_or_text": truncate_text(post["title_or_text"])})
    return kept
