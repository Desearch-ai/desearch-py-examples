# Sample output
Made by Desearch ([https://desearch.ai](https://desearch.ai))

Run on 2026-10-30 11:17 Asia/Tbilisi; today = 2026-10-30.
Re-rendered 2026-10-30 from the saved raw response of that run with --from-raw after the --hide-unclear fix; no new API calls, same 6 calls and cost.

```sh
python3 scholarship_finder.py --field nursing --level undergraduate --year 2027 --hide-unclear --limit 10
```

Query: nursing undergraduate scholarships 2027 application deadline
Run time: 2026-10-30T11:18:01.424361+04:00
Endpoints used: /search, /web, /web/extract
calls: 6, cost: $0.00700
showing 10 of 10 rows

| Name | Amount | Deadline | Confidence | Source URL | Endpoint | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| Healthcare Scholarships: Invitation to Apply by Nov 13 \| Health Professions Advising | not stated | 2026-11-13 | confirmed on page | [source](<https://hpa.princeton.edu/news/healthcare-scholarships>) | search |  |
| 2027 Undergraduate Scholarship Application  \| FNSNA.ORG | not stated | 2027-01-11 | extract failed | [source](<https://www.fnsna.org/2027-undergraduate-scholarship-application>) | search | no publish date |
| Top 50 Nursing Scholarships in 2026 | $8,000 | 2027-02-02 | date not found on page | [source](<https://scholaroo.com/nursing-scholarships/>) | web | no publish date |
| Bachelor of Science in Nursing Academic Scholarships 2027 | not stated | 2027-02-11 | snippet only | [source](<https://usascholarships.net/scholarships/bachelor-of-science-in-nursing-academic-scholarships-usa-2027>) | web | no publish date |
| Jean Andrews Nursing Scholarship | $5,000 | 2027-02-12 | snippet only | [source](<https://www.scholarships.com/financial-aid/college-scholarships/scholarships-by-major/nursing-scholarships>) | web | no publish date |
| Nursing & Health Scholarships for College Students | not stated | 2027-02-25 | snippet only | [source](<https://scholarshipsclosingsoon.com/for/college/nursing/>) | web | no publish date |
| Scholarships for Nursing Students | $1,000 | 2027-03-15 | snippet only | [source](<https://www.mefa.org/article/scholarships-for-nursing-students/>) | web | no publish date |
| [Page 2] Top 120 Nursing Scholarships to Apply for in April 2026 | not stated | 2027-03-22 | snippet only | [source](<https://bold.org/scholarships/by-major/nursing-scholarships/2/>) | web | no publish date |
| Top 120 Nursing Scholarships to Apply for in October 2026 \| Bold.org | $5,000 | 2027-03-30 | snippet only | [source](<https://bold.org/scholarships/by-major/nursing-scholarships/>) | web | no publish date |
| Nursing scholarships for international students 2026-2027 \| ScholarshipTab | not stated | 2027-12-31 | snippet only | [source](<https://www.scholarshiptab.com/scholarships-by-course/nursing>) | web | no publish date |

Stdout:

```text
Deadlines and amounts are as stated by the source page. Check the official page before applying.

showing 10 of 10 rows

Name                                          Amount                Deadline    Confidence                Endpoint  Flags            Source URL
Healthcare Scholarships: Invitation to Ap...  not stated            2026-11-13  confirmed on page         search                     https://hpa.princeton.edu/news/healthcare-scholarships
2027 Undergraduate Scholarship Applicatio...  not stated            2027-01-11  extract failed            search    no publish date  https://www.fnsna.org/2027-undergraduate-scholarship-application
Top 50 Nursing Scholarships in 2026           $8,000                2027-02-02  date not found on page    web       no publish date  https://scholaroo.com/nursing-scholarships/
Bachelor of Science in Nursing Academic S...  not stated            2027-02-11  snippet only              web       no publish date  https://usascholarships.net/scholarships/bachelor-of-science-in-nursing-academic-scholarships-usa-2027
Jean Andrews Nursing Scholarship              $5,000                2027-02-12  snippet only              web       no publish date  https://www.scholarships.com/financial-aid/college-scholarships/scholarships-by-major/nursing-scholarships
Nursing & Health Scholarships for College...  not stated            2027-02-25  snippet only              web       no publish date  https://scholarshipsclosingsoon.com/for/college/nursing/
Scholarships for Nursing Students             $1,000                2027-03-15  snippet only              web       no publish date  https://www.mefa.org/article/scholarships-for-nursing-students/
[Page 2] Top 120 Nursing Scholarships to ...  not stated            2027-03-22  snippet only              web       no publish date  https://bold.org/scholarships/by-major/nursing-scholarships/2/
Top 120 Nursing Scholarships to Apply for...  $5,000                2027-03-30  snippet only              web       no publish date  https://bold.org/scholarships/by-major/nursing-scholarships/
Nursing scholarships for international st...  not stated            2027-12-31  snippet only              web       no publish date  https://www.scholarshiptab.com/scholarships-by-course/nursing
```

Stderr:

```text
/web/extract: request failed (status 422); error_code: js_required; detail: This page needs JavaScript to show its content. Retry with js=true.
/web/extract: request failed (status 503); error_code: upstream_failed; detail: Crawler upstream unavailable.
calls: 6, cost: $0.00700
```
