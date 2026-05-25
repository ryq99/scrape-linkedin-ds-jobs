---
dataset_info:
  features:
  - name: job_id
    dtype: string
  - name: job_title
    dtype: string
  - name: company_name
    dtype: string
  - name: location
    dtype: string
  - name: salary
    dtype: string
  - name: logo_url
    dtype: string
  - name: job_description
    dtype: string
  - name: scrape_dt
    dtype: string
configs:
- config_name: default
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

## Source Code & Contributions

The dataset was generated using a custom Python + Selenium scraper.
If you'd like to run the scraper under your own LinkedIn account, you can find the source on Github: [🔗 scrape-linkedin-ds-jobs](https://github.com/ryq99/scrape-linkedin-ds-jobs.git).
The repo is actively maintained to keep the scraper working with LinkedIn’s changes.
Contributions are always welcome!