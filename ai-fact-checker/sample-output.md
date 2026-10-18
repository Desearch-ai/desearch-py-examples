# Sample output

Made by Desearch | https://desearch.ai

Saved run from 2026-10-18 (web search + X search, 2 calls, $0.0055), shown in the CLI format:
```
$ python3 app.py --cli "The Great Wall of China is visible from space with the naked eye" --json samples/great-wall-from-space.json --html samples/page.html
Claim: The Great Wall of China is visible from space with the naked eye
10 sources contain most of the claim's key words.
  - Multiple astronauts, including Yang Liwei and Leroy Chiao, confirmed they could not see it without magnification, citing its narrow width (around 4-5 meters) and low contrast with the surrounding landscape as reasons.
  - The myth that it is visible from space predates space travel and originated from a 1932 Ripley's Believe It or Not cartoon, but has been debunked by astronaut observations and scientific explanations.
  - While some structures like cities and large dams are visible from low Earth orbit, the Wall's size and coloration make it indistinguishable to the naked eye from space.
  (1 uncited summary sentence(s) hidden)
 1. [contradicts] Can you see the Great Wall of China from space? | BBC Sky at Night Magazine
 2. [contradicts] Artificial structures visible from space - Wikipedia
 3. [contradicts] Can you see the Great Wall of China from space? | Britannica
 ...
10. [contradicts] r/todayilearned on Reddit: TIL the Great Wall of China is not actually visible from space, its just a myth.
X posts: 1 on topic of 10 for query 'great wall china visible'. Cost $0.0055 (2 calls)
```
A made-up claim (`samples/made-up-claim.json`) returned 10 general science pages, all labelled `unclear`, and the app showed "No strong sources found".

Files: `samples/great-wall-from-space.json`, `samples/made-up-claim.json`, `samples/page.html`. Titles, snippets, summary text and post text are third-party text, quoted as returned by the API.
