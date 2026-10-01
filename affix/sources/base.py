from __future__ import annotations

from dataclasses import asdict, dataclass, field


class ScrapeError(RuntimeError):
    """The page didn't look like we expected. Nothing is written to the database."""


@dataclass
class Listing:
    source_id: str
    url: str                      # the real source page; also the grant's identity
    title: str
    description: str = ""
    amount_text: str = ""         # exactly as the funder wrote it
    amount_min: int | None = None
    amount_max: int | None = None
    status: str = ""              # funder's own word: Open, Mid-Cycle, Closed, ''
    open_date: str | None = None  # ISO yyyy-mm-dd
    close_date: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def grant_id(self) -> str:
        slug = self.url.rstrip("/").rsplit("/", 1)[-1]
        return f"{self.source_id}:{slug}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["grant_id"] = self.grant_id
        return d
