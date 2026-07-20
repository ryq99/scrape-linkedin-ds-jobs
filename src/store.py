"""SQLite persistence — the scraper's cross-run memory: incremental scraping
(skip seen jobs), first/last-seen tracking, crash resumability."""

import sqlite3
import typing
from dataclasses import asdict, fields
from pathlib import Path

import pandas as pd

from schemas import JOB_FIELDS, Job

_DATA_COLS = [f for f in JOB_FIELDS if f != "job_id"]

def _column_type(py_type) -> str:
    """SQLite type from a dataclass annotation (unwraps Optional). All-TEXT
    columns would coerce numbers to strings and break `salary_min > 150000`."""
    args = typing.get_args(py_type)
    if args:
        py_type = next(a for a in args if a is not type(None))
    return {float: "REAL", int: "INTEGER", bool: "INTEGER"}.get(py_type, "TEXT")

_COL_TYPES = {f.name: _column_type(f.type) for f in fields(Job)}

_CREATE_JOBS = f"""CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    {", ".join(f"{col} {_COL_TYPES[col]}" for col in _DATA_COLS)},
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_RUNS = """CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT, queries TEXT,
    jobs_seen INTEGER, jobs_new INTEGER, status TEXT
)
"""

_UPSERT_JOB = f"""INSERT INTO jobs ({", ".join(JOB_FIELDS)}, first_seen, last_seen, times_seen)
VALUES ({", ".join(f":{f}" for f in JOB_FIELDS)}, :scrape_dt, :scrape_dt, 1)
ON CONFLICT(job_id) DO UPDATE SET
    {", ".join(f"{col} = excluded.{col}" for col in _DATA_COLS)},
    last_seen = excluded.last_seen,
    times_seen = jobs.times_seen + 1
"""

def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_JOBS)
    conn.execute(_CREATE_RUNS)
    conn.commit()
    return conn

def seen_ids(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT job_id FROM jobs")}

def upsert_job(conn: sqlite3.Connection, job: Job) -> None:
    """Insert, or refresh all fields + last_seen/times_seen on conflict."""
    conn.execute(_UPSERT_JOB, asdict(job))
    conn.commit()

def touch_last_seen(conn: sqlite3.Connection, job_ids: list[str], scrape_dt: str) -> None:
    """Mark already-known jobs as seen again (no detail re-fetch)."""
    conn.executemany(
        "UPDATE jobs SET last_seen = ?, times_seen = times_seen + 1 WHERE job_id = ?",
        [(scrape_dt, jid) for jid in job_ids],
    )
    conn.commit()

def record_run(conn, started_at, finished_at, queries, jobs_seen, jobs_new, status) -> None:
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, queries, jobs_seen, jobs_new, status) VALUES (?, ?, ?, ?, ?, ?)",
        (started_at, finished_at, queries, jobs_seen, jobs_new, status),
    )
    conn.commit()

def rows_first_seen(conn: sqlite3.Connection, date_prefix: str) -> pd.DataFrame:
    """All jobs first seen on a given day ('YYYY-MM-DD'), for export."""
    return pd.read_sql_query("SELECT * FROM jobs WHERE first_seen LIKE ?", conn, params=(f"{date_prefix}%",))

def stats(conn: sqlite3.Connection) -> dict:
    return {
        "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        "last_run": conn.execute(
            "SELECT started_at, status, jobs_seen, jobs_new FROM runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone(),
    }

def field_completeness(conn: sqlite3.Connection, date_prefix: str) -> dict[str, float]:
    """Fraction of non-null values per field among jobs first seen that day."""
    df = rows_first_seen(conn, date_prefix)
    return {} if df.empty else {c: round(float(df[c].notna().mean()), 3) for c in df.columns}
