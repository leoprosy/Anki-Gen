"""Prove that optional reporting cannot leak content or break offline work."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings
from telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = Path(self.tmp.name) / "analytics-state.json"
        self.prefs = {"analytics_enabled": False}
        self.config = {"project_token": "phc_test", "region": "eu", "app_version": "1.2.1"}
        self.now = 1_790_000_000.0
        self.sent = []
        self.sender = lambda config, batch: self.sent.append(json.loads(json.dumps(batch)))
        self.worker = patch.object(Telemetry, "_start_worker")
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.client = self.make_client()

    def make_client(self):
        return Telemetry(self.state_file, lambda: self.prefs, lambda: self.config,
                         sender=self.sender, clock=lambda: self.now)

    def queued(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))["queue"]

    def test_no_identifier_or_network_before_explicit_consent(self):
        for value in (False, None, "true", 1):
            self.prefs["analytics_enabled"] = value
            self.assertFalse(self.client.track("app_opened"))
            self.client.flush_once()
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.sent, [])

    def test_missing_configuration_creates_no_identifier(self):
        self.prefs["analytics_enabled"] = True
        self.config = None
        self.assertFalse(self.client.track("app_opened"))
        self.assertFalse(self.state_file.exists())

    def test_payload_excludes_content_and_requires_valid_counts(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("cards_saved", card_count=4, filename="private.docx",
                          response="private course", project_id="My course")
        events = self.queued()
        self.assertEqual([e["event"] for e in events], ["first_launch", "app_opened", "cards_saved"])
        props = events[-1]["properties"]
        self.assertEqual(props["card_count"], 4)
        self.assertEqual(set(props), {"card_count", "app_version", "os", "schema_version",
                                     "$process_person_profile", "$geoip_disable"})
        self.assertFalse(props["$process_person_profile"])
        self.assertTrue(props["$geoip_disable"])
        self.assertNotIn("private", json.dumps(events))
        for count in (-1, True, "4", None):
            self.assertFalse(self.client.track("cards_saved", card_count=count))
        self.assertFalse(self.client.track("export_completed", card_count=2, format="private-path"))
        self.assertFalse(self.client.track("course contents"))
        self.assertEqual(len(self.queued()), 3)

    def test_restart_preserves_id_and_only_records_activity_once_per_day(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("app_opened")
        first = self.queued()
        self.client.flush_once()
        restarted = self.make_client()
        restarted.track("app_opened")
        self.assertEqual(self.queued(), [])
        self.now += 86400
        restarted.track("app_opened")
        self.assertEqual([e["event"] for e in self.queued()], ["app_opened"])
        self.assertEqual(first[0]["distinct_id"], self.queued()[0]["distinct_id"])

    def test_failed_upload_retries_same_uuid_and_original_timestamp(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("export_completed", card_count=12, format="zip")
        original = self.queued()
        with patch.object(self.client, "sender", side_effect=OSError("offline")):
            self.assertFalse(self.client.flush_once())
        self.assertEqual(self.queued(), original)
        self.now += 600
        self.assertTrue(self.make_client().flush_once())
        self.assertEqual(self.sent[0], original)
        self.assertEqual(self.queued(), [])

    def test_withdrawal_purges_queue_and_prevents_later_sends(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("app_opened")
        identity = self.queued()[0]["distinct_id"]
        self.prefs["analytics_enabled"] = False
        self.client.preferences_changed()
        self.assertEqual(self.queued(), [])
        self.client.flush_once()
        self.assertEqual(self.sent, [])
        self.prefs["analytics_enabled"] = True
        self.client.preferences_changed()
        self.assertEqual(self.queued()[0]["distinct_id"], identity)

    def test_revocation_during_upload_does_not_restore_pending_events(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("app_opened")

        def revoke(config, batch):
            self.prefs["analytics_enabled"] = False
            self.client.preferences_changed()
            raise OSError("request failed after consent withdrawal")

        self.client.sender = revoke
        self.assertFalse(self.client.flush_once())
        self.assertEqual(self.queued(), [])

    def test_withdrawal_while_preparing_dispatch_drops_snapshot(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("cards_saved", card_count=4)
        reads = 0

        def config_with_withdrawal():
            nonlocal reads
            reads += 1
            if reads == 2:
                self.prefs["analytics_enabled"] = False
                self.client.preferences_changed()
            return self.config

        self.client.config_loader = config_with_withdrawal
        self.assertFalse(self.client.flush_once())
        self.assertEqual(self.sent, [])
        self.assertEqual(self.queued(), [])

    def test_withdrawal_and_reenable_cannot_replay_old_snapshot(self):
        self.prefs["analytics_enabled"] = True
        self.client.track("cards_saved", card_count=4)
        reads = 0

        def config_with_toggle():
            nonlocal reads
            reads += 1
            if reads == 2:
                self.prefs["analytics_enabled"] = False
                self.client.preferences_changed()
                self.prefs["analytics_enabled"] = True
            return self.config

        self.client.config_loader = config_with_toggle
        self.assertFalse(self.client.flush_once())
        self.assertEqual(self.sent, [])

    def test_capacity_and_expiry_bound_offline_storage(self):
        self.prefs["analytics_enabled"] = True
        for _ in range(510):
            self.client.track("cards_saved", card_count=1)
        self.assertLessEqual(len(self.queued()), 500)
        self.now += 8 * 86400
        self.client.flush_once()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.queued(), [])

    def test_failed_storage_is_non_fatal_and_cannot_send(self):
        self.prefs["analytics_enabled"] = True
        self.state_file.mkdir()
        self.assertFalse(self.client.track("cards_saved", card_count=4))
        self.assertFalse(self.client.flush_once())
        self.assertEqual(self.sent, [])

    def test_corrupt_state_is_non_fatal(self):
        self.prefs["analytics_enabled"] = True
        for raw in ("not json", "[]", '{"queue": null}'):
            self.state_file.write_text(raw, encoding="utf-8")
            self.assertFalse(self.client.flush_once())
        self.assertEqual(self.sent, [])


class ConsentSettingTests(unittest.TestCase):
    def test_settings_default_and_validation_require_real_boolean(self):
        self.assertIs(settings.defaults().get("analytics_enabled"), False)
        for value in ("true", 1, [], None):
            self.assertIs(settings._clean({"analytics_enabled": value})["analytics_enabled"], False)
        self.assertIs(settings._clean({"analytics_enabled": True})["analytics_enabled"], True)


if __name__ == "__main__":
    unittest.main()
