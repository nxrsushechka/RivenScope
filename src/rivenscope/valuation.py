"""Explainable asking-price estimator. No third-party pricing or fabricated utility."""
import math
import statistics
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


def estimate(target, candidates, now, profile="Balanced", thresholds=None):
    rules = dict(RISK_PROFILES[profile])
    if thresholds:
        rules.update(thresholds)
    result = Estimate()
    result.explanation = ["Comparable asking prices, not verified transactions or guaranteed resale proceeds."]
    if target.rank is None or not target.measurement or target.disposition is None or len(target.attributes) < 2:
        result.explanation.append("Known rank, disposition, measurement context and rolled attributes are required.")
        return result
    seen, sellers, selected = set(), set(), []
    for candidate in sorted(candidates, key=lambda c: c.observed_at, reverse=True):
        if (candidate.id == target.id or candidate.kind != "direct" or not candidate.price or candidate.status != "active"
                or candidate.weapon != target.weapon or candidate.category != target.category
                or candidate.signature != target.signature or candidate.rank != target.rank
                or candidate.measurement != target.measurement or candidate.disposition != target.disposition
                or (target.seller and candidate.seller == target.seller)):
            continue
        age = (now - candidate.observed_at) / 3600
        if age < 0 or age > rules["max_age_hours"] or candidate.fingerprint in seen or (candidate.seller and candidate.seller in sellers):
            continue
        a = {v.slug: v.value for v in target.attributes}
        b = {v.slug: v.value for v in candidate.attributes}
        distance = statistics.mean(abs(a[s] - b[s]) / max(abs(a[s]), abs(b[s]), 1) for s in a)
        if distance > .25:
            continue
        seen.add(candidate.fingerprint)
        if candidate.seller: sellers.add(candidate.seller)
        similarity = math.exp(-4 * distance)
        # Reroll distance is a disclosed similarity heuristic, not a price premium.
        if target.rerolls is not None and candidate.rerolls is not None:
            similarity *= 1 / (1 + abs(math.log1p(target.rerolls) - math.log1p(candidate.rerolls)) * .12)
        weight = similarity * math.exp(-age / max(rules["max_age_hours"], 1))
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
        "10th–90th weighted asking-price range is dispersion, not a statistical guarantee.",
        f"{profile} thresholds; risk {result.risk}. Fees, liquidity and eventual execution are unknown.",
    ]
    return result
