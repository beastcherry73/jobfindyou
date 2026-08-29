"""Keyless ATS job layer — jobs pulled straight from employers' own job boards.

Every platform here exposes a PUBLIC, UNAUTHENTICATED board endpoint: no API
key, no signup, no paid plan. That matters twice over — there is no credential
to leak or rotate, and the `apply_url` we store is the employer's own
application page rather than an aggregator redirect.

Platforms were chosen empirically, not assumed. Each candidate was tested
against a real company token before being built on (see
scratch/build_ats_registry.py):

    greenhouse      boards-api.greenhouse.io/v1/boards/{token}/jobs
    lever           api.lever.co/v0/postings/{token}
    ashby           api.ashbyhq.com/posting-api/job-board/{token}
    smartrecruiters api.smartrecruiters.com/v1/companies/{token}/postings
    workable        apply.workable.com/api/v1/widget/accounts/{token}
    recruitee       {token}.recruitee.com/api/offers/
    breezy          {token}.breezy.hr/json

Teamtailor was tested and REJECTED: it has no public subdomain board (every
`{token}.teamtailor.com` probed returned 404 — customers run on their own
domains) and api.teamtailor.com requires both an API key and a version header,
so it fails the keyless bar for this tier.

Because the jobs live in our own Postgres, the search filters here are exact
and fully combinable — unlike the aggregator APIs, where each provider supports
a different subset.
"""

import html
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests as http_requests

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              os.pardir, "data", "ats_companies.json")

USER_AGENT = "Mozilla/5.0 (compatible; JobSpike/1.0; +https://www.jobspike.in)"
HTTP_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
HTTP_TIMEOUT = 25

# A handful of enterprise boards carry thousands of postings (Bosch alone had
# ~4.8k). Capping keeps one employer from swamping the corpus and keeps a sync
# pass bounded; the cap is per company per run.
MAX_JOBS_PER_COMPANY = 300

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _text(value, limit=6000):
    """HTML/entity-laden provider text -> flat plain text, length-capped."""
    if not value:
        return ""
    s = str(value)
    # Greenhouse double-escapes ("&lt;p&gt;"), so unescape before stripping.
    if "&lt;" in s or "&amp;" in s:
        s = html.unescape(s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    # Postgres text columns reject NUL bytes outright; scrub control characters
    # before they ever reach a parameter.
    s = s.replace("\x00", " ")
    s = _CTRL_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()[:limit]


def _iso(value):
    """Normalize any provider timestamp to a UTC ISO-8601 string (None if unusable).

    Everything is converted to a single UTC representation on the way in. The
    providers disagree wildly (Lever sends epoch ms, Greenhouse sends
    "-04:00" offsets, Workable sends bare dates), and posted_at has to be
    directly comparable for the "posted within N days" filter and for date
    sorting — under Postgres TIMESTAMPTZ and under dev SQLite's plain text
    columns alike.

    Returns None rather than "" when there is no usable timestamp: posted_at is
    a real TIMESTAMPTZ in production, and Postgres rejects an empty string for
    that type outright. Dev SQLite would have accepted "" and hidden the fault
    until deploy.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Lever reports epoch milliseconds.
        try:
            seconds = value / 1000.0 if value > 1e11 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


# ── Country resolution ─────────────────────────────────────────────────────
# Some platforms hand us an ISO2 code outright (Lever, SmartRecruiters,
# Workable, Recruitee, Breezy); Greenhouse and Ashby give only a location
# string, so it has to be parsed. Anything unresolved is stored as "" and
# simply never matches a country-filtered search — we would rather under-report
# than file a job under the wrong country.
_COUNTRY_ALIASES = {
    "india": "in", "bharat": "in",
    "united states": "us", "usa": "us", "u.s.": "us", "u.s.a.": "us",
    "united states of america": "us", "america": "us",
    "united kingdom": "gb", "uk": "gb", "u.k.": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb",
    "great britain": "gb", "britain": "gb",
    "bangladesh": "bd", "pakistan": "pk", "sri lanka": "lk",
    "united arab emirates": "ae", "uae": "ae", "u.a.e.": "ae",
    "saudi arabia": "sa", "ksa": "sa", "kingdom of saudi arabia": "sa",
    "qatar": "qa", "philippines": "ph", "the philippines": "ph",
    "indonesia": "id", "malaysia": "my", "singapore": "sg", "japan": "jp",
    "hong kong": "hk", "south korea": "kr", "korea": "kr",
    "republic of korea": "kr", "thailand": "th", "vietnam": "vn",
    "viet nam": "vn", "australia": "au", "new zealand": "nz", "canada": "ca",
    "germany": "de", "deutschland": "de", "france": "fr",
    "netherlands": "nl", "the netherlands": "nl", "holland": "nl",
    "italy": "it", "italia": "it", "spain": "es", "espana": "es",
    "austria": "at", "switzerland": "ch", "schweiz": "ch", "poland": "pl",
    "polska": "pl", "ireland": "ie", "republic of ireland": "ie",
    "sweden": "se", "sverige": "se", "norway": "no", "denmark": "dk",
    "finland": "fi", "belgium": "be", "portugal": "pt", "turkey": "tr",
    "turkiye": "tr", "south africa": "za", "nigeria": "ng", "kenya": "ke",
    "egypt": "eg", "brazil": "br", "brasil": "br", "mexico": "mx",
    "argentina": "ar", "chile": "cl", "colombia": "co",
    # Bare codes and extra countries seen in real board strings
    # ("Remote - US", "Remote UK", "Vilnius").
    "us": "us", "gb": "gb", "ind": "in", "sgp": "sg", "deu": "de",
    "can": "ca", "aus": "au", "isr": "il", "israel": "il",
    "lithuania": "lt", "latvia": "lv", "estonia": "ee", "romania": "ro",
    "bulgaria": "bg", "greece": "gr", "hungary": "hu", "ukraine": "ua",
    "serbia": "rs", "croatia": "hr", "slovakia": "sk", "slovenia": "si",
    "czechia": "cz", "czech republic": "cz", "cyprus": "cy", "malta": "mt",
    "luxembourg": "lu", "iceland": "is", "morocco": "ma", "tunisia": "tn",
    "ghana": "gh", "rwanda": "rw", "uganda": "ug", "tanzania": "tz",
    "jordan": "jo", "kuwait": "kw", "bahrain": "bh", "oman": "om",
    "lebanon": "lb", "peru": "pe", "uruguay": "uy", "costa rica": "cr",
    "panama": "pa", "china": "cn", "taiwan": "tw", "cambodia": "kh",
    "myanmar": "mm", "nepal": "np", "mauritius": "mu",
}

# Major hiring hubs in the regions this layer is weighted toward. Used only
# when a location string carries no country at all ("Bengaluru", "Dubai").
_CITY_COUNTRY = {
    "bengaluru": "in", "bangalore": "in", "mumbai": "in", "bombay": "in",
    "delhi": "in", "new delhi": "in", "gurugram": "in", "gurgaon": "in",
    "noida": "in", "hyderabad": "in", "chennai": "in", "pune": "in",
    "kolkata": "in", "ahmedabad": "in", "jaipur": "in", "kochi": "in",
    "coimbatore": "in", "indore": "in", "chandigarh": "in", "trivandrum": "in",
    "thiruvananthapuram": "in", "bhubaneswar": "in", "nagpur": "in",
    "dhaka": "bd", "karachi": "pk", "lahore": "pk", "islamabad": "pk",
    "colombo": "lk",
    "dubai": "ae", "abu dhabi": "ae", "sharjah": "ae", "riyadh": "sa",
    "jeddah": "sa", "dammam": "sa", "doha": "qa", "cairo": "eg",
    "amman": "jo", "kuwait city": "kw", "manama": "bh", "muscat": "om",
    "tel aviv": "il",
    "singapore": "sg", "kuala lumpur": "my", "jakarta": "id", "bandung": "id",
    "surabaya": "id", "manila": "ph", "makati": "ph", "cebu": "ph",
    "taguig": "ph", "bangkok": "th", "hanoi": "vn", "ho chi minh city": "vn",
    "saigon": "vn", "phnom penh": "kh", "yangon": "mm",
    "tokyo": "jp", "osaka": "jp", "seoul": "kr", "hong kong": "hk",
    "taipei": "tw", "shanghai": "cn", "beijing": "cn", "shenzhen": "cn",
    "london": "gb", "manchester": "gb", "edinburgh": "gb", "dublin": "ie",
    "berlin": "de", "munich": "de", "münchen": "de", "hamburg": "de",
    "frankfurt": "de", "paris": "fr", "amsterdam": "nl", "rotterdam": "nl",
    "madrid": "es", "barcelona": "es", "lisbon": "pt", "milan": "it",
    "rome": "it", "zurich": "ch", "zürich": "ch", "vienna": "at",
    "warsaw": "pl", "krakow": "pl", "kraków": "pl", "stockholm": "se",
    "oslo": "no", "copenhagen": "dk", "helsinki": "fi", "brussels": "be",
    "istanbul": "tr", "prague": "cz", "budapest": "hu", "bucharest": "ro",
    "sofia": "bg", "athens": "gr",
    "new york": "us", "nyc": "us", "san francisco": "us", "seattle": "us",
    "austin": "us", "boston": "us", "chicago": "us", "los angeles": "us",
    "denver": "us", "atlanta": "us", "toronto": "ca", "vancouver": "ca",
    "montreal": "ca", "sydney": "au", "melbourne": "au", "brisbane": "au",
    "auckland": "nz", "johannesburg": "za", "cape town": "za",
    "lagos": "ng", "nairobi": "ke", "sao paulo": "br", "são paulo": "br",
    "mexico city": "mx", "buenos aires": "ar", "bogota": "co",
    "bogotá": "co", "santiago": "cl",
    # Added after auditing the live corpus for unresolved location strings.
    "new york city": "us", "palo alto": "us", "san mateo": "us",
    "mountain view": "us", "san jose": "us", "san francisco bay area": "us",
    "sunnyvale": "us", "redwood city": "us", "santa clara": "us",
    "bellevue": "us", "washington dc": "us", "san diego": "us",
    "salt lake city": "us", "ann arbor": "us", "pittsburgh": "us",
    "vilnius": "lt", "kaunas": "lt", "riga": "lv", "tallinn": "ee",
    "tlv": "il", "herzliya": "il", "haifa": "il",
    "belgrade": "rs", "zagreb": "hr", "ljubljana": "si", "bratislava": "sk",
    "wroclaw": "pl", "poznan": "pl", "gdansk": "pl",
    "cluj": "ro", "timisoara": "ro", "porto": "pt", "valencia": "es",
    "malaga": "es", "seville": "es", "toulouse": "fr", "lyon": "fr",
    "cologne": "de", "stuttgart": "de", "dusseldorf": "de", "leipzig": "de",
    "utrecht": "nl", "eindhoven": "nl", "antwerp": "be", "ghent": "be",
    "gothenburg": "se", "malmo": "se", "aarhus": "dk", "bergen": "no",
    "espoo": "fi", "tampere": "fi", "basel": "ch", "geneva": "ch",
    "lausanne": "ch", "graz": "at", "linz": "at", "cork": "ie",
    "galway": "ie", "belfast": "gb", "glasgow": "gb", "leeds": "gb",
    "bristol": "gb", "cambridge": "gb", "oxford": "gb", "cardiff": "gb",
    "ottawa": "ca", "calgary": "ca", "waterloo": "ca", "halifax": "ca",
    "perth": "au", "adelaide": "au", "canberra": "au", "wellington": "nz",
    "christchurch": "nz", "guadalajara": "mx", "monterrey": "mx",
    "medellin": "co", "lima": "pe", "montevideo": "uy", "curitiba": "br",
    "belo horizonte": "br", "rio de janeiro": "br", "porto alegre": "br",
    "accra": "gh", "kigali": "rw", "kampala": "ug", "casablanca": "ma",
    "alexandria": "eg", "giza": "eg",
    "navi mumbai": "in", "thane": "in", "mohali": "in", "vadodara": "in",
    "surat": "in", "lucknow": "in", "mysuru": "in", "mysore": "in",
    "visakhapatnam": "in", "goa": "in", "guwahati": "in",
    "ho chi minh": "vn", "da nang": "vn", "quezon city": "ph",
    "pasig": "ph", "mandaluyong": "ph", "penang": "my", "johor": "my",
    "selangor": "my", "petaling jaya": "my", "yogyakarta": "id",
    "tangerang": "id", "medan": "id", "bekasi": "id", "chiang mai": "th",
}

# Longest-first so "united states" is tested before shorter fragments and
# "san francisco bay area" before "san francisco".
_ALIASES_BY_LENGTH = sorted(_COUNTRY_ALIASES, key=len, reverse=True)
_CITIES_BY_LENGTH = sorted(_CITY_COUNTRY, key=len, reverse=True)

_US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}

_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)


def resolve_country(location, explicit=None):
    """Best-effort ISO2 country for a listing. '' when genuinely unknown.

    ATS location strings are free text and wildly inconsistent: "Remote - US",
    "United States (Remote)", "San Mateo, CA United States", "Spain (Remote)",
    "Home based - EMEA". So rather than trusting position, we scan the whole
    string -- longest country name first, then bare country codes as whole
    tokens, then a US state code, then a known city.

    Strings that name no country at all ("Distributed", "Home based -
    Worldwide", "Europe") correctly resolve to '' and are simply never returned
    by a country-filtered search. We would rather under-report than file a job
    under a country it was never posted in.
    """
    if explicit:
        code = str(explicit).strip().lower()
        if len(code) == 2 and code.isalpha():
            return code
        if code in _COUNTRY_ALIASES:
            return _COUNTRY_ALIASES[code]
    if not location:
        return ""
    text = re.sub(r"[()\[\]|/;]", ",", str(location).lower())
    text = re.sub(r"\s+-\s+", ",", text)
    text = _WS_RE.sub(" ", text)

    # Multi-word country names, longest first ("united states" before "states").
    for alias in _ALIASES_BY_LENGTH:
        if " " in alias and re.search(r"\b" + re.escape(alias) + r"\b", text):
            return _COUNTRY_ALIASES[alias]

    segments = [seg.strip() for seg in text.split(",") if seg.strip()]
    tokens = [t for seg in segments for t in re.findall(r"[a-z.]+", seg)]

    # Single-word country names and bare codes, as WHOLE tokens -- substring
    # matching here would read "us" out of "Houston".
    for token in tokens:
        if token in _COUNTRY_ALIASES:
            return _COUNTRY_ALIASES[token]

    # "San Mateo, CA" -- a bare US state code.
    for seg in reversed(segments):
        if seg in _US_STATES:
            return "us"

    # Fall back to a known hiring hub ("Bengaluru", "New York City", "Dubai").
    for seg in segments:
        if seg in _CITY_COUNTRY:
            return _CITY_COUNTRY[seg]
    for city in _CITIES_BY_LENGTH:
        if re.search(r"\b" + re.escape(city) + r"\b", text):
            return _CITY_COUNTRY[city]
    return ""


def resolve_work_mode(location, remote_flag=None, hybrid_flag=None, workplace=None):
    """'remote' | 'hybrid' | 'onsite' — from platform flags first, text second."""
    wp = (str(workplace or "")).strip().lower()
    if wp in ("remote", "hybrid", "onsite", "on-site", "onSite".lower()):
        return "onsite" if wp in ("onsite", "on-site") else wp
    if hybrid_flag:
        return "hybrid"
    if remote_flag:
        return "remote"
    text = str(location or "")
    if _HYBRID_RE.search(text):
        return "hybrid"
    if _REMOTE_RE.search(text):
        return "remote"
    return "onsite"


# ── Employment type / experience level normalization ───────────────────────
_EMPLOYMENT_MAP = {
    "fulltime": "Full-time", "full time": "Full-time", "full-time": "Full-time",
    "permanent": "Full-time", "regular": "Full-time",
    "parttime": "Part-time", "part time": "Part-time", "part-time": "Part-time",
    "contract": "Contract", "contractor": "Contract", "freelance": "Contract",
    "temporary": "Temporary", "temp": "Temporary", "seasonal": "Temporary",
    "intern": "Internship", "internship": "Internship", "trainee": "Internship",
    "apprenticeship": "Internship", "graduate": "Internship",
}

EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Temporary", "Internship"]


def normalize_employment_type(value):
    """Map any provider's employment wording onto ONE of EMPLOYMENT_TYPES.

    Real boards emit things like "Permanent, Full-Time", "On-Roll", "Parttime
    Fixed Term" and "Independent Contractor". Anything that cannot be placed
    confidently returns '' rather than a tidied-up variant of itself, because
    an exact filter is only useful if the stored values are a genuinely closed
    set.
    """
    if not value:
        return ""
    text = _WS_RE.sub(" ", str(value).replace("_", " ").replace("-", " ")).strip().lower()
    if not text:
        return ""
    # Order matters: the more specific arrangement wins over the contract term,
    # so "Contract, Full-Time" is a contract and "Parttime Fixed Term" is part
    # time.
    if re.search(r"\b(intern|internship|trainee|apprentice)\b", text):
        return "Internship"
    if re.search(r"\b(part time|parttime)\b", text):
        return "Part-time"
    if re.search(r"\b(contract|contractor|freelance|consultant)\b", text):
        return "Contract"
    if re.search(r"\b(temporary|temp|seasonal|fixed term|short term)\b", text):
        return "Temporary"
    if re.search(r"\b(full time|fulltime|permanent|regular|on roll)\b", text):
        return "Full-time"
    return ""


EXPERIENCE_LEVELS = ["internship", "entry", "mid", "senior", "lead", "executive"]

_EXPERIENCE_MAP = {
    "internship": "internship", "intern": "internship", "student": "internship",
    "entry level": "entry", "entry_level": "entry", "entrylevel": "entry",
    "entry": "entry", "junior": "entry", "graduate": "entry",
    "associate": "mid", "mid": "mid", "mid level": "mid", "midlevel": "mid",
    "mid-senior level": "senior", "mid_senior_level": "senior",
    "senior": "senior", "senior level": "senior",
    "lead": "lead", "manager": "lead", "principal": "lead", "staff": "lead",
    "director": "executive", "executive": "executive", "vp": "executive",
    "c level": "executive", "chief": "executive",
}

# Title keywords, checked longest-first so "senior manager" doesn't read as
# "manager". Used when the platform exposes no structured seniority field
# (Greenhouse, Lever, Ashby, Breezy) so the filter works across all sources.
_TITLE_LEVEL_RULES = [
    (r"\b(intern|internship|trainee|apprentice)\b", "internship"),
    (r"\b(chief|cto|ceo|coo|cfo|ciso|vp|vice president|svp|evp|head of|director)\b",
     "executive"),
    # Checked BEFORE the lead rule so "Senior Product Manager" reads as senior.
    (r"\b(sr|senior|snr)\b", "senior"),
    # A bare "manager" is deliberately NOT here: Product/Program/Account Manager
    # are usually individual-contributor roles, and treating them as lead made a
    # third of the corpus "lead" in testing. Only unambiguous people-leadership
    # and technical-seniority titles qualify.
    (r"\b(principal|staff|lead)\b", "lead"),
    # "Product Manager" and "Data Manager" are excluded on purpose -- they are
    # normally IC roles, unlike an Engineering/Design Manager.
    (r"\b(engineering|development|design|software) manager\b", "lead"),
    (r"\bmanager,? (engineering|software|design)\b", "lead"),
    (r"\b(jr|junior|entry level|fresher|campus|new grad|graduate)\b", "entry"),
]


def normalize_experience_level(value, title=""):
    if value:
        key = _WS_RE.sub(" ", str(value)).strip().lower()
        if key in _EXPERIENCE_MAP:
            return _EXPERIENCE_MAP[key]
        squashed = key.replace("_", " ")
        if squashed in _EXPERIENCE_MAP:
            return _EXPERIENCE_MAP[squashed]
    text = (title or "").lower()
    for pattern, level in _TITLE_LEVEL_RULES:
        if level and re.search(pattern, text):
            return level
    return ""


def _money(value):
    """Provider salary figure -> int, or None. Rejects nonsense/zero."""
    if value in (None, "", 0):
        return None
    try:
        n = int(float(value))
    except (ValueError, TypeError):
        return None
    return n if n > 0 else None


# ── Platform adapters ──────────────────────────────────────────────────────
# Each adapter: url(token) -> board endpoint; rows(payload) -> raw job list;
# total(payload, rows) -> corpus size; apply_url(job, token) -> the employer's
# own application page; normalize(job, token, company) -> unified dict.


def _gh_normalize(j, token, company):
    location = ""
    if isinstance(j.get("location"), dict):
        location = j["location"].get("name") or ""
    title = j.get("title") or ""
    return {
        "source_id": str(j.get("id") or ""),
        "title": title,
        "company": j.get("company_name") or company,
        "location": location,
        "country_code": resolve_country(location),
        "work_mode": resolve_work_mode(location),
        "employment_type": "",
        "experience_level": normalize_experience_level(None, title),
        "salary_min": None, "salary_max": None, "salary_currency": "",
        "salary_text": "",
        "posted_at": _iso(j.get("first_published") or j.get("updated_at")),
        "apply_url": j.get("absolute_url") or "",
        "description": _text(j.get("content")),
    }


def _lever_normalize(j, token, company):
    cats = j.get("categories") if isinstance(j.get("categories"), dict) else {}
    location = cats.get("location") or ""
    all_locs = cats.get("allLocations")
    if isinstance(all_locs, list) and len(all_locs) > 1:
        location = ", ".join(str(x) for x in all_locs[:3] if x)
    title = j.get("text") or ""
    salary = j.get("salaryRange") if isinstance(j.get("salaryRange"), dict) else {}
    return {
        "source_id": str(j.get("id") or ""),
        "title": title,
        "company": company,
        "location": location,
        "country_code": resolve_country(location, j.get("country")),
        "work_mode": resolve_work_mode(location, workplace=j.get("workplaceType")),
        "employment_type": normalize_employment_type(cats.get("commitment")),
        "experience_level": normalize_experience_level(None, title),
        "salary_min": _money(salary.get("min")),
        "salary_max": _money(salary.get("max")),
        "salary_currency": (salary.get("currency") or "").upper(),
        "salary_text": "",
        "posted_at": _iso(j.get("createdAt")),
        # hostedUrl is the employer's own Lever board page (the apply form is
        # one click on from there); applyUrl jumps straight into the form.
        "apply_url": j.get("hostedUrl") or j.get("applyUrl") or "",
        "description": _text(j.get("descriptionPlain") or j.get("description")),
    }


def _ashby_normalize(j, token, company):
    location = j.get("location") or ""
    extra = j.get("secondaryLocations")
    if isinstance(extra, list) and extra:
        names = [e.get("location") for e in extra
                 if isinstance(e, dict) and e.get("location")]
        if names:
            location = ", ".join([location] + names[:2]) if location else ", ".join(names[:3])
    country = ""
    addr = j.get("address")
    if isinstance(addr, dict):
        postal = addr.get("postalAddress")
        if isinstance(postal, dict):
            country = postal.get("addressCountry") or ""
    comp = j.get("compensation") if isinstance(j.get("compensation"), dict) else {}
    title = j.get("title") or ""
    return {
        "source_id": str(j.get("id") or ""),
        "title": title,
        "company": company,
        "location": location,
        "country_code": resolve_country(location, country),
        "work_mode": resolve_work_mode(location, remote_flag=j.get("isRemote"),
                                       workplace=j.get("workplaceType")),
        "employment_type": normalize_employment_type(j.get("employmentType")),
        "experience_level": normalize_experience_level(None, title),
        "salary_min": None, "salary_max": None, "salary_currency": "",
        "salary_text": _text(comp.get("scrapeableCompensationSalarySummary")
                             or comp.get("compensationTierSummary"), 120),
        "posted_at": _iso(j.get("publishedAt")),
        "apply_url": j.get("jobUrl") or j.get("applyUrl") or "",
        "description": _text(j.get("descriptionPlain") or j.get("descriptionHtml")),
    }


def _sr_normalize(j, token, company):
    loc = j.get("location") if isinstance(j.get("location"), dict) else {}
    location = loc.get("fullLocation") or ", ".join(
        x for x in [loc.get("city"), loc.get("region")] if x)
    emp = j.get("typeOfEmployment") if isinstance(j.get("typeOfEmployment"), dict) else {}
    exp = j.get("experienceLevel") if isinstance(j.get("experienceLevel"), dict) else {}
    comp = j.get("company") if isinstance(j.get("company"), dict) else {}
    title = j.get("name") or ""
    return {
        "source_id": str(j.get("id") or j.get("uuid") or ""),
        "title": title,
        "company": comp.get("name") or company,
        "location": location,
        "country_code": resolve_country(location, loc.get("country")),
        "work_mode": resolve_work_mode(location, remote_flag=loc.get("remote"),
                                       hybrid_flag=loc.get("hybrid")),
        "employment_type": normalize_employment_type(emp.get("label") or emp.get("id")),
        "experience_level": normalize_experience_level(
            exp.get("id") or exp.get("label"), title),
        "salary_min": None, "salary_max": None, "salary_currency": "",
        "salary_text": "",
        "posted_at": _iso(j.get("releasedDate")),
        "apply_url": f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}",
        "description": "",   # not in the list response; detail needs 1 call/job
    }


def _workable_normalize(j, token, company):
    location = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)
    country = ""
    locs = j.get("locations")
    if isinstance(locs, list) and locs and isinstance(locs[0], dict):
        country = locs[0].get("countryCode") or ""
    title = j.get("title") or ""
    return {
        "source_id": str(j.get("shortcode") or ""),
        "title": title,
        "company": company,
        "location": location,
        "country_code": resolve_country(location, country or j.get("country")),
        "work_mode": resolve_work_mode(location, remote_flag=j.get("telecommuting")),
        "employment_type": normalize_employment_type(j.get("employment_type")),
        "experience_level": normalize_experience_level(j.get("experience"), title),
        "salary_min": None, "salary_max": None, "salary_currency": "",
        "salary_text": "",
        "posted_at": _iso(j.get("published_on") or j.get("created_at")),
        "apply_url": j.get("url") or j.get("application_url") or j.get("shortlink") or "",
        "description": _text(j.get("description")),
    }


def _recruitee_normalize(j, token, company):
    location = j.get("location") or ", ".join(
        x for x in [j.get("city"), j.get("country")] if x)
    salary = j.get("salary") if isinstance(j.get("salary"), dict) else {}
    title = j.get("title") or ""
    return {
        "source_id": str(j.get("id") or j.get("slug") or ""),
        "title": title,
        "company": j.get("company_name") or company,
        "location": location,
        "country_code": resolve_country(location, j.get("country_code") or j.get("country")),
        "work_mode": resolve_work_mode(location, remote_flag=j.get("remote"),
                                       hybrid_flag=j.get("hybrid")),
        "employment_type": normalize_employment_type(j.get("employment_type_code")),
        "experience_level": normalize_experience_level(j.get("experience_code"), title),
        "salary_min": _money(salary.get("min")),
        "salary_max": _money(salary.get("max")),
        "salary_currency": (salary.get("currency") or "").upper(),
        "salary_text": "",
        "posted_at": _iso(j.get("published_at") or j.get("created_at")),
        "apply_url": j.get("careers_apply_url") or j.get("careers_url") or "",
        "description": _text(j.get("description")),
    }


def _breezy_normalize(j, token, company):
    loc = j.get("location") if isinstance(j.get("location"), dict) else {}
    country = ""
    if isinstance(loc.get("country"), dict):
        country = loc["country"].get("id") or loc["country"].get("name") or ""
    location = loc.get("name") or ", ".join(
        x for x in [loc.get("city"), country] if x)
    etype = j.get("type") if isinstance(j.get("type"), dict) else {}
    title = j.get("name") or ""
    return {
        "source_id": str(j.get("id") or ""),
        "title": title,
        "company": j.get("company") if isinstance(j.get("company"), str) else company,
        "location": location,
        "country_code": resolve_country(location, country),
        "work_mode": resolve_work_mode(location, remote_flag=loc.get("is_remote")),
        "employment_type": normalize_employment_type(etype.get("name") or etype.get("id")),
        "experience_level": normalize_experience_level(None, title),
        "salary_min": None, "salary_max": None, "salary_currency": "",
        "salary_text": "",
        "posted_at": _iso(j.get("published_date")),
        "apply_url": j.get("url") or "",
        "description": _text(j.get("description")),
    }


PLATFORMS = {
    "greenhouse": {
        "label": "Greenhouse",
        "url": lambda t: f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true",
        "rows": lambda d: d.get("jobs", []) if isinstance(d, dict) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("absolute_url", ""),
        "normalize": _gh_normalize,
        # Greenhouse-hosted boards let you apply as a guest; no account needed.
        "requires_account": False,
        "destination": "The employer's own Greenhouse-hosted board (often on the "
                       "company's domain). Guest application — no account required.",
    },
    "lever": {
        "label": "Lever",
        "url": lambda t: f"https://api.lever.co/v0/postings/{t}?mode=json",
        "rows": lambda d: d if isinstance(d, list) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("hostedUrl", ""),
        "normalize": _lever_normalize,
        "requires_account": False,
        "destination": "jobs.lever.co/<company> posting page. Guest application "
                       "with an optional resume-autofill; no account required.",
    },
    "ashby": {
        "label": "Ashby",
        "url": lambda t: f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true",
        "rows": lambda d: d.get("jobs", []) if isinstance(d, dict) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("jobUrl", ""),
        "normalize": _ashby_normalize,
        "requires_account": False,
        "destination": "jobs.ashbyhq.com/<company> posting page. Guest "
                       "application; no account required.",
    },
    "smartrecruiters": {
        "label": "SmartRecruiters",
        "url": lambda t: f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=100",
        "rows": lambda d: d.get("content", []) if isinstance(d, dict) else [],
        "total": lambda d, rows: (d.get("totalFound") if isinstance(d, dict) else None) or len(rows),
        "apply_url": lambda j, t: f"https://jobs.smartrecruiters.com/{t}/{j.get('id')}",
        "normalize": _sr_normalize,
        "paginated": True,
        # SmartRecruiters' apply flow asks for an account (or a social/SSO
        # sign-in) before the application can be submitted.
        "requires_account": True,
        "destination": "jobs.smartrecruiters.com/<company>/<id>. Applying "
                       "generally requires creating a SmartRecruiters account "
                       "or signing in with Google/LinkedIn.",
    },
    "workable": {
        "label": "Workable",
        "url": lambda t: f"https://apply.workable.com/api/v1/widget/accounts/{t}?details=true",
        "rows": lambda d: d.get("jobs", []) if isinstance(d, dict) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("url") or j.get("shortlink") or "",
        "normalize": _workable_normalize,
        "requires_account": False,
        "destination": "apply.workable.com/j/<code>. Guest application; no "
                       "account required.",
    },
    "recruitee": {
        "label": "Recruitee",
        "url": lambda t: f"https://{t}.recruitee.com/api/offers/",
        "rows": lambda d: d.get("offers", []) if isinstance(d, dict) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("careers_apply_url") or j.get("careers_url") or "",
        "normalize": _recruitee_normalize,
        "requires_account": False,
        "destination": "The company's Recruitee careers site. Guest "
                       "application; no account required.",
    },
    "breezy": {
        "label": "Breezy HR",
        "url": lambda t: f"https://{t}.breezy.hr/json",
        "rows": lambda d: d if isinstance(d, list) else [],
        "total": lambda d, rows: len(rows),
        "apply_url": lambda j, t: j.get("url", ""),
        "normalize": _breezy_normalize,
        "requires_account": False,
        "destination": "<company>.breezy.hr posting page. Guest application; "
                       "no account required.",
    },
}


def board_url(platform, token):
    return PLATFORMS[platform]["url"](token)


# ── Registry ───────────────────────────────────────────────────────────────
_registry_cache = None


def load_registry():
    """The empirically verified company -> ATS platform mappings."""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        companies = data.get("companies") or []
    except (OSError, ValueError) as e:
        logger.warning(f"ATS registry unavailable: {e}")
        companies = []
    _registry_cache = [c for c in companies
                       if c.get("platform") in PLATFORMS and c.get("token")]
    return _registry_cache


def registry_stats():
    reg = load_registry()
    by_platform, by_region = {}, {}
    for c in reg:
        by_platform[c["platform"]] = by_platform.get(c["platform"], 0) + 1
        by_region[c.get("region", "?")] = by_region.get(c.get("region", "?"), 0) + 1
    return {"companies": len(reg), "by_platform": by_platform, "by_region": by_region}


# ── Fetch ──────────────────────────────────────────────────────────────────
def fetch_board(platform, token, session=None):
    """Fetch one company's full board. Returns [] on any failure (never raises).

    A dead token or a transient network blip must not abort a whole sync pass,
    so failures are logged and skipped.
    """
    spec = PLATFORMS[platform]
    sess = session or http_requests
    rows = []
    try:
        if spec.get("paginated"):
            offset = 0
            while len(rows) < MAX_JOBS_PER_COMPANY:
                url = spec["url"](token) + f"&offset={offset}"
                r = sess.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
                if r.status_code != 200:
                    break
                page = spec["rows"](r.json())
                if not page:
                    break
                rows.extend(page)
                offset += len(page)
                if len(page) < 100:
                    break
        else:
            r = sess.get(spec["url"](token), headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                logger.info(f"ATS {platform}/{token}: HTTP {r.status_code}")
                return []
            rows = spec["rows"](r.json())
    except (http_requests.RequestException, ValueError) as e:
        logger.info(f"ATS {platform}/{token} fetch failed: {e}")
        return []
    return rows[:MAX_JOBS_PER_COMPANY]


def normalize_board(platform, token, company, rows):
    """Raw board rows -> unified job dicts, dropping anything unusable."""
    spec = PLATFORMS[platform]
    out = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            job = spec["normalize"](raw, token, company)
        except Exception as e:            # one bad row must not kill the board
            logger.debug(f"ATS {platform}/{token} row skipped: {e}")
            continue
        if not job.get("title") or not job.get("apply_url"):
            continue
        job["platform"] = platform
        job["company_token"] = token
        job["publisher"] = spec["label"]
        job["fingerprint"] = f"{platform}:{token}:{job['source_id']}"
        job["search_text"] = " ".join([
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
        ]).lower()
        out.append(job)
    return out


# ── Sync ───────────────────────────────────────────────────────────────────
# The registry is walked with a persisted cursor so a pass can stop at a time
# budget and the next invocation resumes where it left off. That matters on
# Vercel, where a function has a hard wall-clock ceiling that a full 250-company
# sweep would blow through.
#
# Every DB block below is deliberately short. backend/database.py shares ONE
# Postgres connection per instance behind a global lock, so holding a
# transaction open across hundreds of HTTP fetches would stall every other
# request on that instance. Fetching happens outside the lock; only the writes
# take it, in batches.

def _timestamp_param(db, value):
    """Return a timestamp parameter in the form THIS driver actually accepts.

    pg8000 sends a Python str as OID 25 (TEXT), and Postgres refuses text where
    it wants TIMESTAMPTZ -- both on INSERT into posted_at and in a `posted_at >=
    ?` comparison. So the Postgres path gets real datetime objects. Dev SQLite
    keeps ISO strings: its columns are plain text, string comparison on
    normalized UTC values is correct there, and its default datetime adapter is
    deprecated from Python 3.12.

    This is exactly the class of bug SQLite hides: every one of these worked in
    dev and would have failed on the first production sync.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    try:
        from backend.database import PgConnection
        if isinstance(db, PgConnection):
            return dt
    except Exception:
        pass
    return dt.isoformat()


_CURSOR_KEY = "ats_sync_cursor"
# The pass is network-bound (a board fetch dwarfs its write), so fetches run in
# parallel. Writes remain serial — one shared Postgres connection per instance.
FETCH_CONCURRENCY = 8
_UPSERT_BATCH = 100
STALE_AFTER_DAYS = 21

_COLUMNS = [
    "fingerprint", "platform", "company_token", "source_id", "title", "company",
    "location", "country_code", "work_mode", "employment_type",
    "experience_level", "salary_min", "salary_max", "salary_currency",
    "salary_text", "posted_at", "apply_url", "description", "search_text",
]


def _read_cursor(db):
    """Where the last pass stopped. 0 when unavailable (dev SQLite has no app_meta)."""
    try:
        row = db.execute("SELECT meta_value FROM app_meta WHERE meta_key = ?",
                         (_CURSOR_KEY,)).fetchone()
        return int(row["meta_value"]) if row and row["meta_value"] else 0
    except Exception:
        return 0


def _write_cursor(db, value):
    try:
        db.execute(
            "INSERT INTO app_meta (meta_key, meta_value) VALUES (?, ?) "
            "ON CONFLICT (meta_key) DO UPDATE SET meta_value = excluded.meta_value",
            (_CURSOR_KEY, str(value)),
        )
    except Exception:
        pass          # dev SQLite without app_meta: a pass just restarts at 0


def _upsert_batch(db, jobs):
    """Insert-or-refresh a batch of jobs, keyed on the UNIQUE fingerprint.

    This is what makes a re-run idempotent: a job already stored is UPDATEd in
    place (and its last_seen_at bumped) rather than inserted a second time.
    """
    if not jobs:
        return 0
    cols = ", ".join(_COLUMNS)
    placeholders = "(" + ", ".join(["?"] * len(_COLUMNS)) + ", CURRENT_TIMESTAMP)"
    updates = ", ".join(
        f"{c} = excluded.{c}" for c in _COLUMNS
        if c not in ("fingerprint", "platform", "company_token", "source_id")
    )
    sql = (
        f"INSERT INTO ats_jobs ({cols}, last_seen_at) VALUES "
        + ", ".join([placeholders] * len(jobs))
        + f" ON CONFLICT (fingerprint) DO UPDATE SET {updates}, "
          "last_seen_at = CURRENT_TIMESTAMP"
    )
    params = []
    for j in jobs:
        for c in _COLUMNS:
            value = j.get(c)
            if c == "posted_at":
                value = _timestamp_param(db, value)
            params.append(value)
    db.execute(sql, params)
    return len(jobs)


def _prune_company(db, platform, token, fingerprints):
    """Drop rows for jobs this company has since taken down.

    Only ever called with a NON-EMPTY live fingerprint set: an empty board is
    indistinguishable from a failed fetch, and we will not delete a company's
    listings on the strength of a network blip.
    """
    if not fingerprints:
        return 0
    marks = ", ".join(["?"] * len(fingerprints))
    cur = db.execute(
        f"DELETE FROM ats_jobs WHERE platform = ? AND company_token = ? "
        f"AND fingerprint NOT IN ({marks})",
        [platform, token] + list(fingerprints),
    )
    return getattr(cur, "rowcount", 0) or 0


def _fetch_and_normalize(entry):
    """Network-only half of a company sync. Safe to run concurrently."""
    platform, token = entry["platform"], entry["token"]
    company = entry.get("company") or token
    raw = fetch_board(platform, token)
    jobs = normalize_board(platform, token, company, raw)
    # A board can legitimately list one job twice (multi-location postings
    # sharing an id); Postgres refuses to touch the same conflict target twice
    # in one statement, so collapse before writing.
    unique = {}
    for j in jobs:
        unique[j["fingerprint"]] = j
    return entry, list(unique.values())


def _store_company(entry, jobs, stats, cursor_value=None):
    """DB-only half. One short transaction per company, cursor included.

    The cursor is committed in the SAME transaction as the company's rows, so a
    sync killed mid-pass (a serverless wall-clock limit, a deploy) still leaves
    a truthful resume point and the next invocation carries on instead of
    redoing work forever.
    """
    from backend.database import get_db

    platform, token = entry["platform"], entry["token"]
    if not jobs:
        # An empty board is indistinguishable from a failed fetch, so nothing is
        # pruned — but the cursor still advances, or one permanently dead board
        # would block the cycle forever.
        stats["failed"] += 1
        if cursor_value is not None:
            try:
                with get_db() as db:
                    _write_cursor(db, cursor_value)
            except Exception:
                pass
        return

    stats["companies"] += 1
    stats["fetched"] += len(jobs)
    try:
        with get_db() as db:
            for i in range(0, len(jobs), _UPSERT_BATCH):
                stats["stored"] += _upsert_batch(db, jobs[i:i + _UPSERT_BATCH])
            stats["pruned"] += _prune_company(
                db, platform, token, [j["fingerprint"] for j in jobs])
            if cursor_value is not None:
                _write_cursor(db, cursor_value)
    except Exception as e:
        logger.warning(f"ATS sync write failed for {platform}/{token}: {e}")
        stats["failed"] += 1


def sync_companies(entries, stats=None):
    """Fetch + store a batch of registry entries. Returns the stats dict."""
    stats = stats if stats is not None else {
        "companies": 0, "fetched": 0, "stored": 0, "pruned": 0, "failed": 0}
    for entry in entries:
        _, jobs = _fetch_and_normalize(entry)
        _store_company(entry, jobs, stats)
    return stats


def prune_stale(days=STALE_AFTER_DAYS):
    """Remove jobs no sync has seen for `days` — boards that vanished entirely."""
    from backend.database import get_db

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with get_db() as db:
            cur = db.execute("DELETE FROM ats_jobs WHERE last_seen_at < ?",
                             (_timestamp_param(db, cutoff),))
            return getattr(cur, "rowcount", 0) or 0
    except Exception as e:
        logger.warning(f"ATS stale prune failed: {e}")
        return 0


def prune_unregistered():
    """Drop jobs whose company is no longer in the registry.

    Companies leave the registry when the apply-URL audit finds their board
    dead (scratch/verify_ats_registry.py --audit --prune). Their rows would
    otherwise linger until the stale sweep, still offering links we already
    know are broken.
    """
    from backend.database import get_db

    registry = load_registry()
    if not registry:
        return 0
    keys = {(c["platform"], c["token"]) for c in registry}
    removed = 0
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT DISTINCT platform, company_token FROM ats_jobs").fetchall()
            gone = [(r["platform"], r["company_token"]) for r in rows
                    if (r["platform"], r["company_token"]) not in keys]
            for platform, token in gone:
                cur = db.execute(
                    "DELETE FROM ats_jobs WHERE platform = ? AND company_token = ?",
                    (platform, token))
                removed += getattr(cur, "rowcount", 0) or 0
    except Exception as e:
        logger.warning(f"ATS unregistered prune failed: {e}")
    return removed


def run_sync(limit=None, time_budget=None, reset=False):
    """Advance the daily sync from the persisted cursor.

    `limit` caps companies per invocation and `time_budget` caps wall-clock
    seconds, so this fits inside a serverless function's ceiling and simply
    resumes next time. When the cursor wraps past the end of the registry it
    resets to 0 and stale rows are pruned, so a full cycle self-heals.

    Boards are fetched FETCH_CONCURRENCY at a time because the pass is almost
    entirely network-bound; the writes stay serialized, since the Postgres
    connection is shared process-wide.
    """
    from backend.database import get_db

    registry = load_registry()
    if not registry:
        return {"error": "ATS registry is empty", "companies": 0}

    started = time.time()
    with get_db() as db:
        cursor = 0 if reset else _read_cursor(db)
    if cursor >= len(registry):
        cursor = 0

    stats = {"companies": 0, "fetched": 0, "stored": 0, "pruned": 0, "failed": 0}
    index = cursor
    processed = 0
    out_of_budget = False

    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        while index < len(registry) and not out_of_budget:
            if limit is not None and processed >= limit:
                break
            end = min(len(registry), index + FETCH_CONCURRENCY)
            if limit is not None:
                end = min(end, index + (limit - processed))
            chunk = registry[index:end]
            for entry, jobs in pool.map(_fetch_and_normalize, chunk):
                index += 1
                processed += 1
                _store_company(entry, jobs, stats,
                               cursor_value=(0 if index >= len(registry) else index))
            if time_budget is not None and (time.time() - started) >= time_budget:
                out_of_budget = True

    completed_cycle = index >= len(registry)
    stats["cursor"] = 0 if completed_cycle else index
    stats["registry_size"] = len(registry)
    stats["completed_cycle"] = completed_cycle
    stats["seconds"] = round(time.time() - started, 1)
    if completed_cycle:
        stats["pruned_unregistered"] = prune_unregistered()
        stats["pruned_stale"] = prune_stale()
    return stats


# ── Search (against our own data) ──────────────────────────────────────────
# Because this is our copy, every filter below is exact and freely combinable —
# the aggregator APIs each honour a different subset, which is why the UI has to
# grey filters out for them.

SORT_OPTIONS = {"relevance", "date", "salary"}


def _like_terms(text):
    return [t for t in re.split(r"[\s,]+", (text or "").strip().lower()) if t]


def search(what="", where="", country="", page=1, per_page=20, what_exclude="",
           work_mode="", experience_level="", employment_type="",
           salary_min=None, salary_max=None, salary_include_unknown=True,
           max_days_old=None, sort_by="relevance"):
    """Query the synced ATS corpus. Returns {count, results} in the unified schema."""
    from backend.database import get_db

    try:
        page = max(1, int(page))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = max(1, min(50, int(per_page)))
    except (ValueError, TypeError):
        per_page = 20

    where_sql = []
    params = []

    for term in _like_terms(what):
        where_sql.append("search_text LIKE ?")
        params.append(f"%{term}%")
    for term in _like_terms(what_exclude):
        where_sql.append("search_text NOT LIKE ?")
        params.append(f"%{term}%")
    if where:
        where_sql.append("LOWER(location) LIKE ?")
        params.append(f"%{where.strip().lower()}%")
    if country:
        # A remote listing that resolves to NO country ("Distributed", "Home
        # based - Worldwide") is plausibly open from anywhere, so it stays in.
        # A remote listing that DOES name one is that country's job: "Remote -
        # Auckland, New Zealand" is a New Zealand role, not an Indonesian one.
        #
        # The previous rule was `work_mode = 'remote'` with no country test at
        # all, which let EVERY located remote row match EVERY country. Measured
        # against the live corpus that was 3,336 of 3,562 remote rows (1,957 of
        # them US, 118 India) surfacing under all 46 countries -- so picking
        # Indonesia returned largely the same list as picking India.
        where_sql.append("(country_code = ? OR (work_mode = 'remote' "
                         "AND COALESCE(country_code, '') = ''))")
        params.append(country.strip().lower())
    if work_mode in ("remote", "hybrid", "onsite"):
        where_sql.append("work_mode = ?")
        params.append(work_mode)
    if experience_level in EXPERIENCE_LEVELS:
        where_sql.append("experience_level = ?")
        params.append(experience_level)
    if employment_type in EMPLOYMENT_TYPES:
        where_sql.append("employment_type = ?")
        params.append(employment_type)

    smin = _money(salary_min)
    smax = _money(salary_max)
    if smin is not None or smax is not None:
        clauses = []
        if smin is not None:
            clauses.append("salary_max >= ?")
            params.append(smin)
        if smax is not None:
            clauses.append("salary_min <= ?")
            params.append(smax)
        salary_clause = "(" + " AND ".join(clauses) + ")"
        if salary_include_unknown:
            # Most ATS boards publish no salary at all; excluding them by
            # default would hide the majority of real listings.
            salary_clause = f"({salary_clause} OR (salary_min IS NULL AND salary_max IS NULL))"
        where_sql.append(salary_clause)

    try:
        days = int(max_days_old) if max_days_old else 0
    except (ValueError, TypeError):
        days = 0
    recency_cutoff = None
    if days > 0:
        where_sql.append("posted_at >= ?")
        recency_cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        params.append(recency_cutoff)          # converted per driver below

    clause = (" WHERE " + " AND ".join(where_sql)) if where_sql else ""

    # NULLs must be ordered explicitly. Postgres sorts NULLs FIRST under DESC
    # while SQLite sorts them last, so without this the production "newest
    # first" list would open with every undated job.
    if sort_by == "salary":
        order = ("ORDER BY (salary_max IS NULL), salary_max DESC, "
                 "(posted_at IS NULL), posted_at DESC")
    else:
        # We hold no relevance score of our own, so "relevance" and "date" both
        # resolve to newest-first rather than pretending to rank.
        order = "ORDER BY (posted_at IS NULL), posted_at DESC"

    offset = (page - 1) * per_page
    try:
        with get_db() as db:
            if recency_cutoff is not None:
                params = [_timestamp_param(db, v) if v is recency_cutoff else v
                          for v in params]
            total = db.execute(
                f"SELECT COUNT(*) AS n FROM ats_jobs{clause}", params).fetchone()
            count = int(total["n"]) if total else 0
            rows = db.execute(
                f"SELECT * FROM ats_jobs{clause} {order} LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()
    except Exception as e:
        logger.warning(f"ATS search failed: {e}")
        return {"count": 0, "results": []}

    return {"count": count, "results": [to_unified(dict(r)) for r in rows]}


_DOMAIN_BY_TOKEN = None


def _domain_index():
    """(platform, token) -> verified company domain, from the registry.

    Built once per process. The domain is resolved OFFLINE by
    scratch/resolve_company_domains.py and persisted into the registry, because
    no ATS API returns a logo or a domain (verified 2026-08-29 against
    Greenhouse, Ashby, Lever and SmartRecruiters). Doing it here at request
    time would mean a DNS round trip per card.
    """
    global _DOMAIN_BY_TOKEN
    if _DOMAIN_BY_TOKEN is None:
        idx = {}
        try:
            for c in load_registry():
                d = (c.get("domain") or "").strip().lower()
                if d:
                    idx[(c.get("platform"), c.get("token"))] = d
        except Exception:          # a missing/!unreadable registry must not
            idx = {}               # break search; cards fall back to a lettermark
        _DOMAIN_BY_TOKEN = idx
    return _DOMAIN_BY_TOKEN


def company_logo_url(domain):
    """Logo URL for a domain, or '' when we have no domain.

    DuckDuckGo's icon service, chosen by measurement on 2026-08-29:
    Clearbit (the usual suggestion) is DEAD - logo.clearbit.com refuses
    connections since its free API was sunset. DuckDuckGo returned HTTP 200 at
    up to ~15KB, Google's favicon service works too but at ~600-1000B, and
    logo.dev requires an API key (rejected: JobSpike stays card-free).

    The UI falls back to a lettermark on error, so a miss here is cosmetic.
    """
    d = (domain or "").strip().lower()
    return f"https://icons.duckduckgo.com/ip3/{d}.ico" if d else ""


def to_unified(row):
    """Map a stored ats_jobs row onto the shared job schema used by every source."""
    label = PLATFORMS.get(row.get("platform"), {}).get("label", "Employer board")
    posted = row.get("posted_at") or ""
    if not isinstance(posted, str):
        posted = getattr(posted, "isoformat", lambda: str(posted))()
    return {
        "id": str(row.get("id") or ""),
        "title": row.get("title") or "",
        "company": row.get("company") or "",
        "location": row.get("location") or "",
        "salary_min": row.get("salary_min"),
        "salary_max": row.get("salary_max"),
        "salary_is_predicted": False,
        "salary_text": row.get("salary_text") or "",
        "employment_type": row.get("employment_type") or "",
        "posted_at": posted,
        "created": posted,                 # alias (existing UI date formatting)
        "publisher": label,
        "apply_url": row.get("apply_url") or "",
        "redirect_url": row.get("apply_url") or "",   # alias (Apply/tracker flow)
        # The stored URL IS the employer's own application page — that is the
        # whole point of this tier, and it ranks with the other direct sources.
        "apply_is_direct": True,
        "description": (row.get("description") or "")[:1500],
        "source": label,
        # Six of the seven platforms let a candidate apply as a guest.
        # SmartRecruiters makes them create an account (or use Google/LinkedIn
        # SSO) first, so the card says so up front rather than letting the user
        # discover it after the click. Driven off the platform spec, never a
        # string match on the source name.
        "requires_account": bool(
            PLATFORMS.get(row.get("platform"), {}).get("requires_account")),
        "work_mode": row.get("work_mode") or "",
        "experience_level": row.get("experience_level") or "",
        "currency": row.get("salary_currency") or "",
        # Empty string when the company has no resolved domain (3 of 251);
        # the card renders a lettermark in that case rather than a broken image.
        "company_domain": _domain_index().get(
            (row.get("platform"), row.get("company_token")), ""),
        "company_logo": company_logo_url(_domain_index().get(
            (row.get("platform"), row.get("company_token")), "")),
    }


def corpus_stats():
    """Live counts for /api/health and the sync report."""
    from backend.database import get_db

    try:
        with get_db() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM ats_jobs").fetchone()
            per = db.execute(
                "SELECT platform, COUNT(*) AS n FROM ats_jobs GROUP BY platform"
            ).fetchall()
            companies = db.execute(
                "SELECT COUNT(DISTINCT company_token) AS n FROM ats_jobs").fetchone()
        return {
            "jobs": int(total["n"]) if total else 0,
            "companies": int(companies["n"]) if companies else 0,
            "by_platform": {r["platform"]: int(r["n"]) for r in per},
        }
    except Exception as e:
        logger.warning(f"ATS corpus stats failed: {e}")
        return {"jobs": 0, "companies": 0, "by_platform": {}}
