"""Shared fixtures for the T-Mobile mock tests (SPEC M17, T19)."""

from __future__ import annotations

import pytest

from tests.helpers import MOCK_TODAY


@pytest.fixture(scope="session")
def client():
    pytest.importorskip("fastapi", reason="fastapi is not installed")
    pytest.importorskip("httpx", reason="httpx is not installed (needed by TestClient)")
    app_module = pytest.importorskip("app", reason="mock/tmobile/app.py does not exist yet")
    from fastapi.testclient import TestClient

    return TestClient(app_module.create_app(today=MOCK_TODAY, public_base="/connectors/tmobile"))


@pytest.fixture(scope="session")
def catalog():
    common = pytest.importorskip("engine.common", reason="mock/tmobile/engine does not exist yet")
    return common.load_catalog()
