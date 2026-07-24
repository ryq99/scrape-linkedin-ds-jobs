"""Entrypoint: python src/main.py {login|scrape|export|stats}"""

import argparse
import logging
import random
import subprocess
import sys
import time
from datetime import datetime, timezone

import browser
import config
import crawler
import export
import parsers
import store
import watchdog
from schemas import Job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("main")

EXIT_OK = 0
EXIT_NO_CARDS = 1        # selector breakage / empty search — investigate
EXIT_NOT_LOGGED_IN = 2   # session expired — run `python src/main.py login`

def notify(message: str) -> None:
    """Best-effort macOS notification (visible next morning after a cron run)."""
    try:
        subprocess.run(["osascript", "-e", f'display notification "{message}" with title "ds_jobs scraper"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass

def cmd_login() -> int:
    """One-time interactive login; the session persists in the profile dir."""
    pw, context, page = browser.launch(headless=False, block_resources=False)
    try:
        page.goto("https://www.linkedin.com/login")
        log.info("Complete the login (incl. any 2FA) in the browser window...")
        page.wait_for_url(lambda url: any(url.startswith(p) for p in browser.LOGGED_IN_PREFIXES), timeout=300_000)
        log.info("Logged in — session saved to %s", config.PROFILE_DIR)
        return EXIT_OK
    except Exception:
        log.error("Login not completed within 5 minutes")
        return EXIT_NOT_LOGGED_IN
    finally:
        browser.close(pw, context)

# --- scrape: Phase A (harvest) → diff → Phase B (details) → export ----------

def harvest_cards(page, args, deadline: watchdog.Deadline) -> dict[str, dict]:
    """Phase A: collect unique cards across all queries, keyed by job_id."""
    cards: dict[str, dict] = {}
    for query in ([args.query] if args.query else config.SCRAPE_QUERIES):
        deadline.check("harvest")
        for card in crawler.harvest_query(page, query, args.window, args.max_pages):
            cards.setdefault(card["job_id"], card)
    return cards

def merge_fields(*sources: dict) -> dict:
    """Merge parser outputs: first non-None value wins (highest priority first)."""
    merged: dict = {}
    for source in sources:
        for key, value in source.items():
            if value is not None and merged.get(key) is None:
                merged[key] = value
    return merged

def build_job(job_id: str, card: dict, sections: dict, run_dt: datetime, ts: str) -> Job:
    """Combine card + detail-page parses into one Job. Sources are listed
    highest-priority first: the structured detail-page header beats card text,
    and description-derived salary/benefits only fill gaps."""
    def parse(name, fn):
        return fn(sections[name]) if sections.get(name) else {}

    fields = merge_fields(
        {"job_id": job_id, "job_url": crawler.job_url(job_id), "search_query": card.get("search_query", ""),
         "scrape_dt": ts, "logo_url": card.get("logo_url")},
        parse("top_card", lambda t: parsers.parse_top_card(t, now=run_dt)),
        parsers.parse_card(card["text"]),
        parse("about_job", parsers.parse_about_job),
        parse("applicant_insights", parsers.parse_applicant_insights),
        parse("company_insights", parsers.parse_company_insights),
        parse("about_company", lambda t: {"about_company": t.strip() or None}),
        parse("people", lambda t: {"hiring_team": parsers.parse_hiring_team(t)}),
    )
    return Job(**{k: v for k, v in fields.items() if k in Job.__dataclass_fields__})

def scrape_details(page, conn, cards: dict[str, dict], new_ids: list[str], run_dt: datetime, ts: str,
                   deadline: watchdog.Deadline) -> None:
    """Phase B: visit each new job's page. Commit per job, so a crash resumes."""
    todo = new_ids[: config.MAX_DETAIL_VISITS]
    for i, job_id in enumerate(todo, 1):
        deadline.check(f"details {i}/{len(todo)}")
        for attempt in (1, 2):
            try:
                sections = crawler.extract_sections(page, job_id)  # hard-capped per visit
                store.upsert_job(conn, build_job(job_id, cards[job_id], sections, run_dt, ts))
                break
            except Exception as e:
                log.warning("Job %s attempt %d failed: %s", job_id, attempt, e)
        if i % 25 == 0:
            log.info("Details: %d/%d", i, len(todo))
        time.sleep(random.uniform(*config.DETAIL_DELAY_RANGE))

def cmd_scrape(args) -> int:
    run_dt = datetime.now(timezone.utc)
    ts = run_dt.strftime("%Y-%m-%d-%H-%M")
    conn = store.connect(config.DB_PATH)
    known = store.seen_ids(conn)
    log.info("Run %s | %d jobs already in store", ts, len(known))

    pw, context, page = browser.launch(headless=not args.headed)
    deadline = watchdog.Deadline(config.MAX_RUN_SECONDS)
    status, cards, new_ids = "failed", {}, []
    try:
        browser.start_trace(context)
        if not browser.ensure_logged_in(page):
            notify("LinkedIn session expired — run: python src/main.py login")
            return EXIT_NOT_LOGGED_IN

        cards = harvest_cards(page, args, deadline)
        if not cards:
            log.error("Zero cards harvested — selectors may have broken")
            notify("Scrape failed: zero job cards found")
            return EXIT_NO_CARDS

        new_ids = [jid for jid in cards if jid not in known]
        store.touch_last_seen(conn, [jid for jid in cards if jid in known], ts)
        log.info("Harvested %d cards: %d new, %d already known", len(cards), len(new_ids), len(cards) - len(new_ids))
        scrape_details(page, conn, cards, new_ids, run_dt, ts, deadline)
        status = "ok"
    except watchdog.RunAborted as e:
        # Wall-clock backstop tripped (wedged/slow browser). Fail fast: the
        # finally below still records the run + trace, and per-job commits mean
        # everything scraped so far is already persisted and gets exported.
        log.error("Run aborted by watchdog: %s", e)
        notify(f"Scrape aborted: {e}")
    finally:
        if status == "ok":  # keep the trace only for failed runs — the cron post-mortem
            browser.discard_trace(context)
        else:
            log.error("Run failed — trace saved to %s", browser.save_trace(context, f"scrape_{ts}"))
        browser.close(pw, context)
        store.record_run(conn, run_dt.isoformat(), datetime.now(timezone.utc).isoformat(),
                         ";".join(config.SCRAPE_QUERIES), len(cards), len(new_ids), status)

    # export + run report
    day = ts[:10]
    df = store.rows_first_seen(conn, day)
    log.info("Field completeness (today's new jobs): %s", store.field_completeness(conn, day))
    if args.no_export:
        log.info("Export skipped (--no-export)")
    else:
        export.export_snapshot(df, ts)
    log.info("Done: %d rows first seen on %s", len(df), day)
    return EXIT_OK

def cmd_export(args) -> int:
    conn = store.connect(config.DB_PATH)
    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = store.rows_first_seen(conn, day)
    if df.empty:
        log.warning("No rows first seen on %s", day)
        return EXIT_NO_CARDS
    export.export_snapshot(df, df["scrape_dt"].iloc[-1])
    return EXIT_OK

def cmd_stats() -> int:
    s = store.stats(store.connect(config.DB_PATH))
    print(f"jobs in store : {s['jobs']}")
    print(f"runs recorded : {s['runs']}")
    if s["last_run"]:
        started, status, seen, new = s["last_run"]
        print(f"last run      : {started} status={status} seen={seen} new={new}")
    return EXIT_OK

def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="ds_jobs", description="LinkedIn job scraper (local, incremental)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Open a browser for one-time interactive login")

    sc = sub.add_parser("scrape", help="Run the daily scrape pipeline")
    sc.add_argument("--window", default=config.TIME_WINDOW, help="f_TPR filter: r86400=24h, r604800=week, ''=all")
    sc.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    sc.add_argument("--query", default=None, help="Single query override")
    sc.add_argument("--headed", action="store_true", help="Visible browser (watch the scrape live)")
    sc.add_argument("--no-export", action="store_true", help="Skip S3/HF export (local dry run)")

    ex = sub.add_parser("export", help="Re-export a day's new jobs to S3 + HF")
    ex.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")

    sub.add_parser("stats", help="Show store statistics")
    return p.parse_args(argv)

def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "login":
        return cmd_login()
    if args.command == "scrape":
        return cmd_scrape(args)
    if args.command == "export":
        return cmd_export(args)
    return cmd_stats()

if __name__ == "__main__":
    sys.exit(main())
