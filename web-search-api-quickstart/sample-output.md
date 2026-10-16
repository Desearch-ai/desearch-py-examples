# Sample output

Run on 2026-10-16 15:14 (Asia/Tbilisi): `GET /search?q=bittensor+subnet&pages=2`.

- 2 Desearch calls (`start=0`, `start=20`), 19 + 20 results, 2 repeated URLs dropped, 37 results returned.
- Cost from the `X-Desearch-Cost-Usd` header: $0.001 per call, $0.002 total. Time: 8.87 s for both calls.
- The same request again within 10 minutes: `"cached": true`, `"calls": 0`, answered in about 2 ms.

First results (trimmed):
```json
{"rank": 3, "domain": "bittensor.com", "title": "Running a subnet - Bittensor Docs", "url": "https://www.bittensor.com/docs/guides/subnets"}
{"rank": 5, "domain": "docs.learnbittensor.org", "title": "Subnet Configuration (Hyperparameters) | Bittensor", "url": "https://docs.learnbittensor.org/subnets/subnet-hyperparameters"}
```
Full response: `samples/search-bittensor-subnet.json`. HTML page: `samples/page.html`. Em dashes in third-party page titles are shown as hyphens.

Bad requests (no API call, HTTP 400):
```
/search?q=            {"error": "Enter a search query."}
/search?q=ok&pages=9  {"error": "Pages must be 1 to 3."}
/search?q=<301 chars> {"error": "A query is at most 300 characters."}
```
