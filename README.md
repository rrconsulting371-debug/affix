# Affix

A free weekly grant digest for start-up nonprofits (under 10 years old) in North Carolina.
Affix watches the grant sources Bri approved, tracks every change, holds back anything
questionable, and emails a digest that Bri approves before it goes out.

- **Owner:** Bri Mondesir, R&R Consulting
- **Builder:** Richard Brown, Knox St. Studios (LaunchProof, Tier 1)
- **Repo:** https://github.com/rrconsulting371-debug/affix
- **Master source list and rules:** "Grant System Build Data.xlsx" (Bri's SharePoint)

_Last updated: October 1, 2026_

## Setup (Mac)
```bash
cd ~/Documents/affix/affix
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in keys; never commit .env
python -m affix status
```
Each new Terminal window: `cd ~/Documents/affix/affix && source .venv/bin/activate`

## Commands
Use `python -m affix <command>`. (The `affix` shortcut isn't working on Bri's Mac yet; see Known issues.)

```bash
python -m affix sources              # sources that have a scraper (config/sources.yaml)
python -m affix scrape               # scrape all enabled sources into the grant database
python -m affix grants               # current grants: open / closing_soon / opening_soon / closed / unknown
python -m affix grants --changes     # history: new grants, deadline moves, amount changes, removals
python -m affix holdback             # what passes the rules, what's held back, and why
python -m affix holdback --evidence  # the exact text that triggered each rule
python -m affix status               # budget, kill switch, settings
python -m affix audit                # today's activity log
```

## How it works
1. **Scrape.** Each source has a scraper in `affix/sources/`. It respects robots.txt and refuses login-gated portals.
2. **Track changes.** Results go into `state/affix.db`. Every new grant, field change and removal is recorded.
   Grants that disappear are marked "no longer listed", never deleted. A scrape that finds nothing changes nothing.
3. **Hold back.** Bri's rules (`config/holdback.yaml`) decide what reaches the digest. Every decision is logged with its reason.
4. **Digest.** Preview, approval and sending come in Sessions 3 and 4.

## Bri's hold-back rules (Oct 1, 2026)
| Rule | What happens |
|---|---|
| Grant amount | No minimum |
| Application fee | Held back |
| Contest, sweepstakes, pitch competition, public vote | Held back |
| Recipients pre-selected by the funder | Held back |
| Deadline passed, or no longer on the funder's site | Held back |
| Invitation-only | Included, with a note |
| "Mid-Cycle" status | Included, with a "cycle underway" note |
| No deadline listed | Included, with a note to check the funder's page |

To change a rule, edit `config/holdback.yaml` and the Filter Criteria tab of the spreadsheet together.

## Sources
| Source | Status |
|---|---|
| Triangle Community Foundation | Scraper live (13 grants on Oct 1; 11 pass the rules) |
| 9 other approved NC sources (NC Community Foundation, FFTC, CFWNC, Winston-Salem Foundation, ZSR, KBR, Golden LEAF, NC Arts Council, City of Raleigh) | Scrapers to build |
| The Black Mill (Substack) | Likely readable via RSS; check it is still posting |
| Mogul Millennial | Email only; needs a forwarding inbox, or leave out of v1 |
| PND RFPs, Candid, ProPublica | Not usable for free (paywalled or past grants only) |

## Build progress
| Session | What | Status |
|---|---|---|
| 1 | Accounts; lock sources, filter criteria, sample grants | GitHub, sources and rules done; Anthropic, Resend, domain, Sample Grants still open |
| 2 | First scraper, grant database with change tracking, hold-back rules | Done (Triangle CF) |
| 2+ | Scrapers for the other approved sources | Next |
| 3 | Branded digest + preview mode | Needs brand color, logo, intro paragraph |
| 4 | One-command approval and send, weekly schedule, docs, handoff | Not started |

## Next up
- [ ] Commit and push tonight's work (see below)
- [ ] Upload the updated spreadsheet to SharePoint (20 sources, 8 rules)
- [ ] Add Richard as a GitHub collaborator
- [ ] Bri: brand color, logo, 2–3 sentence intro, Sample Grants sheet
- [ ] Accounts in Bri's name: Anthropic API, Resend, sending domain

To commit:
```bash
cd ~/Documents/affix/affix
rm -f .git/index.lock
git add .
git commit -m "Triangle CF scraper, grant database, hold-back rules"
git push
```

## Known issues
- **`affix` shortcut fails** ("No module named 'affix'"). Use `python -m affix`. To diagnose:
  `ls -lO .venv/lib/python3.12/site-packages/__editable__*` (look for `hidden`).
- **Rules read the listing page only.** A fee or contest mentioned only on a funder's detail page can slip through.
- **Scrapes run on this Mac** until the weekly job is deployed (Session 4).
- **WealthForge code not yet shared.** `affix/fetch.py` is a stand-in; the Resend module and scheduler wrapper are still to port.

## Governance
- **Audit log:** `state/audit/YYYY-MM-DD.jsonl`, append-only.
- **Budget cap:** `config/settings.yaml → budget.monthly_cap_usd` ($25 default); alerts at 80%, stops at 100%.
- **Kill switch:** `sending.sending_enabled: false` (the default) or `touch state/KILL` stops all email.
- **Ownership:** all code and accounts belong to Bri. Richard has collaborator access during the build.

## Tests
`python -m pytest` (24 tests, all offline, using saved copies of the real pages in `tests/fixtures/`)
