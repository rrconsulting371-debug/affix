# Affix — Phase 1

Curation pipeline + weekly digest for R&R Consulting (owner: Bri Mondesir; builder: Richard Brown, Knox St. Studios).
No web app in Phase 1. See the Phase 1 Technical Spec for full scope.

## Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in keys; never commit .env
affix status
```

## Build progress (spec §13)
| Step | What | Status |
|---|---|---|
| 1 | Skeleton: config, audit, budget, fetch_with_retry | ✅ done — `affix --help` works, audit writes |
| 2 | Ingest + extract + verify (3 real applications) | needs Bri's sample PDF, DOCX, URL |
| 3 | Tag + review + approve | |
| 4 | Outline DOCX (Word + Google Docs) | |
| 5 | Subscribers + matching + digest (dry run) | |
| 6 | Resend delivery + domain auth | |
| 7 | Watcher + requests + scheduling | |
| 8 | Pilot readiness | |

## To port from WealthForge (real code wins)
- `affix/fetch.py` — `fetch_with_retry()` is a placeholder written from the spec
- `affix/deliver.py` — Resend module (step 6)
- `scripts/run_weekly.sh`, `scripts/run_watch.sh` — cron wrapper with lockfile + catch-up (step 7)
- Disk-state caching pattern (`state/`)

## Governance
- Audit log: `state/audit/YYYY-MM-DD.jsonl`, append-only. `affix audit` to read.
- Budget cap: `config/settings.yaml → budget.monthly_cap_usd` (default $25); alerts at 80%, aborts at 100%.
- Kill switch: `sending.sending_enabled: false` or `touch state/KILL`.

## Tests
`python -m pytest` (or `python -m unittest discover tests`)
