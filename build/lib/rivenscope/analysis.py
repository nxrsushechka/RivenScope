"""Local observation pipeline for a future verified contract adapter.

This module performs no networking and does not activate an unavailable API source.
Canonical observations flow through persistence, valuation and notification decisions
as one application workflow; tests exercise it with explicitly controlled data.
"""
from dataclasses import replace
from .config import validate_settings
from .domain import finite
from .notifications import record_notification
from .valuation import estimate


class AnalysisEngine:
    def __init__(self, store):
        self.store = store

    def observe(self, listings, query_key, observed_at, *, complete=False, weapon=""):
        finite(observed_at, "Observation time", 0)
        listings = [replace(item, observed_at=observed_at) for item in listings]
        events = self.store.observe(listings, query_key, observed_at, complete, weapon)
        settings = self.store.settings()
        watchlists = [rule for rule in self.store.watchlists() if rule["enabled"]]
        candidates = {}
        results, messages = {}, []
        by_id = {item.id: item for item in listings}
        for event in events:
            item = by_id.get(event["listing_id"])
            if item is None or item.status != "active":
                continue
            if item.weapon not in candidates:
                candidates[item.weapon] = [row["listing"] for row in self.store.listings(limit=10000, weapon=item.weapon)]
            pool = candidates[item.weapon]
            global_result = estimate(item, pool, observed_at, settings["risk_profile"], settings["risk_thresholds"])
            self.store.save_estimate(item.id, global_result, observed_at)
            results[item.id] = global_result
            # An event can be eligible under several rules but is delivered at most once.
            rules = sorted(watchlists, key=lambda rule: -rule["priority"]) + [None]
            for rule in rules:
                if rule:
                    if rule["weapons"] and item.weapon not in rule["weapons"]:
                        continue
                    if rule["category"] and item.category != rule["category"]:
                        continue
                    rule_settings = validate_settings(settings | rule["settings"])
                    # Recompute with the rule's age/sample limits, not merely the global
                    # estimate's average age. Stale comparables cannot satisfy a stricter rule.
                    result = estimate(item, pool, observed_at, rule_settings["risk_profile"], rule_settings["risk_thresholds"])
                else:
                    result = global_result
                message = record_notification(self.store, event, item, result, settings, rule, observed_at)
                if message:
                    messages.append(message)
                    break
        return {"events": events, "estimates": results, "notifications": messages}
