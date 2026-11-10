"""Local domain schema. This is NOT an undocumented WFM response parser."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from urllib.parse import urlsplit

MARKET_PAGE_SIZE = 250


def finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def safe_market_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "warframe.market" and p.port in (None, 443)
                and not p.username and not p.password and "\\" not in value)
    except ValueError:
        return False


@dataclass(frozen=True)
class Attribute:
    slug: str
    value: float
    positive: bool

    def __post_init__(self):
        if not isinstance(self.slug, str) or not self.slug or len(self.slug) > 120:
            raise ValueError("Invalid attribute slug")
        finite(self.value, "Attribute value")
        if type(self.positive) is not bool:
            raise ValueError("Attribute sign must be explicit")


@dataclass(frozen=True)
class Listing:
    id: str
    weapon: str
    category: str
    attributes: tuple[Attribute, ...]
    kind: str  # direct, auction, auction_buyout
    observed_at: float
    price: float | None = None
    starting_bid: float | None = None
    highest_bid: float | None = None
    buyout: float | None = None
    rank: int | None = None
    mastery: int | None = None
    rerolls: int | None = None
    polarity: str | None = None
    disposition: float | None = None
    measurement: str | None = None  # exact same known display context required for comparisons
    seller: str = ""
    seller_status: str = "unknown"
    platform: str = "unknown"
    crossplay: bool | None = None
    reputation: int | None = None
    url: str = ""
    published_at: float | None = None
    updated_at: float | None = None
    status: str = "active"
    source: str = "warframe.market"

    def __post_init__(self):
        for name in ("id", "weapon", "category", "seller", "measurement", "polarity"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > 300):
                raise ValueError(f"Invalid {name}")
        if not self.id or not self.weapon or self.source != "warframe.market":
            raise ValueError("A WFM identity and weapon are required")
        if self.kind not in {"direct", "auction", "auction_buyout"}:
            raise ValueError("Unknown listing type")
        if self.seller_status not in {"ingame", "online", "offline", "unknown"}:
            raise ValueError("Unknown seller status")
        if self.status not in {"active", "potentially_missing", "closed"}:
            raise ValueError("Unknown listing state")
        for name in ("price", "starting_bid", "highest_bid", "buyout", "observed_at", "published_at", "updated_at", "disposition"):
            if getattr(self, name) is not None:
                finite(getattr(self, name), name, 0)
        for name, maximum in (("rank", 8), ("mastery", 40), ("rerolls", 1000000)):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value <= maximum):
                raise ValueError(f"Invalid {name}")
        if self.crossplay is not None and type(self.crossplay) is not bool:
            raise ValueError("Invalid crossplay flag")
        if self.url and not safe_market_url(self.url):
            raise ValueError("Listing URL must be on https://warframe.market")
        if len(self.attributes) > 4 or len({a.slug for a in self.attributes}) != len(self.attributes):
            raise ValueError("Invalid or duplicate attributes")

    @property
    def acquisition(self):
        return self.price if self.kind == "direct" else self.buyout if self.kind == "auction_buyout" else None

    @property
    def signature(self):
        return tuple(sorted((a.slug, a.positive) for a in self.attributes))

    @property
    def comparable_group(self):
        return (self.weapon, self.category, self.rank, self.disposition, self.measurement, self.signature)

    @property
    def fingerprint(self):
        # Advisory identity: includes seller, exact roll and rank. Never asserts a sale.
        value = [self.seller, self.weapon, self.rank, self.rerolls,
                 sorted((a.slug, a.value, a.positive) for a in self.attributes)]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Observation must be an object")
        data = dict(data)
        try:
            data["attributes"] = tuple(Attribute(**a) for a in data["attributes"])
            return cls(**data)
        except (TypeError, KeyError) as error:
            raise ValueError("Invalid local observation schema") from error


@dataclass
class Estimate:
    status: str = "Insufficient data"
    value: float | None = None
    low: float | None = None
    high: float | None = None
    profit: float | None = None
    discount: float | None = None
    confidence: float = 0
    sample_size: int = 0
    effective_sample: float = 0
    freshness_hours: float | None = None
    comparable_ids: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    risk: str = "High"
    qualifies: bool = False


RISK_PROFILES = {
    "Conservative": {"discount": 30, "profit": 150, "confidence": 75, "samples": 12, "max_age_hours": 24},
    "Balanced": {"discount": 20, "profit": 75, "confidence": 60, "samples": 8, "max_age_hours": 72},
    "Aggressive": {"discount": 10, "profit": 25, "confidence": 40, "samples": 5, "max_age_hours": 168},
}
