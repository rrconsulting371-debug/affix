"""Source scrapers. Each module exposes `scrape(fetch=...) -> list[Listing]`.
Register new scrapers in SCRAPERS; config/sources.yaml decides which ones run."""
from __future__ import annotations

from . import trianglecf

SCRAPERS = {
    "trianglecf": trianglecf,
}
