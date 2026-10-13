# Sample output

Made by Desearch · https://desearch.ai

Run: 2026-10-12 09:38-09:40 Asia/Tbilisi, exit 0.

```bash
python arxivchatter.py "graph neural networks" --out evidence/runs
```

```json
{
 "out": "evidence/runs/20261012-093822-graph-neural-networks",
 "calls": 38,
 "chosen": 15,
 "zero_mention": 11,
 "cost_reported_usd": 0.032,
 "x_cost_calculated_usd": 0.0225
}
```

- 8 `ai-search` calls (`tools: ["arxiv"]`), 10 links each, $0.004 each (cost from the tool result).
- 15 papers kept. All 15 ids resolve in the arXiv API, and the CSV uses the arXiv title.
- 15 Extract reads of abs pages (`js: false`): 15 bodies on the first try, abstract found on all 15.
- 15 X searches: 4 papers with one X post naming them, 11 with none. All 4 posts came from paper-feed accounts that post new arXiv listings. Paper and post dates are in the CSV and digest.
- Cost: $0.032 reported + Extract $0.0075 and X $0.0225 (calculated from the pricing page) = about $0.062.

Files: `samples/papers.csv`, `samples/digest.md`.

## Top of the digest

# Arxiv Chatter Digest: graph neural networks

Papers Desearch returned and public X posts that named them. Paper window 2026-09-12 to 2026-10-12 (arXiv first-version date), X posts from each paper's date. Fetched 2026-10-12T09:38+04:00.

15 papers checked, 4 with at least one X post naming them.

## 1. Scaffold: Support Graph Theory Based Sparsification for Graph Neural Networks

https://arxiv.org/abs/2609.31466 . 2026-09-25 . Siddhartha Shankar Das, Sai Karthik Navuluru, S M Ferdous et al.

**X posts naming it:** 1

> Graph neural networks (GNNs) rely on message passing over graph edges, making their computational and memory costs strongly dependent on graph density. Graph sparsification offers a natural way to reduce these costs, but removing edges indiscriminately can distort important communication structure and degrade predictive performance. We introduce Scaffold, a topology-based, unsupervised graph...

- https://x.com/i/status/2105664332759499156 (2026-10-01, 7 likes, an X account): "Scaffold: Support Graph Theory Based Sparsification for Graph Neural Networks Siddhartha Shankar Das, Sai Karthik Navuluru, S M Ferdous, Rya"

## 2. Attention Graphons: A Graph Limit Perspective on Graph Transformers

https://arxiv.org/abs/2609.35620 . 2026-09-28 . Caio F. Deberaldini Netto, Moshe Eliasof, Luana Ruiz

**X posts naming it:** 1

> Graph Transformers produce, for each attention head, a dense $n\times n$ matrix of learned pairwise interactions. We ask a fundamental question: do these attention-induced graphs converge to a stable limit object as $n$ grows, or does the learned interaction pattern remain unstructured and size-dependent? We answer this using dense graph limit theory, treating each attention matrix as a finite...

- https://x.com/i/status/2106527055689011609 (2026-10-03, 2 likes, an X account): "Attention Graphons: A Graph Limit Perspective on Graph Transformers Caio F. Deberaldini Netto, Moshe Eliasof, Luana Ruiz https://t.co/jB2sEz"


(continues in samples/digest.md)

## Known issues

- X searches with no posts took about 30 s each (11 of 15 here); see README.
