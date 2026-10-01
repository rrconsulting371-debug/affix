"""affix CLI: Tier 1 weekly grant digest. Unbuilt commands are listed and exit cleanly."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, audit, budget, config

# Tier 1 commands still to build: command -> (help text, brief session)
PLANNED = {
    "preview": ("Build this week's digest and save it for review (no sending)", 3),
    "approve": ("Approve this week's digest for sending", 4),
    "send": ("Send the approved digest", 4),
}


def cmd_scrape(args: argparse.Namespace) -> int:
    from . import scrape
    ids = [s["source_id"] for s in scrape.enabled_sources()] if args.all or not args.source else [args.source]
    failed = 0
    for sid in ids:
        try:
            c = scrape.run_source(sid)
            print(f"{sid}: {c['found']} found, {c['new']} new, {c['changed']} changed, "
                  f"{c['delisted']} no longer listed")
        except Exception as e:
            failed += 1
            print(f"{sid}: FAILED - {e}", file=sys.stderr)
    return 1 if failed else 0


def cmd_grants(args: argparse.Namespace) -> int:
    from . import db
    conn = db.connect()
    if args.changes:
        for c in db.changes(conn, since=args.since):
            print(f"{c['changed_at'][:10]}  {c['title'][:50]:50}  {c['field']}: {c['old_value']} -> {c['new_value']}")
        return 0
    rows = db.grants(conn, args.source, include_delisted=args.all)
    for r in rows:
        print(f"{db.lifecycle(r):13} {r['title'][:55]:55} {r['amount_text'] or '-':>18}  "
              f"closes {r['close_date'] or '?':10}  {r['url']}")
    print(f"{len(rows)} grants")
    return 0


def cmd_holdback(args: argparse.Namespace) -> int:
    from . import db, holdback
    conn = db.connect()
    rows = {r["grant_id"]: r for r in db.grants(conn, include_delisted=True)}
    decisions = holdback.evaluate_all(conn)
    shown = [d for d in decisions if d.include]
    held = [d for d in decisions if not d.include]
    print(f"INCLUDED ({len(shown)})")
    for d in shown:
        print(f"  {d.lifecycle:13} {rows[d.grant_id]['title'][:60]}")
        for n in d.notes:
            print(f"                note: {n}")
    print(f"\nHELD BACK ({len(held)})")
    for d in held:
        print(f"  {rows[d.grant_id]['title'][:60]}")
        for reason in d.reasons:
            print(f"                reason: {reason}")
    if args.evidence:
        print("\nEVIDENCE")
        for d in decisions:
            for e in d.evidence:
                print(f"  {d.grant_id}: {e}")
    print("\nEvery decision is logged to the audit log (event: holdback).")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    from . import scrape
    for s in scrape.enabled_sources():
        print(f"{s['source_id']:15} {s['name']:40} {s['url']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    s = config.settings()
    spent = budget.month_spend()
    cap = s["budget"]["monthly_cap_usd"]
    print(f"affix {__version__}  (home: {config.root()})")
    print(f"  models:        extraction={s['models']['extraction']}  narrative={s['models']['narrative']}")
    print(f"  budget:        ${spent:.2f} of ${cap:.2f} this month")
    print(f"  sending:       {'HALTED (kill switch)' if config.kill_switch_active() else 'enabled'}"
          f"  dry_run={s['sending']['dry_run']}")
    print(f"  taxonomy:      v{s['taxonomy_version']}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    if args.note:
        entry = audit.log("system", actor=args.actor, note=args.note)
        print(json.dumps(entry))
        return 0
    for row in audit.read(args.day, event=args.event):
        print(json.dumps(row, ensure_ascii=False))
    return 0


def _planned(name: str, step: int):
    def run(args: argparse.Namespace) -> int:
        print(f"`affix {name}` is not built yet (session {step}).", file=sys.stderr)
        return 2
    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="affix", description="Affix: weekly grant digest.")
    p.add_argument("--version", action="version", version=f"affix {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("status", help="Show config, budget, and kill-switch state")
    s.set_defaults(func=cmd_status)

    a = sub.add_parser("audit", help="Read the audit log, or append a manual note")
    a.add_argument("--day", help="YYYY-MM-DD (default: today, UTC)")
    a.add_argument("--event", help="Filter by event type")
    a.add_argument("--note", help="Append a manual note instead of reading")
    a.add_argument("--actor", default="bri")
    a.set_defaults(func=cmd_audit)

    sc = sub.add_parser("scrape", help="Scrape grant sources into the database")
    sc.add_argument("source", nargs="?", help="source_id (default: all enabled sources)")
    sc.add_argument("--all", action="store_true")
    sc.set_defaults(func=cmd_scrape)

    g = sub.add_parser("grants", help="List grants in the database, or their change history")
    g.add_argument("--source")
    g.add_argument("--all", action="store_true", help="Include grants no longer listed")
    g.add_argument("--changes", action="store_true", help="Show change history instead")
    g.add_argument("--since", help="With --changes: YYYY-MM-DD")
    g.set_defaults(func=cmd_grants)

    hb = sub.add_parser("holdback", help="Show which grants pass the hold-back rules, and why")
    hb.add_argument("--evidence", action="store_true", help="Show the text that triggered each rule")
    hb.set_defaults(func=cmd_holdback)

    so = sub.add_parser("sources", help="List enabled grant sources")
    so.set_defaults(func=cmd_sources)

    for name, (help_text, step) in PLANNED.items():
        sp = sub.add_parser(name, help=f"{help_text}  [session {step}]")
        sp.add_argument("rest", nargs=argparse.REMAINDER)
        sp.set_defaults(func=_planned(name, step))
    return p


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
