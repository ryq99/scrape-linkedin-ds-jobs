"""LinkedIn page access — everything that knows the site's DOM lives here.

Phase A harvests cards from URL-driven search pages (keywords, f_TPR time
filter, and start= pagination are all query params — no typing or clicking).
Phase B extracts raw section text from /jobs/view/{job_id}/. Both anchor on
LinkedIn's stable `componentkey` attributes; parsing happens in parsers.py.
"""

import logging
import urllib.parse

from playwright.sync_api import Page

log = logging.getLogger("crawler")

CARD_SELECTOR = 'div[role="button"][componentkey^="job-card-component-ref-"]'
PAGE_SIZE = 25

SECTION_PREFIXES = {
    "about_job": "JobDetails_AboutTheJob_",
    "about_company": "JobDetails_AboutTheCompany_",
    "applicant_insights": "JobDetails_PremiumApplicantInsights_",
    "company_insights": "JobDetails_PremiumCompanyInsights_",
    "people": "JobDetailsPeopleWhoCanHelpSlot_",
}

# One DOM pass: every card's stable id + innerText + logo src.
_HARVEST_JS = """
() => Array.from(
  document.querySelectorAll('div[role="button"][componentkey^="job-card-component-ref-"]')
).map(card => ({
  job_id: card.getAttribute('componentkey').replace('job-card-component-ref-', ''),
  text: card.innerText,
  logo_url: card.querySelector('img')?.getAttribute('src') ?? null,
}))
"""

# Scroll the results list to the bottom so lazily-rendered cards hydrate.
_SCROLL_LIST_JS = """
() => {
  const card = document.querySelector('div[role="button"][componentkey^="job-card-component-ref-"]');
  for (let p = card; p; p = p.parentElement) {
    if (p.scrollHeight > p.clientHeight + 50) { p.scrollTop = p.scrollHeight; return true; }
  }
  return false;
}
"""

# One DOM pass: all detail sections by componentkey prefix, plus the header
# block above "About the job" (title/company/meta/chips) as top_card.
_COLLECT_SECTIONS_JS = """
(prefixes) => {
  const out = {};
  for (const [name, prefix] of Object.entries(prefixes)) {
    const el = document.querySelector(`[componentkey^="${prefix}"]`);
    out[name] = el ? el.innerText : null;
  }
  const main = document.querySelector('main') || document.body;
  out.top_card = main.innerText.split('About the job')[0].slice(0, 1500);
  return out;
}
"""

def build_search_url(query: str, window: str = "", start: int = 0) -> str:
    params = {"keywords": query}
    if window:
        params["f_TPR"] = window
    if start:
        params["start"] = start
    return "https://www.linkedin.com/jobs/search-results/?" + urllib.parse.urlencode(params)

def harvest_query(page: Page, query: str, window: str, max_pages: int) -> list[dict]:
    """Paginate through a search query; returns deduped card records."""
    seen: dict[str, dict] = {}
    for page_num in range(max_pages):
        page.goto(build_search_url(query, window, page_num * PAGE_SIZE), wait_until="domcontentloaded")
        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
        except Exception:
            break  # no cards rendered = past the last page
        page.evaluate(_SCROLL_LIST_JS)
        page.wait_for_timeout(1_500)
        cards = page.evaluate(_HARVEST_JS)
        log.info("query=%r page=%d cards=%d", query, page_num + 1, len(cards))
        new = [c for c in cards if c["job_id"] not in seen]
        if not new:
            break  # a page of entirely-known cards = pagination wrapped around
        for card in new:
            card["search_query"] = query
            seen[card["job_id"]] = card
    return list(seen.values())

def job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"

def extract_sections(page: Page, job_id: str) -> dict:
    """Raw innerText per section + top_card (None where a section is absent,
    e.g. Premium sections without a subscription)."""
    page.goto(job_url(job_id), wait_until="domcontentloaded")
    page.wait_for_selector(f'[componentkey^="{SECTION_PREFIXES["about_job"]}"]', timeout=15_000)
    for _ in range(4):  # progressive scroll triggers lazy sections (AboutTheCompany, insights)
        page.mouse.wheel(0, 1_500)
        page.wait_for_timeout(400)
    return page.evaluate(_COLLECT_SECTIONS_JS, SECTION_PREFIXES)
