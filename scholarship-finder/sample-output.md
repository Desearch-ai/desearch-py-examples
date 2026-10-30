# Sample output
Made by Desearch ([https://desearch.ai](https://desearch.ai))

Run on 2026-10-30 11:17 Asia/Tbilisi; today = 2026-10-30.

```sh
python3 scholarship_finder.py --field nursing --level undergraduate --year 2027 --hide-unclear --limit 10
```

Query: nursing undergraduate scholarships 2027 application deadline
Run time: 2026-10-30T11:18:01.424361+04:00
Endpoints used: /search, /web, /web/extract
calls: 6, cost: $0.00700
showing 10 of 11 rows

| Name | Amount | Deadline | Confidence | Source URL | Endpoint | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| SON Scholarship Applications \| School of ... | not stated |  | snippet only | [source](<https://www.uab.edu/nursing/home/scholarships-financial-aid/son-scholarship-application>) | search | date negated by source |
| Healthcare Scholarships: Invitation to Ap... | not stated | 2026-11-13 | confirmed on page | [source](<https://hpa.princeton.edu/news/healthcare-scholarships>) | search |  |
| 2027 Undergraduate Scholarship Applicatio... | not stated | 2027-01-11 | extract failed | [source](<https://www.fnsna.org/2027-undergraduate-scholarship-application>) | search | no publish date |
| Top 50 Nursing Scholarships in 2026 | $8,000 | 2027-02-02 | date not found on page | [source](<https://scholaroo.com/nursing-scholarships/>) | web | no publish date |
| Bachelor of Science in Nursing Academic S... | not stated | 2027-02-11 | snippet only | [source](<https://usascholarships.net/scholarships/bachelor-of-science-in-nursing-academic-scholarships-usa-2027>) | web | no publish date |
| Jean Andrews Nursing Scholarship | $5,000 | 2027-02-12 | snippet only | [source](<https://www.scholarships.com/financial-aid/college-scholarships/scholarships-by-major/nursing-scholarships>) | web | no publish date |
| Nursing & Health Scholarships for College... | not stated | 2027-02-25 | snippet only | [source](<https://scholarshipsclosingsoon.com/for/college/nursing/>) | web | no publish date |
| Scholarships for Nursing Students | $1,000 | 2027-03-15 | snippet only | [source](<https://www.mefa.org/article/scholarships-for-nursing-students/>) | web | no publish date |
| [Page 2] Top 120 Nursing Scholarships to ... | not stated | 2027-03-22 | snippet only | [source](<https://bold.org/scholarships/by-major/nursing-scholarships/2/>) | web | no publish date |
| Top 120 Nursing Scholarships to Apply for... | $5,000 | 2027-03-30 | snippet only | [source](<https://bold.org/scholarships/by-major/nursing-scholarships/>) | web | no publish date |

Stdout:

```text
Deadlines and amounts are as stated by the source page. Check the official page before applying.

showing 10 of 11 rows

Name                                          Amount                Deadline    Confidence                Endpoint  Flags                   Source URL
SON Scholarship Applications | School of ...  not stated                        snippet only              search    date negated by source  https://www.uab.edu/nursing/home/scholarships-financial-aid/son-scholarship-application
Healthcare Scholarships: Invitation to Ap...  not stated            2026-11-13  confirmed on page         search                            https://hpa.princeton.edu/news/healthcare-scholarships
2027 Undergraduate Scholarship Applicatio...  not stated            2027-01-11  extract failed            search    no publish date         https://www.fnsna.org/2027-undergraduate-scholarship-application
Top 50 Nursing Scholarships in 2026           $8,000                2027-02-02  date not found on page    web       no publish date         https://scholaroo.com/nursing-scholarships/
Bachelor of Science in Nursing Academic S...  not stated            2027-02-11  snippet only              web       no publish date         https://usascholarships.net/scholarships/bachelor-of-science-in-nursing-academic-scholarships-usa-2027
Jean Andrews Nursing Scholarship              $5,000                2027-02-12  snippet only              web       no publish date         https://www.scholarships.com/financial-aid/college-scholarships/scholarships-by-major/nursing-scholarships
Nursing & Health Scholarships for College...  not stated            2027-02-25  snippet only              web       no publish date         https://scholarshipsclosingsoon.com/for/college/nursing/
Scholarships for Nursing Students             $1,000                2027-03-15  snippet only              web       no publish date         https://www.mefa.org/article/scholarships-for-nursing-students/
[Page 2] Top 120 Nursing Scholarships to ...  not stated            2027-03-22  snippet only              web       no publish date         https://bold.org/scholarships/by-major/nursing-scholarships/2/
Top 120 Nursing Scholarships to Apply for...  $5,000                2027-03-30  snippet only              web       no publish date         https://bold.org/scholarships/by-major/nursing-scholarships/
```

Stderr:

```text
/web/extract: request failed (status 422); error_code: js_required; detail: This page needs JavaScript to show its content. Retry with js=true.
/web/extract: request failed (status 503); error_code: upstream_failed; detail: Crawler upstream unavailable.
calls: 6, cost: $0.00700
```
