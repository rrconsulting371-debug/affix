"""Keep Resend's subscriber segment in step with Bri's Airtable list.

Airtable is where Bri manages people. Resend is what sends. Rules, per Airtable row:
  - Resend says the person unsubscribed  -> Airtable Status becomes Unsubscribed. Never re-added.
  - Status Active + Consent checked       -> in the Resend segment (created/added if needed).
  - Status Active without Consent         -> skipped and reported, so Bri can confirm consent.
  - Status Unsubscribed (set by Bri)      -> unsubscribed in Resend too.
  - Status Paused or Bounced              -> taken out of the segment; kept in Airtable.
People in the Resend segment who aren't in Airtable are reported, never deleted.
Every change is written to the audit log. `dry_run=True` shows the plan and changes nothing.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import airtable, audit, config, deliver

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    marked_unsubscribed_in_airtable: list[str] = field(default_factory=list)
    unsubscribed_in_resend: list[str] = field(default_factory=list)
    removed_from_segment: list[str] = field(default_factory=list)
    already_in_sync: int = 0
    needs_consent: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    only_in_resend: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"{len(self.added)} added to Resend", f"{self.already_in_sync} already in sync"]
        for label, items in [("unsubscribed by email link, now marked Unsubscribed in Airtable", self.marked_unsubscribed_in_airtable),
                             ("marked Unsubscribed in Airtable, now unsubscribed in Resend", self.unsubscribed_in_resend),
                             ("Paused/Bounced, taken out of the send list", self.removed_from_segment),
                             ("Active but Consent not checked (not sent to)", self.needs_consent),
                             ("invalid email", self.invalid),
                             ("listed twice in Airtable (first row used)", self.duplicates),
                             ("in Resend but not in Airtable (left alone)", self.only_in_resend),
                             ("errors", self.errors)]:
            if items:
                out.append(f"{len(items)} {label}: {', '.join(items[:10])}{' …' if len(items) > 10 else ''}")
        return out


def settings() -> dict:
    return config.load_yaml("subscribers.yaml")


def check() -> list[tuple[bool, str]]:
    """Confirm the token works and the table has the columns the sync expects."""
    s = settings()
    results = []
    try:
        tables = airtable.tables()
    except airtable.AirtableError as e:
        return [(False, str(e))]
    results.append((True, f"Airtable token works; base has tables: {', '.join(t['name'] for t in tables)}"))
    table = next((t for t in tables if t["name"] == s["table"]), None)
    if not table:
        return results + [(False, f"No table named '{s['table']}'. Rename it in Airtable, or change 'table' in config/subscribers.yaml")]
    have = {f["name"]: f for f in table["fields"]}
    results.append((True, f"Table '{s['table']}' columns: {', '.join(have)}"))
    optional = {"tags"}
    for key, name in s["fields"].items():
        ok = name in have
        if not ok and key in optional:
            continue
        results.append((ok, f"'{name}' column ({key})" + ("" if ok else " is missing")))
    status = have.get(s["fields"]["status"])
    if status and status.get("options", {}).get("choices"):
        choices = {c["name"] for c in status["options"]["choices"]}
        missing = [v for v in s["status_values"].values() if v not in choices]
        results.append((not missing, "Status options OK" if not missing else f"Status is missing options: {', '.join(missing)}"))
    return results


def _require_columns(s: dict) -> None:
    """Stop before touching anything if a column the sync writes or reads is missing."""
    table = next((t for t in airtable.tables() if t["name"] == s["table"]), None)
    if not table:
        raise airtable.AirtableError(f"No table named '{s['table']}' (see config/subscribers.yaml)")
    have = [f["name"] for f in table["fields"]]
    missing = [name for key, name in s["fields"].items() if key != "tags" and name not in have]
    if missing:
        raise airtable.AirtableError(
            "These columns aren't in Airtable: " + ", ".join(f"'{m}'" for m in missing)
            + ". Your columns are: " + ", ".join(f"'{h}'" for h in have)
            + ". Rename them in Airtable, or change the names in config/subscribers.yaml. Nothing was changed.")


def _resend_contacts_all() -> dict[str, dict]:
    out, after = {}, None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        res = deliver._request("GET", "/contacts", params=params)
        rows = res.get("data", [])
        for c in rows:
            out[c["email"].strip().lower()] = c
        if not res.get("has_more") or not rows:
            return out
        after = rows[-1]["id"]


def _resend(method: str, path: str, body: dict | None = None) -> dict:
    time.sleep(0.55)          # Resend allows ~2 requests/second
    return deliver._request(method, path, body)


def sync(dry_run: bool = False) -> SyncReport:
    s = settings()
    f, sv = s["fields"], s["status_values"]
    table = s["table"]
    segment = deliver._env("RESEND_SEGMENT_ID")
    rep = SyncReport()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _require_columns(s)
    rows = airtable.records(table)
    contacts = _resend_contacts_all()
    seen, updates = set(), []

    for rec in rows:
        fields = rec.get("fields", {})
        email = str(fields.get(f["email"], "")).strip().lower()
        if not email:
            continue
        if not EMAIL_RE.match(email):
            rep.invalid.append(email)
            continue
        if email in seen:
            rep.duplicates.append(email)
            continue
        seen.add(email)
        status = fields.get(f["status"]) or ""
        consent = bool(fields.get(f["consent"]))
        has_id = bool(fields.get(f["resend_id"]))
        contact = contacts.get(email)
        patch = {}
        try:
            if contact and contact.get("unsubscribed"):
                if status != sv["unsubscribed"]:
                    patch[f["status"]] = sv["unsubscribed"]
                    rep.marked_unsubscribed_in_airtable.append(email)
                else:
                    rep.already_in_sync += 1
            elif status == sv["unsubscribed"]:
                if contact:
                    if not dry_run:
                        _resend("PATCH", f"/contacts/{contact['id']}", {"unsubscribed": True})
                    rep.unsubscribed_in_resend.append(email)
                else:
                    rep.already_in_sync += 1
            elif status in (sv["paused"], sv["bounced"]):
                if contact and has_id:
                    if not dry_run:
                        _resend("DELETE", f"/contacts/{contact['id']}/segments/{segment}")
                        patch[f["resend_id"]] = ""
                    rep.removed_from_segment.append(email)
                else:
                    rep.already_in_sync += 1
            elif status == sv["active"]:
                if not consent:
                    rep.needs_consent.append(email)
                elif has_id and contact:
                    rep.already_in_sync += 1
                else:
                    if not dry_run:
                        if contact:
                            _resend("POST", f"/contacts/{contact['id']}/segments/{segment}")
                            cid = contact["id"]
                        else:
                            body = {"email": email, "unsubscribed": False, "segments": [{"id": segment}]}
                            if fields.get(f["first_name"]):
                                body["first_name"] = str(fields[f["first_name"]]).strip()
                            if fields.get(f["last_name"]):
                                body["last_name"] = str(fields[f["last_name"]]).strip()
                            cid = _resend("POST", "/contacts", body).get("id", "")
                        patch[f["resend_id"]] = cid
                    rep.added.append(email)
        except deliver.ResendError as e:
            rep.errors.append(f"{email}: {e}")
            continue
        if patch and not dry_run:
            patch[f["last_synced"]] = now
            updates.append({"id": rec["id"], "fields": patch})

    rep.only_in_resend = sorted(e for e, c in contacts.items() if e not in seen and not c.get("unsubscribed"))
    if updates and not dry_run:
        airtable.update(table, updates)
    if not dry_run:
        audit.log("subscriber_sync", added=rep.added, marked_unsubscribed=rep.marked_unsubscribed_in_airtable,
                  unsubscribed_in_resend=rep.unsubscribed_in_resend, removed=rep.removed_from_segment,
                  needs_consent=rep.needs_consent, errors=rep.errors)
    return rep
