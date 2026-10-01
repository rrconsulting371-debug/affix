"""Run source scrapers and record results in the grant database."""
from __future__ import annotations

from . import audit, config, db
from .fetch import fetch_with_retry
from .sources import SCRAPERS


def enabled_sources() -> list[dict]:
    return [s for s in config.load_yaml("sources.yaml").get("sources", []) if s.get("enabled", True)]


def fetch_html(url: str) -> str:
    r = fetch_with_retry(url)
    return r.content.decode("utf-8", errors="replace")


def run_source(source_id: str, conn=None, fetch=fetch_html) -> dict:
    if source_id not in SCRAPERS:
        raise KeyError(f"No scraper registered for {source_id!r}")
    conn = conn or db.connect()
    run_id = db.start_run(conn, source_id)
    try:
        listings = SCRAPERS[source_id].scrape(fetch=fetch)
    except Exception as e:
        db.fail_run(conn, run_id, f"{type(e).__name__}: {e}")
        audit.log("scrape_failed", source_id=source_id, run_id=run_id, error=str(e))
        raise
    return db.record_scrape(conn, source_id, listings, run_id=run_id)
