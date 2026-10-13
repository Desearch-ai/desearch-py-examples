# Sample output

From my run on 2026-10-10 09:29 Asia/Tbilisi:

```bash
python answercheck.py examples/project-management.json --runs 3 --ab 3 --max-spend 0.40
```

All 63 calls returned 200. Asana is the example brand; the competitor list is in `examples/project-management.json`. The brand list was re-scored from the same saved answers with `--reanalyse` after I added HTML link parsing (no new calls). Below is `answer-check.md` as written, with the title level lowered by one.

## AI Answer Check: Asana

2026-10-10 09:29 (Asia/Tbilisi). 18 questions x 3 runs = 54 answers. Desearch AI Search, tools `web,twitter`, system message: "Answer like a neutral buyer's advisor. Name specific products, say who each one suits, and cite your sources.".

### Share of answer

| Brand | Runs that name it | Share | Share when the question does not name it | Questions (of 18) | Named first | Mean position |
|---|---|---|---|---|---|---|
| Asana (you) | 29 / 54 | 54% | 14 / 39 (36%) | 14 | 15 | 1.69 |
| ClickUp | 24 / 54 | 44% | 21 / 51 (41%) | 12 | 8 | 2.46 |
| Trello | 20 / 54 | 37% | 14 / 48 (29%) | 10 | 8 | 2.5 |
| monday.com | 19 / 54 | 35% | 13 / 48 (27%) | 11 | 9 | 1.74 |
| Wrike | 9 / 54 | 17% | 9 / 54 (17%) | 5 | 2 | 2.67 |
| Jira | 9 / 54 | 17% | 9 / 54 (17%) | 5 | 3 | 3.67 |
| Smartsheet | 7 / 54 | 13% | 7 / 54 (13%) | 6 | 1 | 3.29 |
| Notion | 6 / 54 | 11% | 6 / 54 (11%) | 4 | 0 | 3.5 |
| Basecamp | 4 / 54 | 7% | 4 / 54 (7%) | 4 | 0 | 3.5 |
| Teamwork.com | 0 / 54 | 0% | 0 / 54 (0%) | 0 | 0 | - |

Position = order of first mention among the brands you listed (1 = named first). A question that names a brand ("<brand> alternatives") almost always gets it back, so the fourth column leaves those questions out.

### Per question

| Question | Asana named | Positions | Same brand set in all runs | Cited-domain overlap |
|---|---|---|---|---|
| best project management tool for a 5-person remote team | 1 / 3 | -, 3, - | no (3 sets) | 1.0 |
| best free project management software for small teams | 1 / 3 | 2, -, - | no (3 sets) | 0.33 |
| Asana alternatives | 3 / 3 | 1, 1, 1 | no (3 sets) | 0.17 |
| Trello alternatives | 3 / 3 | 3, 3, 3 | no (2 sets) | 0.2 |
| monday.com alternatives | 2 / 3 | 2, 2, - | no (3 sets) | 0.29 |
| ClickUp alternatives | 3 / 3 | 2, 2, 1 | no (3 sets) | 0.1 |
| is Asana good for marketing teams | 3 / 3 | 1, 1, 1 | yes | 0.33 |
| is Asana worth it for a small agency | 3 / 3 | 1, 1, 1 | yes | 0.2 |
| best project management tool for software development teams | 1 / 3 | 3, -, - | no (3 sets) | 0.67 |
| best project management app for freelancers | 1 / 3 | -, -, 2 | no (2 sets) | 0.32 |
| Asana vs Trello, which is better | 3 / 3 | 1, 1, 1 | yes | 0.47 |
| Asana vs monday.com for a growing startup | 3 / 3 | 2, 1, 2 | yes | 0.21 |
| best project management tool with Gantt charts | 0 / 3 | -, -, - | no (2 sets) | 0.19 |
| best task management app for nonprofits | 1 / 3 | 1, -, - | no (2 sets) | 0.67 |
| easiest project management tool for non-technical teams | 0 / 3 | -, -, - | yes | 0.22 |
| best project management software for agencies managing client work | 0 / 3 | -, -, - | no (3 sets) | 0.38 |
| which project management tool has the best mobile app | 1 / 3 | -, 3, - | no (3 sets) | 0.19 |
| best project management tool for a team of 50 people | 0 / 3 | -, -, - | no (3 sets) | 0.11 |

Cited-domain overlap = mean Jaccard overlap of the cited domains between runs of the same question (1 = identical).

### Top cited domains

Domains linked inside the answers, counted once per answer. These are the pages worth being on. Links to individual X posts are counted under x.com and not listed one by one.

| Domain | Answers citing it |
|---|---|
| thedigitalprojectmanager.com | 8 |
| hive.com | 6 |
| zapier.com | 5 |
| cloudwards.net | 5 |
| x.com | 5 |
| project-management.com | 4 |
| proprofsproject.com | 4 |
| monday.com | 4 |
| asana.com | 4 |
| ones.com | 4 |
| trackstack.tech | 3 |
| airtable.com | 3 |
| baserow.io | 3 |
| cirface.com | 3 |
| tech.co | 3 |

### Top source domains

All links returned with the answers (web results and X posts), counted once per answer.

| Domain | Answers |
|---|---|
| x.com | 54 |
| thedigitalprojectmanager.com | 34 |
| reddit.com | 26 |
| zapier.com | 20 |
| teamwork.com | 19 |
| project-management.com | 16 |
| larksuite.com | 12 |
| wrike.com | 11 |
| hive.com | 11 |
| pcmag.com | 11 |

### How the answers describe Asana

- (best project management tool for a 5-person remote team, run 2) Other options like Trello and Asana are also suitable for small teams, but ClickUp's versatility and value make it the top choice for most remote teams in 2026.
- (best free project management software for small teams, run 1) The best free project management software for small teams in 2026 include Trello, Asana, ClickUp, Wrike, Airtable, Jira, and Zapier, each suited for different needs.
- (Asana alternatives, run 1) Here are some alternatives to Asana:
- (Asana alternatives, run 3) Here are some notable alternatives to Asana in 2026:
- (Trello alternatives, run 1) Asana: Suitable for growing cross-functional teams, supporting task dependencies, timelines, and automation, starting at $10.99/user/month.
- (Trello alternatives, run 2) For more advanced project management, Monday.com and Asana provide extensive views, automation, and collaboration tools, ideal for growing teams.
- (Trello alternatives, run 3) Asana: Suitable for growing teams requiring task dependencies, timelines, and automation, with a free tier for up to 10 users.
- (monday.com alternatives, run 1) Asana: Best for task tracking and team collaboration, offering visual project views and automation, but lacks native time tracking.
- (ClickUp alternatives, run 1) Asana: Focuses on structured project and task management with automation bundles, ideal for teams prioritizing clarity and dependencies.
- (ClickUp alternatives, run 2) Asana: Focused on task and project management with automation bundles, portfolios, and an intuitive interface.
- (ClickUp alternatives, run 3) SmartSuite, Asana, and Monday.com are top alternatives to ClickUp in 2026.
- (is Asana good for marketing teams, run 1) Yes, Asana is suitable for marketing teams.
- (is Asana good for marketing teams, run 2) Yes, Asana is considered good for marketing teams.
- (is Asana good for marketing teams, run 3) Yes, Asana is good for marketing teams.
- (is Asana worth it for a small agency, run 1) Yes, Asana is worth it for a small agency.
- (is Asana worth it for a small agency, run 2) Yes, Asana can be worth it for a small agency, but with caveats.
- (is Asana worth it for a small agency, run 3) Yes, Asana can be worth it for a small agency, especially if you need a comprehensive project management tool with multiple views, task dependencies, and automation features.
- (best project management tool for software development teams, run 1) For a lightweight, all-in-one solution, ClickUp and Asana are suitable for teams seeking flexibility and automation with a gentler learning curve.
- (best project management app for freelancers, run 3) For visual or task-heavy workflows, Trello, Asana, and ClickUp remain strong options, each catering to different preferences and complexity levels.
- (Asana vs Trello, which is better, run 1) The choice between Asana and Trello depends on your team's needs.
- (Asana vs Trello, which is better, run 2) The choice between Asana and Trello depends on your team size and project complexity.
- (Asana vs Trello, which is better, run 3) Both Asana and Trello are popular project management tools, but their suitability depends on your needs.
- (Asana vs monday.com for a growing startup, run 1) For a growing startup, monday.com is generally better suited due to its superior customization, visual workflows, and more affordable plans for mid-sized teams, while Asana excels in extensive integrations and structured task management for teams prioritizing automation and security.
- (Asana vs monday.com for a growing startup, run 2) The best choice between Asana and monday.com for a growing startup depends on your specific needs:
- (Asana vs monday.com for a growing startup, run 3) Asana, on the other hand, excels in structured project management with strong automation and enterprise workflow features, but its higher costs ($24.99/user/month for Advanced) and less flexible views may be less suitable for rapidly scaling startups on a budget.
- (best task management app for nonprofits, run 1) Asana: User-friendly, suitable for managing small to large projects with flexible views and automation.
- (which project management tool has the best mobile app, run 2) Other notable options include ClickUp, which excels in customization and task hierarchy, and Asana, known for offline use and task management, but monday.com stands out for its overall mobile functionality and user experience.

### With vs without the system message

| Question | Variant | Brands named per run | Summary length (chars) | Cited domains per run |
|---|---|---|---|---|
| best project management tool for a 5-person remote team | with | ClickUp, Trello, Basecamp; ClickUp, Trello, Asana; ClickUp, monday.com | 808, 1026, 725 | 1, 1, 1 |
| best project management tool for a 5-person remote team | without | ClickUp, Asana, monday.com; ClickUp, Trello, Asana; ClickUp | 937, 867, 838 | 1, 1, 2 |
| best free project management software for small teams | with | Trello, Asana, ClickUp, Wrike, Jira; ClickUp, Trello, Smartsheet; ClickUp, monday.com | 1620, 1240, 876 | 1, 2, 2 |
| best free project management software for small teams | without | ClickUp, Trello, Smartsheet; ClickUp, Trello, Asana; Trello, Wrike, monday.com | 1007, 836, 1000 | 3, 2, 2 |
| Asana alternatives | with | Asana, Wrike, Basecamp, Notion, ClickUp, Trello, Jira; Asana, Wrike, monday.com, ClickUp, Trello, Jira; Asana, Wrike, monday.com, ClickUp, Trello | 1729, 1061, 1457 | 2, 1, 2 |
| Asana alternatives | without | Asana, Wrike, monday.com, ClickUp, Trello, Notion, Jira, Basecamp; Asana, Wrike, Basecamp, Notion, monday.com, ClickUp, Smartsheet, Jira; Asana, monday.com, ClickUp, Trello, Jira | 2149, 1152, 1325 | 4, 2, 3 |

### Cost

63 calls, 630 billed units, **$0.2520** (sum of the `X-Desearch-Cost-Usd` response headers). Latency 5.5 to 11.0 s per call (median 9.3 s).
