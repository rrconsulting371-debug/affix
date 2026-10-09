"""Hold-back rules (Bri's Filter Criteria, Oct 1 2026)."""
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
TODAY = date(2026, 10, 1)


def row(**kw):
    base = dict(grant_id="t:x", title="Community Grant", description="", amount_text="$10,000",
                amount_min=10000, amount_max=10000, status="Open", open_date="2026-09-01",
                close_date="2026-12-01", listed=1)
    base.update(kw)
    return base


class HoldBack(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        force_sending_off(self.home)
        os.environ["AFFIX_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("AFFIX_HOME", None)
        shutil.rmtree(self.home)

    def ev(self, **kw):
        from affix import holdback
        return holdback.evaluate(row(**kw), TODAY)

    def test_clean_grant_included(self):
        d = self.ev()
        self.assertTrue(d.include)
        self.assertEqual((d.reasons, d.notes), ([], []))

    def test_no_minimum_amount(self):
        self.assertTrue(self.ev(amount_text="$500 - $2,500", amount_min=500, amount_max=2500).include)

    def test_application_fee_held_back(self):
        d = self.ev(description="A $25 application fee is required.")
        self.assertFalse(d.include)
        self.assertIn("Charges an application fee", d.reasons)
        self.assertTrue(d.evidence)

    def test_no_fee_language_is_fine(self):
        self.assertTrue(self.ev(description="There is no application fee to apply.").include)

    def test_contest_held_back(self):
        self.assertFalse(self.ev(title="Founders Pitch Competition").include)
        self.assertFalse(self.ev(description="Winners chosen by public vote.").include)
        self.assertFalse(self.ev(description="Enter our monthly contests.").include)

    def test_award_is_not_a_contest(self):
        self.assertTrue(self.ev(title="GSK IMPACT Awards", description="Honors up to 10 local nonprofits.").include)

    def test_invitation_only_included_with_note(self):
        d = self.ev(description="The Land Transaction Grant Program is by invitation only.")
        self.assertTrue(d.include)
        self.assertTrue(any("invitation" in n.lower() for n in d.notes))

    def test_undated_included_with_note(self):
        d = self.ev(open_date=None, close_date=None, status="")
        self.assertTrue(d.include)
        self.assertTrue(any("No deadline" in n for n in d.notes))

    def test_past_deadline_held_back_even_if_marked_open(self):
        d = self.ev(status="Open", open_date="2026-04-20", close_date="2026-06-01")
        self.assertFalse(d.include)
        self.assertIn("Deadline has passed (2026-06-01)", d.reasons)

    def test_mid_cycle_included_with_its_own_note(self):
        d = self.ev(status="Mid-Cycle", open_date=None, close_date=None)
        self.assertTrue(d.include)
        self.assertEqual(len(d.notes), 1)
        self.assertIn("Cycle underway", d.notes[0])

    def test_pre_selected_recipients_held_back(self):
        d = self.ev(description="Provides assistance through grants to three identified nonprofits.")
        self.assertFalse(d.include)
        self.assertIn("Recipients are pre-selected (not open to applicants)", d.reasons)

    def test_delisted_held_back(self):
        self.assertFalse(self.ev(listed=0).include)


if __name__ == "__main__":
    unittest.main()
