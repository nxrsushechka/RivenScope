"""Explainable asking-price estimator. No third-party pricing or fabricated utility."""
import math
import statistics
from collections import OrderedDict
from .domain import Estimate, RISK_PROFILES


def weighted_quantile(pairs, quantile):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    target, count = total * quantile, 0
    for price, weight in pairs:
        count += weight
        if count >= target:
            return price
    return pairs[-1][0]


def check_cancelled(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("Valuation cancelled")


class PreparedComparables:
    """Immutable sample with bounded reuse of expensive roll-distance calculations.

    Seller/identity exclusions stay per target; cached distances never include
    those exclusions or a target's price. No candidates are approximated away.
    """
    def __init__(self, candidates, now, cancelled=None):
        self.now = now
        self.rows = []
        self.scores = OrderedDict()
        for candidate in sorted(candidates, key=lambda c: c.observed_at, reverse=True):
            check_cancelled(cancelled)
            self.rows.append((candidate, candidate.comparable_group,
                              {a.slug: a.value for a in candidate.attributes},
                              candidate.fingerprint, (now-candidate.observed_at)/3600))

    def scored(self, target, max_age, cancelled=None):
        attributes = {a.slug: a.value for a in target.attributes}
        target_group = target.comparable_group
        key = (target_group, tuple(sorted(attributes.items())), target.rerolls, max_age)
        if key in self.scores:
            self.scores.move_to_end(key)
            return self.scores[key]
        result = []
        for candidate, group, values, fingerprint, age in self.rows:
            check_cancelled(cancelled)
            if (candidate.kind != "direct" or not candidate.price or candidate.status != "active"
                    or group != target_group or not 0 <= age <= max_age):
                continue
            distance = statistics.mean(abs(attributes[s]-values[s]) / max(abs(attributes[s]), abs(values[s]), 1) for s in attributes)
            if distance > .25:
                continue
            similarity = math.exp(-4 * distance)
            if target.rerolls is not None and candidate.rerolls is not None:
                similarity *= 1 / (1 + abs(math.log1p(target.rerolls)-math.log1p(candidate.rerolls)) * .12)
            result.append((candidate, similarity * math.exp(-age/max(max_age, 1)), age, similarity, fingerprint))
        self.scores[key] = result
        if len(self.scores) > 8:
            self.scores.popitem(last=False)
        return result


def estimate(target, candidates, now, profile="Balanced", thresholds=None, cancelled=None):
    check_cancelled(cancelled)
    rules = dict(RISK_PROFILES[profile])
    if thresholds:
        rules.update(thresholds)
    result = Estimate()
    result.explanation = ["Comparable asking prices, not verified transactions or guaranteed resale proceeds."]
    if target.rank is None or not target.measurement or target.disposition is None or len(target.attributes) < 2:
        result.explanation.append("Known rank, disposition, measurement context and rolled attributes are required.")
        return result
    seen, sellers, selected = set(), set(), []
    pool = candidates if isinstance(candidates, PreparedComparables) else PreparedComparables(candidates, now, cancelled)
    if pool.now != now:
        raise ValueError("Prepared sample must use the current valuation time")
    for candidate, weight, age, similarity, fingerprint in pool.scored(target, rules["max_age_hours"], cancelled):
        check_cancelled(cancelled)
        if (candidate.id == target.id or (target.seller and candidate.seller == target.seller)
                or fingerprint in seen or (candidate.seller and candidate.seller in sellers)):
            continue
        seen.add(fingerprint)
        if candidate.seller: sellers.add(candidate.seller)
        selected.append((candidate, weight, age, similarity))
    result.sample_size = len(selected)
    minimum = max(5, rules["samples"])
    if len(selected) < minimum:
        result.explanation.append(f"Only {len(selected)} compatible independent listings; at least {minimum} required.")
        return result
    logs = [math.log(c.price) for c, *_ in selected]
    median = statistics.median(logs)
    mad = statistics.median(abs(x - median) for x in logs)
    cutoff = max(3.5 * 1.4826 * mad, math.log(1.5))
    clean = [row for row in selected if abs(math.log(row[0].price) - median) <= cutoff]
    result.sample_size = len(clean)
    if len(clean) < minimum:
        result.explanation.append("Insufficient sample after robust log-price outlier rejection.")
        return result
    weights = [row[1] for row in clean]
    effective = sum(weights) ** 2 / sum(w * w for w in weights)
    result.effective_sample = round(effective, 2)
    if effective < minimum * .75:
        result.explanation.append("Effective weighted sample is too small.")
        return result
    pairs = [(c.price, w) for c, w, *_ in clean]
    result.value = weighted_quantile(pairs, .5)
    result.low = weighted_quantile(pairs, .1)
    result.high = weighted_quantile(pairs, .9)
    result.freshness_hours = round(sum(w * age for _, w, age, _ in clean) / sum(weights), 2)
    spread = (result.high - result.low) / result.value
    similarity = sum(w * sim for _, w, _, sim in clean) / sum(weights)
    confidence = 92 * min(1, effective / 15) ** .5 * math.exp(-spread) * similarity
    confidence *= math.exp(-result.freshness_hours / (2 * rules["max_age_hours"]))
    result.confidence = round(min(confidence, 90), 1)
    result.comparable_ids = [c.id for c, *_ in clean]
    result.status = "Asking-price estimate"
    if target.acquisition is not None and result.value > 0:
        result.profit = round(result.value - target.acquisition, 2)
        result.discount = round(result.profit / result.value * 100, 2)
    result.risk = "Low" if result.confidence >= 75 else "Moderate" if result.confidence >= 60 else "High"
    if target.kind != "direct":
        result.risk = "High"
        result.explanation.append("Auction: final cost is uncertain; only an explicit buyout can be an acquisition option.")
    result.qualifies = (result.profit is not None and result.profit >= rules["profit"]
                        and result.discount >= rules["discount"] and result.confidence >= rules["confidence"]
                        and result.sample_size >= rules["samples"])
    result.explanation += [
        f"{len(clean)} same-weapon, same-rank, same-disposition, same signed-attribute-set comparables.",
        f"{len(selected) - len(clean)} log-MAD outliers rejected; effective sample {effective:.1f}.",
        "Weights: relative stat distance, observation age and log-reroll distance (heuristic).",
        "Negative utility is controlled by exact negative-attribute matching; no invented market premium.",
        "At most one comparable per known seller reduces correlated relists and seller concentration.",
        "Database sampling is capped at the 10,000 latest compatible asks, independent of the visible page.",
        "10th–90th weighted asking-price range is dispersion, not a statistical guarantee.",
        f"{profile} thresholds; risk {result.risk}. Fees, liquidity and eventual execution are unknown.",
    ]
    return result
