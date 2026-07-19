import json
from datetime import datetime
from pathlib import Path

import pytest

import parsers

FIXTURES = Path(__file__).parent / "fixtures"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text()


# --- robustness: parsers run unattended at 10pm and must never raise --------

JUNK_INPUTS = ["", "\n\n\n", "$", "·村·", "Posted ago", "50% candidates", "x", "🦄\t%%\n$K/yr"]
ALL_PARSERS = [
    parsers.parse_card,
    parsers.parse_top_card,
    parsers.parse_about_job,
    parsers.parse_applicant_insights,
    parsers.parse_company_insights,
    parsers.parse_hiring_team,
    parsers.parse_salary,
    parsers.parse_location,
    parsers.parse_posted_age,
]


@pytest.mark.parametrize("parser", ALL_PARSERS)
@pytest.mark.parametrize("junk", JUNK_INPUTS)
def test_parsers_never_raise_on_junk(parser, junk):
    parser(junk)  # any return value is fine; raising is not


# --- salary -----------------------------------------------------------------

def test_salary_range_k_per_year():
    s = parsers.parse_salary("$132K/yr - $264K/yr")
    assert s["salary_min"] == 132_000
    assert s["salary_max"] == 264_000
    assert s["salary_period"] == "yr"
    assert s["salary_raw"] == "$132K/yr - $264K/yr"


def test_salary_hourly_single():
    s = parsers.parse_salary("$57.69/hr")
    assert s["salary_min"] == 57.69
    assert s["salary_max"] is None
    assert s["salary_period"] == "hr"


def test_salary_full_numbers():
    s = parsers.parse_salary("base pay range of $120,000/yr - $180,000/yr for this role")
    assert s["salary_min"] == 120_000
    assert s["salary_max"] == 180_000


def test_salary_absent():
    assert parsers.parse_salary("no compensation mentioned") is None


# --- posted age -------------------------------------------------------------

def test_posted_age_reposted_with_estimate():
    now = datetime(2026, 7, 18, 12, 0)
    a = parsers.parse_posted_age("Seattle, WA · Reposted 2 hours ago", now=now)
    assert a["is_reposted"] is True
    assert a["posted_age_text"] == "2 hours ago"
    assert a["posted_at_estimate"] == "2026-07-18T10:00"


def test_posted_age_plain():
    a = parsers.parse_posted_age("Posted 2 weeks ago")
    assert a["is_reposted"] is False
    assert a["posted_age_text"] == "2 weeks ago"


# --- location ---------------------------------------------------------------

def test_location_with_workplace_type():
    loc = parsers.parse_location("California, United States (Remote)")
    assert loc == {"location": "California, United States", "workplace_type": "Remote"}


def test_location_plain():
    assert parsers.parse_location("Seattle, WA")["workplace_type"] is None


# --- card -------------------------------------------------------------------

def test_card_verified_benefits():
    c = parsers.parse_card(fx("card_verified.txt"))
    assert c["job_title"] == "Senior Data Product Scientist"
    assert c["company_name"] == "AMC Global Media"
    assert c["location"] == "New York, NY"
    assert c["verified_job"] is True
    assert c["benefits"] == "401(k)"
    assert c["posted_age_text"] == "2 weeks ago"


def test_card_salary_and_workplace():
    c = parsers.parse_card(fx("card_salary.txt"))
    assert c["company_name"] == "Walmart"
    assert c["workplace_type"] == "On-site"
    assert c["salary_min"] == 132_000
    assert c["salary_max"] == 264_000


# --- top card ---------------------------------------------------------------

def test_top_card():
    t = parsers.parse_top_card(fx("top_card.txt"))
    assert t["company_name"] == "Amazon"
    assert t["job_title"] == "Applied Scientist II, Demand Science"
    assert t["location"] == "Seattle, WA"
    assert t["is_reposted"] is True
    assert t["applicants_clicked"] == "7"
    assert t["is_promoted"] is True
    assert t["apply_type"] == "external"
    assert t["employment_type"] == "Full-time"


# --- premium insights -------------------------------------------------------

def test_applicant_insights():
    a = parsers.parse_applicant_insights(fx("applicant_insights.txt"))
    assert a["applicants_total"] == 194
    assert a["applicants_past_day"] == 3
    assert json.loads(a["seniority_dist"])["Senior level"] == 54
    edu = json.loads(a["education_dist"])
    assert edu["a Master's Degree"] == 37


def test_company_insights():
    c = parsers.parse_company_insights(fx("company_insights.txt"))
    assert c["company_headcount"] == 3039
    assert c["headcount_growth_2y"] == "12%"
    assert c["median_tenure"] == 4.7


# --- hiring team ------------------------------------------------------------

def test_hiring_team():
    team = json.loads(parsers.parse_hiring_team(fx("hiring_team.txt")))
    assert team == [{"name": "Lindsey Woodland, PhD", "title": "Vice President, Data Science & Innovation"}]


def test_hiring_team_absent():
    assert parsers.parse_hiring_team("People you can reach out to\nShow all") is None


# --- about job --------------------------------------------------------------

def test_about_job_benefits_and_description():
    text = "About the job\n\nJob Description\n\nGreat role.\nBenefits found in job post\n401(k)"
    a = parsers.parse_about_job(text)
    assert a["benefits"] == "401(k)"
    assert a["job_description"].startswith("Job Description")
    assert "Benefits found" not in a["job_description"]
