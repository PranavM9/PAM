"""Every tool answers the M17 envelope with explained reasons and valid, badged cards."""

from __future__ import annotations

import pytest

from tests.chg0027 import ConnectorCard
from tests.helpers import MOCK_TODAY, TOOL_REQUESTS, call

BADGE = "Synthetic demo data"
CARD_KINDS = {
    "get_household": ["comparison"],
    "list_plans": ["plan"] * 4,
    "tradein_value": ["chart"],
    "optimize_household": ["verdict", "comparison"],
}
IDS = [t[0] for t in TOOL_REQUESTS]


@pytest.mark.parametrize("tool,method,path,body", TOOL_REQUESTS, ids=IDS)
def test_envelope_shape(client, tool, method, path, body):
    res = call(client, method, path, body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert list(out) == ["synthetic", "as_of", "data", "reasons", "pam_cards"]
    assert out["synthetic"] is True
    assert out["as_of"] == MOCK_TODAY
    assert out["data"] not in (None, {}, [])
    assert out["reasons"], f"{tool} returned no reasons"
    for r in out["reasons"]:
        assert set(r) == {"text", "signal", "value"}
        assert isinstance(r["text"], str) and r["text"].strip()
        assert isinstance(r["signal"], str) and r["signal"].strip()


@pytest.mark.parametrize("tool,method,path,body", TOOL_REQUESTS, ids=IDS)
def test_cards_validate_and_carry_badge(client, tool, method, path, body):
    cards = call(client, method, path, body).json()["pam_cards"]
    assert 1 <= len(cards) <= 6
    for raw in cards:
        card = ConnectorCard.model_validate(raw)
        assert BADGE in card.badges
        assert card.connector_id is None, "PAM sets connector_id, never the service"
        assert card.title.isascii()
        if card.image_url:
            assert card.image_url.startswith("/connectors/tmobile/images/")
    if tool in CARD_KINDS:
        assert [c["kind"] for c in cards] == CARD_KINDS[tool]


def test_upgrade_card_order(client):
    _, method, path, body = TOOL_REQUESTS[IDS.index("recommend_upgrade")]
    kinds = [c["kind"] for c in call(client, method, path, body).json()["pam_cards"]]
    assert kinds[:2] == ["verdict", "chart"]
    assert all(k == "product" for k in kinds[2:]) and len(kinds) <= 4


def test_search_cards_are_products(client):
    kinds = [c["kind"] for c in client.get("/catalog/devices?query=camera").json()["pam_cards"]]
    assert kinds and set(kinds) == {"product"}


def test_health(client):
    out = client.get("/health").json()
    assert out["status"] == "ok" and out["synthetic"] is True and out["as_of"] == MOCK_TODAY


def test_images_are_served(client):
    card = client.get("/catalog/devices?query=camera&limit=1").json()["pam_cards"][0]
    path = card["image_url"].removeprefix("/connectors/tmobile")
    res = client.get(path)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")


@pytest.mark.parametrize("method,path,body,status", [
    ("GET", "/customers/cust-nobody", None, 404),
    ("GET", "/tradein/no-such-phone", None, 404),
    ("POST", "/recommend/upgrade", {"customer_id": "cust-chen", "line_id": "chen-nobody"}, 404),
    ("POST", "/recommend/upgrade", {"customer_id": "cust-chen"}, 400),
    ("POST", "/recommend/upgrade", {**{"customer_id": "cust-chen", "line_id": "chen-maya"}, "needs": "jetpack"}, 400),
    ("GET", "/catalog/plans?lines=9", None, 400),
    ("GET", "/catalog/devices?form_factor=tablet", None, 400),
])
def test_errors_use_error_envelope(client, method, path, body, status):
    res = call(client, method, path, body)
    assert res.status_code == status
    out = res.json()
    assert out["synthetic"] is True and out["as_of"] == MOCK_TODAY
    assert set(out["error"]) == {"code", "message"}


def test_query_numbers_may_arrive_as_floats(client):
    """T17 sends `number` parameters through the query string, possibly as `3.0`."""
    out = client.get("/catalog/devices?query=camera&limit=2.0&max_monthly=40.0").json()
    assert len(out["pam_cards"]) == 2
    assert client.get("/tradein/kestrel-5?months_ahead=6.0").status_code == 200
