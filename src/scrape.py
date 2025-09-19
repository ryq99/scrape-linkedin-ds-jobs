import os
import io
import sys
import uuid
import json
import time
from tqdm import tqdm
import argparse
import pandas as pd
import awswrangler as wr
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import boto3
import s3fs

fs = s3fs.S3FileSystem(anon=False)
s3_client = boto3.client('s3', region_name='us-west-2')
ssm_client = boto3.client('ssm', region_name='us-west-2')
user = ssm_client.get_parameter(Name='linkedin_user')['Parameter']['Value']
pwd = ssm_client.get_parameter(Name='linkedin_pwd')['Parameter']['Value']


def create_driver(
        driver_path='driver/chromedriver'
        #driver_path='/usr/bin/chromedriver'
        ):
    options = ChromeOptions()
    #options.add_argument("--headless")
    #options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    
    # Generate a unique ID for this session
    #unique_id = str(uuid.uuid4())
    #user_data_dir = os.path.join(os.getcwd(), "chrome_user_data", f"profile_{unique_id}")
    #os.makedirs(user_data_dir, exist_ok=True)
    #options.add_argument(f"--user-data-dir={user_data_dir}")
    #print(f"Using user data directory: {user_data_dir}")

    service = ChromeService(executable_path=driver_path)

    driver = webdriver.Chrome(
        service=service, 
        options=options
    )

    return driver

def login(driver, user, pwd):
    driver.get("https://www.linkedin.com/")
    sign_in_link = driver.find_element(By.LINK_TEXT, "Sign in")
    sign_in_link.click()

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
    
    return True

def search_jobs(driver, prompt):
    time.sleep(5)
    driver.get("https://www.linkedin.com/jobs/")
    time.sleep(10)

    search_input = driver.find_element(By.XPATH, "//input[@placeholder='Describe the job you want']")
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

def scrape_jobs(driver, num_pages=10):
    # Switch to iframe before scraping job cards
    wait = WebDriverWait(driver, 10)
    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[data-testid="interop-iframe"]')))
    driver.switch_to.frame(iframe)

    all_jobs_data = []
    ith_page = 1
    scraped_job_ids = set()

    while ith_page <= num_pages:
        start_time = time.time()
        while True:
            if time.time() - start_time > 60: # assuming each page should take less than 60 seconds
                print("Stopping after 60 seconds.")
                break

            ith_job = 0
            job_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.job-card-job-posting-card-wrapper[data-job-id]')))
            num_job_cards = len(job_cards)
            print(f"Found {num_job_cards} jobs in page {ith_page}")

            for card in job_cards:
                job_id = card.get_attribute('data-job-id')

                if job_id not in scraped_job_ids:
                    try:
                        job_title, company_name, location, salary, logo_url = scrape_job_card(card)
                        job_description = scrape_job_description(driver, card)
                        
                        # Store the data
                        all_jobs_data.append({
                            "job_id": job_id,
                            "job_title": job_title,
                            "company_name": company_name,
                            "location": location,
                            "salary": salary,
                            "logo_url": logo_url,
                            "job_description": job_description
                        })
                        
                        # Add the ID to our set to mark it as scraped
                        scraped_job_ids.add(job_id)
                        ith_job += 1

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

    return all_jobs_data

def save_to_s3(all_jobs_data):

    wr.s3.to_csv(
        df=pd.DataFrame(all_jobs_data),
        path=f"s3://datascience-linkedin-job-scrape/data/linkedin-scrape_{pd.to_datetime('today').strftime('%Y-%m-%d-%H-%M')}.csv",
        index=False
    )
    print(f"Saved {len(all_jobs_data)} jobs to S3.")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='linkedin_scraper', description='scrape linkedin jobs into a .csv file')
    parser.add_argument('-c', '--prompt', default='Data Scientist, Applied Scientist, Machine Learning Engineer at tech companies')
    parser.add_argument('-p', '--num_pages', default=10)

    args = parser.parse_args()
    prompt, num_pages = args.prompt, args.num_pages
    driver = create_driver()
    login(driver, user, pwd)
    search_jobs(driver, prompt)
    all_jobs_data = scrape_jobs(driver, num_pages)
    save_to_s3(all_jobs_data)
    driver.quit()

