"""affix CLI. Step 1 implements status/audit/budget; later commands are registered
so --help shows the full Phase 1 surface, and they exit cleanly until built."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, audit, budget, config

# command -> (help text, build step that implements it)
PLANNED = {
    "intake": ("Ingest a funder application (PDF, DOCX, or public URL)", 2),
    "review": ("Write a review sheet for a pending grant", 3),
    "edit": ("Open a pending grant's intake JSON in your editor", 3),
    "approve": ("Approve a reviewed grant and generate its DOCX outline", 3),
    "outline": ("Regenerate the DOCX outline for an approved grant", 4),
    "subscriber": ("Add, list, or update subscribers", 5),
    "digest": ("Build this week's digests (dry run)", 5),
    "send": ("Send a built digest: send --date YYYY-MM-DD --confirm", 6),
    "watch": ("Check watched funder pages for changes", 7),
    "request": ("Log and track custom grant requests", 7),
}


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
        print(f"`affix {name}` is not built yet (build step {step}).", file=sys.stderr)
        return 2
    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="affix", description="Affix Phase 1: curation pipeline + weekly digest.")
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

    for name, (help_text, step) in PLANNED.items():
        sp = sub.add_parser(name, help=f"{help_text}  [step {step}]")
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
