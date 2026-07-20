"""Playwright session management: persistent profile, request blocking, tracing."""

import logging

from playwright.sync_api import BrowserContext, Page, sync_playwright

import config

log = logging.getLogger("browser")

# No scrapeable text in these; blocking them cuts page weight dramatically.
# Logo URLs survive: we read <img src> from the DOM, not the image itself.
_BLOCKED_RESOURCES = {"image", "media", "font"}

LOGGED_IN_PREFIXES = (
    "https://www.linkedin.com/feed",
    "https://www.linkedin.com/jobs",
    "https://www.linkedin.com/mynetwork",
    "https://www.linkedin.com/in/",
    "https://www.linkedin.com/messaging",
)

def launch(headless: bool = True, block_resources: bool = True):
    """Open a persistent Chromium context bound to the local profile dir.
    Returns (playwright, context, page); caller must close via close()."""
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(config.PROFILE_DIR),
        headless=headless,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    if block_resources:
        context.route("**/*", _block_heavy_resources)
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page

def _block_heavy_resources(route) -> None:
    if route.request.resource_type in _BLOCKED_RESOURCES:
        route.abort()
    else:
        route.continue_()

def close(pw, context: BrowserContext) -> None:
    context.close()
    pw.stop()

def is_logged_in(page: Page) -> bool:
    return any(page.url.startswith(p) for p in LOGGED_IN_PREFIXES)

def ensure_logged_in(page: Page) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if not is_logged_in(page):
        log.error("Not logged in (url=%s). Run: python src/main.py login", page.url)
        return False
    return True

# --- tracing: recorded every run, kept only for failed ones -----------------

def start_trace(context: BrowserContext) -> None:
    context.tracing.start(screenshots=True, snapshots=True)

def save_trace(context: BrowserContext, name: str):
    config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.TRACE_DIR / f"{name}.zip"
    context.tracing.stop(path=str(path))
    for old in sorted(config.TRACE_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime)[: -config.KEEP_TRACES]:
        old.unlink()
    return path

def discard_trace(context: BrowserContext) -> None:
    context.tracing.stop()
