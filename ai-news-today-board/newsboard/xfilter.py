"""Offline display filtering and compact X post presentation."""
import os
from html import unescape
import re

WORDS = ("fuck", "fucking", "fucker", "fucked", "shit", "porn", "pornography", "nsfw", "xxx", "bitch", "fck")
LINK = re.compile(r"(?:https?://|(?<!\w)(?:t\.co/|www\.))\S+", re.I)
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
    r"coins?|crypto|bitcoin|btc|blockchain|memecoin|airdrop|wallet|defi|nft|pump|"
    r"launchpad|market\s+makers?|supply[-\s]controlled|pre-?sale|tokenomics|"
    r"mint(?:ing|ed)?(?!\s+(?:condition|green)\b)|token\s+launch|liquidity\s+pool|tge|whitelist",
    r"stock\s+list|stocks\s+to\s+watch|buy\s+now",
)


POLITICS = re.compile(
    r"\b(?:trump|newsom|wiener|biden|harris|vance|pelosi|schumer|mcconnell|"
    r"desantis|obama|macron|starmer|sunak|scholz|merz|meloni|von der leyen|"
    r"orb[aá]n|s[aá]nchez|politics|political|elections?|senators?|governors?|congress|"
    r"bill\s+sponsor\w*|legislation\s+sponsor\w*|politico|campaign\w*|"
    r"vot(?:e|es|ed|ing)|partisan|gop|democrats?|republicans?)\b", re.I)
ALLOWLIST = (
    "OpenAI", "Google DeepMind", "Google", "DeepMind", "Anthropic", "Claude",
    "Llama 4", "Meta AI", "Meta", "Hugging Face", "Mistral AI", "Microsoft",
    "Nvidia", "GitHub", "EU AI Act",
)
ALLOWED_HANDLES = {"openai", "googledeepmind", "anthropic", "claudeai", "meta",
                   "huggingface", "mistralai", "microsoft", "nvidia", "github"}


def politics_or_person(text):
    plain = LINK.sub("", text)
    if POLITICS.search(plain):
        return True
    for handle in re.findall(r"(?<![\w@])@([A-Za-z0-9_]+)", plain):
        if handle.lower() not in ALLOWED_HANDLES:
            return True
    plain = re.sub(r"(?<![\w@])@[A-Za-z0-9_]+", "", plain)
    for name in sorted(ALLOWLIST, key=len, reverse=True):
        plain = re.sub(r"\b" + re.escape(name) + r"\b", "", plain, flags=re.I)
    return bool(re.search(r"\b[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?\s+[A-Z][a-z]+\b", plain)
                or re.search(r"\bAndrii\b", plain, re.I))


def decode_text(text):
    """Decode nested HTML entities from X text before processing it."""
    while True:
        decoded = unescape(text)
        if decoded == text:
            return text
        text = decoded


def normalise(text):
    return " ".join(re.findall(r"[a-z0-9]+", LINK.sub("", text.lower())))


def has_profanity(text):
    text = LINK.sub("", text.lower()).translate(LEET)
    if re.search(r"(?<!\S)\*{3,}(?!\S)", text):
        return True
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
    text = decode_text(str(post.get("text") or ""))
    plain = LINK.sub("", text)
    if not any(c.isalnum() for c in plain):
        return False
    lang = post.get("lang", "und")
    if lang != "en":
        if lang != "und":
            return False
        plain = re.sub(r"(?<!\w)[@#]\w+", "", plain)
        letters = [c for c in plain if c.isalpha()]
        if len(letters) < 8 or sum(c.isascii() for c in letters) / len(letters) < 0.85:
            return False
    if has_profanity(text) or politics_or_person(text) or not relevant(text, tag or topic, query):
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
    text = decode_text(text)
    plain = LINK.sub("", text).strip()
    if not plain:
        return ""
    if len(text) <= limit:
        return text
    links = LINK.findall(text)
    suffix = links[0] if links else ""
    # A URL must leave room for readable text and an ellipsis.
    if len(suffix) + 3 > limit:
        suffix = ""
    budget = limit - len(suffix) - (1 if suffix else 0)
    short = plain[:max(0, budget - 1)].rstrip() + "…"
    return short + (" " + suffix if suffix else "")


def prepare_posts(posts, threshold=0.5):
    """Keep strongest representatives before truncating their display text."""
    kept, shingles = [], []
    for post in sorted(posts, key=lambda p: p.get("engagement", 0), reverse=True):
        text = decode_text(post["title_or_text"])
        display = truncate_text(text)
        if not display or not any(c.isalpha() for c in LINK.sub("", display)):
            continue
        words = normalise(text).split()
        current = set(zip(words, words[1:], words[2:])) if len(words) >= 3 else {tuple(words)}
        if any(len(current & other) / len(current | other) >= threshold for other in shingles if current | other):
            continue
        shingles.append(current)
        kept.append({**post, "title_or_text": display})
    return kept
