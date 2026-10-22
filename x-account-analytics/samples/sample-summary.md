# X account analytics: the latest 18 posts

Run at 2026-10-19T15:46:33+04:00. Data: the latest posts Desearch returned for one account (3 page(s) of `GET /twitter/user/posts`), not the full history.

Formula: engagements = likes + reposts + replies + quotes + bookmarks; ER per view % = engagements / views x 100; ER per follower % = engagements / followers x 100.

Rates use original posts, replies, threads and quotes. Reposts are left out: in testing, a repost row had 0 likes, the original post's repost count and a view count of its own, so its counts are not this account's engagement. Posts with no view count stay in the per-follower rate and are left out of the per-view rate. Times are in UTC.

## Account

| followers | posts on profile | posts analyzed | first post (UTC) | last post (UTC) | posts per day |
|---|---|---|---|---|---|
| 1739 | 690 | 18 | 2026-10-01 16:02 | 2026-10-16 14:05 | 1.21 |

Post types: 6 original, 0 replies, 12 thread replies to itself, 0 quotes, 0 reposts.

## Engagement (posts in rates: 18)

| metric | median | mean |
|---|---|---|
| engagements per post | 3.5 | 4.278 |
| ER per view % (n=18) | 4.669 | 4.576 |
| ER per follower % | 0.202 | 0.246 |

Best weekday (UTC): Thu (median engagements 4, n=9). Best hour (UTC): 16 (median engagements 4, n=5). Slots with at least 2 posts are compared by median engagements; with this few posts treat them as hints, not rules.

## By post type

| type | posts | median engagements | median ER per view % | median ER per follower % |
|---|---|---|---|---|
| thread | 12 | 3 | 6.34 | 0.173 |
| original | 6 | 7 | 2.135 | 0.403 |

## By media

| media | posts | median engagements | median ER per view % | median ER per follower % |
|---|---|---|---|---|
| none | 18 | 3.5 | 4.669 | 0.202 |

## Top posts by engagements

| date (UTC) | type | media | engagements | views | ER per view % | link |
|---|---|---|---|---|---|---|
| 2026-10-08 14:01 | original | none | 8 | 309 | 2.589 | https://x.com/desearch_ai/status/2108196144929288624 |
| 2026-10-04 16:02 | original | none | 8 | 458 | 1.747 | https://x.com/desearch_ai/status/2106777073817960868 |
| 2026-10-15 14:02 | original | none | 7 | 210 | 3.333 | https://x.com/desearch_ai/status/2110732993300148437 |
| 2026-10-13 17:02 | original | none | 7 | 358 | 1.955 | https://x.com/desearch_ai/status/2110053692263252149 |
| 2026-10-01 16:02 | original | none | 6 | 383 | 1.567 | https://x.com/desearch_ai/status/2105689843087122681 |

## Top posts by ER per view

| date (UTC) | type | media | engagements | views | ER per view % | link |
|---|---|---|---|---|---|---|
| 2026-10-15 14:02 | thread | none | 3 | 39 | 7.692 | https://x.com/desearch_ai/status/2110733125961830864 |
| 2026-10-16 14:05 | thread | none | 3 | 42 | 7.143 | https://x.com/desearch_ai/status/2111096093094347221 |
| 2026-10-15 14:02 | thread | none | 3 | 42 | 7.143 | https://x.com/desearch_ai/status/2110733042272833853 |
| 2026-10-08 14:02 | thread | none | 4 | 56 | 7.143 | https://x.com/desearch_ai/status/2108196420100698462 |
| 2026-10-01 16:15 | thread | none | 4 | 56 | 7.143 | https://x.com/desearch_ai/status/2105693086294958195 |

## Exclusions (0 posts left out of all rates, 0 more left out of the per-view rate)

- none

## Pages

| page | status | cursor sent | returned | new | repeats | next cursor | seconds |
|---|---|---|---|---|---|---|---|
| 1 | 200 | no | 9 | 9 | 0 | yes | 2.44 |
| 2 | 200 | yes | 6 | 5 | 1 | yes | 2.42 |
| 3 | 200 | yes | 4 | 4 | 0 | yes | 1.79 |
