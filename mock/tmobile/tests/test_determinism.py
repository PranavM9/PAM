"""The same request returns the same bytes, for every tool."""

from __future__ import annotations

import pytest

from tests.helpers import TOOL_REQUESTS, call


@pytest.mark.parametrize("tool,method,path,body", TOOL_REQUESTS, ids=[t[0] for t in TOOL_REQUESTS])
def test_identical_bytes(client, tool, method, path, body):
    first = call(client, method, path, body)
    second = call(client, method, path, body)
    assert first.status_code == 200
    assert first.content == second.content


def test_fresh_app_gives_identical_bytes(client):
    app_module = pytest.importorskip("app")
    from fastapi.testclient import TestClient

    other = TestClient(app_module.create_app(today="2026-10-18", public_base="/connectors/tmobile"))
    for _, method, path, body in TOOL_REQUESTS:
        assert call(client, method, path, body).content == call(other, method, path, body).content
