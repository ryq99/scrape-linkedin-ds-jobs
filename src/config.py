"""Central configuration: environment variables with sensible local defaults."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# --- scraping ---------------------------------------------------------------
_DEFAULT_QUERIES = "machine learning scientist, machine learning engineer, data scientist"
# Multiple queries separated by ";" (a single query may contain commas).
SCRAPE_QUERIES = [q.strip() for q in os.getenv("SCRAPE_QUERIES", _DEFAULT_QUERIES).split(";") if q.strip()]
# LinkedIn f_TPR filter: r86400 = past 24h, r604800 = past week. Empty = no filter.
TIME_WINDOW = os.getenv("TIME_WINDOW", "r86400")
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))
MAX_DETAIL_VISITS = int(os.getenv("MAX_DETAIL_VISITS", "300"))  # per-run cap (rate hygiene)
DETAIL_DELAY_RANGE = (2.0, 5.0)  # jittered seconds between detail-page visits

# --- paths ------------------------------------------------------------------
DB_PATH = Path(os.getenv("DB_PATH", PROJECT_DIR / "data" / "jobs.db"))
PROFILE_DIR = Path(os.getenv("PROFILE_DIR", PROJECT_DIR / "chrome_user_data"))
TRACE_DIR = PROJECT_DIR / "logs" / "traces"
KEEP_TRACES = 5

# --- export sinks (only required by the export step) ------------------------
S3_PREFIX = os.getenv("S3_PREFIX", "")
HF_REPO_ID = os.getenv("HF_REPO_ID", "")
SSM_REGION = os.getenv("SSM_REGION", "us-west-2")
SSM_HF_TOKEN = "hf_hub_access_token"
HF_README_PATH = str(PROJECT_DIR / "hf_dataset_readme.md")
