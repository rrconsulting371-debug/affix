"""Build the weekly digest from the grant database and the hold-back decisions.

Sections, in order (each grant appears once):
  Closing soon   deadline within `closing_soon_days`
  Opening soon   open date still ahead
  New this week  first seen within `new_within_days`
  Open now       everything else that passed the rules, except...
  On the radar   funder says the cycle is underway (Mid-Cycle)

`affix preview` writes the email (HTML + plain text) plus a reviewer copy that shows
what was held back and why. Nothing is sent from here.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import audit, config, db, holdback

SECTIONS = [
    ("closing_soon", "Closing soon", "Deadlines in the next {closing_soon_days} days."),
    ("opening_soon", "Opening soon", "Not open yet. Get a head start."),
    ("new", "New this week", "Added since last week's list."),
    ("open", "Open now", "Accepting applications or on a rolling basis."),
    ("radar", "On the radar", "Cycle underway. Watch for the next opening."),
]


@dataclass
class Item:
    grant_id: str
    title: str
    url: str
    funder: str
    amount: str
    deadline: str          # human words
    description: str
    notes: list[str] = field(default_factory=list)
    section: str = "open"


@dataclass
class Digest:
    date: str
    subject: str
    name: str
    intro: str
    sections: dict[str, list[Item]]
    held: list[dict]
    counts: dict


def settings() -> dict:
    return config.load_yaml("digest.yaml")


def _funders() -> dict:
    return {s["source_id"]: s["name"] for s in config.load_yaml("sources.yaml").get("sources", [])}


def _day(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _deadline_words(row, today: date) -> str:
    if row["close_date"]:
        close = date.fromisoformat(row["close_date"])
        left = (close - today).days
        when = "today" if left == 0 else "tomorrow" if left == 1 else f"{left} days left"
        if row["open_date"] and date.fromisoformat(row["open_date"]) > today:
            return f"Opens {_day(date.fromisoformat(row['open_date']))} · Closes {_day(close)}"
        return f"Closes {_day(close)} ({when})"
    if row["open_date"] and date.fromisoformat(row["open_date"]) > today:
        return f"Opens {_day(date.fromisoformat(row['open_date']))}"
    return "No deadline listed"


def _shorten(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


def build(conn=None, today: date | None = None, log: bool = True) -> Digest:
    today = today or date.today()
    s = settings()
    conn = conn or db.connect()
    funders = _funders()
    rows = {r["grant_id"]: r for r in db.grants(conn, include_delisted=True)}
    decisions = holdback.evaluate_all(conn, today=today, log=log)
    new_since = (datetime.now(timezone.utc) - timedelta(days=s.get("new_within_days", 7))).isoformat()
    soon = s.get("closing_soon_days", 30)

    sections = {key: [] for key, _, _ in SECTIONS}
    held = []
    for d in decisions:
        r = rows[d.grant_id]
        if not d.include:
            held.append({"grant_id": d.grant_id, "title": r["title"], "url": r["url"], "reasons": d.reasons,
                         "evidence": d.evidence})
            continue
        life = db.lifecycle(r, today, closing_days=soon)
        status = (r["status"] or "").strip().lower()
        if life == "closing_soon":
            key = "closing_soon"
        elif life == "opening_soon":
            key = "opening_soon"
        elif status in ("mid-cycle", "mid cycle"):
            key = "radar"
        elif r["first_seen"] >= new_since:
            key = "new"
        else:
            key = "open"
        sections[key].append(Item(
            grant_id=d.grant_id, title=r["title"], url=r["url"], funder=funders.get(r["source_id"], r["source_id"]),
            amount=r["amount_text"] or "Amount not listed", deadline=_deadline_words(r, today),
            description=_shorten(r["description"], s.get("description_chars", 220)),
            notes=[n for n in d.notes if "No deadline listed" not in n and "Cycle underway" not in n],
            section=key))
    for key in sections:
        sections[key].sort(key=lambda i: (rows[i.grant_id]["close_date"] or "9999", i.title))

    counts = {k: len(v) for k, v in sections.items()}
    counts["included"] = sum(counts.values())
    counts["held"] = len(held)
    bits = []
    if counts["closing_soon"]:
        bits.append(f"{counts['closing_soon']} closing soon")
    if counts["new"]:
        bits.append(f"{counts['new']} new")
    if counts["opening_soon"]:
        bits.append(f"{counts['opening_soon']} opening soon")
    subject = f"{s['name']} · {today.strftime('%b')} {today.day}" + (f": {', '.join(bits)}" if bits else "")

    dg = Digest(date=today.isoformat(), subject=subject, name=s["name"], intro=s.get("intro", "").strip(),
                sections=sections, held=held, counts=counts)
    if log:
        audit.log("digest_build", date=dg.date, subject=subject, counts=counts,
                  grant_ids=[i.grant_id for v in sections.values() for i in v])
    return dg


# ---------- rendering ----------

def _text_on(hex_color: str) -> str:
    """Black or white text, whichever reads better on the brand color (WCAG luminance)."""
    h = hex_color.lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#ffffff"
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#111111" if (lum + 0.05) / 0.05 > 1.05 / (lum + 0.05) else "#ffffff"


def _logo_src(s: dict, for_preview: bool) -> str | None:
    if not for_preview and s.get("logo_url"):
        return s["logo_url"]
    f = s.get("logo_file")
    if f:
        p = config.root() / f
        if p.exists():
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
    return s.get("logo_url") or None


def _darken(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(int(c * factor) for c in (r, g, b))


def _tint(hex_color: str, amount: float) -> str:
    """Mix with white: amount 0 = the color, 1 = white."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(int(c + (255 - c) * amount) for c in (r, g, b))


def render_html(dg: Digest, review: bool = False) -> str:
    s = settings()
    e = html.escape
    navy = s.get("brand_color", "#1B588F")
    c = s.get("colors") or {}
    accent = c.get("accent", navy)
    warm_text = _darken(c.get("warm", "#7a5f46"), 0.72)     # brown, darkened to read on white
    page_bg = _tint(c.get("sand", "#f4f4f2"), 0.55)
    f = s.get("fonts") or {}
    head_font = f.get("heading", "Georgia, serif")
    body_font = f.get("body", "Helvetica, Arial, sans-serif")
    ink, muted = "#1d2733", "#5b6470"
    logo = _logo_src(s, for_preview=review)
    d = date.fromisoformat(dg.date)
    date_words = f"{d.strftime('%B')} {d.day}, {d.year}"

    intro_html = "".join(f'<p style="margin:0 0 14px;">{e(para.strip())}</p>'
                         for para in dg.intro.split("\n\n") if para.strip())
    logo_cell = (f'<td width="72" valign="middle" style="padding-right:16px;"><img src="{logo}" alt="R&amp;R" width="64" '
                 f'style="display:block;width:64px;height:auto;border:0;"></td>') if logo else ""
    out = []
    if review:
        out.append(f'''<div style="background:#fff4ce;border-bottom:1px solid #e0b100;color:#3d3000;padding:12px 16px;font:14px/1.4 {body_font};">
<strong>PREVIEW, NOT SENT.</strong> Subject: {e(dg.subject)}<br>{dg.counts['included']} grants included, {dg.counts['held']} held back (listed at the bottom; subscribers won't see that part).</div>''')
    out.append(f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{page_bg};">
<tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:6px;overflow:hidden;font-family:{body_font};color:{ink};">
<tr><td style="padding:28px 32px 20px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>{logo_cell}
<td valign="middle"><div style="font-family:{head_font};font-size:28px;line-height:1.15;font-weight:700;color:{navy};">{e(dg.name)}</div>
<div style="font-size:13px;color:{muted};margin-top:4px;letter-spacing:.04em;">{e(date_words.upper())} &nbsp;·&nbsp; {e(s.get("sender_brand", ""))}</div></td>
</tr></table></td></tr>
<tr><td style="height:5px;line-height:5px;font-size:0;background:{navy};">&nbsp;</td></tr>
<tr><td style="height:3px;line-height:3px;font-size:0;background:{accent};">&nbsp;</td></tr>
<tr><td style="padding:24px 32px 6px;font-size:16px;line-height:1.6;">{intro_html}</td></tr>''')
    summary = " · ".join(f"{dg.counts[k]} {label.lower()}" for k, label, _ in SECTIONS if dg.counts.get(k))
    if summary:
        out.append(f'<tr><td style="padding:4px 32px 4px;font-size:13px;color:{muted};">This week: {e(summary)}</td></tr>')
    for key, label, blurb in SECTIONS:
        items = dg.sections.get(key) or []
        if not items:
            continue
        out.append(f'''<tr><td style="padding:28px 32px 2px;">
<div style="font-family:{head_font};font-size:21px;font-weight:700;color:{navy};padding-bottom:6px;border-bottom:2px solid {accent};">{e(label)}</div>
<div style="font-size:13px;color:{muted};margin-top:8px;">{e(blurb.format(**s))}</div></td></tr>''')
        for it in items:
            notes = "".join(f'<div style="font-size:13px;color:{warm_text};margin-top:8px;font-weight:600;">{e(n)}</div>' for n in it.notes)
            out.append(f'''<tr><td style="padding:14px 32px 14px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td width="3" style="background:{_tint(accent, 0.35)};font-size:0;">&nbsp;</td>
<td style="padding-left:14px;">
<a href="{e(it.url)}" style="font-size:17px;font-weight:700;color:{ink};text-decoration:none;">{e(it.title)}</a>
<div style="font-size:13px;color:{muted};margin-top:2px;">{e(it.funder)}</div>
<div style="font-size:14px;margin-top:8px;"><strong style="color:{navy};">{e(it.amount)}</strong> &nbsp;·&nbsp; {e(it.deadline)}</div>
<div style="font-size:14px;line-height:1.55;color:#3a4350;margin-top:6px;">{e(it.description)}</div>{notes}
<div style="margin-top:10px;"><a href="{e(it.url)}" style="font-size:13px;font-weight:700;color:{navy};text-decoration:underline;text-decoration-color:{accent};">View on funder&#39;s site &rarr;</a></div>
</td></tr></table></td></tr>''')
    out.append(f'''<tr><td style="padding:28px 32px 8px;font-size:15px;line-height:1.5;">
<div style="font-family:{head_font};font-style:italic;font-size:18px;color:{navy};">{e(s.get("signoff", ""))}</div></td></tr>
<tr><td style="padding:20px 32px 28px;background:{_tint(c.get("sand", "#f4f4f2"), 0.75)};font-size:12px;line-height:1.6;color:{muted};">
{e(s.get('verify_note', ''))}<br><br>{e(s.get('footer', ''))}<br>
Questions? Reply to this email. &nbsp;·&nbsp; <a href="{{{{unsubscribe_url}}}}" style="color:{muted};">Unsubscribe</a></td></tr>
</table></td></tr></table>''')
    if review and dg.held:
        rows = "".join(
            f'<li style="margin-bottom:8px;"><a href="{e(h["url"])}" style="color:{navy};">{e(h["title"])}</a><br><span style="color:#8a1c1c;">{e("; ".join(h["reasons"]))}</span>'
            + "".join(f'<br><span style="color:#666;font-size:12px;">{e(x)}</span>' for x in h["evidence"]) + "</li>"
            for h in dg.held)
        out.append(f'''<div style="max-width:600px;margin:0 auto 32px;padding:16px 20px;border:1px dashed #b3b3ad;background:#fff;font:14px/1.4 {body_font};color:{ink};">
<strong>Held back this week (reviewer only)</strong><ul style="padding-left:18px;">{rows}</ul></div>''')
    fonts_link = f'<link href="{e(f["web_fonts_url"])}" rel="stylesheet">' if f.get("web_fonts_url") else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{fonts_link}<title>{e(dg.subject)}</title></head><body style="margin:0;padding:0;background:{page_bg};">{"".join(out)}</body></html>')


def render_text(dg: Digest) -> str:
    s = settings()
    d = date.fromisoformat(dg.date)
    lines = [dg.name.upper(), f"{d.strftime('%B')} {d.day}, {d.year}", "", dg.intro, ""]
    for key, label, blurb in SECTIONS:
        items = dg.sections.get(key) or []
        if not items:
            continue
        lines += [label.upper(), blurb.format(**s), ""]
        for it in items:
            lines += [it.title, f"  {it.funder}", f"  {it.amount} · {it.deadline}", f"  {it.description}"]
            lines += [f"  Note: {n}" for n in it.notes]
            lines += [f"  {it.url}", ""]
    if s.get("signoff"):
        lines += [s["signoff"], ""]
    lines += ["--", s.get("verify_note", "").strip(), s.get("footer", "").strip(),
              "Unsubscribe: {{unsubscribe_url}}"]
    return "\n".join(lines)


def write_preview(dg: Digest) -> Path:
    out = config.root() / "outputs" / "previews" / dg.date
    out.mkdir(parents=True, exist_ok=True)
    (out / "email.html").write_text(render_html(dg, review=False), encoding="utf-8")
    (out / "preview.html").write_text(render_html(dg, review=True), encoding="utf-8")
    (out / "email.txt").write_text(render_text(dg), encoding="utf-8")
    manifest = asdict(dg)
    manifest["status"] = "preview"           # Session 4: approve -> approved -> sent
    manifest["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "digest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return out
