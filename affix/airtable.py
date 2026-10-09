"""Small Airtable REST client (https://airtable.com/developers/web/api). Needs AIRTABLE_TOKEN and
AIRTABLE_BASE_ID in .env. Airtable allows ~5 requests/second per base and 10 records per update."""
from __future__ import annotations

import os
import time

from . import config

API = "https://api.airtable.com/v0"
_last_call = [0.0]


class AirtableError(RuntimeError):
    pass


def _env(name: str) -> str:
    config.load_env()
    v = os.environ.get(name, "").strip()
    if not v:
        raise AirtableError(f"{name} is not set. Add it to the .env file in the project folder.")
    return v


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    import httpx

    wait = 0.22 - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    r = httpx.request(method, API + path, params=params, json=body, timeout=30,
                      headers={"Authorization": f"Bearer {_env('AIRTABLE_TOKEN')}"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else (err or r.text)
        hint = {401: " (check AIRTABLE_TOKEN)", 403: " (the token may not have access to this base, or lacks a scope)",
                404: " (check AIRTABLE_BASE_ID and the table name in config/subscribers.yaml)"}.get(r.status_code, "")
        raise AirtableError(f"Airtable said {r.status_code}: {msg}{hint}")
    return data


def base_id() -> str:
    return _env("AIRTABLE_BASE_ID")


def tables() -> list[dict]:
    return _request("GET", f"/meta/bases/{base_id()}/tables").get("tables", [])


def records(table: str) -> list[dict]:
    out, offset = [], None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        data = _request("GET", f"/{base_id()}/{table}", params=params)
        out += data.get("records", [])
        offset = data.get("offset")
        if not offset:
            return out


def update(table: str, updates: list[dict]) -> None:
    """updates: [{"id": recXXX, "fields": {...}}]. Sent 10 at a time; select values are typecast."""
    for i in range(0, len(updates), 10):
        _request("PATCH", f"/{base_id()}/{table}", body={"records": updates[i:i + 10], "typecast": True})
