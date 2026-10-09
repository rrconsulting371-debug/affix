"""Airtable <-> Resend subscriber sync. Both services are faked; nothing real is touched."""
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


class Sync(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "config", self.home / "config")
        force_sending_off(self.home)
        os.environ.update(AFFIX_HOME=str(self.home), RESEND_API_KEY="re_test", RESEND_SEGMENT_ID="seg_1",
                          AIRTABLE_TOKEN="pat_test", AIRTABLE_BASE_ID="app_test")
        from affix import airtable, deliver, subscribers
        self.at, self.dl, self.sub = airtable, deliver, subscribers
        self.rows = []
        self.contacts = {}
        self.resend_calls, self.at_updates = [], []

        def fake_resend(method, path, body=None, params=None, idempotency_key=None):
            if method == "GET" and path == "/contacts":
                return {"data": list(self.contacts.values()), "has_more": False}
            self.resend_calls.append((method, path, body))
            if method == "POST" and path == "/contacts":
                return {"id": "c_new_" + body["email"]}
            return {"id": "ok"}
        self._orig = (deliver._request, subscribers._resend, airtable.records, airtable.update, airtable.tables)
        names = ["Email", "First Name", "Last Name", "Status", "Consent", "Resend ID", "Last Synced", "Notes"]
        airtable.tables = lambda: [{"name": "Subscribers", "fields": [{"name": n} for n in names]}]
        deliver._request = fake_resend
        subscribers._resend = lambda m, p, b=None: fake_resend(m, p, b)
        airtable.records = lambda table: self.rows
        airtable.update = lambda table, ups: self.at_updates.extend(ups)

    def tearDown(self):
        self.dl._request, self.sub._resend, self.at.records, self.at.update, self.at.tables = self._orig
        for k in ("AFFIX_HOME", "RESEND_API_KEY", "RESEND_SEGMENT_ID", "AIRTABLE_TOKEN", "AIRTABLE_BASE_ID"):
            os.environ.pop(k, None)
        shutil.rmtree(self.home)

    def row(self, rid, email, status="Active", consent=True, resend_id=None, first=None):
        f = {"Email": email, "Status": status, "Consent": consent}
        if resend_id:
            f["Resend ID"] = resend_id
        if first:
            f["First Name"] = first
        self.rows.append({"id": rid, "fields": f})

    def test_new_active_consented_person_is_added(self):
        self.row("rec1", "Ana@Example.org", first="Ana")
        rep = self.sub.sync()
        self.assertEqual(rep.added, ["ana@example.org"])
        method, path, body = self.resend_calls[0]
        self.assertEqual((method, path, body["segments"], body["first_name"]), ("POST", "/contacts", [{"id": "seg_1"}], "Ana"))
        self.assertEqual(self.at_updates[0]["fields"]["Resend ID"], "c_new_ana@example.org")

    def test_no_consent_means_not_added(self):
        self.row("rec1", "ana@example.org", consent=False)
        rep = self.sub.sync()
        self.assertEqual(rep.needs_consent, ["ana@example.org"])
        self.assertEqual(self.resend_calls, [])

    def test_unsubscribe_link_wins_and_is_never_undone(self):
        self.row("rec1", "ana@example.org", status="Active", resend_id="c1")
        self.contacts["ana@example.org"] = {"id": "c1", "email": "ana@example.org", "unsubscribed": True}
        rep = self.sub.sync()
        self.assertEqual(rep.marked_unsubscribed_in_airtable, ["ana@example.org"])
        self.assertEqual(self.at_updates[0]["fields"]["Status"], "Unsubscribed")
        self.assertEqual(self.resend_calls, [])            # never re-subscribed

    def test_bri_marks_unsubscribed_in_airtable(self):
        self.row("rec1", "ana@example.org", status="Unsubscribed", resend_id="c1")
        self.contacts["ana@example.org"] = {"id": "c1", "email": "ana@example.org", "unsubscribed": False}
        rep = self.sub.sync()
        self.assertEqual(rep.unsubscribed_in_resend, ["ana@example.org"])
        self.assertEqual(self.resend_calls[0], ("PATCH", "/contacts/c1", {"unsubscribed": True}))

    def test_paused_is_taken_out_of_segment(self):
        self.row("rec1", "ana@example.org", status="Paused", resend_id="c1")
        self.contacts["ana@example.org"] = {"id": "c1", "email": "ana@example.org", "unsubscribed": False}
        rep = self.sub.sync()
        self.assertEqual(rep.removed_from_segment, ["ana@example.org"])
        self.assertEqual(self.resend_calls[0][:2], ("DELETE", "/contacts/c1/segments/seg_1"))

    def test_existing_contact_is_added_to_segment(self):
        self.row("rec1", "ana@example.org")
        self.contacts["ana@example.org"] = {"id": "c9", "email": "ana@example.org", "unsubscribed": False}
        self.sub.sync()
        self.assertEqual(self.resend_calls[0][:2], ("POST", "/contacts/c9/segments/seg_1"))

    def test_second_sync_changes_nothing(self):
        self.row("rec1", "ana@example.org", resend_id="c1")
        self.contacts["ana@example.org"] = {"id": "c1", "email": "ana@example.org", "unsubscribed": False}
        rep = self.sub.sync()
        self.assertEqual((rep.already_in_sync, self.resend_calls, self.at_updates), (1, [], []))

    def test_dry_run_changes_nothing(self):
        self.row("rec1", "ana@example.org")
        rep = self.sub.sync(dry_run=True)
        self.assertEqual(rep.added, ["ana@example.org"])
        self.assertEqual((self.resend_calls, self.at_updates), ([], []))

    def test_missing_column_stops_before_any_change(self):
        self.at.tables = lambda: [{"name": "Subscribers", "fields": [{"name": "Email"}, {"name": "Status"}]}]
        self.row("rec1", "ana@example.org")
        with self.assertRaises(self.at.AirtableError):
            self.sub.sync()
        self.assertEqual((self.resend_calls, self.at_updates), ([], []))

    def test_invalid_duplicate_and_resend_only(self):
        self.row("rec1", "not-an-email")
        self.row("rec2", "ana@example.org", resend_id="c1")
        self.row("rec3", "ANA@example.org")
        self.contacts["ana@example.org"] = {"id": "c1", "email": "ana@example.org", "unsubscribed": False}
        self.contacts["old@example.org"] = {"id": "c2", "email": "old@example.org", "unsubscribed": False}
        rep = self.sub.sync()
        self.assertEqual((rep.invalid, rep.duplicates, rep.only_in_resend),
                         (["not-an-email"], ["ana@example.org"], ["old@example.org"]))


if __name__ == "__main__":
    unittest.main()
