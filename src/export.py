"""Export sinks: S3 CSV snapshot (full schema, private) + HF split (public fields).

Contracts: S3 {S3_PREFIX}/linkedin-scrape_{ts}.csv; HF one split per run
(dashes → underscores), dataset card synced from hf_dataset_readme.md.
"""

import logging

import boto3
import pandas as pd

import config
from schemas import PRIVATE_FIELDS

log = logging.getLogger("export")

def public_view(df: pd.DataFrame) -> pd.DataFrame:
    """Drop login/Premium-gated columns — the public dataset gets public data only."""
    return df.drop(columns=[c for c in PRIVATE_FIELDS if c in df.columns])

def save_to_s3(df: pd.DataFrame, scrape_dt: str) -> None:
    import awswrangler as wr

    path = f"{config.S3_PREFIX.rstrip('/')}/linkedin-scrape_{scrape_dt}.csv"
    wr.s3.to_csv(df=df, path=path, index=False)
    log.info("Saved %d rows to %s", len(df), path)

def save_to_hf(df: pd.DataFrame, scrape_dt: str) -> None:
    import datasets
    from huggingface_hub import HfApi

    datasets.disable_progress_bars()  # keep scrape.log readable
    token = boto3.client("ssm", region_name=config.SSM_REGION).get_parameter(
        Name=config.SSM_HF_TOKEN, WithDecryption=True
    )["Parameter"]["Value"]
    split = scrape_dt.replace("-", "_")
    # str-or-None (not .astype(str), which turns NULLs into "None"/"nan" strings)
    df = public_view(df).map(lambda v: None if pd.isna(v) else str(v))
    datasets.DatasetDict({split: datasets.Dataset.from_pandas(df, preserve_index=False)}).push_to_hub(
        config.HF_REPO_ID, token=token)
    HfApi().upload_file(
        path_or_fileobj=config.HF_README_PATH, path_in_repo="README.md",
        repo_id=config.HF_REPO_ID, repo_type="dataset", token=token,
    )
    log.info("Pushed %d rows to HF %s (split=%s)", len(df), config.HF_REPO_ID, split)

def export_snapshot(df: pd.DataFrame, scrape_dt: str) -> None:
    if df.empty:
        log.info("No new rows to export")
        return
    if not (config.S3_PREFIX and config.HF_REPO_ID):
        raise RuntimeError("S3_PREFIX and HF_REPO_ID must be set for export")
    save_to_s3(df, scrape_dt)
    save_to_hf(df, scrape_dt)
