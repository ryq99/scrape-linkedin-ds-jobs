import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Iterator, Optional

import boto3
import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("linkedin_scraper")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Job:
    job_id: str
    job_title: str
    company_name: str
    location: str
    salary: str
    logo_url: str
    job_description: str
    scrape_dt: str


# ---------------------------------------------------------------------------
# Helpers: timestamp + credentials
# ---------------------------------------------------------------------------

def utc_scrape_ts() -> str:
    return pd.Timestamp.utcnow().strftime("%Y-%m-%d-%H-%M")


def get_ssm_parameter(ssm_client, name: str) -> str:
    """Fetch a single SecureString parameter from AWS SSM Parameter Store."""
    return ssm_client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


SSM_REGION         = os.environ["SSM_REGION"]
SSM_LINKEDIN_USER  = "linkedin_user"
SSM_LINKEDIN_PWD   = "linkedin_pwd"
SSM_HF_TOKEN       = "hf_hub_access_token"
S3_PREFIX          = os.environ["S3_PREFIX"]
HF_REPO_ID         = os.environ["HF_REPO_ID"]
HF_README_PATH     = "hf_dataset_readme.md"


def get_credentials() -> tuple[str, str, str]:
    """Fetch LinkedIn credentials and HF token from AWS SSM Parameter Store."""
    log.info("Fetching credentials from SSM (region=%s)", SSM_REGION)
    ssm = boto3.client("ssm", region_name=SSM_REGION)
    user     = get_ssm_parameter(ssm, SSM_LINKEDIN_USER)
    pwd      = get_ssm_parameter(ssm, SSM_LINKEDIN_PWD)
    hf_token = get_ssm_parameter(ssm, SSM_HF_TOKEN)
    log.info("Credentials loaded from SSM")
    return user, pwd, hf_token


# ---------------------------------------------------------------------------
# Browser setup
# ---------------------------------------------------------------------------

def create_driver(driver_path: Optional[str], headless: bool, chrome_binary: Optional[str]) -> webdriver.Chrome:
    options = ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    if driver_path:
        return webdriver.Chrome(service=ChromeService(executable_path=driver_path), options=options)
    return webdriver.Chrome(options=options)


# ---------------------------------------------------------------------------
# LinkedIn flow: login + search
# ---------------------------------------------------------------------------

def _logged_in(driver) -> bool:
    try:
        driver.find_element(By.CSS_SELECTOR, "[data-testid='primary-nav']")
        return True
    except NoSuchElementException:
        return False


def login(driver, user: str, pwd: str, wait_seconds: int = 120) -> None:
    """Sign into LinkedIn. Waits up to ``wait_seconds`` for any 2FA challenge to clear."""
    driver.get("https://www.linkedin.com/")
    try:
        driver.find_element(By.LINK_TEXT, "Sign in").click()
    except NoSuchElementException:
        pass  # Already on a sign-in page or already authenticated.

    try:
        alt = driver.find_element(By.XPATH, "//button[contains(., 'Sign in using another account')]")
        alt.click()
        time.sleep(3)
    except NoSuchElementException:
        try:
            driver.find_element(By.ID, "username").send_keys(user)
            pwd_input = driver.find_element(By.ID, "password")
            pwd_input.send_keys(pwd)
            pwd_input.send_keys(Keys.RETURN)
        except NoSuchElementException:
            log.warning("Username/password fields not found; assuming session already active")

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _logged_in(driver):
            log.info("Logged in to LinkedIn")
            return
        time.sleep(2)
    raise TimeoutException(f"Login not completed within {wait_seconds}s")


def search_jobs(driver, prompt: str) -> None:
    driver.get("https://www.linkedin.com/jobs/")
    time.sleep(10)  # Page transitions on /jobs/ are slow; explicit wait sometimes misses the input.

    search_input = driver.find_element(By.XPATH, "//input[@placeholder='Describe the job you want']")
    driver.execute_script("arguments[0].value = '';", search_input)
    search_input.send_keys(prompt)
    search_input.send_keys(Keys.RETURN)
    time.sleep(5)
    log.info("Searched for: %s", prompt)


# ---------------------------------------------------------------------------
# Scraping a single card + the description panel
# ---------------------------------------------------------------------------

def _safe_attr(card, css: str, attr: str, default: str = "Not available") -> str:
    try:
        return card.find_element(By.CSS_SELECTOR, css).get_attribute(attr)
    except NoSuchElementException:
        return default


_META_KEYWORDS = ('posted', ' ago', '·', 'easy apply', 'actively recruiting', 'promoted', 'viewed')


def _js_click(driver, element) -> None:
    """Scroll into view and click via JS — avoids ElementClickInterceptedException."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", element)


def scrape_card(card) -> tuple[str, str, str, str, str]:
    # aria-label is "Dismiss {title} job" — only stable title source since CSS classes are obfuscated
    aria = ""
    try:
        aria = card.find_element(By.CSS_SELECTOR, 'button[aria-label^="Dismiss"]').get_attribute("aria-label") or ""
    except NoSuchElementException:
        pass
    job_title = re.sub(r'^Dismiss\s+|\s+job$', '', aria).strip() or "Not available"

    # Card text layout: title (repeated), company, location, [salary/benefit], [metadata…]
    title_lower = job_title.lower()
    clean = [
        line for line in (l.strip() for l in card.text.split('\n'))
        if line and line.lower() not in (title_lower, title_lower + ' (verified job)', 'verified job')
    ]

    company_name = clean[0] if clean else "Not available"
    location = clean[1] if len(clean) > 1 else "Not available"
    salary = "Not available"
    if len(clean) > 2 and not any(kw in clean[2].lower() for kw in _META_KEYWORDS):
        salary = clean[2]

    return job_title, company_name, location, salary, _safe_attr(card, 'img[data-loaded="true"]', "src")


def scrape_description(driver, card, job_id: str) -> str:
    try:
        _js_click(driver, card)
        time.sleep(2)
        panel = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'[componentkey="JobDetails_AboutTheJob_{job_id}"]')
            )
        )
        return panel.text
    except TimeoutException:
        log.warning("Job-details panel did not load for %s; skipping description", job_id)
        return "Not available"


# ---------------------------------------------------------------------------
# Main scraping loop
# ---------------------------------------------------------------------------

# LinkedIn now uses obfuscated CSS class names; the stable hook is the componentkey attribute.
CARD_SELECTOR = 'div[role="button"][componentkey^="job-card-component-ref-"]'


def iter_jobs(driver, num_pages: int, scrape_dt: str) -> Iterator[Job]:
    """Yield each unique job seen across up to ``num_pages`` pages of results."""
    wait = WebDriverWait(driver, 10)
    seen: set[str] = set()

    for page in range(1, num_pages + 1):
        page_started = time.time()

        while True:
            if time.time() - page_started > 90:
                log.info("Page %d: 90s budget exceeded, moving on", page)
                break

            cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, CARD_SELECTOR)))
            log.info("Page %d: %d cards visible", page, len(cards))

            for card in cards:
                try:
                    job_id = (card.get_attribute("componentkey") or "").replace("job-card-component-ref-", "")
                except StaleElementReferenceException:
                    continue
                if not job_id or job_id in seen:
                    continue
                try:
                    title, company, location, salary, logo = scrape_card(card)
                    description = scrape_description(driver, card, job_id)
                except (NoSuchElementException, StaleElementReferenceException) as e:
                    log.warning("Skipping card %s: %s", job_id, e.__class__.__name__)
                    continue

                seen.add(job_id)
                yield Job(
                    job_id=job_id,
                    job_title=title,
                    company_name=company,
                    location=location,
                    salary=salary,
                    logo_url=logo,
                    job_description=description,
                    scrape_dt=scrape_dt,
                )

            driver.execute_script("arguments[0].scrollIntoView();", cards[-1])
            time.sleep(2)
            new_cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
            if len(new_cards) == len(cards):
                break

        try:
            _js_click(driver, wait.until(EC.presence_of_element_located((By.XPATH, '//span[text()="Next"]'))))
            time.sleep(5)
        except TimeoutException:
            log.info("No more pages after page %d", page)
            break


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def to_dataframe(jobs: list[Job]) -> pd.DataFrame:
    return pd.DataFrame([asdict(j) for j in jobs])


def save_to_s3(df: pd.DataFrame, s3_path: str) -> None:
    import awswrangler as wr  # imported lazily so the module is optional for local dev
    wr.s3.to_csv(df=df, path=s3_path, index=False)
    log.info("Saved %d rows to %s", len(df), s3_path)


def save_to_hf(df: pd.DataFrame, repo_id: str, readme_path: str, hf_token: str) -> None:
    from datasets import Dataset, DatasetDict
    from huggingface_hub import HfApi

    df = df.astype(str)
    split_name = df["scrape_dt"].iloc[0].replace("-", "_")
    DatasetDict({split_name: Dataset.from_pandas(df)}).push_to_hub(repo_id, token=hf_token)
    HfApi().upload_file(
        path_or_fileobj=readme_path,
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
        token=hf_token,
    )
    log.info("Pushed %d rows to HF dataset %s (split=%s)", len(df), repo_id, split_name)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="linkedin_scraper", description="Scrape LinkedIn jobs to S3 and Hugging Face.")
    p.add_argument(
        "-p", "--prompt", default="AI/ML Data Scientist at tech companies", 
        help="Search prompt describing the jobs to scrape"
        )
    p.add_argument(
        "-n", "--num-pages", type=int, default=10, 
        help="Number of result pages to scrape (default: 10)"
        )
    p.add_argument(
        "--headless", dest="headless", action="store_true", default=True,
        help="Run in headless mode (no visible browser; default behavior)"
        )
    p.add_argument(
        "--no-headless", dest="headless", action="store_false", 
        help="Run with visible browser (useful for local debugging)"
        )
    p.add_argument(
        "--driver-path", default=os.getenv("CHROMEDRIVER_PATH"), 
        help="Path to chromedriver binary (optional; uses PATH if omitted)"
        )
    p.add_argument(
        "--chrome-binary", default=os.getenv("CHROME_BINARY"),
        help="Path to Chrome/Chromium binary (optional)"
        )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    scrape_dt = utc_scrape_ts()
    s3_path = f"{S3_PREFIX.rstrip('/')}/linkedin-scrape_{scrape_dt}.csv"

    user, pwd, hf_token = get_credentials()
    driver = create_driver(args.driver_path, args.headless, args.chrome_binary)

    jobs: list[Job] = []
    try:
        login(driver, user, pwd)
        search_jobs(driver, args.prompt)
        for job in iter_jobs(driver, args.num_pages, scrape_dt):
            jobs.append(job)
    finally:
        driver.quit()

    if not jobs:
        log.warning("No jobs scraped; skipping uploads")
        return 1

    df = to_dataframe(jobs)
    log.info("Scraped %d unique jobs", len(df))

    save_to_s3(df, s3_path)
    save_to_hf(df, repo_id=HF_REPO_ID, readme_path=HF_README_PATH, hf_token=hf_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
