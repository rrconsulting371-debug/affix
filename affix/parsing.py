"""Small, deterministic parsers for amounts and dates as funders write them.
Never guesses: anything it can't read cleanly comes back as None and the raw text is kept."""
from __future__ import annotations

import re
from datetime import date, datetime

_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?")
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%B %d %Y")


def _to_int(num: str, suffix: str | None) -> int:
    value = float(num.replace(",", ""))
    if suffix:
        value *= 1_000 if suffix.lower() == "k" else 1_000_000
    return int(round(value))


def parse_amount(text: str | None) -> tuple[int | None, int | None]:
    """'$50,000' -> (50000, 50000); '$500 - $2,500' -> (500, 2500);
    'Up to $10,000' -> (None, 10000); 'See RFP details' / '' -> (None, None)."""
    if not text:
        return None, None
    values = [_to_int(n, s) for n, s in _MONEY.findall(text)]
    if not values:
        return None, None
    if len(values) >= 2:
        return min(values), max(values)
    if re.search(r"\b(up to|max(imum)?|not to exceed)\b", text, re.I):
        return None, values[0]
    if re.search(r"\b(at least|minimum|starting at)\b", text, re.I):
        return values[0], None
    return values[0], values[0]


def parse_date(text: str | None) -> str | None:
    """'June 1, 2026' -> '2026-06-01'. Returns None for blank or unreadable text."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text.strip().rstrip("."))
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", cleaned)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def as_date(iso: str | None) -> date | None:
    return date.fromisoformat(iso) if iso else None
