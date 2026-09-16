# JobSpike marketing plan

Written 16 September 2026. Every number below was measured, not estimated.

## Where you actually are

| Measure | Value | Source |
| --- | --- | --- |
| Visitors, last 30 days | 57 | Vercel Web Analytics |
| Pageviews, last 30 days | 107 | Vercel Web Analytics |
| Registered users, total | 16 | production database |
| Registered in last 30 days | 7 | production database |
| Users who ran an analysis | 8 of 16 | production database |
| Analyses run, all time | 37 | production database |
| Live job listings | ~36,000 from 476 employer boards | production database |

Read that honestly: roughly two visitors a day, and half the people who sign up
never upload anything. That second number matters more than traffic. Sending
1,000 visitors at a funnel that loses half its signups wastes the 1,000.

## The one-line positioning

**A free career tool that reads your resume the way an employer's software
does, and shows you 36,000 jobs straight from company career pages.**

Not "AI-powered career OS". The three things a stranger can verify in ten
seconds are: it is free, it needs no account to try, and the jobs link to the
employer rather than an aggregator.

## Rules this plan sticks to

You are 14 and you built this. That is the story, and it is a *better* story
than a fake one, so:

- Never post as a recruiter, a laid-off worker, or "someone who struggled to
  find a job". No invented before/after screenshots, testimonials or results.
- Never claim user numbers you do not have. "16 users" is fine to not mention;
  "thousands of job seekers" is a lie.
- Platform minimum ages: Reddit, Quora, Discord, Instagram, Facebook and
  YouTube are 13+. **LinkedIn requires 16 and Fishbowl is for verified
  professionals — both are off the table**, however good the audience looks.
- Where a community forbids promotion, participate without promoting. That is
  not a workaround, it is the actual rule.

## Channels, ranked by return for the effort

### 1. Direct outreach to placement officers and training institutes (highest)

One placement officer forwards a link to 200 final-year students. Nothing else
you can do gives that leverage, and it is the one channel where being a
14-year-old who built a working tool is an *advantage* — it is genuinely
interesting, and people reply to interesting.

Targets, in order:
1. Training & Placement Officers (TPOs) at engineering and degree colleges.
2. Campus placement-cell student coordinators (often easier to reach than the
   TPO, and they run the WhatsApp groups).
3. Coding bootcamps and training institutes that promise placement support.
4. Career counsellors at schools with senior-secondary batches.

Scripts: `cold-email.md` and `call-script.md` in this folder. **Do not send
anything from those files until you have read it yourself and it sounds like
you.** Send in small batches (20–30), from your own address, one at a time.

### 2. Guides and comparison pages (compounding, already shipped)

`/guides` and `/compare/resumax` are live, in the sitemap, and written to be
worth linking to. This is the only channel that keeps working while you sleep,
and it takes weeks to show up, so it needs starting early and then leaving
alone. Next steps, in order:

1. Submit the sitemap in Google Search Console (free, needs a DNS or file
   verification) — without this, indexing can take weeks longer.
2. Add two guides a month. The ones with the clearest search demand, and no
   good honest page ranking for them: "resume format for freshers India",
   "how to tailor a resume to a job description", "what to write when you have
   no work experience".
3. Every guide ends with the tool, not with a hard sell.

### 3. Communities (slow, high risk of being banned, do it properly)

I could not verify individual subreddit rules — Reddit is unreachable from my
tooling, and I will not guess rules or invent thread links. So the rule is:
**open the subreddit, read its rules page, and only then decide.** Candidates
worth checking, all of which have the right audience:

- r/resumes, r/jobs, r/careerguidance, r/cscareerquestions
- r/developersIndia, r/india, r/indianstartups, r/JEENEETards (for school-age
  audiences), r/EngineeringStudents
- r/SideProject and r/InternetIsBeautiful (these *do* generally welcome
  "I built this" posts, but check)

How to behave, regardless of subreddit:
- Answer 10 questions genuinely for every 1 time you mention the tool. The
  widely-quoted "90/10" rule is a real norm and moderators enforce it.
- The mention should be a sentence, not a pitch: "I built a free thing that
  does exactly this comparison — link in profile if it's useful."
- Post as yourself: "I'm 14 and I built this because…" This is allowed, it is
  true, and it is the thing people actually upvote.
- One subreddit at a time, for a week, before adding another. A ban is
  permanent and it is invisible until you notice nobody replies.

### 4. Short video (Instagram Reels, YouTube Shorts)

A 30-second screen recording — upload a resume, watch the score and the
missing keywords appear — carries better than any written description. Post
the same clip to both. No face needed. Caption in plain language, no hashtag
spam. This costs one afternoon to make five clips.

### 5. Quora (slow but permanent)

Answers to "how do I get my resume past ATS" style questions rank in Google
for years. Same 10:1 discipline. Write the answer so it is useful even if
nobody clicks the link.

## What to do first, in order

| When | Do | Time |
| --- | --- | --- |
| This week | Google Search Console + submit sitemap | 1 hour |
| This week | Fix the signup→upload drop (see below) | — |
| This week | Build the TPO list: 40 colleges, name + email + phone | 2 hours |
| Next week | Send email batch 1 (20 colleges), then call the ones who opened | 3 hours |
| Next week | Record 5 short clips, post to Reels + Shorts | 1 afternoon |
| Ongoing | 2 guides a month; 1 community, properly | 2 hours/week |

## The thing worth fixing before any of it

Half your registered users (8 of 16) never ran a single analysis. Whatever
sends them away is costing you more than any channel will earn. Worth watching
a real person sign up, in silence, without helping them, and writing down
where they hesitate.

## What to measure

Weekly, four numbers only:

1. Visitors (Vercel Analytics)
2. Signups (database)
3. Analyses run (database)
4. Signups who ran an analysis, as a percentage — currently 50%

If a channel does not move number 3, it is not working, no matter what it does
to number 1.
