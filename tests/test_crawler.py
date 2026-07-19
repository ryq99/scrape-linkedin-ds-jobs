"""URL construction only — DOM interaction is exercised against the live site
by the nightly run (completeness report + exit codes are the tripwires there)."""

import crawler


def test_search_url_encodes_query():
    url = crawler.build_search_url("machine learning engineer, data scientist")
    assert url.startswith("https://www.linkedin.com/jobs/search-results/?")
    assert "keywords=machine+learning+engineer%2C+data+scientist" in url


def test_search_url_window_and_pagination():
    url = crawler.build_search_url("ds", window="r86400", start=25)
    assert "f_TPR=r86400" in url
    assert "start=25" in url


def test_search_url_omits_empty_params():
    url = crawler.build_search_url("ds")
    assert "f_TPR" not in url
    assert "start" not in url


def test_job_url():
    assert crawler.job_url("4434053701") == "https://www.linkedin.com/jobs/view/4434053701/"
