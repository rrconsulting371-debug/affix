"""Digest build + preview. Uses the saved Triangle CF pages; nothing is sent."""
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def force_sending_off(home):
    """Tests always start with sending switched off, whatever the live setting is."""
    p = home / "config" / "settings.yaml"
    p.write_text(p.read_text().replace("sending_enabled: true", "sending_enabled: false"))
FIX = REPO / "tests" / "fixtures"
PAGES = {
    "https://trianglecf.org/apply/grants-for-nonprofits/": (FIX / "trianglecf_page1.html").read_text(),
    "https://trianglecf.org/apply/grants-for-nonprofits/page/2/": (FIX / "trianglecf_page2.html").read_text(),
}
TODAY = date(2026, 10, 1)


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        force_sending_off(self.home)
        os.environ["AFFIX_HOME"] = str(self.home)
        from affix import db, scrape
        self.conn = db.connect()
        scrape.run_source("trianglecf", conn=self.conn, fetch=PAGES.__getitem__)

    def tearDown(self):
        os.environ.pop("AFFIX_HOME", None)
        shutil.rmtree(self.home)

    def test_sections_and_subject(self):
        from affix import digest
        dg = digest.build(self.conn, today=TODAY, log=False)
        ids = {k: [i.grant_id for i in v] for k, v in dg.sections.items()}
        self.assertIn("trianglecf:our-impact-housing-affordability", ids["closing_soon"])
        self.assertIn("trianglecf:faith-based-housing-affordability-grant-program", ids["closing_soon"])
        self.assertEqual(dg.held[0]["grant_id"], "trianglecf:fund-for-the-triangle-responsive-grantmaking")
        all_ids = [i for v in ids.values() for i in v]
        self.assertEqual(len(all_ids), len(set(all_ids)))  # each grant once
        self.assertTrue(dg.subject.startswith("Your Affix Grant List · Oct 1: 2 closing soon"))

    def test_every_item_links_to_the_funder(self):
        from affix import digest
        dg = digest.build(self.conn, today=TODAY, log=False)
        for items in dg.sections.values():
            for i in items:
                self.assertTrue(i.url.startswith("https://trianglecf.org/award/"))

    def test_preview_files_and_review_only_content(self):
        from affix import digest
        dg = digest.build(self.conn, today=TODAY, log=False)
        out = digest.write_preview(dg)
        email = (out / "email.html").read_text()
        review = (out / "preview.html").read_text()
        self.assertIn("Housing Affordability", email)
        self.assertNotIn("Responsive Grantmaking", email)      # held back
        self.assertNotIn("PREVIEW, NOT SENT", email)
        self.assertIn("PREVIEW, NOT SENT", review)
        self.assertIn("Responsive Grantmaking", review)        # reviewer sees what was held
        self.assertIn("Deadline has passed", review)
        self.assertTrue((out / "email.txt").read_text().startswith("YOUR AFFIX GRANT LIST"))
        self.assertTrue((out / "digest.json").exists())

    def test_text_color_follows_brand(self):
        from affix.digest import _text_on
        self.assertEqual(_text_on("#1F4E79"), "#ffffff")
        self.assertEqual(_text_on("#F5D547"), "#111111")


if __name__ == "__main__":
    unittest.main()
