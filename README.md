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

## What this is
Tier 1: a free weekly grant digest for North Carolina nonprofits. It watches the sources Bri approved
(master list: "Grant System Build Data.xlsx"), tracks every change, holds back anything questionable,
and emails a digest that Bri approves before it goes out.

## Commands
```bash
affix sources              # enabled sources (config/sources.yaml)
affix scrape               # scrape all enabled sources into state/affix.db
affix grants               # current grants: open / closing_soon / opening_soon / closed / unknown
affix grants --changes     # change history (new grants, deadline moves, amount changes, delistings)
```

## Build progress
| Session | What | Status |
|---|---|---|
| 0 | Skeleton: config, audit log, budget cap, kill switch, fetch_with_retry | done |
| 2 | First scraper (Triangle Community Foundation) + grant database with change tracking | done |
| 2 | Hold-back rules (stale, undated, fee, contest, invite-only, under minimum) | waiting on Filter Criteria tab |
| 2+ | Scrapers for the other approved NC sources | next |
| 3 | Branded digest + preview mode | |
| 4 | Approval command, schedule, docs, handoff | |

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
