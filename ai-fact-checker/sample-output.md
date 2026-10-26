# Sample output

Made by Desearch | https://desearch.ai

Saved source data from October 18, 2026, adapted offline to the current X-off format. No new API call was made. The $0.004 cost and one-call count describe the current web-only path; saved JSON timing is retained from the original run with X enabled.

The CLI output below was generated from `samples/great-wall-from-space.json` with the current renderer. A live CLI check uses this command:

```bash
python3 app.py --cli "The Great Wall of China is visible from space with the naked eye" --json out.json --html out.html
```

```text
Claim: The Great Wall of China is visible from space with the naked eye
10 sources returned.
  - While some structures like cities and large dams are visible from low Earth orbit, the Wall's size and coloration make it indistinguishable to the naked eye from space.
  (1 uncited summary sentence(s) hidden)
2 summary sentence(s) that judged the claim were hidden.
 1. Can you see the Great Wall of China from space? | BBC Sky at Night Magazine
    www.skyatnightmagazine.com
    https://www.skyatnightmagazine.com/space-science/can-you-see-great-wall-china-from-space
    One of the biggest is the idea that the Great Wall of China is the only human-made structure that can be seen from space. Is this true?
 2. Artificial structures visible from space - Wikipedia
    en.wikipedia.org
    https://en.wikipedia.org/wiki/Artificial_structures_visible_from_space
    The centimetre-band Spaceborne Imaging Radar of STS-59 and STS-68 was able to detect not only the Great Wall but also invisible buried segments of it. The human naked eye has an angular resolution of approximately 280 microradians (μrad) (approx 0.016° or 1 minute of arc), and the ISS targets
 3. Can you see the Great Wall of China from space? | Britannica
    www.britannica.com
    https://www.britannica.com/question/Can-you-see-the-Great-Wall-of-China-from-space
    You typically can’t see the Great Wall of China from space. A popular myth, the claim was disproved when astronauts stated that the Great Wall of China was not visible with the naked eye from the Moon.
 4. Is the Great Wall of China Visible From Space? Real Answer - Nibble Blog
    nibble-app.com
    https://nibble-app.com/blog/is-the-great-wall-of-china-visible-from-space
    Is the Great Wall of China visible from space with the naked eye, or is that an old myth astronauts and NASA have quietly debunked over several decades now?
 5. Great Wall - NASA
    www.nasa.gov
    https://www.nasa.gov/image-article/great-wall/
    The Great Wall of China and Inner Mongolia are featured in this image photographed by Expedition 10 Commander Leroy Chiao on the International Space Station. Despite myths to the contrary, the wall isn't visible from the moon, and is difficult or impossible to see from Earth orbit without the high-powered lenses used for this photo.
 6. What makes the Great Wall of China the only man-made object visible from space? | Science Questions with Surprising Answers
    www.wtamu.edu
    https://www.wtamu.edu/~cbaird/sq/2012/12/11/what-makes-the-great-wall-of-china-the-only-man-made-object-visible-from-space/
    The Great Wall of China is not visible to the naked eye from space, even in low-earth orbit, according to NASA. Even though the wall is very long, ...
 7. Can You See the Great Wall from the Space or Moon? Visibility from Outer Space
    www.travelchinaguide.com
    https://www.travelchinaguide.com/china_great_wall/facts/seen-from-space.htm
    Is the Great Wall truly visible from the moon? It is generally accepted that the Great Wall cannot be seen from the space which is proved from both the theory analysis and astronauts’ seeing.
 8. Great Wall of China is visible from space: Fact or myth? | - The Times of India
    timesofindia.indiatimes.com
    https://timesofindia.indiatimes.com/life-style/travel/news/great-wall-of-china-is-visible-from-space-fact-or-myth/articleshow/128671144.cms
    The enduring myth of the Great Wall of China being visible from space is debunked. Despite its immense length, the Wall's narrow width and similar color to its surroundings make it nearly impossible to see from orbit with the naked eye. Astronauts confirm this, highlighting that modern, larger structures are far more discernible.
 9. The Great Wall of China is not actually visible from space with the naked eye , astronauts from Apollo to the ISS have confirmed it , and the popular myth that it is predates space travel itself, with the best-known version coming from a 1932 Ripley's Believe It or Not cartoon
    spacedaily.com
    https://spacedaily.com/d-the-great-wall-of-china-is-not-actually-visible-from-space-with-the-naked-eye-astronauts-from-apollo-to-the-iss-have-confirmed-it-and-the-popular-myth-that-it-is-predates-space-tra/
    "The Great Wall of China is not visible from orbit with the naked eye. It's too narrow, and it follows the natural contours and colours of the landscape." So
10. r/todayilearned on Reddit: TIL the Great Wall of China is not actually visible from space, its just a myth.
    www.reddit.com
    https://www.reddit.com/r/todayilearned/comments/1kg3uwe/til_the_great_wall_of_china_is_not_actually/
    Veteran US astronaut Gene Cernan has stated: "At Earth orbit of 100 miles (160 km) to 200 miles (320 km) high, the Great Wall of China is, indeed, visible to the naked eye." Ed Lu, Expedition 7 Science Officer aboard the International Space
Cost $0.004 (1 calls)
```

The made-up claim in `samples/made-up-claim.json` returned general science pages. The page says "10 sources returned." A source count does not establish source quality or the claim's accuracy. With fewer than two displayed sources, the page also says "Few sources returned. Read them before you share anything."

Files: `samples/great-wall-from-space.json`, `samples/made-up-claim.json`, `samples/page.html`, `public/sample.json`. Sources are shown neutrally, without stance labels. Saved titles, snippets and summaries have HTML and punctuation cleanup applied. Summary sentences with judgment language were removed offline and counted in `summary.verdict_hidden`; the remaining cited sentences were kept. The QA regression excerpt in `samples/fixtures/eiffel-summary.json` retains the original summary as test input. X is off, so post fields and the X section are omitted. Enable X explicitly with the CLI `--x` flag or the server's `DEMO_X_ENABLED=1` setting.
