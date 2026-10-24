"""Find sentence similarity evidence on public pages returned by Desearch."""
import argparse
from contextlib import nullcontext
import csv
from datetime import datetime
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo

import requests

NO_MATCH = 'No matching sources found among the pages the search returned for the sampled sentences. This does not prove the text is original.'
TZ = ZoneInfo('Asia/Tbilisi')
STOP = set('about after again because before being could every first other should their there these those through which while would'.split())
MATCH_COLUMNS = 'sentence_index sentence query_style rank url canonical_url title published_date score exact containment longest_run_words longest_run_share evidence_snippet snippet_score page_score verified_on_page'.split()
SENTENCE_COLUMNS = 'sentence_index sentence query_used searches results_returned matching_results best_score best_canonical_url best_url overlap found_online'.split()


def split_sentences(text):
    lines = text.strip().splitlines()
    if len(lines) > 1 and not re.search(r'[.!?]', lines[0]):
        lines = lines[1:]
    text = re.sub(r'\s+', ' ', ' '.join(lines)).strip()
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def pick_sentences(sentences, max_sentences=8, min_words=8):
    candidates = []
    for index, sentence in enumerate(sentences, 1):
        words = normalize(sentence).split()
        if len(words) >= min_words:
            weight = sum(len(w) >= 5 and w not in STOP for w in words)
            candidates.append((weight, len(words), index, sentence))
    best = sorted(candidates, key=lambda r: (-r[0], -r[1], r[2]))[:max_sentences]
    return [(r[2], r[3]) for r in sorted(best, key=lambda r: r[2])]


def query_window(sentence, max_words=18):
    words = list(re.finditer(r'\S+', sentence))
    if len(words) <= max_words:
        return sentence
    weights = [sum(len(w) >= 5 and w not in STOP for w in normalize(m.group()).split())
               for m in words]
    start = max(range(len(words) - max_words + 1),
                key=lambda i: sum(weights[i:i + max_words]))
    return sentence[words[start].start():words[start + max_words - 1].end()]


def estimate_cost(sentences, count=10, price_per_result=0.0005, query_style='quoted'):
    n = sentences if isinstance(sentences, int) else len(sentences)
    return n * (2 if query_style == 'both' else 1) * count * price_per_result


def web_cost_parts(sentences, query_style='quoted', verify_pages=3, max_pages=10,
                   web_price=0.001, extract_price=0.0005):
    n = sentences if isinstance(sentences, int) else len(sentences)
    return (n * (2 if query_style == 'both' else 1) * web_price,
            min(max_pages, n * verify_pages) * extract_price)


def score_snippet(sentence, snippet):
    return max((score_result(sentence, {'page_text': part})
                for part in [snippet, *snippet.split('...')]), key=lambda r: r['score'])


def select_candidates(rows, partial_threshold, verify_pages, max_pages):
    selected = {}
    for index in dict.fromkeys(r['sentence_index'] for r in rows):
        own = {}
        for row in rows:
            if row['sentence_index'] != index or row['snippet_score'] < partial_threshold or not row['url']:
                continue
            key = row['canonical_url']
            if key not in own or row['snippet_score'] > own[key]['snippet_score']:
                own[key] = row
        for row in sorted(own.values(), key=lambda r: -r['snippet_score'])[:verify_pages]:
            if len(selected) < max_pages:
                selected.setdefault(row['canonical_url'], row['url'])
    return selected


def response_metadata(record, response, raw=None):
    headers = {k: v for k, v in response.headers.items() if k.lower().startswith('x-desearch-')}
    record['desearch_headers'] = headers
    lower = {k.lower(): v for k, v in headers.items()}
    for key in ('cost_usd', 'usage_count', 'service'):
        value = lower.get('x-desearch-' + key.replace('_', '-'), (raw or {}).get(key))
        if value is not None and key != 'service':
            value = float(value)
        record[key] = value


def build_body(sentence, query_style='quoted', mode='balanced', count=10, max_query_words=18):
    sentence = query_window(sentence, max_query_words)
    query = '"' + sentence.replace('"', '') + '"' if query_style == 'quoted' else sentence
    if not 1 <= len(query) <= 2000:
        raise ValueError('Search query must contain 1 to 2000 characters')
    return dict(query=query, mode=mode, count=count, page_text=True, highlights=True)


def normalize(text):
    text = unicodedata.normalize('NFKC', text).lower()
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in text).split())


def score_result(sentence, result):
    page = result.get('page_text') or ' '.join(result.get('highlights') or [])
    a, b = normalize(sentence).split(), normalize(page).split()
    exact = bool(a) and ' '.join(a) in ' '.join(b)
    n = 3 if len(a) >= 3 else 2
    grams = [tuple(a[i:i+n]) for i in range(len(a)-n+1)]
    pagegrams = {tuple(b[i:i+n]) for i in range(len(b)-n+1)}
    containment = sum(g in pagegrams for g in grams) / len(grams) if grams else 0.0
    run = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match()
    # Map normalized words back to original character offsets for readable passages.
    offsets = []
    for match in re.finditer(r'\w+', page, re.UNICODE):
        offsets.extend([match.start()] * len(normalize(match.group()).split()))
    start = offsets[run.b] if run.b < len(offsets) else 0
    start = max(0, start - 70)
    snippet = page[start:start+200]
    return dict(score=1.0 if exact else containment, exact=exact, containment=containment,
                longest_run_words=run.size, longest_run_share=run.size/len(a) if a else 0,
                evidence_snippet=snippet)


def canonical_url(url):
    parts = urlsplit(url)
    if parts.hostname in ('translate.google.com', 'translate.googleusercontent.com'):
        inner = dict(parse_qsl(parts.query)).get('u')
        if inner and urlsplit(inner).scheme.lower() in ('http', 'https'):
            return canonical_url(inner)
    if parts.hostname == 'web.archive.org':
        match = re.match(r'/web/[^/]+/(.+)', parts.path)
        if match:
            return canonical_url(match.group(1) + ('?' + parts.query if parts.query else ''))
    host = (parts.hostname or '').lower()
    translated = host.endswith('.translate.goog')
    if translated:
        host = host[:-len('.translate.goog')].replace('--', '\x00').replace('-', '.').replace('\x00', '-')
    if host.startswith('www.'):
        host = host[4:]
    if parts.port:
        host += ':' + str(parts.port)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and not (translated and k.startswith('_x_tr_'))]
    return urlunsplit(('https' if parts.scheme.lower() in ('http', 'https') else parts.scheme.lower(), host, parts.path.rstrip('/'), urlencode(query), ''))


def is_mirror(url):
    host = (urlsplit(url).hostname or '').lower()
    return (host == 'archive.org' or host.endswith('.archive.org') or
            host in ('translate.google.com', 'translate.googleusercontent.com') or
            host.endswith('.translate.goog'))


def representative(urls):
    return next((url for url in urls if not is_mirror(url)), urls[0])


def group_matches(matches):
    groups = {}
    for row in matches:
        canonical = canonical_url(row['url'])
        key = (row['sentence_index'], canonical)
        previous = groups.get(key)
        urls = list(previous['mirror_urls'] if previous else [])
        if row['url'] not in urls:
            urls.append(row['url'])
        if previous is None or row['score'] > previous['score']:
            groups[key] = dict(row, canonical_url=canonical)
        groups[key]['mirror_urls'] = urls
        groups[key]['url'] = representative(urls)
    return sorted(groups.values(), key=lambda r: (r['sentence_index'], -r['score']))


def summarize(sampled, matches, calls, all_results=None, threshold=0.6, partial_threshold=0.4):
    grouped = group_matches(matches)
    sentences = []
    for index, sentence in sampled:
        rows = [r for r in (matches if all_results is None else all_results) if r['sentence_index'] == index]
        owncalls = [c for c in calls if c.get('kind') != 'extract' and c['sentence_index'] == index]
        best = max(rows, key=lambda r: r['score'], default={})
        score = best.get('score', 0)
        overlap = ('match' if score >= threshold else 'partial' if score >= partial_threshold else 'none') if best else 'none'
        sentences.append(dict(sentence_index=index, sentence=sentence,
            query_used='\n'.join(dict.fromkeys(c.get('query', '') for c in owncalls)), searches=len(owncalls),
            results_returned=sum(c['results_returned'] for c in owncalls),
            matching_results=sum(r['sentence_index'] == index for r in matches), best_score=score,
            best_canonical_url=best.get('canonical_url', ''), best_url=best.get('url', ''),
            overlap=overlap, found_online='yes' if overlap == 'match' else 'no'))
    found = sum(r['found_online'] == 'yes' for r in sentences)
    sources = {}
    for row in grouped:
        source = sources.setdefault(row['canonical_url'], dict(url=row['canonical_url'], title=row['title'],
            published_date=row['published_date'], sentences=set(), mirrors=[], best_score=0))
        source['sentences'].add(row['sentence_index'])
        source['best_score'] = max(source['best_score'], row['score'])
        for url in row['mirror_urls']:
            if url not in source['mirrors']:
                source['mirrors'].append(url)
        source['representative_url'] = representative(source['mirrors'])
    return dict(sentences=sentences, found=found, share=100*found/len(sampled) if sampled else 0,
        partial=sum(r['overlap'] == 'partial' for r in sentences),
        sources=sorted(sources.values(), key=lambda s: (-len(s['sentences']), -s['best_score'], s['url'])),
        cost=sum(c.get('cost_usd') or 0 for c in calls), calls=len(calls),
        search_cost=sum(c.get('cost_usd') or 0 for c in calls if c.get('kind') != 'extract'),
        extract_cost=sum(c.get('cost_usd') or 0 for c in calls if c.get('kind') == 'extract'),
        slowest=max((c['elapsed_ms']/1000 for c in calls), default=0),
        empty_calls=sum(c.get('kind') != 'extract' and c['results_returned'] == 0 for c in calls),
        empty_cost=sum(c.get('cost_usd') or 0 for c in calls if c.get('kind') != 'extract' and c['results_returned'] == 0))


class SearchClient:
    def __init__(self, key, session=None, timeout=90):
        self.key, self.session, self.timeout = key, session or requests.Session(), timeout

    def redact(self, value):
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if isinstance(value, str) and self.key:
            return value.replace(self.key, '[redacted]')
        return value

    def search(self, body, index, style, engine='search'):
        record = dict(time=datetime.now(TZ).isoformat(), sentence_index=index, query_style=style, query=body['query'],
            http_status=None, elapsed_ms=0, cost_usd=None, usage_count=None, service=None,
            desearch_headers={}, results_returned=0)
        start = time.monotonic()
        raw = {}
        try:
            response = (self.session.get('https://api.desearch.ai/web', params={'query': body['query']},
                headers={'Authorization': self.key, 'User-Agent': 'desearch-plagiarism-checker/1.0'}, timeout=self.timeout)
                if engine == 'web' else self.session.post('https://api.desearch.ai/search', json=body,
                headers={'Authorization': self.key, 'User-Agent': 'desearch-plagiarism-checker/1.0'}, timeout=self.timeout))
            record['http_status'] = response.status_code
            record['desearch_headers'] = {k:v for k,v in response.headers.items() if k.lower().startswith('x-desearch-')}
            try:
                raw = response.json()
            except ValueError:
                raw = {'detail': response.text}
            if not isinstance(raw, dict):
                raw = {'detail': raw}
            response_metadata(record, response, raw)
            record['results_returned'] = len(raw.get('data' if engine == 'web' else 'results') or [])
            if response.status_code >= 400:
                record['error'] = str(raw.get('detail', raw))
        except requests.RequestException as exc:
            record['error'] = str(exc) or type(exc).__name__
            raw = {'error': record['error']}
        record['elapsed_ms'] = round((time.monotonic()-start)*1000, 2)
        # Redact even if a remote error or page unexpectedly echoes credentials.
        return self.redact(record), self.redact(raw)

    def extract(self, url):
        record = dict(kind='extract', url=url, time=datetime.now(TZ).isoformat(),
                      http_status=None, elapsed_ms=0, cost_usd=None, results_returned=0,
                      desearch_headers={}, bytes=0)
        start = time.monotonic()
        text = ''
        try:
            response = self.session.get('https://api.desearch.ai/web/extract',
                params={'url': url, 'format': 'text'},
                headers={'Authorization': self.key, 'User-Agent': 'desearch-plagiarism-checker/1.0'},
                timeout=self.timeout)
            record['http_status'] = response.status_code
            response_metadata(record, response)
            text = response.text
            record['bytes'] = len(getattr(response, 'content', text.encode('utf-8')))
            if response.status_code >= 400:
                record['error'] = text
        except requests.RequestException as exc:
            record['error'] = str(exc) or type(exc).__name__
        record['elapsed_ms'] = round((time.monotonic() - start) * 1000, 2)
        return self.redact(record), self.redact(text)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', nargs='?')
    p.add_argument('--text')
    p.add_argument('--max-sentences', type=int, default=8)
    p.add_argument('--min-words', type=int, default=8)
    p.add_argument('--max-query-words', type=int, default=18)
    p.add_argument('--query-style', choices=['quoted', 'plain', 'both'], default='quoted')
    p.add_argument('--engine', choices=['web', 'search'], default='web')
    p.add_argument('--verify-pages', type=int, default=3)
    p.add_argument('--max-pages', type=int, default=10)
    p.add_argument('--web-price', type=float, default=0.001)
    p.add_argument('--extract-price', type=float, default=0.0005)
    p.add_argument('--mode', choices=['fast', 'balanced'], default='balanced')
    p.add_argument('--count', type=int, choices=[10,15,20], default=10)
    p.add_argument('--threshold', type=float, default=0.6)
    p.add_argument('--partial-threshold', type=float, default=0.4)
    p.add_argument('--replay', metavar='RAW_DIR')
    p.add_argument('--price-per-result', type=float, default=0.0005)
    p.add_argument('--max-cost', type=float, default=0.25)
    p.add_argument('--yes', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--timeout', type=float, default=90)
    p.add_argument('--out', default='output/')
    p.add_argument('--run-name', default=datetime.now(TZ).strftime('%Y%m%d-%H%M%S-%f'))
    p.add_argument('--key-file', default=os.environ.get('DESEARCH_KEY_FILE', '~/.desearch_api_key'))
    p.add_argument('--expect-fingerprint')
    return p


def write_csv(path, columns, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def cell(value):
    return str(value or '').replace('|', '\\|').replace('\n', ' ')


def write_summary(path, summary, sampled, args):
    setting_keys = ('max_sentences', 'min_words', 'query_style', 'threshold', 'partial_threshold', 'run_name', 'engine')
    setting_keys += ('mode', 'count') if args.engine == 'search' else ('verify_pages', 'max_pages')
    lines = ['# Matching sources found on the web', '', 'Input: ' + (args.file or 'inline text'),
        'Date/time: ' + datetime.now(TZ).isoformat() + ' (Asia/Tbilisi)', '',
        'Settings: ' + json.dumps(dict(input=args.file or 'inline text', **{k:getattr(args, k) for k in setting_keys})), '',
        f"{summary['found']} of {len(sampled)} sampled sentences have at least one matching public page ({summary['share']:.1f}%).", '',
        '| Canonical URL | Title | Published date | Sentences matched | Best score | Mirror count |', '| --- | --- | --- | --- | --- | --- |']
    for s in summary['sources']:
        lines.append(f"| {cell(s['representative_url'])} | {cell(s['title'])} | {cell(s['published_date'])} | {len(s['sentences'])} | {s['best_score']:.3f} | {max(0,len(s['mirrors'])-1)} |")
    for s in summary['sources']:
        if len(s['mirrors']) > 1:
            lines += ['', 'Mirror URLs for ' + cell(s['representative_url']) + ': ' + ', '.join(cell(u) for u in sorted(s['mirrors']) if u != s['representative_url'])]
    if summary['partial']:
        lines += ['', f"{summary['partial']} sampled sentences have partial overlap (score between {args.partial_threshold:g} and {args.threshold:g}); check them by hand."]
    lines += ['', '| Sentence | Text | Found online | Best score | Canonical URL | Best URL | Overlap |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in summary['sentences']:
        lines.append(f"| {r['sentence_index']} | {cell(r['sentence'])} | {r['found_online']} | {r['best_score']:.3f} | {cell(r['best_canonical_url'])} | {cell(r['best_url'])} | {r['overlap']} |")
    lines += ['', f"{'cost of the original run' if args.replay else 'Total cost'}: ${summary['cost']:.6f} USD. Calls: {summary['calls']}. Slowest call: {summary['slowest']:.2f} s.",
        f"Search cost: ${summary['search_cost']:.6f} USD. Extract cost: ${summary['extract_cost']:.6f} USD.",
        f"Empty-result calls: {summary['empty_calls']}; their cost: ${summary['empty_cost']:.6f} USD.", '',
        'How to read this: A match means the page shares that wording; it does not say who wrote it first. Sentences that were not sampled were not checked. Only pages returned by the search were compared.']
    if args.replay:
        lines += ['', 'Replay of saved responses, no new searches, cost $0']
    if not summary['found']:
        lines += ['', NO_MATCH]
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if (args.file is None) == (args.text is None):
        p.error('Supply exactly one FILE, - for stdin, or --text')
    if args.verify_pages < 0 or args.max_pages < 0 or args.max_sentences < 1 or args.min_words < 1 or args.max_query_words < 1 or not 0 <= args.threshold <= 1 or not 0 <= args.partial_threshold <= 1 or any(
        not math.isfinite(v) or v < 0 for v in (args.price_per_result, args.max_cost, args.web_price, args.extract_price)) or not math.isfinite(args.timeout) or args.timeout <= 0:
        p.error('Invalid numeric option')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_name):
        p.error('Run name must contain only letters, digits, underscores or hyphens')
    try:
        text = args.text if args.text is not None else (sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8'))
    except OSError as exc:
        print(f'Cannot read input: {exc}', file=sys.stderr)
        return 2
    sampled = pick_sentences(split_sentences(text), args.max_sentences, args.min_words)
    styles = ['quoted', 'plain'] if args.query_style == 'both' else [args.query_style]
    try:
        plan = [(index, sentence, style, build_body(sentence, style, args.mode, args.count, args.max_query_words)) for index, sentence in sampled for style in styles]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    search_estimate, extract_estimate = web_cost_parts(sampled, args.query_style, args.verify_pages, args.max_pages, args.web_price, args.extract_price) if args.engine == 'web' else (estimate_cost(sampled, args.count, args.price_per_result, args.query_style), 0)
    estimate = search_estimate + extract_estimate
    print('Planned sentences:')
    for index, sentence in sampled:
        suffix = f' (window of {args.max_query_words} words)' if query_window(sentence, args.max_query_words) != sentence else ''
        print(f'{index}: {sentence[:80]}{suffix}')
    if args.replay:
        print('Replay of saved responses, no new searches, cost $0')
    else:
        print(f'{len(plan)} searches (${search_estimate:.6f}) + extracts (${extract_estimate:.6f}); estimated max cost: ${estimate:.6f} USD (' + ('price list rate, confirm in Console' if args.engine == 'web' else 'observed rate, confirm in Console') + ')')
    sys.stdout.flush()
    if not args.replay and estimate > args.max_cost:
        print('Estimate exceeds --max-cost; refusing to run.', file=sys.stderr)
        return 4
    if args.dry_run:
        return 0
    if plan and not args.replay and not args.yes:
        if not sys.stdin.isatty():
            print('Non-interactive stdin: pass --yes to run paid searches.', file=sys.stderr)
            return 1
        answer = input(f'Run {len(plan)} paid searches for about ${estimate:.6f}? [y/N]')
        if answer.strip().lower() not in ('y', 'yes'):
            return 1
    key = ''
    if plan and not args.replay:
        try:
            key = Path(args.key_file).expanduser().read_text(encoding='utf-8').strip()
        except OSError:
            print('Cannot read key file.', file=sys.stderr)
            return 2
        if not key or (args.expect_fingerprint is not None and not hashlib.sha256(key.encode()).hexdigest().startswith(args.expect_fingerprint)):
            print('Empty key or fingerprint mismatch.', file=sys.stderr)
            return 2
    client = None if args.replay else SearchClient(key, timeout=args.timeout)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rawdir = out / (args.run_name+'-raw')
    if not args.replay:
        rawdir.mkdir(exist_ok=True)
    matches, calls, all_results = [], [], []
    saved_calls = []
    if args.replay:
        saved_log = Path(args.replay).with_name(Path(args.replay).name.removesuffix('-raw') + '-calls.jsonl')
        if saved_log.exists():
            try:
                saved_calls = [json.loads(line) for line in saved_log.read_text(encoding='utf-8').splitlines()]
            except (OSError, ValueError):
                saved_calls = []
    exit_code = 0
    with (nullcontext(None) if args.replay else (out / (args.run_name+'-calls.jsonl')).open('a', encoding='utf-8')) as log:
        for index, sentence, style, body in plan:
            if args.replay:
                try:
                    raw = json.loads((Path(args.replay) / f'{index}-{style}.json').read_text(encoding='utf-8'))
                    if not isinstance(raw, dict):
                        raise ValueError('Expected a JSON object')
                except (OSError, ValueError) as exc:
                    print(f'Cannot replay sentence {index} {style}: {exc}', file=sys.stderr)
                    return 2
                record = dict(sentence_index=index, query_style=style, query=body['query'], elapsed_ms=0,
                    http_status=None, cost_usd=raw.get('cost_usd'), results_returned=len(raw.get('data' if args.engine == 'web' else 'results') or []))
                saved = next((c for c in saved_calls if c.get('kind') != 'extract' and c.get('sentence_index') == index and c.get('query_style') == style), {})
                record['query'] = saved.get('query', record['query'])
                record['cost_usd'] = saved.get('cost_usd', record['cost_usd'])
                if 'error' in raw or ('detail' in raw and 'results' not in raw):
                    record['error'] = str(raw.get('error', raw.get('detail')))
            else:
                record, raw = client.search(body, index, style, args.engine)
            calls.append(record)
            if log is not None:
                log.write(json.dumps(record, ensure_ascii=False)+'\n')
                log.flush()
            if not args.replay:
                (rawdir / f'{index}-{style}.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"Sentence {index} {style}: {record['elapsed_ms']/1000:.2f} s, cost ${record.get('cost_usd') or 0:.6f}")
            if record['elapsed_ms'] > 20000:
                print('Warning: slow response', file=sys.stderr)
            if 'error' in record:
                print(f"API error ({record['http_status']}): {record['error']}", file=sys.stderr)
            else:
                for rank, result in enumerate(raw.get('data' if args.engine == 'web' else 'results') or [], 1):
                    evidence = (max((score_snippet(text, result.get('snippet') or '')
                                    for text in (sentence, query_window(sentence, args.max_query_words))),
                                   key=lambda r: r['score'])
                                if args.engine == 'web' else score_result(sentence, result))
                    url = result.get('link' if args.engine == 'web' else 'url', '')
                    all_results.append(dict(sentence_index=index, sentence=sentence, query_style=style, rank=rank,
                            url=url, canonical_url=canonical_url(url),
                            snippet_score=evidence['score'] if args.engine == 'web' else '', page_score='', verified_on_page='no',
                            title=result.get('title',''), published_date='' if args.engine == 'web' else result.get('published_date'), **evidence))
                    if evidence['score'] >= args.threshold:
                        matches.append(all_results[-1])
            if record['http_status'] in (401, 402):
                exit_code = 2
                break
        if args.engine == 'web' and not exit_code and args.verify_pages:
            source_dir = Path(args.replay) if args.replay else rawdir
            extracts = {}
            if args.replay and (source_dir / 'extracts.json').exists():
                try:
                    extracts = json.loads((source_dir / 'extracts.json').read_text(encoding='utf-8'))
                except (OSError, ValueError) as exc:
                    print(f'Cannot replay extracts: {exc}', file=sys.stderr)
                    return 2
            for canonical, url in select_candidates(all_results, args.partial_threshold, args.verify_pages, args.max_pages).items():
                if args.replay:
                    if url not in extracts:
                        continue
                    try:
                        page = (source_dir / extracts[url]).read_text(encoding='utf-8')
                        saved = next((c for c in saved_calls if c.get('kind') == 'extract' and c.get('url') == url), {})
                        calls.append(dict(saved, kind='extract', url=url, elapsed_ms=0, results_returned=0))
                    except OSError as exc:
                        print(f'Cannot replay extract: {exc}', file=sys.stderr)
                        return 2
                else:
                    record, page = client.extract(url)
                    calls.append(record)
                    log.write(json.dumps(record, ensure_ascii=False) + '\n')
                    log.flush()
                    if 'error' in record:
                        print(f"Extract error ({record['http_status']}): {record['error']}", file=sys.stderr)
                        if record['http_status'] in (401, 402):
                            exit_code = 2
                            break
                        continue
                    filename = f'extract-{len(extracts) + 1}.txt'
                    (rawdir / filename).write_text(page, encoding='utf-8')
                    extracts[url] = filename
                    (rawdir / 'extracts.json').write_text(json.dumps(extracts, indent=2), encoding='utf-8')
                for row in all_results:
                    if row['canonical_url'] == canonical:
                        evidence = score_result(row['sentence'], {'page_text': page})
                        row['page_score'] = evidence['score']
                        row['verified_on_page'] = 'yes' if evidence['score'] >= args.threshold else 'no'
                        if evidence['score'] > row['score']:
                            row.update(evidence)
        matches = [row for row in all_results if row['score'] >= args.threshold]
    matches.sort(key=lambda r: (r['sentence_index'], -r['score']))
    summary = summarize(sampled, matches, calls, all_results, args.threshold, args.partial_threshold)
    write_csv(out / (args.run_name+'-matches.csv'), MATCH_COLUMNS, matches)
    write_csv(out / (args.run_name+'-sentences.csv'), SENTENCE_COLUMNS, summary['sentences'])
    write_summary(out / (args.run_name+'-summary.md'), summary, sampled, args)
    print('Matching sources found on the web')
    print(f"{summary['found']} of {len(sampled)} sampled sentences have at least one matching public page ({summary['share']:.1f}%).")
    print(f"{'cost of the original run' if args.replay else 'Total cost'}: ${summary['cost']:.6f} USD; {summary['calls']} calls; slowest {summary['slowest']:.2f} s; empty-result calls {summary['empty_calls']} (${summary['empty_cost']:.6f}).")
    if not summary['found']:
        print(NO_MATCH)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
