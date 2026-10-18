"""M16 connector tests: store, visibility, executor, cards, chat hook, REST and CLI (SPEC §8 M16, §9.3 T17).

Behavior:
    No internet: a local `ThreadingHTTPServer` on 127.0.0.1 plays the outside service and records
    every request it receives, so "refused without a request" is checked by counting them. Its
    `/api/items/{id}` route answers with the M17 envelope (`synthetic`, `as_of`, `data`, `reasons`,
    `pam_cards`) to check the T19 interface early. The LLM is a scripted fake of
    `orchestrator.stream_chat`; the MCP server is the real in-process M11 server.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from pam.agents.manifest import create_agent
from pam.api import app as app_mod
from pam.chat import keystore, llm, orchestrator
from pam.cli.main import app
from pam.connectors import cards as cards_mod
from pam.connectors import executor, store
from pam.connectors.store import ConnectorNotFound
from pam.contracts.agent import AgentManifest, ReadScope
from pam.contracts.api import ChatRequest, ToolCallEvent
from pam.contracts.config import ConnectorsCfg, ModelEntry, PamConfig
from pam.contracts.connector import Connector, ConnectorAuth, ConnectorParam, ConnectorResult, ConnectorTool
from pam.contracts.retrieval import ContextBundle
from pam.core import tokens
from pam.core.config import dump_toml
from pam.core.errors import PamError, VaultBusy
from pam.core.vault import Vault, init_vault, set_vault_override

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
PLAIN_MODEL = ModelEntry(id="openrouter/acme/plain:free", label="Plain")
TOOLS_MODEL = ModelEntry(id="openrouter/acme/tooly:free", label="Tooly", supports_tools=True)
AGENT = "advisor"
SECRET = "sk-test-0123456789-very-secret"
SECRET_VAR = "ACME_TEST_SECRET"
RENDERED = "# Known facts\n- school: UW\n"
TIMEOUT_S = 0.3
SLOW_S = 1.0
MAX_BYTES = 2000

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PAM_VAULT", raising=False)
    monkeypatch.delenv(SECRET_VAR, raising=False)
    set_vault_override(None)
    keystore.bind(None)
    yield
    set_vault_override(None)
    keystore.bind(None)


# --- the outside service ---------------------------------------------------------------------


def _card(title: str, **kw) -> dict:
    return {"kind": "product", "title": title, "badges": ["Synthetic demo data"], **kw}


class _Handler(BaseHTTPRequestHandler):
    """Routes under `/api`; every request is appended to `server.seen` before it is answered."""

    def log_message(self, *args) -> None:  # keep pytest output quiet
        pass

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.seen.append(
            {"method": method, "path": self.path, "headers": dict(self.headers), "body": body}
        )
        parts = urlsplit(self.path)
        path, query = parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}
        if path.startswith("/api/items/"):
            self._json({
                "synthetic": True, "as_of": "2026-10-18",
                "data": {"id": path.rsplit("/", 1)[1], "query": query},
                "reasons": [{"text": "Battery is low.", "signal": "line.device.battery_health", "value": 78}],
                "pam_cards": [
                    _card("Aurora 9", image_url="images/aurora.svg", price={"amount": 29.17, "was": 35.0}),
                    _card("Lumen 4", image_url="/connectors/acme/images/lumen.svg"),
                ],
            })
        elif path == "/api/recommend":
            self._json({"echo": json.loads(body or b"{}")})
        elif path == "/api/redirect":
            self.send_response(302)
            self.send_header("Location", "/api/items/1")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/api/slow":
            time.sleep(SLOW_S)
            self._json({"late": True})
        elif path == "/api/big":
            self._json({"blob": "x" * (MAX_BYTES * 2)})
        elif path == "/api/text":
            self._raw(200, b"not json", "text/plain")
        elif path == "/api/scalar":
            self._raw(200, b"42", "application/json")
        elif path == "/api/fail":
            self._raw(500, json.dumps({"detail": self.headers.get("x-api-key", "")}).encode(), "application/json")
        elif path == "/api/leaky":
            self._json({"echo": self.headers.get("x-api-key") or self.headers.get("Authorization")})
        else:
            self._raw(404, b"{}", "application/json")

    def _json(self, payload) -> None:
        self._raw(200, json.dumps(payload).encode(), "application/json")

    def _raw(self, status: int, data: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    """Start the local service; `server.url` is its origin and `server.seen` its request log."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    srv.seen = []
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- vault and connector helpers ---------------------------------------------------------------


def _write_config(v: Vault, **connectors) -> None:
    cfg = PamConfig(
        models=[PLAIN_MODEL, TOOLS_MODEL],
        connectors=ConnectorsCfg(timeout_seconds=TIMEOUT_S, max_response_bytes=MAX_BYTES, **connectors),
    )
    v.config_path.write_text(dump_toml(cfg), encoding="utf-8")


@pytest.fixture
def vault(tmp_path) -> Vault:
    """An empty vault with two models (one with tools) and the custom agent `advisor`."""
    init_vault(tmp_path / "vault")
    v = Vault(tmp_path / "vault")
    _write_config(v)
    create_agent(
        AgentManifest(name=AGENT, display_name="Advisor", origin="custom", created_at=NOW,
                      read=ReadScope(all=False), write="own", tools=["get_context"]),
        v,
    )
    return v


def _tools() -> list[ConnectorTool]:
    simple = ("redirect", "slow", "big", "text", "scalar", "fail", "leaky")
    return [
        ConnectorTool(name="get_item", description="Get an item", path="/items/{id}", params=[
            ConnectorParam(name="id", required=True),
            ConnectorParam(name="query"),
            ConnectorParam(name="limit", type="number"),
            ConnectorParam(name="fresh", type="boolean"),
        ]),
        ConnectorTool(name="recommend", description="Recommend", method="POST", path="/recommend", params=[
            ConnectorParam(name="customer_id", required=True),
            ConnectorParam(name="budget", type="number"),
        ]),
        *(ConnectorTool(name=n, description=n, path=f"/{n}") for n in simple),
    ]


def _connector(server=None, **kw) -> Connector:
    base = {
        "id": "acme", "name": "Acme (synthetic)",
        "base_url": f"{server.url if server else 'http://127.0.0.1:9'}/api",
        "public_base_url": "/connectors/acme", "tools": _tools(), "agents": [AGENT],
    }
    return Connector(**{**base, **kw})


def _call(v: Vault, tool: str, args, connector_id: str = "acme") -> ConnectorResult:
    return asyncio.run(executor.call(v, connector_id, tool, args))


def _commits(v: Vault) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=v.root, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _names(schemas: list[dict]) -> list[str]:
    return [s["function"]["name"] for s in schemas]


# --- store -----------------------------------------------------------------------------------


def test_init_creates_the_connectors_folder_in_its_single_commit(vault):
    assert (vault.root / "connectors" / ".gitkeep").is_file()
    assert vault.connectors_dir == vault.root / "connectors"
    assert vault.connector_path("acme") == vault.root / "connectors" / "acme.yaml"
    assert _commits(vault)[-1] == "pam: init vault"


def test_save_round_trips_with_exactly_one_commit(vault):
    before = len(_commits(vault))
    c = _connector()
    sha = store.save_connector(vault, c)
    assert sha and len(sha) == 40
    assert _commits(vault)[0] == "connector: save acme"
    assert len(_commits(vault)) == before + 1
    assert store.get_connector(vault, "acme") == c
    assert vault.connector_path("acme").read_text(encoding="utf-8") == store.dump_yaml(c)
    assert store.save_connector(vault, c) is None  # same bytes: no commit
    assert len(_commits(vault)) == before + 1
    store.save_connector(vault, c.model_copy(update={"description": "changed"}))
    assert len(_commits(vault)) == before + 2


def test_save_validates_the_model(vault):
    bad = _connector().model_copy(update={"id": "Not A Slug"})  # model_copy skips validation
    with pytest.raises(PamError) as e:
        store.save_connector(vault, bad)
    assert e.value.exit_code == 2


def test_archive_instead_of_delete(vault):
    store.save_connector(vault, _connector())
    sha = store.archive_connector(vault, "acme")
    assert sha and _commits(vault)[0] == "connector: archive acme"
    assert vault.connector_path("acme").is_file()
    archived = store.get_connector(vault, "acme")
    assert (archived.archived, archived.enabled) == (True, False)
    assert store.list_connectors(vault) == []
    assert [c.id for c in store.list_connectors(vault, include_archived=True)] == ["acme"]
    assert store.archive_connector(vault, "acme") is None


def test_list_is_sorted_by_id(vault):
    for cid in ("zeta", "acme", "mid"):
        store.save_connector(vault, _connector(id=cid))
    assert [c.id for c in store.list_connectors(vault)] == ["acme", "mid", "zeta"]


def test_invalid_files_are_reported_logged_and_skipped(vault, caplog):
    store.save_connector(vault, _connector())
    vault.connector_path("broken").write_text("id: broken\n", encoding="utf-8")
    vault.connector_path("other").write_text(store.dump_yaml(_connector(id="acme2")), encoding="utf-8")
    vault.connector_path("junk").write_text("- a\n- b\n", encoding="utf-8")
    entries = {e.id: e for e in store.scan_connectors(vault)}
    assert entries["acme"].valid
    assert not entries["broken"].valid and "name" in entries["broken"].error
    assert not entries["other"].valid and "does not match" in entries["other"].error
    assert not entries["junk"].valid
    with caplog.at_level(logging.WARNING, logger="pam.connectors.store"):
        assert [c.id for c in store.list_connectors(vault)] == ["acme"]
    assert "connectors/broken.yaml" in caplog.text
    with pytest.raises(PamError) as e:
        store.get_connector(vault, "broken")
    assert e.value.exit_code == 2


@pytest.mark.parametrize("cid", ["nope", "../acme", "ACME", ""])
def test_get_unknown_or_non_slug_id_is_not_found(vault, cid):
    store.save_connector(vault, _connector())
    with pytest.raises(ConnectorNotFound):
        store.get_connector(vault, cid)


def test_archive_unknown_is_not_found(vault):
    with pytest.raises(ConnectorNotFound):
        store.archive_connector(vault, "nope")


# --- visibility and tool schemas ---------------------------------------------------------------


def test_only_ticked_agents_see_the_tools(vault):
    store.save_connector(vault, _connector())
    names = _names(executor.tools_for(vault, AGENT))
    assert names[:2] == ["acme__get_item", "acme__recommend"]
    assert executor.tools_for(vault, "default") == []  # default is not implicit
    assert executor.tools_for(vault, "someone-else") == []


def test_default_sees_tools_only_when_ticked_explicitly(vault):
    store.save_connector(vault, _connector(agents=["default"]))
    assert executor.tools_for(vault, "default")


def test_disabled_and_archived_connectors_are_hidden(vault):
    store.save_connector(vault, _connector(enabled=False))
    assert executor.tools_for(vault, AGENT) == []
    store.save_connector(vault, _connector())
    assert executor.tools_for(vault, AGENT)
    store.archive_connector(vault, "acme")
    assert executor.tools_for(vault, AGENT) == []


def test_tool_schema_shape(vault):
    store.save_connector(vault, _connector())
    schema = executor.tools_for(vault, AGENT)[0]
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["description"] == "Get an item (via Acme (synthetic), an outside service)"
    assert fn["parameters"] == {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": ""},
            "query": {"type": "string", "description": ""},
            "limit": {"type": "number", "description": ""},
            "fresh": {"type": "boolean", "description": ""},
        },
        "required": ["id"],
    }
    assert "required" not in executor.tools_for(vault, AGENT)[2]["function"]["parameters"]


def test_cap_and_order_by_connector_then_tool(vault):
    _write_config(vault, max_tools_per_turn=3)
    store.save_connector(vault, _connector(id="beta"))
    store.save_connector(vault, _connector(id="acme"))
    assert _names(executor.tools_for(vault, AGENT)) == ["acme__get_item", "acme__recommend", "acme__redirect"]
    _write_config(vault, max_tools_per_turn=20)
    names = _names(executor.tools_for(vault, AGENT))
    assert len(names) == 18 and names[9] == "beta__get_item"


def test_over_long_tool_names_are_skipped(vault, caplog):
    long_id = "a" * 40
    store.save_connector(vault, _connector(id=long_id, tools=[
        ConnectorTool(name="t" * 23, description="long", path="/x"),
        ConnectorTool(name="short", description="ok", path="/x"),
    ]))
    with caplog.at_level(logging.WARNING, logger="pam.connectors.executor"):
        assert _names(executor.tools_for(vault, AGENT)) == [f"{long_id}__short"]
    assert "too long" in caplog.text


def test_store_is_read_per_call(vault):
    assert executor.tools_for(vault, AGENT) == []
    store.save_connector(vault, _connector())
    assert executor.tools_for(vault, AGENT)


@pytest.mark.parametrize("name,expected", [
    ("acme__get_item", ("acme", "get_item")),
    ("my-api__a__b", ("my-api", "a__b")),
    ("get_context", None),
    ("__x", None),
    ("acme__", None),
])
def test_split_tool_name(name, expected):
    assert executor.split_tool_name(name) == expected


# --- executor ----------------------------------------------------------------------------------


def test_get_fills_the_path_and_the_query_string(vault, server):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "get_item", {"id": "a b", "query": "camera", "limit": 3, "fresh": True})
    assert result.ok and result.status == 200 and result.error is None
    assert result.latency_ms >= 0
    [req] = server.seen
    assert req["method"] == "GET"
    assert urlsplit(req["path"]).path == "/api/items/a%20b"
    assert parse_qs(urlsplit(req["path"]).query) == {"query": ["camera"], "limit": ["3"], "fresh": ["true"]}
    assert result.data["data"] == {"id": "a%20b", "query": {"query": "camera", "limit": "3", "fresh": "true"}}
    assert "pam_cards" not in result.data
    assert result.data["synthetic"] is True and result.data["reasons"][0]["signal"]


def test_post_sends_a_json_body(vault, server):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "recommend", {"customer_id": "cust-chen", "budget": 40, "unused": None})
    assert result.ok
    [req] = server.seen
    assert req["method"] == "POST" and urlsplit(req["path"]).path == "/api/recommend"
    assert json.loads(req["body"]) == {"customer_id": "cust-chen", "budget": 40}
    assert result.data == {"echo": {"customer_id": "cust-chen", "budget": 40}}


@pytest.mark.parametrize("args,needle", [
    ({"id": "1", "bogus": 1}, "undeclared"),
    ({}, "missing"),
    ({"id": None}, "missing"),
    ({"id": 5}, "id must be a string"),
    ({"id": "1", "limit": "3"}, "limit must be a number"),
    ({"id": "1", "limit": True}, "limit must be a number"),
    ({"id": "1", "fresh": "yes"}, "fresh must be a boolean"),
    (["id", "1"], "JSON object"),
])
def test_bad_arguments_are_refused_without_a_request(vault, server, args, needle):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "get_item", args)
    assert not result.ok and result.status is None
    assert result.error["code"] == "BAD_ARGUMENTS" and needle in result.error["message"]
    assert server.seen == []


@pytest.mark.parametrize("value", ["../x", "..", ".", "a/b", "a\\b", "../../etc/passwd"])
def test_path_escape_is_refused_without_a_request(vault, server, value):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "get_item", {"id": value})
    assert result.error["code"] == "BAD_ARGUMENTS" and result.status is None
    assert server.seen == []


@pytest.mark.parametrize("path", ["/../admin", "/items/../../admin", "/./x"])
def test_connector_path_outside_base_url_is_refused(vault, server, path):
    store.save_connector(vault, _connector(server, tools=[ConnectorTool(name="evil", description="e", path=path)]))
    result = _call(vault, "evil", {})
    assert result.error["code"] == "BAD_ARGUMENTS" and "base_url" in result.error["message"]
    assert server.seen == []


def test_placeholder_must_be_a_declared_parameter(vault, server):
    tool = ConnectorTool(name="odd", description="o", path="/items/{nope}")
    store.save_connector(vault, _connector(server, tools=[tool]))
    assert _call(vault, "odd", {}).error["code"] == "BAD_ARGUMENTS"
    assert server.seen == []


def test_redirect_is_not_followed(vault, server):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "redirect", {})
    assert not result.ok and result.status == 302 and result.error["code"] == "HTTP_302"
    assert [urlsplit(r["path"]).path for r in server.seen] == ["/api/redirect"]


@pytest.mark.parametrize("tool,code,status", [
    ("slow", "TIMEOUT", None),
    ("big", "BAD_RESPONSE", 200),
    ("text", "BAD_RESPONSE", 200),
    ("scalar", "BAD_RESPONSE", 200),
    ("fail", "HTTP_500", 500),
])
def test_service_errors_are_results_not_exceptions(vault, server, tool, code, status):
    store.save_connector(vault, _connector(server))
    result = _call(vault, tool, {})
    assert not result.ok and result.error["code"] == code and result.status == status
    assert result.data is None and result.cards == []


def test_unreachable_service(vault):
    store.save_connector(vault, _connector(base_url=f"http://127.0.0.1:{_closed_port()}"))
    result = _call(vault, "fail", {})
    assert result.error["code"] == "UNREACHABLE" and result.status is None


def test_unknown_connector_or_tool_raises_not_found(vault):
    store.save_connector(vault, _connector())
    with pytest.raises(ConnectorNotFound):
        _call(vault, "nope", {})
    with pytest.raises(ConnectorNotFound):
        _call(vault, "get_item", {"id": "1"}, connector_id="missing")


# --- secrets -----------------------------------------------------------------------------------


def _secured(server, auth_type: str = "api_key") -> Connector:
    header = "x-api-key" if auth_type == "api_key" else None
    return _connector(server, auth=ConnectorAuth(type=auth_type, header=header, env_var=SECRET_VAR))


def test_missing_secret_is_refused_without_a_request(vault, server):
    store.save_connector(vault, _secured(server))
    result = _call(vault, "leaky", {})
    assert result.error["code"] == "MISSING_SECRET" and SECRET_VAR in result.error["message"]
    assert server.seen == []


def test_api_key_header_is_sent_and_never_returned_or_logged(vault, server, monkeypatch, caplog):
    monkeypatch.setenv(SECRET_VAR, SECRET)
    store.save_connector(vault, _secured(server))
    with caplog.at_level(logging.DEBUG):
        ok = _call(vault, "leaky", {})
        failed = _call(vault, "fail", {})
    assert [r["headers"].get("x-api-key") for r in server.seen] == [SECRET, SECRET]
    assert ok.ok and ok.data == {"echo": keystore.REDACTED}  # the service echoed it back
    assert failed.error["code"] == "HTTP_500"
    for result in (ok, failed):
        assert SECRET not in result.model_dump_json()
    assert SECRET not in caplog.text
    log = subprocess.run(["git", "log", "-p", "--all"], cwd=vault.root, capture_output=True, text=True).stdout
    assert SECRET_VAR in log and SECRET not in log


def test_bearer_auth(vault, server, monkeypatch):
    monkeypatch.setenv(SECRET_VAR, SECRET)
    store.save_connector(vault, _secured(server, "bearer"))
    result = _call(vault, "leaky", {})
    assert server.seen[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in result.model_dump_json()


def test_settings_store_secret_wins_over_the_environment(vault, server, monkeypatch):
    monkeypatch.setenv(SECRET_VAR, "from-env")
    assert keystore.lookup_secret(SECRET_VAR, vault) == "from-env"
    keystore.store_path(vault).parent.mkdir(parents=True, exist_ok=True)
    keystore.store_path(vault).write_text(json.dumps({SECRET_VAR: SECRET}), encoding="utf-8")
    assert keystore.lookup_secret(SECRET_VAR, vault) == SECRET
    store.save_connector(vault, _secured(server))
    _call(vault, "leaky", {})
    assert server.seen[0]["headers"]["x-api-key"] == SECRET
    monkeypatch.delenv(SECRET_VAR)
    keystore.store_path(vault).write_text("{}", encoding="utf-8")
    assert keystore.lookup_secret(SECRET_VAR, vault) is None


# --- cards ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("url,base,expected", [
    ("images/a.svg", "/connectors/acme", "/connectors/acme/images/a.svg"),
    ("/connectors/acme/images/a.svg", "/connectors/acme", "/connectors/acme/images/a.svg"),
    ("images/a.svg", "/connectors/acme/", "/connectors/acme/images/a.svg"),
    ("img.svg", "https://cdn.example/base", "https://cdn.example/base/img.svg"),
    ("https://cdn.example/a.png", None, "https://cdn.example/a.png"),
    ("http://cdn.example/a.png", "/connectors/acme", None),
    ("//evil.example/a.png", "/connectors/acme", None),
    ("javascript:alert(1)", "/connectors/acme", None),
    ("data:image/svg+xml;base64,AAAA", "/connectors/acme", None),
    ("images/a.svg", None, None),
])
def test_resolve_url(url, base, expected):
    assert cards_mod.resolve_url(url, base) == expected


def test_cards_are_validated_resolved_capped_and_stamped(caplog):
    connector = _connector()
    raw = [
        {"kind": "bogus", "title": "dropped"},
        "not a card",
        _card("c1", image_url="images/1.svg", connector_id="evil"),
        _card("c2", image_url="http://insecure.example/2.png", link={"label": "Go", "url": "http://x.example"}),
        _card("c3", link={"label": "Go", "url": "/connectors/acme/plans"}),
        *(_card(f"c{i}") for i in range(4, 9)),
    ]
    body = {"data": {"a": 1}, "pam_cards": raw}
    with caplog.at_level(logging.WARNING, logger="pam.connectors.cards"):
        data, cards = cards_mod.extract_cards(body, connector)
    assert data == {"data": {"a": 1}}
    assert [c.title for c in cards] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert {c.connector_id for c in cards} == {"acme"}
    assert cards[0].image_url == "/connectors/acme/images/1.svg"
    assert cards[1].image_url is None and cards[1].link is None
    assert cards[2].link.url == "/connectors/acme/plans"
    assert "dropped invalid card 0" in caplog.text and "kept the first 6" in caplog.text


@pytest.mark.parametrize("body", [[{"pam_cards": []}], {"x": 1}, {"pam_cards": "nope"}])
def test_bodies_without_a_card_list(body):
    data, cards = cards_mod.extract_cards(body, _connector())
    assert cards == []
    assert data == ({"x": 1} if body == {"x": 1} else {} if isinstance(body, dict) else body)


def test_call_returns_the_mock_envelope_cards(vault, server):
    store.save_connector(vault, _connector(server))
    result = _call(vault, "get_item", {"id": "7"})
    assert [c.image_url for c in result.cards] == [
        "/connectors/acme/images/aurora.svg", "/connectors/acme/images/lumen.svg",
    ]
    assert result.cards[0].price.amount == 29.17


# --- the model's tool message --------------------------------------------------------------------


def test_model_message_ok_and_error_shapes():
    ok = ConnectorResult(ok=True, status=200, latency_ms=3, data={"a": 1})
    assert json.loads(executor.model_message(ok, "acme", "t", 1500)) == {"connector": "acme", "tool": "t", "data": {"a": 1}}
    err = ConnectorResult(ok=False, latency_ms=3, error={"code": "TIMEOUT", "message": "slow"})
    assert json.loads(executor.model_message(err, "acme", "t", 1500))["error"] == {"code": "TIMEOUT", "message": "slow"}


def test_model_message_is_trimmed_to_the_token_budget():
    big = ConnectorResult(ok=True, status=200, latency_ms=3, data={"rows": [f"row {i} text" for i in range(2000)]})
    text = executor.model_message(big, "acme", "t", 100)
    assert text.endswith(executor.TRUNCATED_SUFFIX)
    assert tokens.count(text) <= 100 + 2  # the cut can merge one token across the joint


# --- chat orchestrator hook -----------------------------------------------------------------------


class ScriptedLLM:
    """Stand-in for `stream_chat`: one scripted list of deltas per call; records every call."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls: list[dict] = []

    async def __call__(self, model, messages, tools=None):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        script = self.rounds.pop(0) if self.rounds else [llm.LLMDelta(text="ok", finish_reason="stop")]
        for item in script:
            yield item


@pytest.fixture
def fake_llm(monkeypatch):
    def install(*rounds) -> ScriptedLLM:
        fake = ScriptedLLM(*rounds)
        monkeypatch.setattr(orchestrator, "stream_chat", fake)
        return fake

    return install


@pytest.fixture
def fixed_context(monkeypatch):
    """Replace `build_context` with a fixed bundle so injection mode needs no index."""
    from pam.retrieve import context as context_module

    def build_context(bound_vault, request):
        return ContextBundle(
            agent=request.agent, query=request.query, persona=None, facts=[], conflicts=[], projects=[],
            episodes=[], working=None, rendered=RENDERED, tokens_used=5, token_budget=2000,
            baseline_tokens=0, tokens_saved=0, generated_at=NOW,
        )

    monkeypatch.setattr(context_module, "build_context", build_context)


def _tool_round(*calls):
    return [llm.LLMDelta(tool_calls=list(calls), finish_reason="tool_calls")]


def _text(text="done"):
    return [llm.LLMDelta(text=text), llm.LLMDelta(finish_reason="stop")]


def _turn(vault, **kw) -> list:
    req = ChatRequest(message="Should I upgrade my phone?", model=kw.pop("model", TOOLS_MODEL.id), **kw)

    async def collect():
        return [e async for e in orchestrator.run_turn(vault, req)]

    return asyncio.run(collect())


def _tool_names(tools) -> list[str]:
    return [t["function"]["name"] for t in tools or []]


def test_tool_call_event_carries_cards(vault, server, fake_llm):
    store.save_connector(vault, _connector(server))
    call = llm.ToolCall(id="c1", name="acme__get_item", arguments={"id": "7"})
    fake = fake_llm(_tool_round(call), _text("Wait 3 months."))
    events = _turn(vault, agent=AGENT, mode="tool")
    [event] = [e for e in events if isinstance(e, ToolCallEvent)]
    assert event.name == "acme__get_item" and event.arguments == {"id": "7"}
    assert [c.title for c in event.cards] == ["Aurora 9", "Lumen 4"]
    assert {c.connector_id for c in event.cards} == {"acme"}
    assert event.result_summary.startswith('{"connector": "acme"')
    assert events[-1].type == "done"
    first, second = fake.calls
    assert {"acme__get_item", "acme__recommend", "get_context"} <= set(_tool_names(first["tools"]))
    system = first["messages"][0]["content"]
    assert f"{llm.MEMORY_GUIDE}\n\n{llm.CONNECTOR_NOTE}" in system
    tool_msg = second["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    payload = json.loads(tool_msg["content"])
    assert payload["connector"] == "acme" and payload["tool"] == "get_item"
    assert "pam_cards" not in payload["data"] and payload["data"]["synthetic"] is True


def test_connector_error_is_a_tool_result_not_a_failed_turn(vault, server, fake_llm):
    store.save_connector(vault, _connector(server))
    call = llm.ToolCall(id="c1", name="acme__get_item", arguments={"id": "../x"})
    fake_llm(_tool_round(call), _text())
    events = _turn(vault, agent=AGENT, mode="tool")
    [event] = [e for e in events if isinstance(e, ToolCallEvent)]
    assert event.result_summary.startswith("ERROR:") and "BAD_ARGUMENTS" in event.result_summary
    assert event.cards == [] and events[-1].type == "done"
    assert server.seen == []


def test_injection_with_tools_adds_the_note_after_the_memory_guide(vault, server, fake_llm, fixed_context):
    store.save_connector(vault, _connector(server))
    fake = fake_llm(_text())
    _turn(vault, agent=AGENT)
    assert fake.calls[0]["messages"][0]["content"] == (
        f"{llm.PAM_PREAMBLE}\n\n{llm.MEMORY_GUIDE}\n\n{llm.CONNECTOR_NOTE}\n\n{RENDERED}"
    )
    assert "acme__get_item" in _tool_names(fake.calls[0]["tools"])


def test_default_agent_gets_no_connector_tools(vault, server, fake_llm, fixed_context):
    store.save_connector(vault, _connector(server))
    fake = fake_llm(_text(), _text())
    _turn(vault, mode="tool")
    _turn(vault)
    for call in fake.calls:
        assert not any("__" in n for n in _tool_names(call["tools"]))
        assert llm.CONNECTOR_NOTE not in call["messages"][0]["content"]


def test_model_without_tool_support_gets_no_connector_tools(vault, server, fake_llm, fixed_context):
    store.save_connector(vault, _connector(server, agents=["default", AGENT]))
    fake = fake_llm(_text())
    _turn(vault, agent=AGENT, model=PLAIN_MODEL.id)
    assert fake.calls[0]["tools"] is None
    assert llm.CONNECTOR_NOTE not in fake.calls[0]["messages"][0]["content"]


def test_unoffered_connector_name_is_not_called(vault, server, fake_llm):
    store.save_connector(vault, _connector(server))  # ticked for advisor only
    call = llm.ToolCall(id="c1", name="acme__get_item", arguments={"id": "7"})
    fake_llm(_tool_round(call), _text())
    events = _turn(vault, mode="tool")  # default agent
    [event] = [e for e in events if isinstance(e, ToolCallEvent)]
    assert event.result_summary.startswith("ERROR:") and event.cards == []
    assert server.seen == []


def test_secret_never_reaches_chat_events(vault, server, fake_llm, monkeypatch):
    monkeypatch.setenv(SECRET_VAR, SECRET)
    store.save_connector(vault, _secured(server))
    calls = [llm.ToolCall(id=f"c{i}", name=f"acme__{t}", arguments={}) for i, t in enumerate(("leaky", "fail"))]
    fake = fake_llm(_tool_round(*calls), _text())
    events = _turn(vault, agent=AGENT, mode="tool")
    assert len(server.seen) == 2
    assert all(SECRET not in e.model_dump_json() for e in events)
    assert all(SECRET not in json.dumps(c["messages"]) for c in fake.calls)


# --- REST --------------------------------------------------------------------------------------


@pytest.fixture
def client(vault):
    return TestClient(app_mod.create_app(vault.root))


def _error(response, status: int) -> dict:
    assert response.status_code == status, response.text
    assert set(response.json()) == {"error"}
    return response.json()["error"]


def test_rest_create_read_list_archive(client, vault, server):
    body = _connector(server).model_dump(mode="json")
    put = client.put("/api/connectors/acme", json=body)
    assert put.status_code == 200 and put.json() == body
    assert _commits(vault)[0] == "connector: save acme"
    assert client.get("/api/connectors").json() == [body]
    assert client.get("/api/connectors/acme").json() == body
    archived = client.post("/api/connectors/acme/archive")
    assert archived.status_code == 200 and archived.json()["archived"] is True
    assert client.get("/api/connectors").json() == []
    assert [c["id"] for c in client.get("/api/connectors?include_archived=true").json()] == ["acme"]


def test_rest_errors(client, vault, monkeypatch):
    body = _connector().model_dump(mode="json")
    assert _error(client.put("/api/connectors/other", json=body), 400)["code"] == "VALIDATION_ERROR"
    assert _error(client.put("/api/connectors/acme", json={**body, "base_url": None}), 400)["code"] == "VALIDATION_ERROR"
    assert _error(client.get("/api/connectors/nope"), 404)["code"] == "NOT_FOUND"
    assert _error(client.post("/api/connectors/nope/archive"), 404)["code"] == "NOT_FOUND"
    client.put("/api/connectors/acme", json=body)
    assert _error(client.post("/api/connectors/acme/tools/nope/call", json={}), 404)["code"] == "NOT_FOUND"

    def busy(*args, **kwargs):
        raise VaultBusy("vault is busy")

    monkeypatch.setattr(store, "save_connector", busy)
    assert _error(client.put("/api/connectors/acme", json=body), 409)["code"] == "CONFLICT"


def test_rest_call_tool(client, server):
    client.put("/api/connectors/acme", json=_connector(server).model_dump(mode="json"))
    ok = client.post("/api/connectors/acme/tools/get_item/call", json={"id": "7"})
    assert ok.status_code == 200
    result = ConnectorResult.model_validate(ok.json())
    assert result.ok and [c.title for c in result.cards] == ["Aurora 9", "Lumen 4"]
    bad = ConnectorResult.model_validate(client.post("/api/connectors/acme/tools/get_item/call").json())
    assert bad.error["code"] == "BAD_ARGUMENTS"


def test_openapi_lists_the_connector_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"get", "put"} <= set(paths["/api/connectors/{id}"])
    for path in ("/api/connectors", "/api/connectors/{id}/archive", "/api/connectors/{id}/tools/{tool}/call"):
        assert path in paths


# --- CLI ---------------------------------------------------------------------------------------


def _pam(vault, *args):
    return runner.invoke(app, ["--vault", str(vault.root), *args])


def _yaml_file(tmp_path: Path, connector: Connector) -> Path:
    path = tmp_path / "connector.yaml"
    path.write_text(store.dump_yaml(connector), encoding="utf-8")
    return path


def test_cli_add_list_show_archive(vault, tmp_path):
    added = _pam(vault, "connector", "add", str(_yaml_file(tmp_path, _connector())))
    assert added.exit_code == 0, added.output
    assert added.output.startswith("Saved connector acme (commit ")
    again = _pam(vault, "connector", "add", str(_yaml_file(tmp_path, _connector())))
    assert "unchanged, no commit" in again.output
    vault.connector_path("broken").write_text("id: broken\n", encoding="utf-8")
    listed = _pam(vault, "connector", "list")
    assert listed.exit_code == 0
    assert "acme  Acme (synthetic)  enabled  9 tools  agents: advisor" in listed.output
    assert "broken  INVALID:" in listed.output
    rows = json.loads(_pam(vault, "--json", "connector", "list").output)
    assert [(r["id"], r["valid"]) for r in rows] == [("acme", True), ("broken", False)]
    shown = _pam(vault, "connector", "show", "acme")
    assert shown.output == store.dump_yaml(_connector())
    assert _pam(vault, "connector", "archive", "acme").exit_code == 0
    assert "acme" not in _pam(vault, "connector", "list").output
    assert "acme  Acme (synthetic)  archived" in _pam(vault, "connector", "list", "--all").output
    for output in (listed.output, shown.output):
        output.encode("ascii")


def test_cli_add_invalid_file_exits_2(vault, tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: bad\n", encoding="utf-8")
    result = _pam(vault, "connector", "add", str(path))
    assert result.exit_code == 2
    assert not vault.connector_path("bad").exists()


def test_cli_show_unknown_exits_1(vault):
    assert _pam(vault, "connector", "show", "nope").exit_code == 1


def test_cli_call_prints_status_and_card_titles(vault, server):
    store.save_connector(vault, _connector(server))
    result = _pam(vault, "connector", "call", "acme", "get_item", "--arg", "id=7", "--arg", "limit=3",
                  "--arg", "fresh=yes", "--arg", "query=camera")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("ok  HTTP 200  ") and lines[0].endswith("  2 cards")
    assert lines[1:] == ["- [product] Aurora 9", "- [product] Lumen 4"]
    assert parse_qs(urlsplit(server.seen[0]["path"]).query) == {"limit": ["3"], "fresh": ["true"], "query": ["camera"]}


def test_cli_call_json_and_errors(vault, server):
    store.save_connector(vault, _connector(server))
    ok = _pam(vault, "connector", "call", "acme", "get_item", "--arg", "id=7", "--json")
    assert ConnectorResult.model_validate_json(ok.output).ok
    bad = _pam(vault, "connector", "call", "acme", "get_item", "--arg", "limit=x")
    assert bad.exit_code == 1 and bad.output.startswith("error  ") and "BAD_ARGUMENTS" in bad.output
    assert _pam(vault, "connector", "call", "acme", "get_item", "--arg", "novalue").exit_code == 2
    assert server.seen[1:] == []
