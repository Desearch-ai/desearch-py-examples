"""Capture exactly two paid calls, or build the saved sample offline."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from searchapp import core
from searchapp.client import Client
from searchapp.service import shape_search, shape_answer

ROOT = Path(__file__).resolve().parents[1]
BANNED_NAMES = ('perplexity', 'tavily', 'exa', 'serpapi', 'serper', 'brave', 'bing', 'google', 'firecrawl', 'jina', 'apify', 'kagi', 'you.com', 'scrapingdog', 'chatgpt', 'openai')
BANNED = re.compile(r'\b(?:' + '|'.join(re.escape(x) for x in BANNED_NAMES) + r')\b', re.I)


def normalize(value, field='$'):
    if isinstance(value, str):
        value = value.replace('\u2014', '-').replace('\u2013', '-')
        if BANNED.search(value):
            raise ValueError('Banned name in field ' + field)
    elif isinstance(value, dict):
        value = {k: normalize(v, field + '.' + k) for k, v in value.items()}
    elif isinstance(value, list):
        value = [normalize(v, f'{field}[{i}]') for i, v in enumerate(value)]
    return value


def build():
    search, answer = [json.loads((ROOT / 'tests/fixtures' / ('sample-' + kind + '.json')).read_text()) for kind in ('search', 'answer')]
    s = shape_search(search['query'], search['body'], search['mode'], search['count'], search['start_date'], search['end_date'], search['cost'], search['latency'])
    a = shape_answer(answer['query'], answer['body'], [r['url'] for r in s['results']], answer['cost'], answer['latency'])
    return normalize(dict(search=s, answer=a, sample=True, saved_at=search['captured_at'], note='This is a saved real run.'))


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    capture = sub.add_parser('capture')
    capture.add_argument('query')
    capture.add_argument('--range', default='year')
    sub.add_parser('build')
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            sample = build()
            slug = re.sub(r'[^a-z0-9]+', '-', sample['search']['query'].lower()).strip('-')
            for path in (ROOT / 'public/sample.json', ROOT / 'samples' / (slug + '.json')):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(dump(sample))
            print(f"Built saved sample: {sample['search']['query']} | {len(sample['search']['results'])} results | captured {sample['saved_at']} | public/sample.json and samples/{slug}.json")
        else:
            key = os.getenv('DESEARCH_API_KEY', '').strip()
            if not key:
                raise ValueError('Set DESEARCH_API_KEY in the environment.')
            q = core.clean_query(args.query)
            start, end = core.date_window(args.range)
            client = Client(key, quiet=True)
            outputs = []
            for kind, call, payload in (('search', client.search, core.search_body(q, 'fast', 10, start, end)), ('answer', client.ai_search, core.answer_body(q))):
                status, body, rec = call(payload)
                value = dict(query=q, mode='fast', count=10, start_date=start, end_date=end,
                             captured_at=dt.datetime.now(dt.timezone.utc).isoformat(), status=status,
                             cost=rec['cost'] if rec['cost_known'] else None, latency=rec['latency_s'], body=body)
                text = dump(value)
                if key in text:
                    raise ValueError('Refusing to write output containing the key.')
                outputs.append((kind, text))
            for kind, text in outputs:
                path = ROOT / 'tests/fixtures' / ('sample-' + kind + '.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
