"""Triangle CF scraper + grant database change tracking. Runs offline from saved fixtures."""
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
PAGES = {
    "https://trianglecf.org/apply/grants-for-nonprofits/": (FIX / "trianglecf_page1.html").read_text(),
    "https://trianglecf.org/apply/grants-for-nonprofits/page/2/": (FIX / "trianglecf_page2.html").read_text(),
}


class Parsing(unittest.TestCase):
    def test_amounts(self):
        from affix.parsing import parse_amount
        self.assertEqual(parse_amount("$50,000"), (50000, 50000))
        self.assertEqual(parse_amount("$500 - $2,500"), (500, 2500))
        self.assertEqual(parse_amount("Up to $10,000"), (None, 10000))
        self.assertEqual(parse_amount("See RFP details"), (None, None))
        self.assertEqual(parse_amount(""), (None, None))
        self.assertEqual(parse_amount("$20,000 "), (20000, 20000))

    def test_dates(self):
        from affix.parsing import parse_date
        self.assertEqual(parse_date("June 1, 2026"), "2026-06-01")
        self.assertEqual(parse_date("October 16, 2026"), "2026-10-16")
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("Rolling"))


class Scraper(unittest.TestCase):
    def test_parse_and_paginate(self):
        from affix.sources import trianglecf
        listings = trianglecf.scrape(fetch=PAGES.__getitem__)
        self.assertEqual(len(listings), 6)
        by = {l.grant_id: l for l in listings}
        h = by["trianglecf:our-impact-housing-affordability"]
        self.assertEqual((h.open_date, h.close_date, h.amount_min, h.status), ("2026-09-14", "2026-10-16", 25000, "Open"))
        self.assertEqual(by["trianglecf:clancy-theys-1949-fund"].title, "Clancy & Theys 1949 Fund")
        self.assertIn("trianglecf:faith-based-housing-affordability-grant-program", by)  # from page 2
        self.assertTrue(all(l.url.startswith("https://trianglecf.org/award/") for l in listings))

    def test_empty_page_is_an_error(self):
        from affix.sources import trianglecf
        from affix.sources.base import ScrapeError
        with self.assertRaises(ScrapeError):
            trianglecf.scrape(fetch=lambda url: "<html><body>Redesigned site</body></html>")


class Database(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        os.environ["AFFIX_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("AFFIX_HOME", None)
        shutil.rmtree(self.home)

    def test_change_tracking_across_runs(self):
        from affix import db, scrape
        conn = db.connect()
        first = scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        self.assertEqual((first["new"], first["changed"], first["delisted"]), (6, 0, 0))

        same = scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        self.assertEqual((same["new"], same["changed"], same["delisted"]), (0, 0, 0))

        # Week 2: deadline extended, one grant removed from page 2.
        week2 = dict(PAGES)
        week2["https://trianglecf.org/apply/grants-for-nonprofits/"] = PAGES[
            "https://trianglecf.org/apply/grants-for-nonprofits/"].replace("October 16, 2026", "October 23, 2026")
        week2["https://trianglecf.org/apply/grants-for-nonprofits/page/2/"] = "<html><body></body></html>"
        c = scrape.run_source("trianglecf", conn=conn, fetch=week2.__getitem__)
        self.assertEqual((c["changed"], c["delisted"]), (1, 1))
        hist = [(r["field"], r["old_value"], r["new_value"])
                for r in db.changes(conn, grant_id="trianglecf:our-impact-housing-affordability")]
        self.assertIn(("close_date", "2026-10-16", "2026-10-23"), hist)
        self.assertEqual(len(db.grants(conn)), 5)
        self.assertEqual(len(db.grants(conn, include_delisted=True)), 6)

        # Week 3: it comes back -> relisted, history keeps both events.
        c = scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        self.assertEqual(c["relisted"], 1)

    def test_failed_scrape_changes_nothing(self):
        from affix import db, scrape
        conn = db.connect()
        scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        with self.assertRaises(Exception):
            scrape.run_source("trianglecf", conn=conn, fetch=lambda u: "<html></html>")
        self.assertEqual(len(db.grants(conn)), 6)  # nothing delisted by a broken page
        last = conn.execute("SELECT ok, error FROM scrape_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        self.assertEqual(last["ok"], 0)

    def test_lifecycle(self):
        from affix import db, scrape
        conn = db.connect()
        scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        today = date(2026, 10, 1)
        life = {r["grant_id"]: db.lifecycle(r, today) for r in db.grants(conn)}
        self.assertEqual(life["trianglecf:our-impact-housing-affordability"], "closing_soon")
        self.assertEqual(life["trianglecf:fund-for-the-triangle-responsive-grantmaking"], "closed")
        self.assertEqual(life["trianglecf:gsk-impact-awards"], "open")
        self.assertEqual(life["trianglecf:the-paul-green-foundation"], "unknown")
        self.assertEqual(db.lifecycle(conn.execute(
            "SELECT * FROM grants WHERE grant_id='trianglecf:faith-based-housing-affordability-grant-program'").fetchone(),
            date(2026, 9, 20)), "opening_soon")


if __name__ == "__main__":
    unittest.main()
