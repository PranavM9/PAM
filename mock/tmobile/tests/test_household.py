"""Household Mix Optimizer: the M17 verdicts, coverage, and full enumeration."""

from __future__ import annotations

import copy
from itertools import product

import pytest


def optimize(client, customer_id, **extra):
    res = client.post("/recommend/household", json={"customer_id": customer_id, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def test_hale_saves_at_least_20(client):
    out = optimize(client, "cust-hale")
    assert out["data"]["verdict"] == "change"
    assert out["data"]["savings_monthly"] >= 20


def test_okafor_keeps_plan(client):
    out = optimize(client, "cust-okafor")
    assert out["data"]["verdict"] == "keep"
    assert out["data"]["best_savings_found"] < 5
    assert out["pam_cards"][0]["title"] == "Keep your plan"


@pytest.mark.parametrize("customer_id", ["cust-chen", "cust-rivera", "cust-okafor", "cust-northwind", "cust-hale"])
def test_every_line_is_covered(client, catalog, customer_id):
    household = pytest.importorskip("engine.household")
    out = optimize(client, customer_id)
    customer = catalog.customers[customer_id]
    for line, plan_id in zip(customer["lines"], out["data"]["best"]["plans"]):
        plan = catalog.plans[plan_id]
        peak = max(u["data_gb"] for u in line["usage"])
        hotspot = max(u["hotspot_gb"] for u in line["usage"])
        assert plan["premium_data_gb"] is None or plan["premium_data_gb"] >= peak
        assert plan["hotspot_gb"] >= hotspot
        assert household.covers(plan, line)


def test_enumeration_covers_every_combination(catalog):
    """A 2-line household with a known answer: Starter for the light line, Plus for the other."""
    household = pytest.importorskip("engine.household")
    base = catalog.customers["cust-hale"]
    two = copy.deepcopy(base)
    two["autopay"] = False
    two["services_elsewhere"] = []
    two["account_addons"] = []
    two["home_internet"] = None
    light, heavy = two["lines"]
    light["plan_id"] = heavy["plan_id"] = "max"
    for u in light["usage"]:
        u.update(data_gb=8.0, hotspot_gb=1.0, intl_days=0)
    for u in heavy["usage"]:
        u.update(data_gb=30.0, hotspot_gb=5.0, intl_days=0)
    heavy["person"]["student"] = False
    r = household.optimize(catalog, two)
    bundles = [a for a in catalog.addons.values() if a["kind"] == "bundle"]
    assert r["combinations_checked"] == len(catalog.plans) ** 2 * 2 ** len(bundles)
    assert r["best"]["plans"] == ["starter", "plus"]
    assert r["best"]["bundles"] == []
    # Brute force independently over plans only (bundles only add cost here).
    costs = {}
    for a, b in product(catalog.plans, repeat=2):
        if household.covers(catalog.plans[a], light) and household.covers(catalog.plans[b], heavy):
            costs[(a, b)] = catalog.plans[a]["price_per_line"][1] + catalog.plans[b]["price_per_line"][1]
    assert r["best"]["cost"]["total"] == min(costs.values())
    assert r["savings_monthly"] == 160 - min(costs.values())


def test_student_plan_needs_a_student(catalog):
    household = pytest.importorskip("engine.household")
    line = copy.deepcopy(catalog.customers["cust-chen"]["lines"][2])
    assert household.covers(catalog.plans["student"], line)
    line["person"]["student"] = False
    assert not household.covers(catalog.plans["student"], line)


def test_home_internet_option_is_considered(client):
    without = optimize(client, "cust-chen")["data"]
    with_internet = optimize(client, "cust-chen", include_home_internet=True)["data"]
    assert with_internet["combinations_checked"] == 2 * without["combinations_checked"]
    assert with_internet["best"]["carrier_internet"] is True


def test_changed_lines_are_explained(client):
    out = optimize(client, "cust-chen")
    changed = [l for l in out["data"]["lines"] if l["current_plan"] != l["suggested_plan"]]
    assert changed
    texts = " ".join(r["text"] for r in out["reasons"])
    for line in changed:
        assert line["name"] in texts
