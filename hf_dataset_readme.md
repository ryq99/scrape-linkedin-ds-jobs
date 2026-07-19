---
configs:
- config_name: default
  data_files:
  - split: train
    path: "data/2026_*.parquet"
- config_name: legacy
  data_files:
  - split: train
    path:
    - "data/2023_*.parquet"
    - "data/2024_*.parquet"
  - split: test
    path: "data/2025_*.parquet"
license: bigscience-openrail-m
---

## Intended Use

This dataset is released under the **BigScience OpenRAIL-M license**.  
It is provided strictly for **research and educational purposes**.  
Any form of **commercial use, redistribution, or use for profit-oriented applications is prohibited**.

## Data & Privacy

The dataset contains **publicly visible job-posting fields only** (title, company, location,
description, salary where posted, etc.). Fields that are login-gated or Premium-gated on
LinkedIn — applicant statistics, company insights, hiring-team contacts — are **not published**
here. Missing values are empty/NULL rather than sentinel strings.

Two configs, split along a schema change:
- **`default`** — data from 2026-07 onward, full public schema (the Hub infers columns from the parquet files)
- **`legacy`** — 2023–2025 data with the original 8-column schema
  (`job_id`, `job_title`, `company_name`, `location`, `salary`, `logo_url`, `job_description`, `scrape_dt`)

## Source Code & Contributions

The dataset was generated using a custom Python + Playwright scraper.
If you'd like to run the scraper under your own LinkedIn account, you can find the source on Github: [🔗 scrape-linkedin-ds-jobs](https://github.com/ryq99/scrape-linkedin-ds-jobs.git).
The repo is actively maintained to keep the scraper working with LinkedIn’s changes.
