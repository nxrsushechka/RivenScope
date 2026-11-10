"""Explicit synthetic fixtures for local engines only. Never loaded by production."""
from dataclasses import replace
from rivenscope.domain import Listing, Attribute

NOW = 1794240000.0


def listing(id_="test-1", price=500, **kwargs):
    values = dict(id=id_, weapon="torid", category="rifle",
                  attributes=(Attribute("critical_damage", 120, True), Attribute("multishot", 80, True), Attribute("zoom", -30, False)),
                  kind="direct", observed_at=NOW, price=price, rank=8, mastery=16,
                  rerolls=20, disposition=1.3, measurement="mods_console", seller="TestSeller-" + id_,
                  seller_status="ingame", platform="pc", crossplay=True)
    return Listing(**(values | kwargs))


def comparables(n=20):
    return [listing(f"comp-{i}", 1000 + (i % 5 - 2) * 20) for i in range(n)]
