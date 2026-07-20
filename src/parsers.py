"""Pure text→field parsers. No browser dependencies — fully unit-testable.

Inputs are innerText captures of LinkedIn UI regions (see tests/fixtures).
Anything a parser cannot find is None — never a sentinel like "Not available".
"""

import json
import re
from datetime import datetime, timedelta

def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.split("\n") if l.strip()]

# --- salary -----------------------------------------------------------------

_SALARY_RE = re.compile(
    r"\$(?P<num>[\d,]+(?:\.\d+)?)(?P<mag>[KM])?\s*(?:/|per\s*)(?P<period>yr|hr|year|hour|mo|month|wk|week)",
    re.IGNORECASE,
)
_PERIOD_NORM = {"yr": "yr", "year": "yr", "hr": "hr", "hour": "hr", "mo": "mo", "month": "mo", "wk": "wk", "week": "wk"}
_MAGNITUDE = {"K": 1_000, "M": 1_000_000}

def _salary_value(m: re.Match) -> float:
    return float(m["num"].replace(",", "")) * (_MAGNITUDE[m["mag"].upper()] if m["mag"] else 1)

def parse_salary(text: str) -> dict | None:
    """Parse '$132K/yr - $264K/yr' or '$57.69/hr' style strings (first match wins)."""
    matches = list(_SALARY_RE.finditer(text))
    if not matches:
        return None
    low = matches[0]
    # A second amount with the same period is the top of a range.
    high = matches[1] if len(matches) > 1 and matches[1]["period"].lower() == low["period"].lower() else None
    return {
        "salary_min": _salary_value(low),
        "salary_max": _salary_value(high) if high else None,
        "salary_period": _PERIOD_NORM[low["period"].lower()],
        "salary_raw": text[low.start(): (high or low).end()],
    }

# --- posted age -------------------------------------------------------------

_AGE_RE = re.compile(r"(Reposted|Posted)?\s*(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.IGNORECASE)
_AGE_UNIT_HOURS = {"minute": 1 / 60, "hour": 1, "day": 24, "week": 24 * 7, "month": 24 * 30}

def parse_posted_age(text: str, now: datetime | None = None) -> dict | None:
    m = _AGE_RE.search(text)
    if not m:
        return None
    qty, unit = int(m.group(2)), m.group(3).lower()
    return {
        "posted_age_text": f"{qty} {unit}{'s' if qty != 1 else ''} ago",
        "is_reposted": (m.group(1) or "").lower() == "reposted",
        "posted_at_estimate": (now - timedelta(hours=qty * _AGE_UNIT_HOURS[unit])).strftime("%Y-%m-%dT%H:%M")
        if now else None,
    }

# --- location / workplace type ----------------------------------------------

_WORKPLACE_RE = re.compile(r"\s*\((Remote|Hybrid|On-site)\)\s*$", re.IGNORECASE)

def parse_location(raw: str) -> dict:
    m = _WORKPLACE_RE.search(raw)
    if m:
        return {"location": raw[: m.start()].strip(), "workplace_type": m.group(1)}
    return {"location": raw.strip(), "workplace_type": None}

# --- search-result card -----------------------------------------------------

_BENEFIT_WORDS = ("benefit", "401(k)", "medical", "dental", "vision", "tuition")

def parse_card(text: str) -> dict:
    """Card layout: title [(Verified job)] / title repeat / company / location /
    [salary or benefits] / noise (social proof, posted age, view state)."""
    lines = _lines(text)
    out: dict = {"verified_job": "(Verified job)" in text}
    if not lines:
        return out

    title = re.sub(r"\s*\(Verified job\)\s*$", "", lines[0]).strip()
    out["job_title"] = title
    rest = [l for l in lines[1:] if l.lower() != title.lower() and "verified job" not in l.lower()]
    if rest:
        out["company_name"] = rest[0]
    if len(rest) > 1:
        out.update(parse_location(rest[1]))

    for line in rest[2:]:  # only salary and benefits matter; skip the noise
        salary = parse_salary(line) if "$" in line else None
        if salary:
            out.update(salary)
        elif any(word in line.lower() for word in _BENEFIT_WORDS):
            out["benefits"] = re.sub(r"\s*benefits?$", "", line).strip()

    age = parse_posted_age(text)
    if age:
        out["posted_age_text"] = age["posted_age_text"]
    return out

# --- job-view top card ------------------------------------------------------

_EMPLOYMENT_TYPES = ("Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer")
_CLICKED_RE = re.compile(r"(Over\s+[\d,]+|[\d,]+)\s+people\s+clicked\s+apply", re.IGNORECASE)

def parse_top_card(text: str, now: datetime | None = None) -> dict:
    """Detail-page header. The meta line looks like
    'Seattle, WA · Reposted 2 hours ago · 7 people clicked apply',
    preceded by the company and title lines."""
    out: dict = {}
    lines = _lines(text)

    meta = next((l for l in lines if "·" in l and _AGE_RE.search(l)), None)
    if meta:
        out.update(parse_location(meta.split("·")[0]))
        out.update(parse_posted_age(meta, now=now) or {})
        if m := _CLICKED_RE.search(meta):
            out["applicants_clicked"] = m.group(1)
        idx = lines.index(meta)
        if idx >= 2:
            out["company_name"], out["job_title"] = lines[idx - 2], lines[idx - 1]
        elif idx == 1:
            out["job_title"] = lines[0]

    out["is_promoted"] = "Promoted by hirer" in text
    out["apply_type"] = "easy" if "Easy Apply" in text else ("external" if "Apply" in text else None)
    out["employment_type"] = next((t for t in _EMPLOYMENT_TYPES if t in lines), None)
    return out

# --- about-the-job section --------------------------------------------------

_ABOUT_HEADER_RE = re.compile(r"^About the job\s*\n+", re.IGNORECASE)

def parse_about_job(text: str) -> dict:
    """Split AboutTheJob into description, benefits, and salary fallback."""
    out: dict = {}
    body = _ABOUT_HEADER_RE.sub("", text.strip())
    if "Benefits found in job post" in body:
        body, _, tail = body.partition("Benefits found in job post")
        if benefits := _lines(tail):
            out["benefits"] = benefits[0]
    out["job_description"] = body.strip()
    out.update(parse_salary(body) or {})
    return out

# --- premium applicant insights ---------------------------------------------

_SENIORITY_RE = re.compile(r"(\d+)%\s+(.+?)\s+candidates?$", re.IGNORECASE)
_EDUCATION_RE = re.compile(r"(\d+)%\s*\t?\s*have\s+(.+?)(?:\s*\(Similar to you\))?$", re.IGNORECASE)

def parse_applicant_insights(text: str) -> dict:
    """Counts sit on their own line right before a 'total'/'in the past day'
    label; distributions are '54% Senior level candidates'-style lines."""
    out: dict = {}
    lines = _lines(text)
    seniority: dict[str, int] = {}
    education: dict[str, int] = {}

    for i, line in enumerate(lines):
        prev = lines[i - 1].replace(",", "") if i else ""
        if line == "total" and prev.isdigit():
            out["applicants_total"] = int(prev)
        elif line == "in the past day" and prev.isdigit():
            out["applicants_past_day"] = int(prev)
        elif m := _SENIORITY_RE.match(line):
            seniority[m.group(2)] = int(m.group(1))
        elif m := _EDUCATION_RE.match(line):
            education[m.group(2)] = int(m.group(1))

    if seniority:
        out["seniority_dist"] = json.dumps(seniority)
    if education:
        out["education_dist"] = json.dumps(education)
    return out

# --- premium company insights -----------------------------------------------

_TENURE_RE = re.compile(r"Median employee tenure:?\s*([\d.]+)", re.IGNORECASE)

def parse_company_insights(text: str) -> dict:
    """Numbers sit on their own line right before their label line."""
    out: dict = {}
    lines = _lines(text)
    for i, line in enumerate(lines):
        prev = lines[i - 1] if i else ""
        if line == "Total employees" and prev.replace(",", "").isdigit():
            out["company_headcount"] = int(prev.replace(",", ""))
        elif line == "Company-wide" and prev.endswith("%"):
            out["headcount_growth_2y"] = prev
    if m := _TENURE_RE.search(text):
        out["median_tenure"] = float(m.group(1))
    return out

# --- hiring team ------------------------------------------------------------

_TEAM_NOISE = ("message", "show all", "people you can reach out to")

def parse_hiring_team(text: str) -> str | None:
    """Lines after 'Meet the hiring team' alternate name / [• degree] / title."""
    if "Meet the hiring team" not in text:
        return None
    people, name = [], None
    for line in _lines(text.split("Meet the hiring team", 1)[1]):
        if line.lower() in _TEAM_NOISE or line.startswith("•"):
            continue
        if name is None:
            name = line
        else:
            people.append({"name": name, "title": line})
            name = None
    return json.dumps(people) if people else None
