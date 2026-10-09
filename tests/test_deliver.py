"""Delivery safety checks. Resend is faked: nothing is ever sent from tests."""
import json
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
DAY = "2026-10-01"


class Delivery(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        force_sending_off(self.home)
        os.environ.update(AFFIX_HOME=str(self.home), RESEND_API_KEY="re_test", RESEND_SEGMENT_ID="seg_1",
                          FROM_EMAIL="Bri <grants@updates.example.org>", ADMIN_EMAIL="bri@example.org")
        from affix import db, deliver, digest, scrape
        conn = db.connect()
        scrape.run_source("trianglecf", conn=conn, fetch=PAGES.__getitem__)
        digest.write_preview(digest.build(conn, today=date(2026, 10, 1), log=False))
        self.calls = []
        self.fail_next = False

        def fake(method, path, body=None, params=None, idempotency_key=None):
            if self.fail_next:
                self.fail_next = False
                raise deliver.ResendError("Resend said 500: boom")
            self.calls.append((method, path, body))
            return {"id": f"id_{len(self.calls)}", "data": [], "has_more": False}
        self._orig = deliver._request
        deliver._request = fake
        self.deliver = deliver

    def tearDown(self):
        self.deliver._request = self._orig
        for k in ("AFFIX_HOME", "RESEND_API_KEY", "RESEND_SEGMENT_ID", "FROM_EMAIL", "ADMIN_EMAIL"):
            os.environ.pop(k, None)
        shutil.rmtree(self.home)

    def enable_sending(self):
        p = self.home / "config" / "settings.yaml"
        p.write_text(p.read_text().replace("sending_enabled: false", "sending_enabled: true"))

    def manifest(self):
        return json.loads((self.home / "outputs" / "previews" / DAY / "digest.json").read_text())

    def test_send_test_goes_to_admin_only(self):
        self.deliver.send_test(DAY)
        method, path, body = self.calls[-1]
        self.assertEqual((method, path, body["to"]), ("POST", "/emails", ["bri@example.org"]))
        self.assertTrue(body["subject"].startswith("[TEST] "))
        self.assertNotIn("{{unsubscribe_url}}", body["html"])

    def test_send_blocked_while_switched_off(self):
        self.deliver.approve(DAY)
        with self.assertRaises(self.deliver.SendBlocked):
            self.deliver.send(DAY)
        self.assertEqual(self.calls, [])

    def test_send_requires_approval(self):
        self.enable_sending()
        with self.assertRaises(self.deliver.SendBlocked):
            self.deliver.send(DAY)
        self.assertEqual(self.calls, [])

    def test_approved_digest_goes_out_as_broadcast_once(self):
        self.enable_sending()
        self.deliver.approve(DAY)
        self.deliver.send(DAY)
        method, path, body = self.calls[-1]
        self.assertEqual((method, path, body["segment_id"], body["send"]), ("POST", "/broadcasts", "seg_1", True))
        self.assertIn("{{{RESEND_UNSUBSCRIBE_URL}}}", body["html"])
        self.assertEqual(self.manifest()["status"], "sent")
        with self.assertRaises(self.deliver.SendBlocked):      # never twice
            self.deliver.send(DAY)
        self.assertEqual(len(self.calls), 1)

    def test_edit_after_approval_blocks_send(self):
        self.enable_sending()
        self.deliver.approve(DAY)
        p = self.home / "outputs" / "previews" / DAY / "email.html"
        p.write_text(p.read_text() + "<!-- edited -->")
        with self.assertRaises(self.deliver.SendBlocked):
            self.deliver.send(DAY)
        self.assertEqual(self.calls, [])

    def test_failed_send_can_be_retried(self):
        self.enable_sending()
        self.deliver.approve(DAY)
        self.fail_next = True
        with self.assertRaises(self.deliver.ResendError):
            self.deliver.send(DAY)
        self.assertEqual(self.manifest()["status"], "approved")
        self.deliver.send(DAY)
        self.assertEqual(self.manifest()["status"], "sent")

    def test_kill_file_stops_test_sends_too(self):
        (self.home / "state").mkdir(exist_ok=True)
        (self.home / "state" / "KILL").touch()
        with self.assertRaises(self.deliver.SendBlocked):
            self.deliver.send_test(DAY)


if __name__ == "__main__":
    unittest.main()
