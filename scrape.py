import os
print(os.getcwd())
import time
import pandas as pd
import dill as pkl
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

company = "Meta"
keywords = f"{company.lower()} data scientist"
location = "united states"
filter_promotion = True

date = pd.to_datetime("today").strftime("%Y-%m-%d")
n_pages = 20


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



driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()))

email = "yrc602@gmail.com"
password = "y0a6n0g2"
#actions.login(driver, email, password)

### Go to linkedin and login
driver.get("https://www.linkedin.com/login")
time.sleep(3)
driver.find_element(by=By.ID, value="username").send_keys(email)
driver.find_element(by=By.ID, value="password").send_keys(password)
driver.find_element(by=By.ID, value="password").send_keys(Keys.RETURN)

### Go to jobs page
time.sleep(3)
driver.get("https://www.linkedin.com/jobs/")
time.sleep(3)

### Find the keywords/location search bars
# insert keywords
search_bars = driver.find_elements(by=By.CLASS_NAME, value="jobs-search-box__text-input")
search_keywords = search_bars[0]
search_keywords.send_keys(keywords)
search_keywords.send_keys(Keys.RETURN)
time.sleep(3)
# insert location
search_bars_rel = driver.find_elements(by=By.CLASS_NAME, value="jobs-search-box__text-input")
search_location = search_bars_rel[3]
search_location.clear()
search_location.send_keys(location)
search_location.send_keys(Keys.RETURN)
time.sleep(3)

### Get the sidebar jobs list elements
df_jobs = pd.DataFrame(columns=['company', 'position', 'location', 'full_text', 'details'])
#outputs = []
for p in range(1, n_pages):
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

    try:      
        driver.find_element(by=By.XPATH, value=f"//button[@aria-label='Page {p + 1}']").click()
    except:
        print("end of job scraping.")
        break

df_jobs.to_csv(f"data/linkedin-scrape_{'-'.join(keywords.split(' '))}_{date}.csv", index=False)