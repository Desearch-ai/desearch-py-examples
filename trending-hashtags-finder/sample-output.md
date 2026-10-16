# Sample output

Made by Desearch | https://desearch.ai

Command (2026-10-16 14:34 Asia/Tbilisi):

```bash
python find_hashtags.py --countries US=23424977,GB=23424975,IN=23424848,JP=23424856,Worldwide=1 --top 6 --sample 20 --hours 6 --check-empty "#qzxvplorbintrend2026"
```

Console log (stderr) said `12 calls, header total $0.0539`.

## Trending hashtags on X, 2026-10-16 14:35 +04

### Hashtags among trends

| Country | Hashtags | Trends |
|---|---|---|
| US | 5 | 50 |
| GB | 5 | 50 |
| IN | 5 | 50 |
| JP | 5 | 50 |
| Worldwide | 5 | 50 |

### Shortlist

| Hashtag | Countries (rank) | Sample | Accounts | Newest (min) | Posts/h | Median likes | Lang | Also used with | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| #それスノ | JP (1), Worldwide (1) | 20 | 20 | 0 | 6545.5 | 0.0 | ja | #恋とき #mentor #竹財輝之助 | use: trending in several countries |
| #NayyiNavellionDistrict | IN (1) | 18 | 18 | 0 | 568.4 | 0.0 | en | - | use: local |
| #DIESELxJENO | Worldwide (2) | 8 | 8 | 0 | 1371.4 | 0.0 | en | #JAEMINxLeeJeans #JAEMIN_LeeAPACAmbassador | use: local |
| #Whalefall | IN (2) | 19 | 17 | 0 | 53.7 | 1 | en | #Tesla #Ranabaali #WorldFoodDay | use: local |
| #[political-tag] | IN (3) | 17 | 15 | 0 | 104.3 | 0 | hi | #AbhijeetDipke #Ranabaali #WhaleFallMovie | use: local |
| #MCIPSG | GB (5) | 7 | 7 | 9 | 1.4 | 0 | fr | #Akliouche #yağmur #BuenosDíasATodos | use: local |
| #Tesla | IN (5) | - | - | - | - | - | - | - | not sampled |
| #毎週金曜はおつピザ | JP (5) | - | - | - | - | - | - | - | not sampled |
| #รับได้ใช่ไหมByAuAu | Worldwide (6) | - | - | - | - | - | - | - | not sampled |
| #يوم_الجمعه | Worldwide (8) | - | - | - | - | - | - | - | not sampled |
| #日向坂ちゃんねる | JP (8) | - | - | - | - | - | - | - | not sampled |
| #AytaçDikmenPBLKögren | Worldwide (9) | - | - | - | - | - | - | - | not sampled |
| #君島みお | JP (9) | - | - | - | - | - | - | - | not sampled |
| #FourthConcertD1 | US (10) | - | - | - | - | - | - | - | not sampled |
| #CelebrityTraitors | GB (12) | - | - | - | - | - | - | - | not sampled |
| #OlandriaxWWW20 | US (12) | - | - | - | - | - | - | - | not sampled |
| #Ranabaali | IN (12) | - | - | - | - | - | - | - | not sampled |
| #アニポケ | JP (15) | - | - | - | - | - | - | - | not sampled |
| #lovestruck | GB (28) | - | - | - | - | - | - | - | not sampled |
| #ThisIsMyCrew | US (30) | - | - | - | - | - | - | - | not sampled |
| #FridayFeeling | GB (31) | - | - | - | - | - | - | - | not sampled |
| #ASongOrMovieForLeading | GB (32) | - | - | - | - | - | - | - | not sampled |
| #WinOurWay | US (32) | - | - | - | - | - | - | - | not sampled |
| #LaGranjaSalvación | US (36) | - | - | - | - | - | - | - | not sampled |

Notes:

- Posts/h is measured inside the sample (20 newest posts divided by the time between oldest and newest), so a very busy hashtag shows a large number.
- `#MCIPSG` kept 7 of 15 posts: the other 8 were older than 6 hours and were dropped in code.
- Example post links for each row are in `samples/shortlist.csv` as `x.com/i/status/<id>`.
