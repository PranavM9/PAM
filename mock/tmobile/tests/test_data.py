"""Synthetic data integrity: files, references, fictional names and the copy rules."""

from __future__ import annotations

import re

import pytest

from tests.helpers import DATA, ROOT, load

DENY = ["iphone", "galaxy", "pixel", "go5g", "magenta", "essentials"]
BRANDS = {"Aurora", "Lumen", "Kestrel", "Nimbus"}
PLANS = {"Starter", "Plus", "Max", "Student"}
HOUSEHOLDS = {"cust-chen": 4, "cust-rivera": 1, "cust-okafor": 5, "cust-northwind": 3, "cust-hale": 2}


def test_devices_shape():
    devices = load("devices")["devices"]
    current = [d for d in devices if d["status"] == "current"]
    older = [d for d in devices if d["status"] == "older"]
    assert len(current) == 12 and len(older) == 8
    assert {d["brand"] for d in devices} == BRANDS
    assert {d["form_factor"] for d in current} == {"budget", "mid", "flagship", "foldable"}
    for d in devices:
        assert 2 <= len(d["colours"]) <= 4
        assert len(d["highlights"]) == 3
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c["hex"]) for c in d["colours"])
        for tier in d["storage"]:
            assert tier["monthly_24"] == round(tier["full_price"] / 24, 2)


def test_plans_and_addons_shape():
    assert {p["name"] for p in load("plans")["plans"]} == PLANS
    for p in load("plans")["plans"]:
        assert len(p["price_per_line"]) == 5
    kinds = [a["icon"] for a in load("addons")["addons"]]
    for icon in ("shield", "case", "charger", "earbuds", "watch", "router", "play", "plane"):
        assert icon in kinds
    assert sum(a["kind"] == "bundle" for a in load("addons")["addons"]) == 2


def test_every_image_exists():
    paths = []
    for d in load("devices")["devices"]:
        paths += [c["image"] for c in d["colours"]]
    paths += [p["image"] for p in load("plans")["plans"]]
    paths += [a["image"] for a in load("addons")["addons"]]
    paths += [l["person"]["avatar"] for c in load("customers")["customers"] for l in c["lines"]]
    missing = [p for p in paths if not (ROOT / p).is_file()]
    assert not missing, missing


def test_households_and_references():
    customers = {c["id"]: c for c in load("customers")["customers"]}
    devices = {d["id"] for d in load("devices")["devices"]}
    plans = {p["id"] for p in load("plans")["plans"]}
    addons = {a["id"] for a in load("addons")["addons"]}
    assert {k: len(v["lines"]) for k, v in customers.items()} == HOUSEHOLDS
    for c in customers.values():
        assert c["owner_line_id"] in {l["id"] for l in c["lines"]}
        for line in c["lines"]:
            assert line["device_id"] in devices
            assert line["plan_id"] in plans
            assert len(line["usage"]) == 6
            assert 0 <= len(line["support_contacts"]) <= 3
            assert set(line["addons"]) <= addons
            assert {a["addon_id"] for a in line["accessories"]} <= addons


def test_maya_matches_the_story():
    chen = next(c for c in load("customers")["customers"] if c["id"] == "cust-chen")
    maya = next(l for l in chen["lines"] if l["person"]["first_name"] == "Maya")
    assert maya["device_id"] == "kestrel-5"
    assert maya["battery_health"] == 78
    assert maya["financing"]["months_left"] == 0
    assert round(sum(u["data_gb"] for u in maya["usage"]) / 6) == 38
    assert round(sum(u["hotspot_gb"] for u in maya["usage"]) / 6) == 6
    assert [h["amount"] for h in chen["bill_history"]][0] == 212
    assert [h["amount"] for h in chen["bill_history"]][-1] == 236


@pytest.mark.parametrize("name", ["devices", "plans", "addons", "tradein", "customers", "messages"])
def test_no_real_brand_or_plan_names(name):
    load(name)
    text = (DATA / f"{name}.json").read_text(encoding="utf-8").lower()
    for word in DENY:
        assert not re.search(rf"\b{word}\b", text), f"{word} in {name}.json"


def test_titles_are_ascii():
    for d in load("devices")["devices"]:
        assert d["name"].isascii() and all(c["name"].isascii() for c in d["colours"])
    for item in load("plans")["plans"] + load("addons")["addons"]:
        assert item["name"].isascii()
    messages = load("messages")
    for key, text in messages.items():
        if ".title." in key:
            assert text.isascii(), key


def test_messages_follow_the_copy_rules():
    messages = load("messages")
    raw = (DATA / "messages.json").read_text(encoding="utf-8")
    assert "!" not in raw
    for key, text in messages.items():
        assert text.isascii(), key
        assert not re.search(r"\b[A-Z]{4,}\b", text), f"capitals for emphasis in {key}"
        sentences = [s for s in re.split(r"(?<=[.?])\s+", text.strip()) if s]
        assert len(sentences) <= 2, key
        assert not re.search(r"\$\d+\.\d(?!\d)", text), f"money must use 2 decimals in {key}"
