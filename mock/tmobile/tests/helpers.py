"""Constants and helpers shared by the T-Mobile mock tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MOCK_TODAY = "2026-10-18"
MAYA = {"customer_id": "cust-chen", "line_id": "chen-maya", "monthly_budget": 40, "needs": "battery,camera"}

# One request per tool: (tool, method, path, JSON body or None).
TOOL_REQUESTS = [
    ("get_household", "GET", "/customers/cust-chen", None),
    ("search_devices", "GET", "/catalog/devices?query=camera", None),
    ("list_plans", "GET", "/catalog/plans?lines=4", None),
    ("tradein_value", "GET", "/tradein/kestrel-5", None),
    ("recommend_upgrade", "POST", "/recommend/upgrade", MAYA),
    ("optimize_household", "POST", "/recommend/household", {"customer_id": "cust-hale"}),
    ("suggest_addons", "POST", "/recommend/addons",
     {"customer_id": "cust-chen", "line_id": "chen-maya", "device_id": "aurora-fold"}),
]


def load(name: str) -> dict:
    """Read `data/<name>.json`, or skip when the data files do not exist yet."""
    path = DATA / f"{name}.json"
    if not path.exists():
        pytest.skip(f"mock/tmobile/data/{name}.json does not exist yet")
    return json.loads(path.read_text(encoding="utf-8"))


def call(client, method: str, path: str, body: dict | None):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body)


def load_tool(name: str):
    """Import `tools/<name>.py` by path, or skip when it does not exist yet."""
    path = ROOT / "tools" / f"{name}.py"
    if not path.exists():
        pytest.skip(f"mock/tmobile/tools/{name}.py does not exist yet")
    spec = importlib.util.spec_from_file_location(f"mock_tools_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
