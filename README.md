# Affix

A free weekly grant digest for start-up nonprofits (under 10 years old) in North Carolina.
Affix watches the grant sources Bri approved, tracks every change, holds back anything
questionable, and emails a digest that Bri approves before it goes out.

- **Owner:** Bri Mondesir, R&R Consulting
- **Builder:** Richard Brown, Knox St. Studios (LaunchProof, Tier 1)
- **Repo:** https://github.com/rrconsulting371-debug/affix
- **Master source list and rules:** "Grant System Build Data.xlsx" (Bri's SharePoint)

_Last updated: October 8, 2026 (Resend wiring)_

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
python -m affix preview --open       # build this week's digest and open it (never sends)
python -m affix send-test            # email this week's digest to you only, marked [TEST]
python -m affix approve              # approve this week's digest exactly as previewed
python -m affix send                 # send the approved digest to all subscribers (asks you to type SEND)
python -m affix subscribers          # list subscribers (kept in your Resend account)
python -m affix subscribers add someone@example.org --first-name Ana
python -m affix status               # budget, kill switch, settings
python -m affix audit                # today's activity log
```

## How it works
1. **Scrape.** Each source has a scraper in `affix/sources/`. It respects robots.txt and refuses login-gated portals.
2. **Track changes.** Results go into `state/affix.db`. Every new grant, field change and removal is recorded.
   Grants that disappear are marked "no longer listed", never deleted. A scrape that finds nothing changes nothing.
3. **Hold back.** Bri's rules (`config/holdback.yaml`) decide what reaches the digest. Every decision is logged with its reason.
4. **Preview.** `preview` builds the digest into `outputs/previews/<date>/`:
   `preview.html` (what Bri reviews, with the held-back list), `email.html` (what subscribers get),
   `email.txt` (plain text) and `digest.json` (the record approval will use). Look, name and intro
   live in `config/digest.yaml`.
5. **Test, approve, send.** `send-test` emails the week's digest to you only. `approve` records the exact
   file you approved. `send` delivers it to your subscriber list as a Resend Broadcast, and refuses if
   sending is switched off, the digest isn't approved, the file changed after approval, or it was already sent.
   Resend adds the unsubscribe link and never emails anyone who unsubscribed.

## Email setup (Resend)
- Account, domain and API key are in Bri's name at resend.com.
- Sending domain: a subdomain (e.g. `updates.getrrconsulting.com`) verified in Resend, with its DNS records
  added where the domain's DNS is managed. Add a DMARC record after it verifies.
- `.env` needs `RESEND_API_KEY`, `RESEND_SEGMENT_ID` (the "Affix Grant List" segment), `FROM_EMAIL`, `ADMIN_EMAIL`.
- Subscriber sends stay off until `sending_enabled: true` in `config/settings.yaml`. `touch state/KILL` stops all email.
- The logo is a hosted image (`logo_url` in `config/digest.yaml`) because Gmail and Outlook block embedded ones.

## The digest
- **Name:** Your Affix Grant List (header and subject line)
- **Look:** R&R brand board. Navy #1B588F, teal #5FA8A3 (accents only), brown #9B7E63 (notes),
  sand #D9CCC4 (background). Bodoni Moda headings (stand-in for Bauer Bodoni), Nunito body.
  Logo: hosted on Bri's Squarespace site (`logo_url`). Signs off "Let's connect! — Bri M",
  with support@getrrconsulting.com as the contact. Replies to the digest go to support@.
- **Coming soon box:** previews the paid plans, **Affix Aligned** (grants matched to your organization's
  profile) and **Affix Apply** (hands-on application help). No prices; readers reply for early access.
  Edit or switch off under `upcoming_plans` in `config/digest.yaml`.
- **Opens with** Bri's welcome intro. Edit it in `config/digest.yaml` (blank lines = new paragraphs).
- **Sections:** Closing soon (30 days) · Opening soon · New this week · Open now · On the radar (cycle underway).
- **Preview:** `python -m affix preview --open` saves to `outputs/previews/<date>/`:
  `preview.html` (your review copy, with what was held back and why), `email.html` (what subscribers get),
  `email.txt` (plain text), `digest.json` (the record approval will use). Nothing is sent.
- Fonts show in Apple Mail and on iPhone; Gmail and Outlook use close fallbacks.

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
| 3 | Branded digest + preview mode | Done (R&R branding, Bri's intro) |
| 4 | Approval and send via Resend | Done: domain verified, first test email delivered (Oct 8) |
| 4 | Weekly schedule (not on a laptop), docs, handoff | Not started |

## Next up
- [ ] Commit and push Session 3 (see below)
- [ ] Decide: "Your Affix Grant List" or "The Affix Grant List" (the intro says "The")
- [ ] Decide: keep the welcome intro in every issue, or send it once as a welcome email
- [ ] Decide: add a "Resource of the week" section for the templates the intro promises?
- [ ] Upload the updated spreadsheet to SharePoint (20 sources, 8 rules)
- [ ] Add Richard as a GitHub collaborator
- [ ] Session 4 accounts in Bri's name: Resend + sending domain (Anthropic API only if needed)
- [ ] Sample Grants sheet (10–15 good-fit grants)

To commit:
```bash
cd ~/Documents/affix/affix
rm -f .git/index.lock
git add .
git commit -m "Session 3: branded digest and preview mode"
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
`python -m pytest` (35 tests, all offline, using saved copies of the real pages in `tests/fixtures/`)
