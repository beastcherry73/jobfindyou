"""Daily digest — resume-matched shortlist over the synced ATS corpus.

The digest shows a user a short, ranked list of roles matched to their resume.
Scoring every listing with Groq is not affordable (the corpus is ~18k rows and
climbing), so the work is split in two stages:

  STAGE 1  keyword scoring. No AI call, no schema change. Narrows the corpus
      to ~10-15 plausible candidates per user.
  STAGE 2 (`ai_score`)  the existing Groq job-match prompt, run ONLY on those
      survivors. ~10 AI calls per user per day, not 18k.

Stage 1 has TWO implementations, because a batch job and a web request want
opposite things and one function cannot be good at both:

  BATCH    `build_index` + `rank`. One corpus pass scored against the union of
           every user's keywords, then a set lookup per user. Right when many
           users are served from one pass.
  REQUEST  `recall` + `score_rows`. Narrows in SQL first and scores only the
           survivors, so the shared connection lock is held for a fraction of
           the time. Right when ONE user is waiting on the response. This is
           what /api/digest uses; see the long comment above `_RECALL_CAP`.

Stage 2 is NOT wired to /api/digest: ten sequential Groq calls would exceed the
serverless time budget. The For You tab scores its visible cards through the
existing /api/jobs/match route instead, a few at a time.

Why the matching is not done in SQL
-----------------------------------
The obvious implementation - a pile of `LIKE '%keyword%'` terms scored in SQL -
was built first and measured, and failed on both counts:

  * WRONG. `LIKE '%rest%'` matches "inte(rest)" and `LIKE '%express%'` matches
    "(Express)ion", so "Expression of Interest: SMB Account Executive" scored 8
    against a backend engineer's resume - a sales role outranking real backend
    jobs. Substring matching cannot express a word boundary, and `\\b` is not
    available in either engine's LIKE.
  * SLOW. ~0.9s per keyword over 18k rows; 11.8s for one 13-keyword resume.
    The production connection is SHARED and serialized by a module lock
    (see CLAUDE.md), so a multi-second scan blocks every other request.

So SQL does only what it is good at - cheap recency/country narrowing, read in
batches - and the text matching happens in Python against normalized token
strings, where a word boundary is expressible.

(The request path does additionally use LIKE, but only as a RECALL filter whose
over-matching is then corrected in Python. LIKE still never decides a score.
The distinction is spelled out above `_RECALL_CAP`.)

Memory
------
The first cut held the whole corpus slice in memory to score it per user, which
measured 88 MB for 6.8k rows and would grow with the corpus. Instead
`build_index` streams the corpus in batches and, for each job, records only
WHICH keywords hit - then discards the text. What survives is job metadata plus
two small integer sets per row, so peak memory is one batch, not one corpus.
This also inverts the cost: matching happens once against the union of every
user's keywords, and each user's ranking is then a set lookup rather than
another pass over the corpus.

Corpus facts this has to tolerate
---------------------------------
  * `search_text` is NOT used: it holds only title + company + location, so
    keywords like "Kubernetes" would never match - they live in the
    description. We score `title` (high weight) and `description` (low).
  * ~15% of rows have an empty description (SmartRecruiters and Breezy do not
    return one in their list responses). Those rows still match on title alone.
  * `posted_at` is nullable, and Postgres sorts NULLs FIRST under DESC while
    SQLite sorts them last - so ordering is done in Python on a normalized key.
  * One opening posted to several locations is several rows with distinct
    fingerprints; the digest keeps only the best-ranked row per title+company.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# How far back a listing may have been posted to be digest-eligible. A digest
# is a "what is worth applying to now" surface, not an archive.
DEFAULT_MAX_DAYS_OLD = 30

# Candidates surviving stage 1 and handed to stage 2. This is the ceiling on
# Groq spend per user, not merely a display limit.
DEFAULT_LIMIT = 15

# Of those, how many are actually sent to Groq.
DEFAULT_AI_LIMIT = 10

# Rows pulled from the database per round trip. Keeps peak memory to one batch
# and each `with get_db()` block short, per the shared-connection rule.
_BATCH = 500

# A title hit is worth much more than a description hit: "Backend Engineer" in
# the title means the role IS that; the same words in a description may be one
# line of a requirements list.
_TITLE_WEIGHT = 3
_DESC_WEIGHT = 1

# Resume keyword lists routinely include generic filler that matches most
# postings and so carries no ranking signal.
_STOP_KEYWORDS = {
    "agile", "scrum", "communication", "teamwork", "leadership", "collaboration",
    "problem solving", "time management", "stakeholder management", "management",
    "team", "work", "experience", "skills", "project management", "planning",
    "analysis", "strategy", "operations", "business", "professional",
}

# Cap on keywords per user. Beyond this the tail is noise, and cost is linear.
_MAX_KEYWORDS = 18

_NON_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text):
    """Lowercase and reduce to space-delimited tokens, padded at both ends.

    Padding lets a caller test `" kw " in tokenized` as an exact word-sequence
    match, which is what stops "rest" matching "interest". Punctuation becomes
    a separator, so "Node.js" and "CI/CD" tokenize the same way the equivalent
    keyword does.
    """
    if not text:
        return " "
    return " " + _NON_TOKEN_RE.sub(" ", str(text).lower()).strip() + " "


def _sort_key(posted_at):
    """Normalize posted_at (datetime on Postgres, ISO string on SQLite, or
    None) into a float for ordering. Undated rows sort last."""
    if not posted_at:
        return 0.0
    if isinstance(posted_at, datetime):
        dt = posted_at
    else:
        try:
            dt = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def normalize_keywords(raw):
    """Clean a stored suggested_keywords list into scoreable, tokenized terms.

    Returns (display, needle) pairs: `display` is the human-readable keyword
    for explaining a match, `needle` its padded token form. De-duplicated on
    the token form, order preserved (analyses list most relevant first).
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = [raw]
    if not isinstance(raw, list):
        return []

    out, seen = [], set()
    for item in raw:
        if not isinstance(item, str):
            continue
        display = item.strip()
        needle = _tokenize(display)
        if len(needle.strip()) < 2 or needle.strip() in _STOP_KEYWORDS or needle in seen:
            continue
        seen.add(needle)
        out.append((display, needle))
        if len(out) >= _MAX_KEYWORDS:
            break
    return out


def _skill_keywords(full_json):
    """The skills a resume ACTUALLY demonstrates, from an analysis payload.

    Deliberately NOT `suggested_keywords`. That column holds what the resume is
    MISSING and should add - the gap list. Matching the corpus against it
    surfaces jobs the user is least qualified for: a frontend resume (React,
    TypeScript) whose gaps were Node/AWS/Kubernetes produced a digest of
    backend roles, which Groq then scored 5-28%. The two-stage design caught
    it, but the signal was wrong at the source.

    Order matters - `matched_keywords` are the terms an analysis confirmed
    present in the resume, so they lead.
    """
    if isinstance(full_json, str):
        try:
            full_json = json.loads(full_json)
        except (ValueError, TypeError):
            return []
    if not isinstance(full_json, dict):
        return []

    out = []
    ka = full_json.get("keyword_analysis")
    if isinstance(ka, dict) and isinstance(ka.get("matched_keywords"), list):
        out.extend(ka["matched_keywords"])
    sa = full_json.get("skills_analysis")
    if isinstance(sa, dict) and isinstance(sa.get("industry_specific"), list):
        out.extend(sa["industry_specific"])
    return out


def latest_keywords(db, user_id):
    """Skills from this user's most recent analysis, normalized. [] if none.

    Reads the resume's demonstrated skills out of `full_json`; falls back to
    the `suggested_keywords` column only for older rows that predate those
    fields, where a gap-based match still beats no digest at all.
    """
    row = db.execute(
        "SELECT full_json, suggested_keywords FROM analyses "
        "WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        return []
    skills = _skill_keywords(row["full_json"]) if row["full_json"] else []
    if skills:
        return normalize_keywords(skills)
    if row["suggested_keywords"]:
        logger.info(f"Digest for user {user_id}: no skill keywords, "
                    f"falling back to suggested_keywords")
        return normalize_keywords(row["suggested_keywords"])
    return []


def latest_resume_text(db, user_id):
    """Raw resume text from the user's most recent analysis. '' if none.

    Mirrors the lookup the /api/jobs/match route does, kept here so the digest
    service does not have to import from the route layer.
    """
    row = db.execute(
        "SELECT full_json FROM analyses WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row or not row["full_json"]:
        return ""
    try:
        fj = row["full_json"]
        fj = json.loads(fj) if isinstance(fj, str) else fj
        return (fj.get("raw_text") or fj.get("rawText") or "").strip()
    except Exception:
        return ""


def _hits(tokenized, needle_pos, max_n):
    """Indices of every needle occurring in `tokenized`, by n-gram lookup.

    Testing each needle against each job with `in` is O(jobs x needles), which
    measured 24s for 600 needles over 4.9k rows and grows with every new user.
    Generating the job's own n-grams and intersecting against a dict instead
    costs O(job length x max_n) - independent of how many keywords exist across
    the whole user base, which is the term that actually grows.
    """
    tokens = tokenized.split()
    if not tokens:
        return set()
    found = set()
    for i in range(len(tokens)):
        for n in range(1, max_n + 1):
            if i + n > len(tokens):
                break
            pos = needle_pos.get(" ".join(tokens[i:i + n]))
            if pos is not None:
                found.add(pos)
    return found


class Index:
    """Corpus metadata plus, per job, which keywords hit. Carries no job text.

    `title_hits[i]` / `desc_hits[i]` are sets of indices into `needles`.
    """

    def __init__(self, needles):
        self.needles = needles
        self.jobs = []
        self.title_hits = []
        self.desc_hits = []
        # Bare (unpadded) needle text -> its index, for n-gram lookup.
        self.needle_pos = {n.strip(): i for i, n in enumerate(needles)}
        self.max_n = max((len(n.split()) for n in self.needle_pos), default=1)

    def __len__(self):
        return len(self.jobs)


def build_index(db, needles, max_days_old=DEFAULT_MAX_DAYS_OLD, country=""):
    """Stream the digest-eligible corpus once, recording keyword hits only.

    `needles` is the de-duplicated union of every user's padded keyword forms,
    so one pass serves every user in the run. Job text is tokenized, tested,
    and dropped inside the loop - it is never accumulated.
    """
    needles = list(needles)
    index = Index(needles)

    where, params = [], []
    if max_days_old:
        # posted_at is TIMESTAMPTZ in production; pg8000 sends a bare ISO
        # string as TEXT and Postgres rejects the comparison. Reuse the ats
        # helper that already solves this rather than re-deriving it.
        from backend.services.ats import _timestamp_param
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(max_days_old))
        # Undated rows are kept: a missing posted_at means the board published
        # none, not that the job is old.
        where.append("(posted_at IS NULL OR posted_at >= ?)")
        params.append(_timestamp_param(db, cutoff))
    if country:
        # Same rule as ats.search (fixed in b811d31): a remote listing crosses
        # a country boundary only when it resolves to NO country at all. A
        # remote job that names another country is that country's job.
        # Measured on production before the fix: for country='id' this clause
        # returned 1,516 rows of which 1,383 (91%) were other countries.
        where.append("(country_code = ? OR (work_mode = 'remote' "
                     "AND COALESCE(country_code, '') = ''))")
        params.append(country.strip().lower())
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    # Paged by id so the ordering is stable across batches; final ordering is
    # applied in Python, where NULL handling does not differ per engine.
    offset = 0
    while True:
        rows = db.execute(
            "SELECT id, fingerprint, title, company, location, work_mode, "
            "       employment_type, experience_level, apply_url, posted_at, "
            "       platform, description "
            f"FROM ats_jobs{clause} ORDER BY id LIMIT ? OFFSET ?",
            tuple(params + [_BATCH, offset]),
        ).fetchall()
        if not rows:
            break

        for r in rows:
            th = _hits(_tokenize(r["title"]), index.needle_pos, index.max_n)
            dh = _hits(_tokenize(r["description"]), index.needle_pos, index.max_n)
            if not th and not dh:
                continue          # cannot surface for any user; do not retain
            index.jobs.append({
                "id": r["id"], "fingerprint": r["fingerprint"],
                "title": r["title"], "company": r["company"],
                "location": r["location"], "work_mode": r["work_mode"],
                "employment_type": r["employment_type"],
                "experience_level": r["experience_level"],
                "apply_url": r["apply_url"], "posted_at": r["posted_at"],
                "platform": r["platform"],
                "_recency": _sort_key(r["posted_at"]),
            })
            index.title_hits.append(th)
            index.desc_hits.append(dh)
            # t_title/t_desc and the row's description go out of scope here.

        if len(rows) < _BATCH:
            break
        offset += _BATCH

    return index


def rank(index, keywords, limit=DEFAULT_LIMIT):
    """Rank an index against one user's keywords. No AI, no DB, no text.

    Returns candidate dicts carrying `match_score` and `matched_keywords` (the
    terms that actually hit), so the prompt - and later the UI - can say why a
    role surfaced instead of asserting a bare number.
    """
    if not keywords or not len(index):
        return []

    # Map this user's needles onto their positions in the shared needle list.
    wanted = {}
    for display, needle in keywords:
        try:
            wanted[index.needles.index(needle)] = display
        except ValueError:
            continue
    if not wanted:
        return []

    scored = []
    for i, job in enumerate(index.jobs):
        th, dh = index.title_hits[i], index.desc_hits[i]
        total, matched = 0, []
        for pos, display in wanted.items():
            in_title = pos in th
            if in_title:
                total += _TITLE_WEIGHT
            elif pos in dh:
                total += _DESC_WEIGHT
            else:
                continue
            matched.append(display)
        if total > 0:
            out = {k: v for k, v in job.items() if k != "_recency"}
            out["match_score"] = total
            out["matched_keywords"] = matched
            scored.append((total, job["_recency"], out))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    deduped, seen = [], set()
    for _, _, job in scored:
        key = (_tokenize(job.get("title")), _tokenize(job.get("company")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
        if len(deduped) >= int(limit):
            break
    return deduped



# ── Single-user request path (stage 1, fast) ───────────────────────────
#
# `build_index` above is the BATCH path: it scans the corpus once against the
# union of every user's keywords, which is the right shape for a nightly job
# serving many users from one pass. It is the wrong shape for a request. It
# tokenizes every eligible row (~6.3k) inside the `with get_db()` block, and
# measured 13-23s cold / 3-4s warm with the shared connection lock HELD - which
# per CLAUDE.md stalls every other request on the instance.
#
# The request path below narrows in SQL FIRST, then scores in Python with the
# lock already released. Measured over the same corpus and four users: 0.4-1.3s
# total, of which only 0.18-0.77s holds the lock - a 3-8x improvement warm, and
# far more cold.
#
# This does NOT contradict the module docstring's rejection of SQL matching.
# LIKE was rejected for PRECISION ("%rest%" matches "interest") and that
# rejection still stands - LIKE never decides a score here. It is used only for
# RECALL, where over-matching is harmless: Python then re-scores every recalled
# row with real word boundaries. The docstring's "0.9s per keyword / 11.8s for
# 13" figure came from running one query PER keyword; a single OR'd query is
# one scan whatever the keyword count (measured 0.82s for the same 13).
#
# FIDELITY, measured honestly: against the batch path's top 15 this returns the
# same set for narrow keyword sets (15/15 for users whose recall fits under
# _RECALL_CAP) but diverges for broad ones (12/15 and 9/15 for two users whose
# recall was truncated). Every divergence sat in the description-only tail -
# rows scoring 1 point per hit - never among the title matches. That is
# acceptable HERE and would not be in the batch path, because stage 1 on this
# path only has to assemble a plausible pool: the AI stage re-ranks it, and
# ordering the user actually sees comes from the match percentage, not from
# `match_score`. Removing the cap does restore exact parity, but costs 3-5.5s
# for broad keyword sets (single-token probes like "cloud"/"api" recall 76% of
# the corpus), which is the stall this path exists to avoid.

# Ceiling on rows pulled back for scoring. Title matches are ordered first (see
# `recall`), so truncation can only ever discard description-only matches -
# the cheapest tier, worth 1 point against a title hit's 3.
_RECALL_CAP = 2500

# LIKE wildcards. Defensive only: probes are derived from tokenized needles and
# `_tokenize` already reduces "%" and "_" to separators, so a wildcard cannot
# reach the pattern today. Escaping it costs nothing and stops that becoming a
# silent injection of wildcards if tokenization is ever relaxed.
_LIKE_ESCAPE = ("\\", "%", "_")


def _recall_probe(needle):
    """The most selective single token of a keyword, escaped for LIKE.

    The scoring needles are TOKENIZED ("Node.js" -> " node js "), but LIKE runs
    against RAW column text ("node.js"), so probing with the whole needle would
    silently miss every multi-word keyword. Any ONE token of a keyword is a
    sound recall probe instead: text containing the full keyword necessarily
    contains each of its tokens, so the probe cannot exclude a true match. The
    longest token is chosen because it is the most selective of the valid ones.
    """
    tokens = needle.split()
    if not tokens:
        return ""
    probe = max(tokens, key=len)
    for ch in _LIKE_ESCAPE:
        probe = probe.replace(ch, "\\" + ch)
    return probe


def recall(db, needles, max_days_old=DEFAULT_MAX_DAYS_OLD, country="", cap=_RECALL_CAP):
    """Cheap SQL narrowing of the corpus to rows that MIGHT match. Lock held.

    Over-matches by design; `score_rows` applies the real word-boundary test.
    Ordered title-matches-first so hitting `cap` can only drop the weakest
    tier: ordering purely by recency instead measured a real fidelity loss
    (12/15 against the batch path, a 6-point role displaced by a 5).
    """
    probes = [p for p in (_recall_probe(n) for n in needles) if p]
    if not probes:
        return []

    where, params = [], []
    if max_days_old:
        # posted_at is TIMESTAMPTZ in production and pg8000 sends a bare ISO
        # string as TEXT, which Postgres refuses to compare. Same helper the
        # batch path uses.
        from backend.services.ats import _timestamp_param
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(max_days_old))
        where.append("(posted_at IS NULL OR posted_at >= ?)")
        params.append(_timestamp_param(db, cutoff))
    if country:
        # Same rule as ats.search: a remote listing crosses a country boundary
        # only when it resolves to NO country at all.
        where.append("(country_code = ? OR (work_mode = 'remote' "
                     "AND COALESCE(country_code, '') = ''))")
        params.append(country.strip().lower())

    title_sql = " OR ".join([r"LOWER(title) LIKE ? ESCAPE '\'"] * len(probes))
    match_sql = " OR ".join(
        [r"LOWER(title) LIKE ? ESCAPE '\' "
         r"OR LOWER(COALESCE(description, '')) LIKE ? ESCAPE '\'"] * len(probes))

    for p in probes:
        params += [f"%{p}%", f"%{p}%"]
    where.append("(" + match_sql + ")")
    # Title-priority tier repeats the probes, then the cap.
    params += [f"%{p}%" for p in probes]
    params.append(int(cap))

    # Column list matches what ats.to_unified reads, so a recalled row can be
    # mapped onto the same job schema every other source already returns
    # (company_logo, redirect_url, requires_account...) instead of the digest
    # inventing a second shape the UI would have to special-case.
    return db.execute(
        "SELECT id, fingerprint, title, company, location, work_mode, "
        "       employment_type, experience_level, apply_url, posted_at, "
        "       platform, company_token, salary_min, salary_max, "
        "       salary_text, salary_currency, description "
        "FROM ats_jobs WHERE " + " AND ".join(where) +
        " ORDER BY (CASE WHEN " + title_sql + " THEN 0 ELSE 1 END), "
        # NULLs forced last explicitly: Postgres sorts them FIRST under DESC
        # and SQLite last (see CLAUDE.md).
        "(posted_at IS NULL), posted_at DESC LIMIT ?",
        tuple(params),
    ).fetchall()


def score_rows(rows, keywords, limit=DEFAULT_LIMIT):
    """Word-boundary scoring of recalled rows. No DB, no lock, no AI.

    Same weights and same title+company de-duplication as `rank`, so the two
    paths agree; only the candidate set differs (recalled subset vs whole
    corpus). Keywords are few here (<= _MAX_KEYWORDS), so a direct padded
    substring test beats the n-gram index `_hits` builds - that index pays off
    only in the batch case, where the needle list is the union across users.
    """
    scored = []
    for r in rows:
        t_title = _tokenize(r["title"])
        t_desc = _tokenize(r["description"])
        total, titled, matched = 0, 0, []
        for display, needle in keywords:
            if needle in t_title:
                total += _TITLE_WEIGHT
                titled += 1
            elif needle in t_desc:
                total += _DESC_WEIGHT
            else:
                continue
            matched.append(display)
        if total > 0:
            scored.append((titled, total, _sort_key(r["posted_at"]), r, matched))

    # Any title match outranks every description-only match, whatever the raw
    # total. Sorting on `total` alone let laundry-list job descriptions win:
    # "Partner Solutions Engineer" name-drops five technologies in its body and
    # so scored 5, beating a genuine "Frontend Engineer" title match on 3 - and
    # it surfaced for a React resume AND a Python one, which is the tell that
    # the signal was the JD's breadth, not the role's fit. A title states what
    # the role IS; a body mention may be one line of a wish list.
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

    from backend.services.ats import to_unified

    out, seen = [], set()
    for titled, total, _, r, matched in scored:
        key = (_tokenize(r["title"]), _tokenize(r["company"]))
        if key in seen:
            continue
        seen.add(key)
        job = to_unified(dict(r))
        job["match_score"] = total
        job["matched_keywords"] = matched
        out.append(job)
        if len(out) >= int(limit):
            break
    return out


def fetch_descriptions(db, job_ids):
    """Descriptions for the surviving candidates only - {id: description}.

    Stage 1 deliberately discards description text, so it is read back here for
    the handful of rows that actually reach the Groq prompt.
    """
    ids = [int(i) for i in job_ids if i is not None]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = db.execute(
        f"SELECT id, description FROM ats_jobs WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    return {r["id"]: (r["description"] or "") for r in rows}


def ai_score(candidates, descriptions, resume_text, ai_limit=DEFAULT_AI_LIMIT):
    """Stage 2: run the existing Groq job-match prompt on the top candidates.

    Exactly one Groq call per candidate, capped at `ai_limit`, so the per-user
    AI spend is bounded and predictable. A candidate whose call fails keeps its
    keyword score and is marked `ai_scored: False` rather than being dropped -
    a partial digest beats no digest.

    Returns the scored candidates ordered by AI match_percent (AI-scored first,
    then any that failed, which retain keyword order).
    """
    from backend.prompts import JOB_MATCH_PROMPT
    from backend.services.ai import call_groq, GroqError
    from backend.services.helpers import clean_json

    if not resume_text:
        return []

    out, calls = [], 0
    for cand in candidates:
        job = dict(cand)
        desc = descriptions.get(job.get("id"), "")
        # Without a description there is nothing for the model to compare
        # against; the keyword score already stands on the title alone.
        if calls >= int(ai_limit) or not desc.strip():
            job["ai_scored"] = False
            out.append(job)
            continue
        try:
            prompt = JOB_MATCH_PROMPT.format(
                job_description=desc[:4000], resume_text=resume_text[:12000],
            )
            parsed = json.loads(clean_json(
                call_groq(prompt, max_tokens=1500, json_mode=True)))
            calls += 1
            if not isinstance(parsed, dict) or "match_percent" not in parsed:
                raise ValueError("no match_percent in response")
            job["match_percent"] = max(0, min(100, int(parsed.get("match_percent", 0))))
            for key in ("matching_keywords", "missing_keywords"):
                val = parsed.get(key)
                job[key] = val if isinstance(val, list) else []
            job["gap_summary"] = parsed.get("gap_summary") or ""
            job["ai_scored"] = True
        except (GroqError, ValueError, TypeError, KeyError) as e:
            # One bad listing must not cost the whole digest.
            logger.warning(f"Digest AI score failed for job {job.get('id')}: {e}")
            job["ai_scored"] = False
        out.append(job)

    out.sort(key=lambda j: (j.get("ai_scored", False), j.get("match_percent", -1)),
             reverse=True)
    return out


def build_for_user(db, user_id, index=None, limit=DEFAULT_LIMIT,
                   ai_limit=DEFAULT_AI_LIMIT, max_days_old=DEFAULT_MAX_DAYS_OLD,
                   country=""):
    """Full digest for one user. Pass a shared `index` when running a batch -
    building one per user re-reads the corpus needlessly."""
    keywords = latest_keywords(db, user_id)
    if not keywords:
        return {"keywords": [], "candidates": []}
    if index is None:
        index = build_index(db, [n for _, n in keywords],
                            max_days_old=max_days_old, country=country)

    candidates = rank(index, keywords, limit=limit)
    if not candidates:
        return {"keywords": [d for d, _ in keywords], "candidates": []}

    descriptions = fetch_descriptions(db, [c["id"] for c in candidates])
    resume_text = latest_resume_text(db, user_id)
    scored = ai_score(candidates, descriptions, resume_text, ai_limit=ai_limit)
    return {"keywords": [d for d, _ in keywords], "candidates": scored}
