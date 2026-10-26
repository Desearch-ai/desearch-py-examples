"""Functions copied verbatim from article-summarizer-mcp/article_summarizer.py and checked by a parity test."""
import collections
import re

MIN_WORDS = 150


HANDLE_RE = re.compile(r"(?<![\w/@.])@\w{1,15}\b")


NUMBER_RE = re.compile(r"(?:[$£€]\s?)?\d[\d,.]*(?:\s?(?:%|percent|bn|billion|million|m\b|k\b|trillion))?", re.I)


STOP = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only
or other our out over own said same she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you
your one two new like says say get got make made many much even well way back still""".split())


def word_count(text):
    return len(re.findall(r"\w+", text or ""))


def is_near_empty(text, min_words=MIN_WORDS):
    return word_count(text) < min_words


def sentences(text):
    """Split into sentences, keeping each one exactly as written."""
    out = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = para.strip()
        if not para:
            continue
        for s in re.split(r"(?<=[.!?\u201d\"])\s+(?=[\u201c\"A-Z0-9$£€])", para):
            s = s.strip()
            if 6 <= len(s.split()) <= 60:
                out.append(s)
    return out


def _words(s):
    return [w for w in re.findall(r"[a-z][a-z'\u2019]+", s.lower()) if w not in STOP and len(w) > 2]


def key_sentences(text, n=5):
    """The opening sentence plus the n-1 sentences that share the most frequent words, in article order."""
    sents = sentences(text)
    if len(sents) <= n:
        return sents
    freq = collections.Counter(w for s in sents for w in set(_words(s)))
    def score(i):
        ws = set(_words(sents[i]))
        return sum(freq[w] for w in ws) / (len(ws) ** 0.5 + 1)
    picked = {0}
    for i in sorted(range(1, len(sents)), key=score, reverse=True):
        if len(picked) >= n:
            break
        if all(_overlap(sents[i], sents[j]) < 0.6 for j in picked):
            picked.add(i)
    return [sents[i] for i in sorted(picked)]


def _overlap(a, b):
    wa, wb = set(_words(a)), set(_words(b))
    return len(wa & wb) / (min(len(wa), len(wb)) or 1)


def numbers_mentioned(text, limit=8):
    """Sentences that carry a figure, with the figures found. Bare years (1990-2099) alone do not count."""
    rows, seen = [], set()
    for s in sentences(text):
        figs = [m.group(0).strip(" ,.") for m in NUMBER_RE.finditer(s)]
        figs = [f for f in figs if f and not re.fullmatch(r"(19|20)\d\d", f) and not re.fullmatch(r"\d\.\d+\.?", f)]
        if figs and s not in seen:
            seen.add(s)
            rows.append({"figures": figs, "sentence": s})
        if len(rows) >= limit:
            break
    return rows


def hide_handles(text):
    return HANDLE_RE.sub("(an account)", text or "")
