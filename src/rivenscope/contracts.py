"""Read-only legacy WFM auction search, verified against a captured native response.

v1 is unsupported upstream. A search is always partial, never proof of removal.
Raw roll display context is not verified; valuation remains unavailable for it.
"""
from datetime import datetime
import re
from urllib.parse import urlencode

from .domain import Attribute, Listing, finite

SLUG = re.compile(r"[a-z0-9_()/ -]{1,200}")
IDENTITY = re.compile(r"[A-Za-z0-9_-]{1,100}")
PREFIX = "contracts:"


def contract_key(weapon):
    if not isinstance(weapon, str) or not SLUG.fullmatch(weapon):
        raise ValueError("Invalid weapon slug")
    return PREFIX + weapon


def contract_weapon(key):
    if not isinstance(key, str) or not key.startswith(PREFIX):
        raise ValueError("Invalid contract query")
    weapon = key[len(PREFIX):]
    contract_key(weapon)
    return weapon


def search_path(key):
    return "/v1/auctions/search?" + urlencode({"type": "riven", "weapon_url_name": contract_weapon(key)})


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing or invalid auction timestamp")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Auction timestamps must have a timezone")
        return finite(date.timestamp(), "Auction timestamp", 0)
    except (ValueError, OverflowError) as error:
        raise ValueError("Invalid auction timestamp") from error


def parse_auctions(payload, weapon, observed_at, weapons, attributes):
    """Validate the entire response before returning any canonical observations."""
    contract_key(weapon)
    finite(observed_at, "Observation time", 0)
    if weapon not in weapons or not attributes:
        raise ValueError("Sync the weapon and attribute catalogs before reading contracts")
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Invalid auction response envelope")
    envelope = payload.get("payload")
    rows = envelope.get("auctions") if isinstance(envelope, dict) else None
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Invalid or oversized auction collection")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid auction record")
        identity = row.get("id")
        if not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or identity in seen:
            raise ValueError("Invalid or duplicate auction ID")
        seen.add(identity)
        item, owner = row.get("item"), row.get("owner")
        if (not isinstance(item, dict) or item.get("type") != "riven"
                or item.get("weapon_url_name") != weapon or not isinstance(owner, dict)):
            raise ValueError("Unexpected auction type, weapon or owner")
        for key in ("is_direct_sell", "closed", "visible", "private"):
            if type(row.get(key)) is not bool:
                raise ValueError(f"Invalid auction flag: {key}")
        raw_attributes = item.get("attributes")
        if not isinstance(raw_attributes, list) or not 2 <= len(raw_attributes) <= 4:
            raise ValueError("Invalid rolled attributes")
        rolled = []
        for attribute in raw_attributes:
            if not isinstance(attribute, dict) or attribute.get("url_name") not in attributes:
                raise ValueError("Unknown auction attribute; refresh the catalog")
            rolled.append(Attribute(attribute["url_name"], attribute.get("value"), attribute.get("positive")))
        for key in ("starting_price", "buyout_price", "top_bid"):
            if row.get(key) is not None:
                finite(row[key], key, 0)
        direct, buyout = row["is_direct_sell"], row.get("buyout_price")
        if buyout is not None and buyout <= 0:
            raise ValueError("Buyout must be positive; a zero value is not a confirmed free purchase")
        seller_status = owner.get("status", "unknown")
        if seller_status not in ("ingame", "online", "offline", "unknown"):
            seller_status = "unknown"
        seller = owner.get("ingame_name")
        if not isinstance(seller, str) or not seller:
            raise ValueError("Missing seller name")
        crossplay = [o.get("crossplay") for o in (row, owner)]
        if any(v is not None and type(v) is not bool for v in crossplay):
            raise ValueError("Invalid auction crossplay flag")
        platform = owner.get("platform", "unknown")  # Auction market != seller platform.
        if not isinstance(platform, str) or len(platform) > 100:
            raise ValueError("Invalid seller platform")
        reputation = owner.get("reputation")
        if reputation is not None:
            finite(reputation, "Seller reputation")
        result.append(Listing(
            id=identity, weapon=weapon, category=weapons[weapon]["rivenType"], attributes=tuple(rolled),
            kind="direct" if direct else "auction_buyout" if buyout is not None else "auction",
            observed_at=observed_at, price=buyout if direct else None,
            starting_bid=row.get("starting_price"), highest_bid=row.get("top_bid"), buyout=buyout,
            rank=item.get("mod_rank"), mastery=item.get("mastery_level"), rerolls=item.get("re_rolls"),
            polarity=item.get("polarity"), disposition=None, measurement=None,
            seller=seller, seller_status=seller_status, platform=platform,
            crossplay=all(crossplay) if all(v is not None for v in crossplay) else None,
            reputation=reputation, url=f"https://warframe.market/auction/{identity}",
            published_at=timestamp(row.get("created")), updated_at=timestamp(row.get("updated")),
            status="closed" if row["closed"] or row["private"] or not row["visible"] else "active",
        ))
    return result
