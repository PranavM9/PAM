"""Timekeeper: Maya's verdict, the honest no-change option, and explained scores."""

from __future__ import annotations

import pytest

from tests.helpers import MAYA


@pytest.fixture(scope="module")
def maya(client):
    return client.post("/recommend/upgrade", json=MAYA).json()


def test_maya_waits_or_replaces_battery(maya):
    assert maya["data"]["verdict"] in ("replace_battery", "wait_3_months")
    assert maya["data"]["verdict"] != "upgrade_now"


def test_maya_reasons_cite_battery_and_tradein_curve(maya):
    signals = {r["signal"] for r in maya["reasons"]}
    assert "line.device.battery_health" in signals
    assert "tradein.curve" in signals
    battery = next(r for r in maya["reasons"] if r["signal"] == "line.device.battery_health")
    assert battery["value"] == 78


def test_no_change_is_always_scored_and_listed(client, maya):
    def no_change(out):
        found = [o for o in out["data"]["options"] if o["id"] == "no_change"]
        assert len(found) == 1
        assert found[0]["eligible"] is True and isinstance(found[0]["score"], float)
        return found[0]

    no_change(maya)
    for line in ("chen-mei", "chen-david", "chen-leo"):
        no_change(client.post("/recommend/upgrade", json={"customer_id": "cust-chen", "line_id": line}).json())


def test_winner_has_lowest_score_and_every_option_is_explained(maya):
    options = maya["data"]["options"]
    scored = [o for o in options if o["eligible"]]
    winner = next(o for o in options if o["id"] == maya["data"]["verdict"])
    assert winner["score"] == min(o["score"] for o in scored)
    for o in options:
        assert o["reasons"], f"{o['id']} has no reasons"
        if o["eligible"]:
            assert set(o["money"]) == {"monthly_now", "monthly_after", "once", "total_24m"}


def test_option_ids(maya):
    assert [o["id"] for o in maya["data"]["options"]] == [
        "no_change", "replace_battery", "upgrade_now", "wait_3_months", "wait_6_months"]


def test_verdict_card_names_the_winner(maya):
    verdict = maya["pam_cards"][0]
    assert verdict["kind"] == "verdict"
    assert verdict["title"] == maya["data"]["verdict_label"]


def test_budget_is_respected(maya):
    for o in maya["data"]["options"]:
        if o["eligible"] and o["device_id"]:
            assert o["money"]["monthly_after"] - o["money"]["monthly_now"] <= 40


def test_healthy_phone_without_needs_keeps_phone(client):
    out = client.post("/recommend/upgrade", json={"customer_id": "cust-chen", "line_id": "chen-mei"}).json()
    assert out["data"]["verdict"] == "no_change"


def test_phone_without_updates_is_not_offered_a_battery(client):
    out = client.post("/recommend/upgrade", json={"customer_id": "cust-chen", "line_id": "chen-david"}).json()
    battery = next(o for o in out["data"]["options"] if o["id"] == "replace_battery")
    assert battery["eligible"] is False
    assert "updates" in out["data"]["issues"]


def test_parse_needs():
    upgrade = pytest.importorskip("engine.upgrade", reason="mock/tmobile/engine does not exist yet")
    assert upgrade.parse_needs("camera, battery,camera") == ["camera", "battery"]
    assert upgrade.parse_needs(None) == []
    with pytest.raises(ValueError):
        upgrade.parse_needs("camera,jetpack")
