"""Tests for the field-merge pipeline in main.build_job / main.merge_fields.

This is the data-quality core: it decides which parser's value lands in every
record. Fixtures are real innerText captures, so this doubles as an end-to-end
test of parse → merge → Job.
"""

from datetime import datetime
from pathlib import Path

import main
from schemas import Job

FIXTURES = Path(__file__).parent / "fixtures"
RUN_DT = datetime(2026, 7, 18, 12, 0)
TS = "2026-07-18-12-00"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text()


def make_card(text: str) -> dict:
    return {"text": text, "search_query": "data scientist", "logo_url": "https://logo.png"}


def full_sections() -> dict:
    return {
        "top_card": fx("top_card.txt"),
        "about_job": "About the job\n\nGreat role.\nBenefits found in job post\nMedical",
        "applicant_insights": fx("applicant_insights.txt"),
        "company_insights": fx("company_insights.txt"),
        "about_company": "AMC Global Media is a media company.",
        "people": fx("hiring_team.txt"),
    }


# --- merge_fields: the one rule -------------------------------------------

def test_merge_first_non_none_wins():
    merged = main.merge_fields({"a": 1, "b": None}, {"a": 2, "b": 3}, {"c": None})
    assert merged == {"a": 1, "b": 3}


def test_merge_keeps_false_values():
    # False is a real value (is_reposted=False), not a gap to fill.
    merged = main.merge_fields({"flag": False}, {"flag": True})
    assert merged["flag"] is False


# --- build_job: priority + end-to-end -------------------------------------

def test_top_card_beats_card_text():
    # Card says Walmart/Bellevue; top card says Amazon/Seattle. Top card wins.
    job = main.build_job("42", make_card(fx("card_salary.txt")), full_sections(), RUN_DT, TS)
    assert job.job_title == "Applied Scientist II, Demand Science"
    assert job.company_name == "Amazon"
    assert job.location == "Seattle, WA"


def test_card_fills_gaps_top_card_leaves():
    # Top card has no workplace_type or salary — the card's values fill in.
    job = main.build_job("42", make_card(fx("card_salary.txt")), full_sections(), RUN_DT, TS)
    assert job.workplace_type == "On-site"
    assert job.salary_min == 132_000
    assert job.salary_max == 264_000


def test_description_salary_never_overrides_card_salary():
    sections = full_sections()
    sections["about_job"] = "About the job\n\nPay: $999K/yr for this role."
    job = main.build_job("42", make_card(fx("card_salary.txt")), sections, RUN_DT, TS)
    assert job.salary_min == 132_000  # card value kept; description only fills gaps


def test_description_salary_used_when_card_has_none():
    sections = full_sections()
    sections["about_job"] = "About the job\n\nPay: $100K/yr - $150K/yr."
    job = main.build_job("42", make_card(fx("card_verified.txt")), sections, RUN_DT, TS)
    assert job.salary_min == 100_000
    assert job.salary_max == 150_000


def test_full_record_end_to_end():
    job = main.build_job("42", make_card(fx("card_salary.txt")), full_sections(), RUN_DT, TS)
    assert job.job_id == "42"
    assert job.job_url == "https://www.linkedin.com/jobs/view/42/"
    assert job.search_query == "data scientist"
    assert job.scrape_dt == TS
    assert job.employment_type == "Full-time"
    assert job.is_reposted is True
    assert job.applicants_clicked == "7"
    assert job.applicants_total == 194
    assert job.company_headcount == 3039
    assert job.median_tenure == 4.7
    assert job.benefits == "Medical"
    assert "Lindsey Woodland" in job.hiring_team
    assert job.about_company == "AMC Global Media is a media company."


def test_missing_sections_degrade_to_none():
    # e.g. Premium lapsed, or a section failed to lazy-load.
    sections = {k: None for k in full_sections()}
    job = main.build_job("42", make_card(fx("card_verified.txt")), sections, RUN_DT, TS)
    assert job.job_title == "Senior Data Product Scientist"  # card still parsed
    assert job.applicants_total is None
    assert job.hiring_team is None
    assert job.job_description is None


def test_all_parser_keys_are_job_fields():
    """build_job silently drops unknown keys — so a typo'd key in any parser
    would silently lose data. Catch that drift here."""
    import parsers

    outputs = [
        parsers.parse_card(fx("card_salary.txt")),
        parsers.parse_top_card(fx("top_card.txt"), now=RUN_DT),
        parsers.parse_about_job("About the job\n\nx\nBenefits found in job post\ny"),
        parsers.parse_applicant_insights(fx("applicant_insights.txt")),
        parsers.parse_company_insights(fx("company_insights.txt")),
        parsers.parse_salary("$100K/yr - $150K/yr") or {},
        parsers.parse_location("Seattle, WA (Remote)"),
        parsers.parse_posted_age("Posted 2 weeks ago") or {},
    ]
    job_fields = set(Job.__dataclass_fields__)
    for out in outputs:
        unknown = set(out) - job_fields
        assert not unknown, f"parser produced keys that Job would drop: {unknown}"
