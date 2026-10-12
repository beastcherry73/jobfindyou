# Job finder audit and first improvement

Date: 2026-10-12

Implementation commit: `8b91373` on `codex/job-finder-trust`.

## Scope and baseline

JobSpike is a Flask application with server-rendered templates and vanilla
JavaScript. The signed-in job finder is the `jobsearch` section of
`templates/workspace.html`, rendered from `templates/partials/jobsearch.html`.
`GET /api/jobs/search` calls `backend.services.jobsources.unified_search`,
which currently queries the application's own ATS corpus in
`backend/services/ats.py`.

The corpus is assembled from public, employer-hosted job boards on Workday,
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, and Breezy.
Rows are keyed by `platform:company_token:source_id`, upserted on each fetch,
and are removed only when an employer board subsequently returns a non-empty
set that omits them, or when a row is not seen for 21 days. Search supports
keyword, location/country, date, work mode, employment type, salary,
experience level, account-friction, pagination, and sort. Search deduplicates
multi-location title/company clusters and records how many locations were
collapsed.

Strengths verified from source and local ATS tests:

- Every normal search result points to the original employer/ATS posting, not
  an aggregator redirect.
- Fingerprints prevent re-sync duplicates; the test suite checks this.
- The early-career filter recognizes internship, intern, trainee,
  apprenticeship, junior, entry-level, fresher, campus, new-grad and graduate
  signals. It is a title/structured-field heuristic, not a guarantee of an
  employer's experience requirement.
- Application clicks are recorded as `Viewed`, not falsely marked as an
  application; candidates self-report the transition to `Applied`.

Known baseline limitations:

- This review did not have production database, Vercel, or authenticated-user
  credentials, so it cannot state the live inventory size, recency, link pass
  rate, production health payload, or deployed commit.
- The employer registry is smaller and geographically narrower than a global
  general-purpose engine. The repository itself notes lower coverage where
  employers use regional ATS products outside its supported platforms.
- Existing analytics instrumentation was not found in the relevant Flask,
  template, or deployment source. No tracker was added because no configured
  privacy-conscious provider was evidenced.

## Highest-impact problems, ranked

| Rank | Problem | Evidence | Impact / safe response |
| --- | --- | --- | --- |
| 1 | A result had a posted date but no per-listing evidence of when JobSpike last observed it on the employer board. | `ats_jobs.last_seen_at` was stored and updated on successful fetches but omitted by the search result mapper and UI. | High trust impact; exposed the real timestamp with deliberately cautious language. |
| 2 | Early-career coverage is constrained by the supported employer-board registry, especially outside the largest ATS platforms. | Registry/platform design and repository handover. | High impact, higher operational risk; expand only through small, policy-compliant, measured registry experiments. |
| 3 | The product has no evidenced event measurement for search-to-application conversion. | No analytics event handling/provider configuration found in relevant code. | High measurement value but needs a chosen provider/privacy review; document before implementation. |

## Implemented improvement

Search results now include `last_checked_at`, sourced only from the persisted
`ats_jobs.last_seen_at` value. This is populated by a successful fetch that
returned that exact job from its employer-hosted board. Cards say `Checked …`
and details say `Employer board checked …`. The wording does **not** claim the
job is verified, active, or that an application is guaranteed to complete.
The page attribution was corrected to explain this rule and later-refresh
removal behavior.

Regression coverage asserts that every ATS search result carries this real
timestamp. The normal result query now selects `last_seen_at` only for the
visible page, preserving the existing narrow ranking query.

## HiringCafe comparison (research completed 2026-10-12)

Sources: [HiringCafe search](https://hiringcafe.com/),
[How to Avoid Ghost Jobs](https://hiringcafe.com/insights/how-to-avoid-ghost-jobs),
[Off-Board Job Market](https://hiringcafe.com/insights/off-board-job-market), and
[ChatGPT search documentation](https://hiringcafe.com/documentation/hiringcafe-chatgpt-app).

| Area | HiringCafe: verified observation | JobSpike: verified repository observation | Gap that matters to early-career candidates | Realistic next move |
| --- | --- | --- | --- | --- |
| Sources and links | Says it sources from employer career pages and checks each apply page about every four hours. | Uses eight employer-hosted ATS platforms; job links are direct. | HiringCafe claims a more frequent individual check. | Measure JobSpike's actual sync completion interval before changing any claim. |
| Search/filtering | Public UI/documents show extensive structured filters; cards expose save, applied, hide, pay, work mode and seniority. | Supports combined filters, direct links, account-friction filter, results detail, tracking and resume match. | JobSpike needs stronger proof of its smaller corpus's freshness. | Shipped last-successful employer-board check per card. |
| Freshness/quality | Says it preserves original date, filters some low-quality jobs, and exposes a quality-filter reversal mode. | Preserves source posted date when provided, deduplicates, prunes stale/unregistered rows, but has no user-visible quality-reason ledger. | Candidates need to distinguish posting date from observation date. | Shipped the observation date; defer quality labels until rules and data are auditable. |
| Organization | UI exposes Saved, Mark Applied and Hide. | Tracker saves viewed roles and supports self-reported applied/interview/offer/rejected. | JobSpike is already competitive on basic application organization. | Improve duplicate prevention in a later tracker-focused task. |
| Candidate matching | HiringCafe advertises Talent Agent; public ChatGPT documentation says its connector cannot do resume-aware matching. | Offers explicit, on-demand resume match evidence and a tailored-resume handoff. | Resume-aware matching can help early-career candidates if it stays explainable. | Keep evidence chips; do not make unsupported placement claims. |
| Scale | Homepage currently reports millions of jobs and companies. | No live count was verified in this audit. | JobSpike must not compete on invented scale. | Differentiate on direct-source provenance, visible checks and entry-level workflow. |

## Differentiation hypothesis

For students, interns, and fresh graduates, JobSpike may be useful as a
smaller but auditable employer-source finder: direct original postings,
explicit last-observed time, transparent account friction, an entry-level
filter, and explainable resume-to-role evidence in one flow. This is a
hypothesis, not a superiority claim. Validate it by measuring zero-result rate,
search refinement, detail views, outbound application-link clicks, and return
visits after privacy review.

## Test record

- `python -X utf8 scratch/test_ats_layer.py`: 124 passed, 0 failed, 0 skipped
  after the fix. An initial ordinary console run hit a pre-existing Windows
  CP1252 printing error before the changed assertion; UTF-8 mode was used for
  the complete suite.
- `python scratch/check_template_js.py`: 8 templates, 14 inline script blocks,
  0 errors.
- Focused Flask-context assertion: five search results each returned a
  non-empty `last_checked_at` value.

## Deployment and remaining risks

No preview or production deployment was attempted: no deployment credentials
or deployment tool configuration was available in this session. No production
data was changed. Before a release, run the PostgreSQL-only ATS verification,
then deploy a preview and verify the signed-in browse flow on desktop and a
narrow mobile viewport.

An independent-review attempt was made, but the separate review environment's
command runner failed before it could inspect the diff (`setup refresh` error).
This is recorded as a process limitation rather than represented as a review.

Next three highest-value tasks:

1. Run a bounded, policy-compliant registry experiment for regional,
   early-career employers; publish measured coverage and link-health results.
2. Add a minimal consent-aware event sink for search, result/detail view and
   original-link click events after choosing a configured provider.
3. Add a visible corpus/sync-health fallback that explains when freshness is
   delayed instead of serving silently stale results.
