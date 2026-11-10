import json
from pathlib import Path
from dataclasses import replace
import unittest
from rivenscope.domain import Attribute, Listing, safe_market_url
from rivenscope.filters import validate, matches, evaluate, server_plan
from rivenscope.network import parse_manifest, decode_response, Outcome
from rivenscope.valuation import estimate, weighted_quantile, PreparedComparables
from rivenscope.scheduler import Budget, FairQueue, retry_seconds
from rivenscope.config import validate_settings
from .helpers import NOW, listing, comparables

FIXTURES = Path(__file__).parent / "fixtures/live"


class ParsingTests(unittest.TestCase):
    def test_recorded_verified_manifest(self):
        for key, count in (("weapons", 420), ("attributes", 50)):
            raw = (FIXTURES / (key + ".json")).read_bytes()
            self.assertEqual(len(decode_response(Outcome(key, 200, raw))), count)
        data = parse_manifest(json.loads((FIXTURES / "versions.json").read_text()), "versions")
        self.assertIn("rivens", data["collections"])

    def test_errors_and_wrong_schema(self):
        for outcome in (Outcome("weapons", 429), Outcome("weapons", 0, error="Timeout"), Outcome("weapons", 200, b"<html>")):
            with self.assertRaises(ValueError): decode_response(outcome)
        with self.assertRaises(ValueError): parse_manifest({"data": [{"id": "ordinary-order"}], "error": None}, "weapons")
        with self.assertRaises(ValueError): parse_manifest({"data": [], "error": None}, "weapons")

    def test_duplicate_manifest_rejected(self):
        item = json.loads((FIXTURES / "weapons.json").read_text())["data"][0]
        with self.assertRaises(ValueError): parse_manifest({"data": [item, item]}, "weapons")

    def test_remote_display_fields_are_validated(self):
        item = json.loads((FIXTURES / "weapons.json").read_text())["data"][0]
        for changes in ({"rivenType": []}, {"reqMasteryRank": True}, {"i18n": {"en": {"name": ["bad"]}}}):
            with self.assertRaises(ValueError): parse_manifest({"data": [item | changes]}, "weapons")

    def test_domain_rejects_bad_values(self):
        for value in (float("nan"), float("inf"), -1, True):
            with self.assertRaises(ValueError): listing(price=value)
        with self.assertRaises(ValueError): listing(rank=9)
        with self.assertRaises(ValueError): listing(attributes=(Attribute("a", 1, True), Attribute("a", 2, True)))

    def test_urls(self):
        self.assertTrue(safe_market_url("https://warframe.market/auctions"))
        for url in ("https://warframe.market.evil/a", "file:///tmp/x", "javascript:1", "https://evil@warframe.market/a", "https://warframe.market:12", "https://warframe.market\\@evil"):
            self.assertFalse(safe_market_url(url))


class FilterTests(unittest.TestCase):
    def test_nested_example(self):
        ast = {"op": "AND", "children": [
            {"field": "weapon", "op": "eq", "value": "torid"},
            {"field": "positive.critical_damage", "op": "gt", "value": 100},
            {"field": "positive.multishot", "op": "exists"},
            {"op": "OR", "children": [{"field": "negative.zoom", "op": "exists"}, {"field": "negative_count", "op": "eq", "value": 0}]},
            {"field": "price", "op": "le", "value": 1500}]}
        validate(ast)
        self.assertTrue(matches(ast, listing()))
        self.assertFalse(matches(ast, listing(price=2000)))
        self.assertFalse(server_plan(ast)["available"])

    def test_unknown_not_does_not_match(self):
        expression = {"op": "NOT", "children": [{"field": "polarity", "op": "eq", "value": "madurai"}]}
        validate(expression)
        self.assertIsNone(evaluate(expression, listing()))
        self.assertFalse(matches(expression, listing()))
        self.assertTrue(matches({"field": "polarity", "op": "absent"}, listing()))

    def test_sign_not_numeric_sign(self):
        item = listing(attributes=(Attribute("recoil", -10, True),))
        self.assertTrue(matches({"field": "positive.recoil", "op": "exists"}, item))
        self.assertFalse(matches({"field": "negative.recoil", "op": "exists"}, item))

    def test_restrictions_and_invalid_ast(self):
        attrs = {v["slug"]: v for v in json.loads((FIXTURES / "attributes.json").read_text())["data"]}
        with self.assertRaises(ValueError): validate({"field": "negative.punch_through", "op": "exists"}, attrs, "rifle")
        with self.assertRaises(ValueError): validate({"field": "positive.punch_through", "op": "exists"}, attrs, "melee")
        for ast in ({"op": "NOT", "children": []}, {"op": "OR", "children": []}, {"field": "price", "op": "eq", "value": "bad"}, {"field": "__class__", "op": "exists"}):
            with self.assertRaises(ValueError): validate(ast)
        ast = {"op": "AND", "children": []}
        for _ in range(14): ast = {"op": "NOT", "children": [ast]}
        with self.assertRaises(ValueError): validate(ast)

    def test_all_comparisons(self):
        for op, value in (("eq", 500), ("ne", 1), ("gt", 499), ("ge", 500), ("lt", 501), ("le", 500), ("in", [500, 700])):
            ast = {"field": "price", "op": op, "value": value}
            validate(ast); self.assertTrue(matches(ast, listing()))


class ValuationTests(unittest.TestCase):
    def test_prepared_sample_keeps_target_exclusions_and_thresholds_separate(self):
        items=comparables()
        pool=PreparedComparables(items,NOW)
        first=estimate(listing(seller=items[0].seller),pool,NOW)
        second=estimate(listing(seller=items[1].seller),pool,NOW)
        self.assertEqual(first.sample_size,19)
        self.assertNotIn(items[0].id,first.comparable_ids)
        self.assertIn(items[0].id,second.comparable_ids)
        self.assertNotIn(items[1].id,second.comparable_ids)
        cheaper=estimate(listing(price=100,seller=items[0].seller),pool,NOW)
        self.assertEqual(cheaper.value,first.value)
        self.assertEqual(cheaper.profit,first.profit+400)
        stale=PreparedComparables([replace(c,observed_at=NOW-48*3600) for c in items],NOW)
        self.assertIsNotNone(estimate(listing(),stale,NOW,"Balanced").value)
        self.assertIsNone(estimate(listing(),stale,NOW,"Conservative").value)
        with self.assertRaises(ValueError): estimate(listing(),pool,NOW+1)

    def test_expensive_valuation_can_be_cancelled(self):
        with self.assertRaises(InterruptedError):
            estimate(listing(),comparables(),NOW,cancelled=lambda:True)

    def test_estimate_formulas_and_explanation(self):
        result = estimate(listing(), comparables(), NOW)
        self.assertEqual(result.value, 1000)
        self.assertEqual(result.profit, 500)
        self.assertEqual(result.discount, 50)
        self.assertTrue(result.qualifies)
        self.assertLessEqual(result.confidence, 90)
        self.assertLessEqual(result.low, result.value)
        self.assertGreaterEqual(result.high, result.value)
        self.assertGreater(len(result.explanation), 3)

    def test_insufficient_unknown_context_and_zero(self):
        for target, sample in ((listing(), []), (listing(rank=None), comparables()), (listing(measurement=None), comparables()), (listing(), [replace(c, price=0) for c in comparables()])):
            result = estimate(target, sample, NOW)
            self.assertIsNone(result.value); self.assertEqual(result.status, "Insufficient data")

    def test_no_cross_context_or_unlike_stat_comparison(self):
        for change in ({"rank": 0}, {"disposition": 1.2}, {"weapon": "soma"}, {"attributes": (Attribute("damage", 200, True),)}, {"observed_at": NOW - 400 * 3600}):
            result = estimate(listing(), [replace(c, **change) for c in comparables()], NOW)
            self.assertIsNone(result.value)

    def test_auction_bids_never_enter_prices(self):
        candidates = [replace(c, kind="auction", starting_bid=1, highest_bid=2) for c in comparables()]
        self.assertIsNone(estimate(listing(), candidates, NOW).value)
        result = estimate(listing(kind="auction", starting_bid=1), comparables(), NOW)
        self.assertIsNotNone(result.value); self.assertIsNone(result.profit); self.assertFalse(result.qualifies)
        self.assertIsNone(evaluate({"field": "price", "op": "lt", "value": 100}, listing(kind="auction", starting_bid=1)))
        result = estimate(listing(kind="auction_buyout", buyout=600), comparables(), NOW)
        self.assertEqual(result.profit, 400); self.assertEqual(result.risk, "High")

    def test_outlier_and_repost_dedup(self):
        sample = comparables() + [listing("outlier", 900000)]
        result = estimate(listing(), sample, NOW)
        self.assertEqual(result.value, 1000); self.assertNotIn("outlier", result.comparable_ids)
        base = comparables()[0]
        clones = [replace(base, id=f"repost-{i}") for i in range(20)]
        self.assertIsNone(estimate(listing(), clones, NOW).value)

    def test_weighted_quantile(self):
        self.assertIsNone(weighted_quantile([], .5))
        self.assertEqual(weighted_quantile([(10, 1), (100, 5)], .5), 100)


class SchedulerCoreTests(unittest.TestCase):
    def test_shared_budget_never_exceeds_ten_per_minute(self):
        budget = Budget()
        starts = []
        for tenth in range(36000):
            now = tenth / 10
            if budget.ready_at(now) <= now:
                budget.start(now); starts.append(now)
        for now in starts:
            self.assertLessEqual(sum(now-60 < value <= now for value in starts), 10)
        with self.assertRaises(ValueError): budget.start(starts[-1])

    def test_retry_after_and_persistent_block(self):
        b = Budget(); b.failure(NOW, 429, "120", rng=lambda: 0)
        self.assertEqual(b.cooldown, NOW + 120)
        b.failure(NOW, 403, rng=lambda: 0)
        other = Budget(); other.restore(b.snapshot(), NOW)
        self.assertGreaterEqual(other.ready_at(NOW), NOW + 900)
        self.assertEqual(retry_seconds("Mon, 09 Nov 2026 16:00:00 GMT", 0), 1794240000)

    def test_fairness_priority_and_coalescing(self):
        q = FairQueue(); q.add("low", 1, 0); q.add("high", 10, 0)
        q.add("high", 5, 0, "second")
        self.assertEqual(len(q.jobs), 2)
        self.assertEqual(q.pop(0).key, "high")
        for second in range(1, 61):
            q.add("high", 10, second)
            job = q.pop(second)
            if job.key == "low": break
        else: self.fail("Low-priority job starved")

    def test_settings_validation(self):
        self.assertEqual(validate_settings({})["risk_profile"], "Balanced")
        for settings in ({"catalog_interval_minutes": 1}, {"desktop": "yes"}, {"risk_profile": "Guaranteed"}, {"unknown": True}):
            with self.assertRaises(ValueError): validate_settings(settings)
