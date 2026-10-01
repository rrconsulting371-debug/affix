"""Hold-back rules: decide what reaches the digest, and say why.

Every decision carries its reasons (held back) or notes (shown to subscribers), plus the
exact text that triggered it, so Bri can see why the system did what it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import audit, config, db


@dataclass
class Decision:
    grant_id: str
    include: bool
    lifecycle: str
    reasons: list[str] = field(default_factory=list)   # why held back
    notes: list[str] = field(default_factory=list)     # shown with the grant in the digest
    evidence: list[str] = field(default_factory=list)  # text that triggered a rule


def rules() -> dict:
    return config.load_yaml("holdback.yaml")


def _find(text: str, phrases: list[str]) -> str | None:
    for p in phrases:
        m = re.search(r"\b" + re.escape(p.lower()) + r"(s|es)?\b", text)
        if m:
            return p
    return None


def _snippet(text: str, phrase: str, width: int = 60) -> str:
    i = text.lower().find(phrase.lower())
    return text[max(0, i - width): i + len(phrase) + width].strip() if i >= 0 else phrase


def evaluate(row, today: date | None = None, r: dict | None = None) -> Decision:
    r = r or rules()
    life = db.lifecycle(row, today)
    d = Decision(grant_id=row["grant_id"], include=True, lifecycle=life)
    raw = f"{row['title']} {row['description'] or ''}"
    text = raw.lower()

    if not row["listed"]:
        d.reasons.append("No longer listed on the funder's site")
    elif life == "closed":
        d.reasons.append(f"Deadline has passed ({row['close_date']})" if row["close_date"]
                         else "Funder marks it closed")

    for key, rule in (r.get("deal_breakers") or {}).items():
        hit = _find(text, rule.get("match", []))
        if hit and not _find(text, rule.get("unless", [])):
            d.reasons.append(rule["label"])
            d.evidence.append(f'{key}: "...{_snippet(raw, hit)}..."')

    minimum = r.get("minimum_amount")
    if minimum and row["amount_max"] is not None and row["amount_max"] < minimum:
        d.reasons.append(f"Below minimum amount (${minimum:,})")

    notes = r.get("notes") or {}
    inv = notes.get("invitation_only")
    if inv:
        hit = _find(text, inv.get("match", []))
        if hit:
            d.notes.append(inv["note"])
            d.evidence.append(f'invitation_only: "...{_snippet(raw, hit)}..."')
    if notes.get("mid_cycle") and (row["status"] or "").strip().lower() in ("mid-cycle", "mid cycle"):
        d.notes.append(notes["mid_cycle"])
    elif notes.get("undated") and not row["close_date"]:
        d.notes.append(notes["undated"])

    d.include = not d.reasons
    return d


def evaluate_all(conn, today: date | None = None, log: bool = True) -> list[Decision]:
    r = rules()
    decisions = [evaluate(row, today, r) for row in db.grants(conn, include_delisted=True)]
    if log:
        for d in decisions:
            audit.log("holdback", grant_id=d.grant_id, include=d.include, lifecycle=d.lifecycle,
                      reasons=d.reasons, notes=d.notes, evidence=d.evidence,
                      rules_version=r.get("version"))
    return decisions
