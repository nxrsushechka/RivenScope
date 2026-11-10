from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from rivenscope.storage import Store, SCHEMA_VERSION, new_watchlist
from rivenscope.notifications import record_notification
from rivenscope.config import validate_settings
from rivenscope.valuation import estimate
from .helpers import NOW, listing, comparables


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rivenscope-")
        self.root = Path(self.temp.name); self.path = self.root / "test.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_schema_and_persistence(self):
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.store.save_watchlist(new_watchlist()); self.store.close(); self.store = Store(self.path)
        self.assertEqual(len(self.store.watchlists()), 1)
        self.assertEqual(self.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_upgrade_v1_creates_backup(self):
        self.store.db.execute("DROP TABLE cache"); self.store.db.execute("DELETE FROM migrations WHERE version=2")
        self.store.db.execute("PRAGMA user_version=1"); self.store.db.commit(); self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(list(self.root.glob("pre-migration-*.sqlite"))), 1)

    def test_discovery_repeated_price_cycles_and_restart(self):
        item = listing()
        events = self.store.observe([item], "global", NOW)
        self.assertEqual(events[0]["kind"], "existing")
        self.assertEqual(self.store.observe([replace(item, observed_at=NOW+1)], "global", NOW+1), [])
        changed = replace(item, price=400)
        event = self.store.observe([changed], "global", NOW+2)[0]
        self.assertEqual(event["kind"], "price_changed")
        event2 = self.store.observe([item], "global", NOW+3)[0]
        self.assertNotEqual(event["id"], event2["id"])
        self.store.close(); self.store = Store(self.path)
        events = self.store.observe([listing("new")], "global", NOW+4)
        self.assertEqual(events[0]["kind"], "new")
        self.assertEqual(self.store.summary()["snapshots"], 4)

    def test_status_bid_and_absence_semantics(self):
        item = listing(kind="auction", starting_bid=100)
        self.store.observe([item], "q", NOW, complete=True)
        self.assertEqual(self.store.observe([], "q", NOW+1, complete=False), [])
        events = self.store.observe([replace(item, highest_bid=150, seller_status="online")], "q", NOW+2)
        self.assertEqual({e["kind"] for e in events}, {"bid_changed", "status_changed"})
        events = self.store.observe([], "q", NOW+3, complete=True)
        self.assertEqual(events[0]["kind"], "potentially_missing")
        self.assertNotEqual(self.store.listings()[0]["listing"].status, "sold")

    def test_duplicates_rejected_atomically(self):
        with self.assertRaises(ValueError): self.store.observe([listing(), listing()], "q", NOW)
        self.assertEqual(self.store.summary()["listings"], 0)

    def test_unchanged_listing_return_is_recorded_once_across_restart(self):
        item = listing()
        self.store.observe([item], "q", NOW, complete=True)
        self.store.observe([], "q", NOW+1, complete=True)
        self.store.close(); self.store = Store(self.path)
        returned = self.store.observe([replace(item, observed_at=NOW+2)], "q", NOW+2, complete=True)
        self.assertEqual([e["kind"] for e in returned], ["status_changed"])
        self.assertEqual(self.store.listings()[0]["listing"].status, "active")
        self.assertEqual(len(self.store.history(item.id)["snapshots"]), 2)
        self.assertEqual(self.store.observe([item], "q", NOW+3, complete=True), [])
        self.assertEqual(len(self.store.history(item.id)["events"]), 3)

    def test_export_import_watchlists(self):
        self.store.save_watchlist(new_watchlist()); dest = self.root / "presets.json"
        self.store.export_file(dest, "watchlists"); self.store.import_file(dest, "watchlists")
        self.assertEqual(len(self.store.watchlists()), 2)
        with self.assertRaises(ValueError): self.store.export_file(dest, "watchlists")
        value = json.loads(dest.read_text()); value["version"] = 999; dest.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.store.import_file(dest, "watchlists")
        self.assertEqual(len(self.store.watchlists()), 2)

    def test_settings_confirmation_and_csv_injection(self):
        dest = self.root / "settings.json"; self.store.export_file(dest, "settings")
        with self.assertRaises(ValueError): self.store.import_file(dest, "settings")
        self.store.import_file(dest, "settings", True)
        self.store.observe([listing(seller="=HYPERLINK('bad')")], "q", NOW)
        csv_path = self.root / "market.csv"; self.store.export_file(csv_path, "csv")
        self.assertIn("'=HYPERLINK", csv_path.read_text())
        self.store.export_file(self.root / "data.json", "listings")
        self.assertEqual(len(json.loads((self.root / "data.json").read_text())["data"]), 1)

    def test_backup_restore_and_invalid_source(self):
        self.store.save_watchlist(new_watchlist()); backup = self.root / "backup.sqlite"
        self.store.backup(backup); self.store.save_watchlist(new_watchlist())
        with self.assertRaises(ValueError): self.store.restore(backup)
        previous = self.store.restore(backup, True)
        self.assertTrue(Path(previous).exists()); self.assertEqual(len(self.store.watchlists()), 1)
        bad = self.root / "bad.sqlite"; bad.write_text("corrupt")
        with self.assertRaises(sqlite3.DatabaseError): self.store.restore(bad, True)
        self.assertEqual(len(self.store.watchlists()), 1)

    def test_analytics_never_mix_bids(self):
        self.store.observe([listing(), listing("auction", kind="auction", highest_bid=200)], "q", NOW)
        analytics = self.store.analytics(now=NOW)
        self.assertEqual(analytics["prices"], [500]); self.assertEqual(len(analytics["bids"]), 1)
        self.assertEqual(len(analytics["asking"]), 1)

    def test_current_analytics_excludes_inactive_stale_and_future_asks(self):
        self.store.observe([listing("stale", price=50)], "stale", NOW-73*3600)
        self.store.observe([listing("missing", price=100)], "q", NOW-1, complete=True)
        self.store.observe([], "q", NOW, complete=True)
        self.store.observe([listing("closed", price=200, status="closed"),
                            listing("current", price=600)], "recent", NOW)
        self.store.observe([listing("future", price=700)], "future", NOW+1)
        analytics = self.store.analytics(now=NOW)
        self.assertEqual(analytics["prices"], [600])
        self.assertEqual(len(analytics["asking"]), 5)  # History is preserved.

    def test_qualified_analytics_respects_weapon_state_and_freshness(self):
        items = [listing("torid"), listing("other", weapon="other"),
                 listing("closed", status="closed"), listing("old_estimate")]
        self.store.observe(items, "q", NOW)
        result = estimate(listing(), comparables(), NOW)
        self.assertTrue(result.qualifies)
        for item in items:
            self.store.save_estimate(item.id, result, NOW-73*3600 if item.id == "old_estimate" else NOW)
        self.assertEqual(self.store.analytics(now=NOW)["qualified"], 2)
        self.assertEqual(self.store.analytics("torid", now=NOW)["qualified"], 1)
        self.assertEqual(self.store.analytics("other", now=NOW)["qualified"], 1)
        self.assertEqual(self.store.analytics(now=NOW+73*3600)["qualified"], 0)

    def test_notification_dedup_limits_and_existing_suppression(self):
        target = listing(); result = estimate(target, comparables(), NOW); settings = validate_settings({})
        event = {"id": "1", "kind": "existing"}
        self.assertIsNone(record_notification(self.store, event, target, result, settings, now=NOW))
        event["kind"] = "new"
        self.assertIsNotNone(record_notification(self.store, event, target, result, settings, now=NOW))
        self.assertIsNone(record_notification(self.store, event, target, result, settings, now=NOW+1))
        self.assertIsNone(record_notification(self.store, event, target, result, settings, watchlist=new_watchlist(), now=NOW+1))
        settings["notification_limit"] = 1
        self.assertIsNone(record_notification(self.store, {"id": "2", "kind": "new"}, target, result, settings, now=NOW+2))
        self.store.close(); self.store = Store(self.path)
        self.assertIsNone(record_notification(self.store, event, target, result, settings, now=NOW+70))

    def test_local_history_starts_empty(self):
        self.assertEqual(self.store.analytics()["asking"], [])
        self.assertEqual(self.store.listings(), [])
        self.assertEqual(self.store.notifications(), [])
