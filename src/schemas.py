"""Job record schema. All optional fields default to None (never "Not available")."""

from dataclasses import dataclass, fields

@dataclass
class Job:
    # identity
    job_id: str
    job_url: str
    search_query: str
    scrape_dt: str

    # core
    job_title: str | None = None
    company_name: str | None = None
    location: str | None = None
    workplace_type: str | None = None      # Remote | Hybrid | On-site
    employment_type: str | None = None     # Full-time | Contract | ...
    job_description: str | None = None
    logo_url: str | None = None
    verified_job: bool = False

    # salary (parsed from card and/or description)
    salary_raw: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None       # yr | hr

    # posting meta
    posted_age_text: str | None = None     # "2 hours ago"
    posted_at_estimate: str | None = None
    is_reposted: bool = False
    is_promoted: bool = False
    apply_type: str | None = None          # easy | external
    applicants_clicked: str | None = None  # "7" or "Over 100"
    benefits: str | None = None

    # company
    about_company: str | None = None
    company_headcount: int | None = None
    headcount_growth_2y: str | None = None
    median_tenure: float | None = None

    # premium applicant insights (JSON strings)
    applicants_total: int | None = None
    applicants_past_day: int | None = None
    seniority_dist: str | None = None
    education_dist: str | None = None

    # people
    hiring_team: str | None = None         # JSON: [{"name", "title"}]

JOB_FIELDS = [f.name for f in fields(Job)]

# Access tiers: LOGIN fields render only for signed-in accounts, PREMIUM need a
# subscription. Both are personalized/gated → local store + private S3 only,
# EXCLUDED from the public Hugging Face dataset (see export.public_view).
LOGIN_FIELDS = ["is_promoted", "apply_type", "applicants_clicked", "hiring_team"]
PREMIUM_FIELDS = [
    "company_headcount", "headcount_growth_2y", "median_tenure",
    "applicants_total", "applicants_past_day", "seniority_dist", "education_dist",
]
PRIVATE_FIELDS = LOGIN_FIELDS + PREMIUM_FIELDS
