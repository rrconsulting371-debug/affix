"""Monthly API spend tracking and cap (spec §11).

Spend is reconstructed from llm_call entries in this month's audit logs, so the
audit log is the single source of truth. Call `check()` before every LLM call
and `record()` after it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import audit, config


class BudgetExceeded(RuntimeError):
    pass


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = config.settings().get("pricing_per_mtok", {}).get(model)
    if not prices:
        raise ValueError(f"No pricing configured for model {model!r} in settings.yaml")
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def month_spend(month: str | None = None) -> float:
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    audit_dir = config.state_dir() / "audit"
    if not audit_dir.exists():
        return 0.0
    total = 0.0
    for path in sorted(audit_dir.glob(f"{month}-*.jsonl")):
        for row in audit.read(path.stem, event="llm_call"):
            total += float(row.get("cost_usd", 0))
    return round(total, 6)


def _cap() -> float:
    return float(config.settings()["budget"]["monthly_cap_usd"])


def check() -> float:
    """Raise BudgetExceeded at 100% of cap. Returns current spend."""
    spent = month_spend()
    if spent >= _cap():
        audit.log("budget_alert", level="abort", spent_usd=spent, cap_usd=_cap())
        raise BudgetExceeded(f"Monthly API cap reached: ${spent:.2f} of ${_cap():.2f}")
    return spent


def record(model: str, input_tokens: int, output_tokens: int, purpose: str,
           prompt_hash: str | None = None, source_refs: list | None = None) -> float:
    """Log an LLM call with its estimated cost and fire threshold alerts."""
    before = month_spend()
    cost = estimate_cost(model, input_tokens, output_tokens)
    audit.log("llm_call", model=model, purpose=purpose, prompt_hash=prompt_hash,
              source_refs=source_refs or [], input_tokens=input_tokens,
              output_tokens=output_tokens, cost_usd=round(cost, 6))
    after = before + cost
    cap = _cap()
    for t in config.settings()["budget"].get("alert_thresholds", [0.8, 1.0]):
        if before < t * cap <= after:
            audit.log("budget_alert", level=f"{int(t * 100)}%", spent_usd=round(after, 4), cap_usd=cap)
            # TODO(step 6): email Bri via deliver.send_admin_alert once Resend is ported.
    return cost
