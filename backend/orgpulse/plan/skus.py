"""Workspace SKU -> edition/tier, and edition detection from licence counts.

Verify SKU ids against Google's "Products and SKUs" page
(https://developers.google.com/admin-sdk/licensing/v1/how-tos/products) when
editions change; unknown SKUs are kept in the breakdown and flagged.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

TIER_RANK = {"unknown": -1, "free": 0, "plus": 1, "enterprise": 2}


@dataclass(frozen=True)
class Sku:
    edition: str
    tier: str
    rank: int  # orders editions within the same tier (higher = bigger plan)


SKUS: dict[str, Sku] = {
    "1010020027": Sku("Business Starter", "free", 10),
    "1010020028": Sku("Business Standard", "free", 20),
    "1010020025": Sku("Business Plus", "plus", 30),
    "1010020026": Sku("Enterprise Standard", "enterprise", 40),
    "1010020020": Sku("Enterprise Plus", "enterprise", 50),
    "1010020030": Sku("Frontline Starter", "free", 5),
    "1010020031": Sku("Frontline Standard", "free", 6),
    "1010020034": Sku("Frontline Plus", "plus", 25),
    "1010060001": Sku("Essentials", "free", 1),
    "1010070001": Sku("Education Fundamentals", "free", 8),
    "1010310005": Sku("Education Standard", "enterprise", 35),
    "1010310008": Sku("Education Plus", "enterprise", 45),
}


@dataclass(frozen=True)
class PlanResult:
    edition: str
    tier: str
    breakdown: dict[str, Any]
    licences_assigned: int


def detect_edition(assignments: Iterable[dict[str, Any]]) -> PlanResult:
    """Edition = highest-tier SKU with at least one assignment. Mixed domains keep the breakdown."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for a in assignments:
        sku = str(a.get("skuId"))
        counts[sku] += 1
        if a.get("skuName"):
            names[sku] = str(a["skuName"])

    breakdown: dict[str, Any] = {}
    for sku, n in counts.most_common():
        known = SKUS.get(sku)
        breakdown[sku] = {
            "edition": known.edition if known else names.get(sku, "Unknown SKU"),
            "tier": known.tier if known else "unknown",
            "count": n,
            "known": known is not None,
        }

    known_skus = [SKUS[s] for s in counts if s in SKUS]
    if not known_skus:
        return PlanResult("Unknown", "unknown", breakdown, sum(counts.values()))
    top = max(known_skus, key=lambda k: (TIER_RANK[k.tier], k.rank))
    return PlanResult(top.edition, top.tier, breakdown, sum(counts.values()))


TIER_LABEL = {
    "free": "Free features",
    "plus": "Plus features",
    "enterprise": "Enterprise features",
    "unknown": "Edition unknown",
}
