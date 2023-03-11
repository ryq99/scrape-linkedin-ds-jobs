import io
import os
print(os.getcwd())
import time
from tqdm import tqdm
import argparse
import pandas as pd
import dill as pkl
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import yaml
with open("config.yml", "rb") as f:
    config = yaml.safe_load(f) 
import boto3
s3_client = boto3.client(
    's3', 
    aws_access_key_id=config['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=config['AWS_SECRET_ACCESS_KEY'],
    )

date = pd.to_datetime("today").strftime("%Y-%m-%d")
print(f"Scrape Date: {date}")

parser = argparse.ArgumentParser(prog='linkedin_scraper', description='scrape linkedin jobs into a .csv file')
parser.add_argument('-c', '--company', default='')
parser.add_argument('-t', '--title', default='data scientist')
parser.add_argument('-l', '--location', default='united states')
parser.add_argument('-fp', '--filter_promotion', default=True)
parser.add_argument('-p', '--n_pages', default=30)
company, title, location, keywords, filter_promotion, n_pages = (
    parser.parse_args().company, 
    parser.parse_args().title, 
    parser.parse_args().location,
    f"{parser.parse_args().company.lower()} {parser.parse_args().title.lower()}".strip(),
    parser.parse_args().filter_promotion,
    parser.parse_args().n_pages,
    )


def scroll_to(driver, job_list_item):
    """Scroll to the list item in the column"""
    driver.execute_script("arguments[0].scrollIntoView();", job_list_item)
    job_list_item.click()
    time.sleep(5)

def get_position_data(driver, job):
    """Get the position data for a job posting.
    Parameters
    ----------
    job : Selenium webelement
    Returns
    -------
    list of strings : [position, company, location, details]
    """
    full_text = ', '.join(job.text.split('\n'))
    print(full_text)
    if len(job.find_elements(by=By.TAG_NAME, value="time")) > 0:
        post_date = job.find_elements(by=By.TAG_NAME, value="time")[0].text
    else:
        post_date = ''
    details = driver.find_element(by=By.ID, value="job-details").text
    try:
        [position, company, location] = job.text.split('\n')[:3]

        return [position, company, location, post_date, full_text, details]

    except:

        return ['', '', '', post_date, full_text, details]

# Set up Firefox options
firefox_options = webdriver.FirefoxOptions()
firefox_options.binary_location = '/usr/bin/firefox'
firefox_options.add_argument('--headless')

# Create custom service object
firefox_service = FirefoxService(executable_path='/usr/local/bin/geckodriver')

# Create Firefox driver instance
#driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()))
driver = webdriver.Firefox(service=firefox_service, options=firefox_options)
print(f"Driver: {driver}")
#actions.login(driver, email, password)

### Go to linkedin and login
driver.get("https://www.linkedin.com/login")
time.sleep(3)
driver.find_element(by=By.ID, value="username").send_keys(config['email'])
driver.find_element(by=By.ID, value="password").send_keys(config['password'])
driver.find_element(by=By.ID, value="password").send_keys(Keys.RETURN)

### Go to jobs page
time.sleep(3)
driver.get("https://www.linkedin.com/jobs/")
time.sleep(3)

### Find the keywords/location search bars
# insert keywords
print("insert keywords")
search_bars = driver.find_elements(by=By.CLASS_NAME, value="jobs-search-box__text-input")
search_keywords = search_bars[0]
search_keywords.send_keys(keywords)
search_keywords.send_keys(Keys.RETURN)
time.sleep(3)
# insert location
print("insert location")
try:
    search_bars_rel = driver.find_elements(by=By.CLASS_NAME, value="jobs-search-box__text-input")
    search_location = search_bars_rel[3]
    search_location.clear()
    search_location.send_keys(location)
    search_location.send_keys(Keys.RETURN)
except:
    print("not able to insert location...")
time.sleep(3)

### Get the sidebar jobs list elements
df_jobs = pd.DataFrame(columns=['company', 'position', 'location', 'full_text', 'details'])
#outputs = []
for p in tqdm(range(1, n_pages)):
    job_list = driver.find_elements(by=By.CLASS_NAME, value="occludable-update")
    print(f"Page {p}: {len(job_list)} jobs found.")

    for i, j in enumerate(job_list):
        print(f"{i+1}/{len(job_list)}")
        try:
            # to the current job
            scroll_to(driver, j)
            [position, company, location, post_date, full_text, details] = get_position_data(driver, j)
            if (filter_promotion) and (company.lower() not in full_text.lower()):
                print('this promotion job not appended...\n')
            else:   
                df_jobs = pd.concat([
                    df_jobs, 
                    pd.DataFrame(
                        [[company, position, location, post_date, full_text, details]], 
                        columns=['company', 'position', 'location', 'post_date', 'full_text', 'details'],
                        ),
                    ])
                print('\n')
        except:
            pass
    # save data
    with io.StringIO() as csv_buffer:
        df_jobs.to_csv(csv_buffer, index=False)
        s3_client.put_object(
            Bucket='datascience-linkedin-job-scrape', 
            Key=f"data/linkedin-scrape_{'-'.join(keywords.split(' '))}_{date}.csv", 
            Body=csv_buffer.getvalue(),
            )
    
    try:      
        driver.find_element(by=By.XPATH, value=f"//button[@aria-label='Page {p + 1}']").click()
    except:
        print("end of job scraping.")
        break
