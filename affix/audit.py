"""Append-only audit log: state/audit/{YYYY-MM-DD}.jsonl, one JSON object per event (spec §11).

Event types used across the pipeline:
  intake, llm_call, verification, edit, approval, override, watch_change,
  digest_build, send, request_status, budget_alert, kill_switch, system
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_path(day: str | None = None) -> Path:
    day = day or _now().strftime("%Y-%m-%d")
    path = config.state_dir() / "audit" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log(event: str, actor: str = "system", **fields: Any) -> dict:
    """Append one event. Never rewrites existing lines."""
    entry = {"ts": _now().isoformat(timespec="seconds"), "event": event, "actor": actor, **fields}
    line = json.dumps(entry, ensure_ascii=False, default=str)
    # O_APPEND keeps concurrent writers from clobbering each other.
    fd = os.open(_log_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return entry


def read(day: str | None = None, event: str | None = None) -> list[dict]:
    path = _log_path(day)
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if event is None or r["event"] == event]


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
