"""Step 1 acceptance: `affix --help` works and the audit log writes. Run: python -m pytest  (or python -m unittest)"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def force_sending_off(home):
    """Tests always start with sending switched off, whatever the live setting is."""
    p = home / "config" / "settings.yaml"
    p.write_text(p.read_text().replace("sending_enabled: true", "sending_enabled: false"))


class Step1(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        force_sending_off(self.home)
        os.environ["AFFIX_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("AFFIX_HOME", None)
        shutil.rmtree(self.home)

    def test_help(self):
        from affix.cli import build_parser
        text = build_parser().format_help()
        for cmd in ("scrape", "grants", "sources", "preview", "approve", "send", "status"):
            self.assertIn(cmd, text)

    def test_audit_appends(self):
        from affix import audit
        audit.log("system", note="one")
        audit.log("edit", actor="bri", grant_id="x")
        rows = audit.read()
        self.assertEqual([r["event"] for r in rows], ["system", "edit"])
        self.assertEqual(audit.read(event="edit")[0]["actor"], "bri")

    def test_budget_alerts_and_cap(self):
        from affix import audit, budget
        # $25 cap; sonnet at $3/$15 per Mtok. 1.4M output tokens = $21 -> crosses 80%.
        budget.record("claude-sonnet-4-5", 0, 1_400_000, purpose="test")
        self.assertEqual([r["level"] for r in audit.read(event="budget_alert")], ["80%"])
        budget.check()  # still under cap
        budget.record("claude-sonnet-4-5", 0, 400_000, purpose="test")  # $27 total
        with self.assertRaises(budget.BudgetExceeded):
            budget.check()

    def test_kill_switch(self):
        from affix import config
        self.assertTrue(config.kill_switch_active())  # sending_enabled: false by default
        (self.home / "state").mkdir(exist_ok=True)
        (self.home / "state" / "KILL").touch()
        self.assertTrue(config.kill_switch_active())

    def test_login_gated_url_refused(self):
        from affix import fetch
        with self.assertRaises(fetch.LoginRequired):
            fetch.fetch_with_retry("https://foo.submittable.com/submit/123", check_robots=False)


if __name__ == "__main__":
    unittest.main()
