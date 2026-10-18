"""Catalog search filters and trade-in curves."""

from __future__ import annotations

import pytest

from tests.helpers import load


def search(client, query: str):
    res = client.get("/catalog/devices" + query)
    assert res.status_code == 200, res.text
    return res.json()


def test_search_respects_max_monthly(client, catalog):
    out = search(client, "?max_monthly=25&limit=6")
    assert out["data"]["devices"]
    for d in out["data"]["devices"]:
        assert catalog.devices[d["id"]]["storage"][0]["monthly_24"] <= 25


def test_search_respects_form_factor(client):
    out = search(client, "?form_factor=foldable&limit=6")
    assert {d["form_factor"] for d in out["data"]["devices"]} == {"foldable"}
    assert len(out["data"]["devices"]) == 3


def test_search_respects_limit(client):
    assert len(search(client, "")["pam_cards"]) == 3
    assert len(search(client, "?limit=1")["pam_cards"]) == 1
    assert len(search(client, "?limit=5")["pam_cards"]) == 5


def test_search_only_returns_devices_on_sale(client, catalog):
    out = search(client, "?limit=6&query=kestrel")
    assert out["data"]["devices"]
    assert all(catalog.devices[d["id"]]["status"] == "current" for d in out["data"]["devices"])


def test_search_camera_ranks_camera_phones_first(client, catalog):
    out = search(client, "?query=camera")
    assert all(catalog.devices[d["id"]]["scores"]["camera"] == 5 for d in out["data"]["devices"])


def test_tradein_returns_chart_with_marker(client):
    out = client.get("/tradein/kestrel-5").json()
    card = out["pam_cards"][0]
    assert card["kind"] == "chart"
    assert card["chart"]["marker_x"] == 0
    xs = [p[0] for p in card["chart"]["series"][0]["points"]]
    assert xs[0] < 0 < xs[-1] and xs[-1] == 12
    assert out["data"]["value_now"] == dict(card["chart"]["series"][0]["points"])[0]
    assert "tradein.curve" in {r["signal"] for r in out["reasons"]}


def test_tradein_months_ahead(client):
    out = client.get("/tradein/kestrel-5?months_ahead=6").json()
    assert out["pam_cards"][0]["chart"]["series"][0]["points"][-1][0] == 6
    assert client.get("/tradein/kestrel-5?months_ahead=99").status_code == 400


def test_curves_never_increase():
    tradein = load("tradein")
    devices = {d["id"] for d in load("devices")["devices"]}
    assert {c["device_id"] for c in tradein["curves"]} == devices
    for curve in tradein["curves"]:
        values = curve["values"]
        assert len(values) == 36
        assert all(b <= a for a, b in zip(values, values[1:])), curve["device_id"]
        assert values[-1] > 0


def test_three_promotions_with_end_dates():
    promos = load("tradein")["promotions"]
    assert len(promos) == 3
    for p in promos:
        assert p["end_date"] >= p["start_date"]


def test_plans_priced_for_line_count(client):
    one = client.get("/catalog/plans?lines=1").json()["data"]["plans"]
    four = client.get("/catalog/plans?lines=4").json()["data"]["plans"]
    for a, b in zip(one, four):
        assert b["per_line"] < a["per_line"]
        assert b["total"] == pytest.approx(b["per_line"] * 4)
