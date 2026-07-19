import store
from schemas import Job


def make_job(job_id="123", ts="2026-07-18-05-00", **kw):
    return Job(
        job_id=job_id,
        job_url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        search_query="data scientist",
        scrape_dt=ts,
        **kw,
    )


def test_upsert_and_seen(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    assert store.seen_ids(conn) == set()
    store.upsert_job(conn, make_job(job_title="DS"))
    assert store.seen_ids(conn) == {"123"}


def test_upsert_conflict_updates_and_counts(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_job(conn, make_job(job_title="old title"))
    store.upsert_job(conn, make_job(job_title="new title", ts="2026-07-19-05-00"))
    row = conn.execute("SELECT job_title, first_seen, last_seen, times_seen FROM jobs").fetchone()
    assert row == ("new title", "2026-07-18-05-00", "2026-07-19-05-00", 2)


def test_touch_last_seen(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_job(conn, make_job())
    store.touch_last_seen(conn, ["123"], "2026-07-20-05-00")
    row = conn.execute("SELECT last_seen, times_seen FROM jobs").fetchone()
    assert row == ("2026-07-20-05-00", 2)


def test_rows_first_seen_filters_by_day(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_job(conn, make_job("a", ts="2026-07-18-05-00"))
    store.upsert_job(conn, make_job("b", ts="2026-07-19-05-00"))
    df = store.rows_first_seen(conn, "2026-07-18")
    assert list(df["job_id"]) == ["a"]


def test_run_log_and_stats(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.record_run(conn, "s", "f", "q", 10, 3, "ok")
    s = store.stats(conn)
    assert s["runs"] == 1
    assert s["last_run"] == ("s", "ok", 10, 3)


def test_full_record_round_trip(tmp_path):
    """Numeric and JSON fields must survive SQLite → DataFrame intact."""
    conn = store.connect(tmp_path / "t.db")
    store.upsert_job(conn, make_job(
        job_title="DS", salary_min=132000.0, salary_max=264000.0,
        applicants_total=194, median_tenure=4.7,
        seniority_dist='{"Senior level": 54}', is_reposted=True,
    ))
    row = store.rows_first_seen(conn, "2026-07-18").iloc[0]
    assert row["salary_min"] == 132000.0
    assert row["applicants_total"] == 194
    assert row["median_tenure"] == 4.7
    assert row["seniority_dist"] == '{"Senior level": 54}'
    assert row["is_reposted"] == 1  # SQLite stores booleans as 0/1


def test_field_completeness(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_job(conn, make_job("a", job_title="DS"))
    store.upsert_job(conn, make_job("b"))
    comp = store.field_completeness(conn, "2026-07-18")
    assert comp["job_id"] == 1.0
    assert comp["job_title"] == 0.5
