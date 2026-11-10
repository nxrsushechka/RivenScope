"""End-to-end LOCAL analytics workflow, not a live contract integration test."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from rivenscope.analysis import AnalysisEngine
from rivenscope.config import validate_settings
from rivenscope.storage import Store, new_watchlist
from .helpers import NOW, listing, comparables


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rivenscope-analysis-")
        self.store = Store(Path(self.temp.name) / "db.sqlite")
        self.engine = AnalysisEngine(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_baseline_then_new_deal_then_duplicate(self):
        baseline = self.engine.observe(comparables(), "query", NOW)
        self.assertEqual(baseline["notifications"], [])
        found = self.engine.observe([listing()], "query", NOW + 1)
        self.assertEqual(found["events"][0]["kind"], "new")
        self.assertEqual(len(found["notifications"]), 1)
        self.assertGreater(found["estimates"]["test-1"].value, 0)
        self.assertEqual(self.engine.observe([listing()], "query", NOW + 2)["notifications"], [])

    def test_per_preset_age_limit_recomputes_comparables(self):
        self.engine.observe(comparables(), "query", NOW - 48 * 3600)
        settings = validate_settings({"notify_new": False})
        self.store.save_settings(settings)
        rule = new_watchlist()
        rule["settings"] = {"notify_new": True, "risk_thresholds": settings["risk_thresholds"] | {"max_age_hours": 24}}
        self.store.save_watchlist(rule)
        found = self.engine.observe([listing()], "query", NOW)
        self.assertEqual(found["notifications"], [])
        self.assertIsNotNone(found["estimates"]["test-1"].value)  # global 72h pool exists

    def test_overlapping_rules_emit_once_and_closed_is_silent(self):
        self.engine.observe(comparables(), "query", NOW)
        for priority in (1, 10):
            rule = new_watchlist(); rule["priority"] = priority
            self.store.save_watchlist(rule)
        found = self.engine.observe([listing()], "query", NOW + 1)
        self.assertEqual(len(found["notifications"]), 1)
        self.assertEqual(len(self.store.notifications()), 1)
        found = self.engine.observe([listing("closed", status="closed")], "query", NOW + 2)
        self.assertEqual(found["notifications"], [])

    def test_changed_price_produces_a_new_event_not_a_duplicate(self):
        self.engine.observe(comparables() + [listing(price=1500)], "query", NOW)
        changed = self.engine.observe([listing(price=500)], "query", NOW + 1)
        self.assertEqual(changed["events"][0]["kind"], "price_changed")
        self.assertEqual(len(changed["notifications"]), 1)
        self.assertEqual(self.engine.observe([listing(price=500)], "query", NOW + 2)["notifications"], [])
