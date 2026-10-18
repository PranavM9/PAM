"""Cart Whisperer: protection for foldables, at most 3 items, and an honest "nothing else needed"."""

from __future__ import annotations


def addons(client, customer_id, line_id, device_id):
    res = client.post("/recommend/addons", json={"customer_id": customer_id, "line_id": line_id,
                                                 "device_id": device_id})
    assert res.status_code == 200, res.text
    return res.json()


def test_line_with_everything_gets_one_notice(client):
    out = addons(client, "cust-okafor", "okafor-ada", "aurora-one-pro")
    assert out["data"]["suggestions"] == []
    assert len(out["pam_cards"]) == 1
    card = out["pam_cards"][0]
    assert card["kind"] == "notice"
    assert "nothing else needed" in card["title"].lower()


def test_foldable_gets_protection(client):
    for device_id in ("aurora-fold", "lumen-flip", "nimbus-fold"):
        out = addons(client, "cust-chen", "chen-maya", device_id)
        assert "protection" in [s["addon_id"] for s in out["data"]["suggestions"]]
        signals = {r["signal"] for r in out["reasons"]}
        assert "device.form_factor" in signals


def test_at_most_three_suggestions(client, catalog):
    for customer in catalog.customers.values():
        for line in customer["lines"]:
            for device_id in ("aurora-fold", line["device_id"]):
                out = addons(client, customer["id"], line["id"], device_id)
                assert len(out["data"]["suggestions"]) <= 3
                assert len(out["pam_cards"]) <= 3
                assert all(c["kind"] == "product" for c in out["pam_cards"]) or out["pam_cards"][0]["kind"] == "notice"


def test_every_suggestion_has_a_reason(client):
    out = addons(client, "cust-chen", "chen-mei", "aurora-fold")
    for card in out["pam_cards"]:
        assert card["reasons"]
    assert len(out["reasons"]) == len(out["data"]["suggestions"])
