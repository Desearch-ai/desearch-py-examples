"""Rebuild the public sample offline: python scripts/rebuild_sample.py."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_news_board import build_board


def main():
    raw = json.loads((ROOT / 'samples/sample-raw.json').read_text())
    board = build_board(raw, raw['started'])
    (ROOT / 'public/sample.json').write_text(json.dumps(board, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
