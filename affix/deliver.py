"""Email delivery through Resend (https://resend.com/docs).

Three steps, in this order, each one logged to the audit log:

  send-test  the week's email.html to Bri only (Resend Emails API). Subject starts with [TEST].
  approve    Bri signs off on that exact file. Its fingerprint (SHA-256) is recorded.
  send       the approved file goes to the subscriber segment as a Resend Broadcast.
             Refused if sending is switched off, the digest isn't approved, the file changed
             after approval, or this week's digest was already sent.

Subscribers live in Bri's Resend account (a Segment), so unsubscribes are handled by Resend:
the {{unsubscribe_url}} placeholder becomes Resend's own unsubscribe link at send time.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import audit, config

API = "https://api.resend.com"
UNSUB_PLACEHOLDER = "{{unsubscribe_url}}"
RESEND_UNSUB = "{{{RESEND_UNSUBSCRIBE_URL}}}"


class SendBlocked(RuntimeError):
    """A safety check stopped the send. Nothing went out."""


class ResendError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env(name: str) -> str:
    config.load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise SendBlocked(f"{name} is not set. Add it to the .env file in the project folder.")
    return value


def _request(method: str, path: str, body: dict | None = None, params: dict | None = None,
             idempotency_key: str | None = None) -> dict:
    import httpx

    headers = {"Authorization": f"Bearer {_env('RESEND_API_KEY')}", "Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    r = httpx.request(method, API + path, headers=headers, json=body, params=params, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {"message": r.text}
    if r.status_code >= 400:
        msg = data.get("message") or data.get("error") or r.text
        raise ResendError(f"Resend said {r.status_code}: {msg}")
    return data


# ---------- the week's digest on disk ----------

def digest_dir(date: str) -> Path:
    d = config.root() / "outputs" / "previews" / date
    if not (d / "digest.json").exists():
        raise SendBlocked(f"No digest built for {date}. Run: python -m affix preview --date {date}")
    return d


def _manifest(d: Path) -> dict:
    return json.loads((d / "digest.json").read_text(encoding="utf-8"))


def _save(d: Path, m: dict) -> None:
    (d / "digest.json").write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")


def _fingerprint(d: Path) -> str:
    h = hashlib.sha256()
    for name in ("email.html", "email.txt"):
        h.update((d / name).read_bytes())
    return h.hexdigest()


def _bodies(d: Path, unsubscribe: str) -> tuple[str, str]:
    html = (d / "email.html").read_text(encoding="utf-8").replace(UNSUB_PLACEHOLDER, unsubscribe)
    text = (d / "email.txt").read_text(encoding="utf-8").replace(UNSUB_PLACEHOLDER, unsubscribe)
    return html, text


def _reply_to() -> str | None:
    return (config.load_yaml("digest.yaml").get("reply_to") or "").strip() or None


# ---------- commands ----------

def send_test(date: str, to: str | None = None) -> str:
    """Send this week's email to Bri (or one other address) only."""
    if (config.state_dir() / "KILL").exists():
        raise SendBlocked("state/KILL exists: all email is stopped. Delete that file to allow sending.")
    d = digest_dir(date)
    m = _manifest(d)
    to = to or _env("ADMIN_EMAIL")
    html, text = _bodies(d, "#unsubscribe-link-appears-in-real-sends")
    body = {"from": _env("FROM_EMAIL"), "to": [to], "subject": f"[TEST] {m['subject']}", "html": html, "text": text}
    if _reply_to():
        body["reply_to"] = _reply_to()
    res = _request("POST", "/emails", body)
    m.setdefault("tests", []).append({"to": to, "email_id": res.get("id"), "at": _now()})
    _save(d, m)
    audit.log("send_test", date=date, to=to, email_id=res.get("id"))
    return res.get("id", "")


def approve(date: str, by: str = "bri") -> dict:
    d = digest_dir(date)
    m = _manifest(d)
    if m.get("status") in ("sending", "sent"):
        raise SendBlocked(f"The {date} digest was already {m['status']}.")
    m.update(status="approved", approved_by=by, approved_at=_now(), approved_fingerprint=_fingerprint(d))
    _save(d, m)
    audit.log("approval", date=date, actor=by, subject=m["subject"], fingerprint=m["approved_fingerprint"])
    return m


def send(date: str) -> str:
    """Send the approved digest to the subscriber segment. Returns the Resend broadcast id."""
    if config.kill_switch_active():
        raise SendBlocked("Sending is switched off (sending_enabled: false in config/settings.yaml, "
                          "or a state/KILL file). Nothing was sent.")
    d = digest_dir(date)
    m = _manifest(d)
    if m.get("status") == "sent":
        raise SendBlocked(f"The {date} digest was already sent (broadcast {m.get('broadcast_id')}).")
    if m.get("status") == "sending":
        raise SendBlocked(f"A send for {date} started but didn't finish. Check Resend's Broadcasts page "
                          "before trying again, so subscribers don't get it twice.")
    if m.get("status") != "approved":
        raise SendBlocked(f"The {date} digest isn't approved yet. Run: python -m affix approve --date {date}")
    if _fingerprint(d) != m.get("approved_fingerprint"):
        raise SendBlocked("email.html or email.txt changed after approval. Preview it again and re-approve.")
    segment = _env("RESEND_SEGMENT_ID")
    html, text = _bodies(d, RESEND_UNSUB)
    body = {"segment_id": segment, "from": _env("FROM_EMAIL"), "subject": m["subject"], "html": html,
            "text": text, "name": f"Affix digest {date}", "send": True}
    if _reply_to():
        body["reply_to"] = _reply_to()

    m.update(status="sending", send_started_at=_now())
    _save(d, m)
    try:
        res = _request("POST", "/broadcasts", body)
    except Exception as e:
        m.update(status="approved", last_send_error=str(e))   # nothing went out; safe to retry
        _save(d, m)
        audit.log("send_failed", date=date, error=str(e))
        raise
    m.update(status="sent", sent_at=_now(), broadcast_id=res.get("id"))
    _save(d, m)
    audit.log("send", date=date, broadcast_id=res.get("id"), segment_id=segment, subject=m["subject"])
    return res.get("id", "")


def check() -> list[tuple[bool, str]]:
    """Confirm the Resend setup without sending anything or printing the key."""
    results = []
    config.load_env()
    key = os.environ.get("RESEND_API_KEY", "").strip()
    results.append((key.startswith("re_"), "RESEND_API_KEY is set" if key.startswith("re_")
                    else "RESEND_API_KEY is missing or doesn't start with re_"))
    sender = os.environ.get("FROM_EMAIL", "").strip()
    sender_domain = sender.rsplit("@", 1)[-1].rstrip(">\" .").lower() if "@" in sender else ""
    results.append((bool(sender_domain), f"FROM_EMAIL sends from {sender_domain or '(not set)'}"))
    admin = os.environ.get("ADMIN_EMAIL", "").strip()
    ok_admin = "@" in admin and not admin.endswith(".")
    results.append((ok_admin, f"ADMIN_EMAIL (test emails go here): {admin or '(not set)'}"))
    if key.startswith("re_"):
        try:
            domains = _request("GET", "/domains").get("data", [])
            results.append((True, "API key accepted by Resend"))
            match = [d for d in domains if d.get("name", "").lower() == sender_domain]
            if match:
                status = match[0].get("status", "unknown")
                results.append((status == "verified", f"Domain {sender_domain} is {status} in Resend"))
            else:
                names = ", ".join(d.get("name", "") for d in domains) or "none"
                results.append((False, f"{sender_domain or 'FROM_EMAIL domain'} not found in Resend (your domains: {names})"))
        except ResendError as e:
            results.append((False, f"Resend rejected the request: {e}"))
    seg = os.environ.get("RESEND_SEGMENT_ID", "").strip()
    if not seg:
        results.append((False, "RESEND_SEGMENT_ID is blank (fine for test emails; needed before the real send)"))
    elif key.startswith("re_"):
        try:
            segments = _request("GET", "/segments").get("data", [])
        except ResendError as e:
            segments = None
            results.append((False, f"Couldn't list segments: {e}"))
        if segments is not None:
            match = [x for x in segments if x.get("id") == seg]
            if match:
                results.append((True, f"RESEND_SEGMENT_ID matches segment '{match[0].get('name')}'"))
            else:
                results.append((False, f"RESEND_SEGMENT_ID ({seg[:8]}…, {len(seg)} characters) is not one of your segments"))
                for x in segments:
                    results.append((False, f"    your segment '{x.get('name')}' has ID: {x.get('id')}"))
                if not segments:
                    results.append((False, "    you have no segments yet: create 'Affix Grant List' in Resend"))
    return results


# ---------- subscribers (kept in Bri's Resend account) ----------

def add_subscriber(email: str, first_name: str | None = None) -> str:
    body = {"email": email.strip(), "unsubscribed": False, "segments": [{"id": _env("RESEND_SEGMENT_ID")}]}
    if first_name:
        body["first_name"] = first_name.strip()
    res = _request("POST", "/contacts", body)
    audit.log("subscriber_add", email=email.strip())
    return res.get("id", "")


def list_subscribers() -> list[dict]:
    out, after = [], None
    while True:
        params = {"limit": 100, "segment_id": _env("RESEND_SEGMENT_ID")}
        if after:
            params["after"] = after
        res = _request("GET", "/contacts", params=params)
        rows = res.get("data", [])
        out += rows
        if not res.get("has_more") or not rows:
            return out
        after = rows[-1]["id"]
