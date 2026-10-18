"""Connector tools for agents, and the HTTP calls behind them (SPEC §8 M16).

Behavior:
    `tools_for` turns the connectors that name an agent into OpenAI function-tool schemas called
    `<connector_id>__<tool>`. `call` validates the arguments, builds the request inside the
    connector's `base_url`, sends it without following redirects, and returns a `ConnectorResult`.
    Problems with the request or the service are returned as error results, never raised, and no
    secret ever appears in a result, an error message or a log line.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from pam.chat import keystore
from pam.connectors.cards import extract_cards
from pam.connectors.store import ConnectorNotFound, get_connector, list_connectors
from pam.contracts.config import ConnectorsCfg
from pam.contracts.connector import Connector, ConnectorParam, ConnectorResult, ConnectorTool
from pam.core import config, tokens
from pam.core.errors import PamError
from pam.core.vault import Vault

log = logging.getLogger(__name__)

TOOL_SEPARATOR = "__"
MAX_TOOL_NAME = 64
VIA_SUFFIX = " (via {name}, an outside service)"
DEFAULT_API_KEY_HEADER = "X-API-Key"
TRUNCATED_SUFFIX = "... (truncated)"
TRIM_STEP = 0.9
DOT_SEGMENTS = (".", "..")
PATH_FORBIDDEN = ("/", "\\")

BAD_ARGUMENTS = "BAD_ARGUMENTS"
MISSING_SECRET = "MISSING_SECRET"
UNREACHABLE = "UNREACHABLE"
TIMEOUT = "TIMEOUT"
BAD_RESPONSE = "BAD_RESPONSE"

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_TOOL_NAME = re.compile(r"^[a-z0-9_-]{1,64}$")
_JSON_TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "number": (int, float), "boolean": (bool,)}


class _Refused(Exception):
    """A call refused before any request is sent; becomes an error result."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def tool_name(connector: Connector, tool: ConnectorTool) -> str:
    """Return the model-facing name of a connector tool, `<connector_id>__<tool>`."""
    return f"{connector.id}{TOOL_SEPARATOR}{tool.name}"


def split_tool_name(name: str) -> tuple[str, str] | None:
    """Split `<connector_id>__<tool>` into its parts.

    Behavior:
        Splits at the first `__`; connector ids are slugs, so they never contain `_`.
    Returns:
        `(connector_id, tool)`, or `None` when `name` is not a connector tool name.
    Parameters:
        name: A tool name chosen by the model.
    """
    connector_id, sep, tool = name.partition(TOOL_SEPARATOR)
    return (connector_id, tool) if sep and connector_id and tool else None


def tool_schema(connector: Connector, tool: ConnectorTool) -> dict[str, Any]:
    """Build the OpenAI function-tool schema for one connector tool.

    Returns:
        `{"type": "function", "function": {"name", "description", "parameters"}}`; the
        description ends with ` (via <connector name>, an outside service)`.
    Parameters:
        connector: The connector.
        tool: One of its tools.
    """
    properties = {p.name: {"type": p.type, "description": p.description} for p in tool.params}
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    required = [p.name for p in tool.params if p.required]
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": tool_name(connector, tool),
            "description": tool.description + VIA_SUFFIX.format(name=connector.name),
            "parameters": parameters,
        },
    }


def tools_for(vault: Vault, agent: str) -> list[dict[str, Any]]:
    """List the connector tools an agent may use this turn.

    Behavior:
        A connector counts only if it is enabled, not archived, and lists `agent` in `agents`; the
        `default` agent gets nothing implicitly. Tools come in connector-id then tool order, at most
        `connectors.max_tools_per_turn` of them. A tool whose name would exceed 64 characters of
        `[a-z0-9_-]` is skipped with a warning. The store is read on every call, so edits apply on the
        next turn.
    Returns:
        OpenAI function-tool schemas.
    Parameters:
        vault: The vault.
        agent: The agent's name.
    """
    cap = config.load(vault).connectors.max_tools_per_turn
    schemas: list[dict[str, Any]] = []
    for connector in list_connectors(vault):
        if not connector.enabled or agent not in connector.agents:
            continue
        for tool in connector.tools:
            name = tool_name(connector, tool)
            if not _TOOL_NAME.match(name) or len(name) > MAX_TOOL_NAME:
                log.warning("connector %s: tool name %s is too long; skipped", connector.id, name)
                continue
            if len(schemas) == cap:
                return schemas
            schemas.append(tool_schema(connector, tool))
    return schemas


async def call(vault: Vault, connector_id: str, tool: str, args: dict[str, Any]) -> ConnectorResult:
    """Run one connector tool as an HTTP request.

    Behavior:
        Refused without a request (code `BAD_ARGUMENTS`): arguments that are not an object, an
        undeclared argument, a missing required one, a wrong type, a path value with `/`, `\\`
        or a dot segment, or a final URL outside `base_url`. `None` counts as absent. Path
        placeholders are filled URL-encoded; the other arguments go to the query string (GET) or a
        JSON body (POST). The secret named by `auth.env_var` comes from the keystore, then the
        environment (`MISSING_SECRET` if unset); a body that echoes it back has it masked as `***`
        before parsing. Redirects are not followed. Errors: `UNREACHABLE`,
        `TIMEOUT`, `HTTP_<status>` for any non-2xx status, and `BAD_RESPONSE` for a body over
        `connectors.max_response_bytes` or one that is not a JSON object or array. A successful
        body's `pam_cards` become the result's cards and the rest is its data.
    Exceptions:
        ConnectorNotFound: No such connector, or it has no such tool.
        PamError: The connector file is invalid (exit code 2).
    Returns:
        The result; `status` is `None` when no request was sent.
    Parameters:
        vault: The vault.
        connector_id: Connector id.
        tool: Tool name within the connector.
        args: The arguments object.
    """
    connector = get_connector(vault, connector_id)
    spec = next((t for t in connector.tools if t.name == tool), None)
    if spec is None:
        raise ConnectorNotFound(f"connector {connector_id!r} has no tool {tool!r} (not found)")
    cfg = config.load(vault).connectors
    started = time.perf_counter()
    secret: str | None = None
    try:
        url, rest = _build_url(connector, spec, args)
        headers, secret = _auth_headers(connector, vault)
        result = await _send(connector, spec, url, rest, headers, secret, cfg, started)
    except _Refused as e:
        result = _error(started, e.code, str(e))
    if result.error is not None:
        message = _mask(str(result.error.get("message", "")), secret)
        result = result.model_copy(update={"error": {"code": result.error["code"], "message": message}})
    log.info(
        "connector %s.%s: %s in %d ms", connector_id, tool,
        "ok" if result.ok else result.error["code"], result.latency_ms,
    )
    return result


def model_message(result: ConnectorResult, connector_id: str, tool: str, max_tokens: int) -> str:
    """Render a result as the tool message for the model.

    Behavior:
        Success is `{"connector", "tool", "data"}`; an error is `{"connector", "tool", "error"}`.
        Text over `max_tokens` (`tokens.count`) is cut and ends with `... (truncated)`.
    Returns:
        The JSON text for the model.
    Parameters:
        result: The connector result.
        connector_id: Connector id.
        tool: Tool name.
        max_tokens: Token limit (`connectors.max_result_tokens`).
    """
    payload: dict[str, Any] = {"connector": connector_id, "tool": tool}
    if result.ok:
        payload["data"] = result.data
    else:
        payload["error"] = result.error
    text = json.dumps(payload, ensure_ascii=False)
    count = tokens.count(text)
    if count <= max_tokens:
        return text
    budget = max_tokens - tokens.count(TRUNCATED_SUFFIX)
    cut = int(len(text) * budget / count)
    while cut > 0 and tokens.count(text[:cut]) > budget:
        cut = int(cut * TRIM_STEP)
    return text[:cut] + TRUNCATED_SUFFIX


def _build_url(connector: Connector, tool: ConnectorTool, args: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(args, dict):
        raise _Refused(BAD_ARGUMENTS, "arguments must be a JSON object")
    declared = {p.name: p for p in tool.params}
    present = {k: v for k, v in args.items() if v is not None}
    undeclared = sorted(set(present) - set(declared))
    if undeclared:
        raise _Refused(BAD_ARGUMENTS, f"undeclared argument(s): {', '.join(undeclared)}")
    missing = [p.name for p in tool.params if p.required and p.name not in present]
    for name in _PLACEHOLDER.findall(tool.path):
        if name not in declared:
            raise _Refused(BAD_ARGUMENTS, f"path placeholder {{{name}}} is not a declared parameter")
        if name not in present and name not in missing:
            missing.append(name)
    if missing:
        raise _Refused(BAD_ARGUMENTS, f"missing required argument(s): {', '.join(missing)}")
    for name, value in present.items():
        _check_type(declared[name], value)

    used: set[str] = set()

    def fill(match: re.Match) -> str:
        name = match.group(1)
        text = _as_text(present[name])
        if any(c in text for c in PATH_FORBIDDEN) or text in DOT_SEGMENTS:
            raise _Refused(BAD_ARGUMENTS, f"{name} may not contain '/', '\\' or be a dot segment")
        used.add(name)
        return quote(text, safe="")

    url = connector.base_url.rstrip("/") + _PLACEHOLDER.sub(fill, tool.path)
    _check_inside(connector.base_url, url)
    return url, {k: v for k, v in present.items() if k not in used}


def _check_type(param: ConnectorParam, value: Any) -> None:
    allowed = _JSON_TYPES[param.type]
    if isinstance(value, bool) and param.type != "boolean" or not isinstance(value, allowed):
        raise _Refused(BAD_ARGUMENTS, f"{param.name} must be a {param.type}")


def _check_inside(base_url: str, url: str) -> None:
    base, target = urlsplit(base_url.rstrip("/")), urlsplit(url)
    segments = unquote(target.path).split("/")
    inside = (
        url.startswith(base_url.rstrip("/"))
        and (target.scheme, target.netloc) == (base.scheme, base.netloc)
        and (target.path == base.path or target.path.startswith(base.path + "/"))
        and not any(s in DOT_SEGMENTS for s in segments)
    )
    if not inside:
        raise _Refused(BAD_ARGUMENTS, "the request URL would leave the connector's base_url")


def _auth_headers(connector: Connector, vault: Vault) -> tuple[dict[str, str], str | None]:
    auth = connector.auth
    if auth.type == "none":
        return {}, None
    try:
        secret = keystore.lookup_secret(auth.env_var, vault) if auth.env_var else None
    except PamError:
        secret = None
    if not secret:
        raise _Refused(MISSING_SECRET, f"secret {auth.env_var or '(auth.env_var not set)'} is not set")
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {secret}"}, secret
    return {auth.header or DEFAULT_API_KEY_HEADER: secret}, secret


async def _send(
    connector: Connector, tool: ConnectorTool, url: str, rest: dict[str, Any],
    headers: dict[str, str], secret: str | None, cfg: ConnectorsCfg, started: float,
) -> ConnectorResult:
    if tool.method == "GET":
        request = {"params": {k: _as_text(v) for k, v in rest.items()}}
    else:
        request = {"json": rest}
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds, follow_redirects=False) as client:
            async with client.stream(tool.method, url, headers=headers, **request) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > cfg.max_response_bytes:
                        return _error(
                            started, BAD_RESPONSE, f"response is larger than {cfg.max_response_bytes} bytes",
                            response.status_code,
                        )
    except httpx.TimeoutException:
        return _error(started, TIMEOUT, f"{connector.name} did not answer within {cfg.timeout_seconds} s")
    except httpx.HTTPError as e:
        return _error(started, UNREACHABLE, f"{connector.name} is unreachable ({type(e).__name__})")
    status = response.status_code
    if not 200 <= status < 300:
        return _error(started, f"HTTP_{status}", f"{connector.name} answered HTTP {status}", status)
    try:
        text = bytes(body).decode("utf-8")
        if secret:
            text = text.replace(secret, keystore.REDACTED)  # a service that echoes the secret back
        parsed = json.loads(text)
    except ValueError:
        return _error(started, BAD_RESPONSE, "response is not JSON", status)
    if not isinstance(parsed, (dict, list)):
        return _error(started, BAD_RESPONSE, "response is not a JSON object or array", status)
    data, cards = extract_cards(parsed, connector)
    return ConnectorResult(ok=True, status=status, latency_ms=_elapsed(started), data=data, cards=cards)


def _error(started: float, code: str, message: str, status: int | None = None) -> ConnectorResult:
    return ConnectorResult(
        ok=False, status=status, latency_ms=_elapsed(started), error={"code": code, "message": message},
    )


def _mask(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, keystore.REDACTED)
    return keystore.redact(text)


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
