"""`connector.yaml` matches T19 step 6, validates as a CHG-0027 `Connector`, and works the way T17 calls it."""

from __future__ import annotations

import re
from urllib.parse import quote

import pytest

from tests.chg0027 import Connector
from tests.helpers import ROOT

TOOLS = ["get_household", "search_devices", "list_plans", "tradein_value", "recommend_upgrade",
         "optimize_household", "suggest_addons"]
# Arguments typed the way a model sends them through T17 (numbers may be floats).
SAMPLE_ARGS = {
    "get_household": {"customer_id": "cust-chen"},
    "search_devices": {"query": "camera", "max_monthly": 45.0, "form_factor": "flagship", "limit": 2.0},
    "list_plans": {"lines": 4.0},
    "tradein_value": {"device_id": "kestrel-5", "months_ahead": 6.0},
    "recommend_upgrade": {"customer_id": "cust-chen", "line_id": "chen-maya", "monthly_budget": 40.0,
                          "needs": "battery,camera"},
    "optimize_household": {"customer_id": "cust-chen", "include_home_internet": True},
    "suggest_addons": {"customer_id": "cust-chen", "line_id": "chen-maya", "device_id": "aurora-fold"},
}
PY_TYPES = {"string": str, "number": (int, float), "boolean": bool}


@pytest.fixture(scope="module")
def connector():
    yaml = pytest.importorskip("yaml", reason="PyYAML is not installed")
    path = ROOT / "connector.yaml"
    if not path.exists():
        pytest.skip("mock/tmobile/connector.yaml does not exist yet")
    return Connector.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_fields_from_t19_step_6(connector):
    assert connector.id == "tmobile"
    assert connector.name == "T-Mobile (synthetic)"
    assert connector.base_url == "http://tmobile-mock:8100"
    assert connector.public_base_url == "/connectors/tmobile"
    assert connector.auth.type == "none"
    assert connector.agents == ["tmobile-advisor"]
    assert connector.enabled and not connector.archived
    assert [t.name for t in connector.tools] == TOOLS


def test_tool_names_fit_the_m16_schema(connector):
    for tool in connector.tools:
        full = f"{connector.id}__{tool.name}"
        assert len(full) <= 64 and re.fullmatch(r"[a-z0-9_-]+", full)
        placeholders = set(re.findall(r"{(\w+)}", tool.path))
        declared = {p.name for p in tool.params}
        assert placeholders <= {p.name for p in tool.params if p.required}
        assert len(declared) == len(tool.params)


def test_sample_args_match_declared_types(connector):
    for tool in connector.tools:
        params = {p.name: p for p in tool.params}
        args = SAMPLE_ARGS[tool.name]
        assert set(args) <= set(params), tool.name
        assert {p.name for p in tool.params if p.required} <= set(args), tool.name
        for name, value in args.items():
            assert isinstance(value, PY_TYPES[params[name].type]), (tool.name, name)


def test_every_tool_answers_when_called_like_t17(client, connector):
    """Fill `{placeholders}` URL-encoded, then GET args go to the query string and POST args to a JSON body."""
    for tool in connector.tools:
        args = dict(SAMPLE_ARGS[tool.name])
        path = tool.path
        for name in re.findall(r"{(\w+)}", tool.path):
            path = path.replace("{" + name + "}", quote(str(args.pop(name)), safe=""))
        if tool.method == "GET":
            res = client.get(path, params=args)
        else:
            res = client.post(path, json=args)
        assert res.status_code == 200, (tool.name, res.text)
        out = res.json()
        assert out["synthetic"] is True and out["pam_cards"], tool.name


def test_every_tool_maps_to_a_route(client, connector):
    routes = {(m, r.path) for r in client.app.routes for m in getattr(r, "methods", ()) or ()}
    for tool in connector.tools:
        assert (tool.method, tool.path) in routes, tool.name
