"""Triangle Community Foundation — https://trianglecf.org/apply/grants-for-nonprofits/

Page structure (checked Oct 1 2026): each grant is an <li class="fl-loop-item"> with
an <h3><a href="/award/..."> title, a description <p>, then <p>Label: <strong>value</strong></p>
rows for Amount, Status, Open Date, Close Date. Results paginate at /page/N/.
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..parsing import parse_amount, parse_date
from .base import Listing, ScrapeError

SOURCE_ID = "trianglecf"
START_URL = "https://trianglecf.org/apply/grants-for-nonprofits/"
MAX_PAGES = 10
LABELS = {"amount": "amount", "status": "status", "open date": "open_date", "close date": "close_date"}


def parse_page(html: str, base_url: str = START_URL) -> tuple[list[Listing], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for item in soup.select("li.fl-loop-item"):
        link = item.select_one("h3 a[href]")
        if not link:
            continue
        fields = {"description": ""}
        for p in item.find_all("p"):
            text = p.get_text(" ", strip=True)
            label, sep, _ = text.partition(":")
            key = LABELS.get(label.strip().lower()) if sep else None
            if key:
                strong = p.find("strong")
                fields[key] = (strong.get_text(" ", strip=True) if strong else text[len(label) + 1:].strip())
            elif not fields["description"]:
                fields["description"] = text
        amount_text = fields.get("amount", "")
        lo, hi = parse_amount(amount_text)
        listings.append(Listing(
            source_id=SOURCE_ID,
            url=urljoin(base_url, link["href"]),
            title=link.get_text(" ", strip=True),
            description=fields["description"],
            amount_text=amount_text,
            amount_min=lo,
            amount_max=hi,
            status=fields.get("status", ""),
            open_date=parse_date(fields.get("open_date")),
            close_date=parse_date(fields.get("close_date")),
            raw={k: v for k, v in fields.items() if k != "description"},
        ))
    nxt_link = soup.select_one("a.next.page-numbers[href]")
    nxt = urljoin(base_url, nxt_link["href"]) if nxt_link else None
    return listings, nxt


def scrape(fetch: Callable[[str], str]) -> list[Listing]:
    """Walk every results page. `fetch(url) -> html` is injected so tests run offline."""
    url, seen_pages, results = START_URL, set(), {}
    while url and url not in seen_pages and len(seen_pages) < MAX_PAGES:
        seen_pages.add(url)
        listings, url = parse_page(fetch(url), url)
        for l in listings:
            results[l.grant_id] = l
    if not results:
        raise ScrapeError("No grants found on trianglecf.org; the page layout may have changed.")
    return list(results.values())
