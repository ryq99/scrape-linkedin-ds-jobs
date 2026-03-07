import os
import time
import argparse
import csv
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import boto3
from datasets import Dataset, DatasetDict
from huggingface_hub import HfApi
api = HfApi()

def utc_scrape_ts():
    return pd.to_datetime('now', utc=True).strftime('%Y-%m-%d-%H-%M')

def get_linkedin_credentials(region, user_param, pwd_param):
    env_user = os.getenv("LINKEDIN_USER")
    env_pwd = os.getenv("LINKEDIN_PWD")
    if env_user and env_pwd:
        return env_user, env_pwd

    ssm_client = boto3.client('ssm', region_name=region)
    user = ssm_client.get_parameter(Name=user_param, WithDecryption=True)['Parameter']['Value']
    pwd = ssm_client.get_parameter(Name=pwd_param, WithDecryption=True)['Parameter']['Value']
    return user, pwd

def create_driver(driver_path=None, headless=True, chrome_binary=None):
    options = ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1365,768")
    options.add_argument("--disable-gpu")
    #options.add_argument("--blink-settings=imagesEnabled=false")
    #options.add_experimental_option(
    #    "prefs",
    #    {
    #        "profile.default_content_setting_values.notifications": 2,
    #        "profile.managed_default_content_settings.images": 2,
    #    },
    #)

    # Use Selenium Manager by default so ChromeDriver matches the installed Chrome.
    if driver_path:
        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    return driver

def login(driver, user, pwd, wait_for_2fa_seconds=120):
    driver.get("https://www.linkedin.com/")
    try:
        sign_in_link = driver.find_element(By.LINK_TEXT, "Sign in")
        sign_in_link.click()
    except NoSuchElementException:
        # If already signed in, continue.
        pass

    try:
        alt_signin_btn = driver.find_element(By.XPATH, "//button[contains(., 'Sign in using another account')]")
        alt_signin_btn.click()
        time.sleep(3)
    except:
        try:
            driver.find_element(by=By.ID, value="username").send_keys(user)
            driver.find_element(by=By.ID, value="password").send_keys(pwd)
            driver.find_element(by=By.ID, value="password").send_keys(Keys.RETURN)

        except:
            print("usr pwd not found in page, can't sign in...")

    if not wait_until_logged_in_or_timeout(driver, timeout_seconds=wait_for_2fa_seconds):
        raise TimeoutException("Login not completed within 120s")

    return True

def wait_until_logged_in_or_timeout(driver, timeout_seconds=120):
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            # LinkedIn global search input (good logged-in signal)
            driver.find_element(By.CSS_SELECTOR, "input[data-testid='typeahead-input']")
            return True
        except NoSuchElementException:
            time.sleep(2)
    return False

def search_jobs(driver, prompt):
    time.sleep(5)
    driver.get("https://www.linkedin.com/jobs/")
    time.sleep(10)

    search_input = driver.find_element(By.XPATH, "//input[@placeholder='Describe the job you want']")
    #search_input = driver.find_element(By.XPATH, "//input[@aria-label='Search by title, skill, or company']")
    driver.execute_script("arguments[0].value = '';", search_input)
    search_input.send_keys(prompt)

    search_input.send_keys(Keys.RETURN)
    time.sleep(5)

    return True

def scrape_job_card(card):
    job_title = card.find_element(By.CSS_SELECTOR, 'div.artdeco-entity-lockup__title span[aria-hidden="true"] strong').text.strip()
    company_name = card.find_element(By.CSS_SELECTOR, 'div.artdeco-entity-lockup__subtitle div[dir="ltr"]').text.strip()
    location = card.find_element(By.CSS_SELECTOR, 'div.artdeco-entity-lockup__caption div[dir="ltr"]').text.strip()
    
    try:
        salary_element = card.find_element(By.CSS_SELECTOR, 'div.artdeco-entity-lockup__metadata > div[dir="ltr"]')
        salary = salary_element.text.strip()
    except NoSuchElementException:
        salary = "Not available"
    
    try:
        logo_element = card.find_element(By.CSS_SELECTOR, 'img.ivm-view-attr__img--centered')
        logo_url = logo_element.get_attribute('src')
    except NoSuchElementException:
        logo_url = "Not available"

    return job_title, company_name, location, salary, logo_url

def scrape_job_description(driver, card):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
        time.sleep(1)
        card.click()
        time.sleep(2) 
        # Wait for the job details panel to load and get the description
        wait = WebDriverWait(driver, 10)
        job_details_container = wait.until(EC.presence_of_element_located((By.ID, 'job-details')))
        job_description = job_details_container.text
    except TimeoutException:
        print("Timeout while trying to load job details, skipping this job.")
        job_description = "Not available"

    return job_description

def scrape_jobs(driver, num_pages=10, scrape_dt=None, output_csv_path=None):
    wait = WebDriverWait(driver, 10)
    # Switch to iframe before scraping job cards
    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[data-testid="interop-iframe"]')))
    driver.switch_to.frame(iframe)

    all_jobs_data = []
    total_jobs = 0
    csv_file = None
    csv_writer = None
    csv_fieldnames = [
        "job_id",
        "job_title",
        "company_name",
        "location",
        "salary",
        "logo_url",
        "job_description",
        "scrape_dt",
    ]
    if output_csv_path:
        csv_file = open(output_csv_path, "w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=csv_fieldnames)
        csv_writer.writeheader()

    ith_page = 1
    scraped_job_ids = set()

    try:
        while ith_page <= num_pages:
            start_time = time.time()
            while True:
                if time.time() - start_time > 90: # assuming each page should take less than 90 seconds
                    print("Stopping after 90 seconds.")
                    break

                job_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.job-card-job-posting-card-wrapper[data-job-id]')))
                num_job_cards = len(job_cards)
                print(f"Found {num_job_cards} jobs in page {ith_page}")

                for card in job_cards:
                    job_id = card.get_attribute('data-job-id')

                    if job_id not in scraped_job_ids:
                        try:
                            job_title, company_name, location, salary, logo_url = scrape_job_card(card)
                            job_description = scrape_job_description(driver, card)

                            row = {
                                "job_id": job_id,
                                "job_title": job_title,
                                "company_name": company_name,
                                "location": location,
                                "salary": salary,
                                "logo_url": logo_url,
                                "job_description": job_description,
                                "scrape_dt": scrape_dt,
                            }
                            if csv_writer:
                                csv_writer.writerow(row)
                            else:
                                all_jobs_data.append(row)

                            scraped_job_ids.add(job_id)
                            total_jobs += 1

                        except NoSuchElementException:
                            print(f"Error scraping card with ID {job_id}, '{job_title}' at '{company_name}' in '{location}'.")
                            continue

                # Scroll down to load the next batch of jobs
                driver.execute_script("arguments[0].scrollIntoView();", job_cards[-1])
                time.sleep(2)  # wait for new jobs to load

                # Check if new job cards have been loaded, if not, break the loop
                job_cards_after_scroll = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.job-card-job-posting-card-wrapper[data-job-id]')))
                if len(job_cards_after_scroll) == num_job_cards:
                    print("No new job cards loaded after scrolling, moving to next page.")
                    break

            ith_page += 1
            try:
                next_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[text()="Next"]')))
                next_button.click()
                time.sleep(5)
            except:
                print("No more pages available.")
                break
    finally:
        if csv_file:
            csv_file.close()

    return all_jobs_data, total_jobs

def save_to_s3(all_jobs_data, s3_path):
    import awswrangler as wr

    wr.s3.to_csv(
        df=pd.DataFrame(all_jobs_data),
        path=s3_path,
        index=False
    )
    print(f"Saved {len(all_jobs_data)} jobs to S3: {s3_path}")

    return True

def upload_csv_file_to_s3(local_path, s3_path, region):
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Invalid s3 path: {s3_path}")
    path_no_prefix = s3_path.replace("s3://", "", 1)
    bucket, key = path_no_prefix.split("/", 1)
    s3_client = boto3.client("s3", region_name=region)
    s3_client.upload_file(local_path, bucket, key)
    print(f"Uploaded CSV to S3: {s3_path}")
    return True

def save_to_hf(all_jobs_data, repo_id, readme_path):
    all_jobs_data = pd.DataFrame(all_jobs_data)
    for c in all_jobs_data.columns:
        all_jobs_data[c] = all_jobs_data[c].astype(str)

    dset = Dataset.from_pandas(all_jobs_data)
    dataset_dict = DatasetDict({dset['scrape_dt'][0].replace('-', '_'): dset})
    dataset_dict.push_to_hub(repo_id)
    api.upload_file(
        path_or_fileobj=readme_path,
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset"
    )
    print(f"Saved {len(all_jobs_data)} jobs to Hugging Face: {repo_id}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='linkedin_scraper', description='scrape linkedin jobs into a .csv file')
    parser.add_argument('-p', '--prompt', default='AI/ML Data Scientist at tech companies')
    parser.add_argument('-n', '--num_pages', type=int, default=10)
    parser.add_argument('--driver-path', default=os.getenv("CHROMEDRIVER_PATH", None), help='Optional path to a specific chromedriver binary')
    parser.add_argument('--chrome-binary', default=os.getenv("CHROME_BINARY", None), help='Optional path to Chrome/Chromium binary')
    parser.add_argument('--headless', dest='headless', action='store_true', default=True, help='Run in headless mode (default: true)')
    parser.add_argument('--no-headless', dest='headless', action='store_false', help='Run with browser UI (local debugging)')
    parser.add_argument('--aws-region', default=os.getenv("AWS_REGION", "us-west-2"))
    parser.add_argument('--linkedin-user-param', default=os.getenv("LINKEDIN_USER_PARAM", "linkedin_user"))
    parser.add_argument('--linkedin-pwd-param', default=os.getenv("LINKEDIN_PWD_PARAM", "linkedin_pwd"))
    parser.add_argument('--s3-prefix', default=os.getenv("S3_PREFIX", "s3://datascience-linkedin-job-scrape/data"))
    parser.add_argument('--stream-to-csv', dest='stream_to_csv', action='store_true', default=True, help='Stream scrape rows to local CSV before S3 upload (default: true)')
    parser.add_argument('--no-stream-to-csv', dest='stream_to_csv', action='store_false', help='Keep all rows in memory and write with pandas/awswrangler')
    parser.add_argument('--login-wait-seconds', type=int, default=int(os.getenv("LOGIN_WAIT_SECONDS", "120")))
    parser.add_argument('--save-hf', action='store_true', default=True)
    parser.add_argument('--hf-repo-id', default=os.getenv("HF_REPO_ID", "ryang2/linkedin-job-scrape"))
    parser.add_argument('--hf-readme-path', default=os.getenv("HF_README_PATH", "hf_dataset_readme.md"))

    args = parser.parse_args()
    prompt, num_pages = args.prompt, args.num_pages
    scrape_dt = utc_scrape_ts()
    s3_path = f"{args.s3_prefix.rstrip('/')}/linkedin-scrape_{scrape_dt}.csv"
    user, pwd = get_linkedin_credentials(args.aws_region, args.linkedin_user_param, args.linkedin_pwd_param)

    driver = create_driver(
        driver_path=args.driver_path,
        headless=args.headless,
        chrome_binary=args.chrome_binary,
    )
    all_jobs_data = []
    total_jobs = 0
    local_csv_path = f"/tmp/linkedin-scrape_{scrape_dt}.csv"
    try:
        login(driver, user, pwd, wait_for_2fa_seconds=args.login_wait_seconds)
        search_jobs(driver, prompt)
        all_jobs_data, total_jobs = scrape_jobs(
            driver,
            num_pages,
            scrape_dt=scrape_dt,
            output_csv_path=local_csv_path if args.stream_to_csv and not args.save_hf else None,
        )
    finally:
        driver.quit()

    if args.stream_to_csv and not args.save_hf:
        upload_csv_file_to_s3(local_csv_path, s3_path=s3_path, region=args.aws_region)
        print(f"Saved {total_jobs} jobs to S3 via streamed CSV.")
        try:
            os.remove(local_csv_path)
        except OSError:
            pass
    else:
        save_to_s3(all_jobs_data, s3_path=s3_path)

    if args.save_hf:
        save_to_hf(all_jobs_data, repo_id=args.hf_repo_id, readme_path=args.hf_readme_path)