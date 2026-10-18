"""MCP server factory: one server per agent for stdio, one ASGI app for streamable HTTP (SPEC §8 M11).

Behavior:
    `build_server` binds a vault and an agent and registers only the tools that agent may call.
    `http_app` returns an ASGI app that serves every agent: the `?agent=` query parameter of each
    request (default `default`) picks the server, built on first use. Importing this module has no
    side effects, so T14 can mount `http_app` at `/mcp` in the FastAPI app.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import parse_qs

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from pam.agents import manifest as agents
from pam.agents.permissions import can_call
from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.mcp_server.tools import TOOL_SPECS, Binding, make_tool

INSTRUCTIONS = (
    "Call get_context at the start of a task and whenever the topic changes. "
    "If conflicts are returned, ask the user and then call supersede_fact. "
    "Log important new facts with add_fact. Never invent memories."
)
DEFAULT_AGENT = "default"

# The REST API that T14 serves next to this app has no host check either, so the check is off.
_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _resolve(vault: Vault | str | os.PathLike | None) -> Vault:
    resolved = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    return resolved.require_initialized()


def build_server(vault: Vault | str | os.PathLike | None, agent: str = DEFAULT_AGENT) -> MCPServer:
    """Create an MCP server bound to one agent.

    Behavior:
        Loads the agent's manifest and registers, in `ToolName` order, each tool the manifest lists
        and `can_call` allows. Tools the agent may not call are not advertised, so the SDK rejects
        calls to them.
    Exceptions:
        PamError: The agent does not exist or its manifest is invalid.
    Returns:
        The server, ready for `run("stdio")` or `streamable_http_app()`.
    Parameters:
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        agent: Name of the agent every call acts for.
    """
    bound_vault = _resolve(vault)
    try:
        manifest = agents.load_manifest(agent, bound_vault)
    except PamError as exc:
        raise PamError(f"cannot serve MCP for agent {agent!r}: {exc}", exit_code=exc.exit_code) from exc
    server = MCPServer(name=f"pam-{agent}", instructions=INSTRUCTIONS)
    binding = Binding(bound_vault, agent)
    for name, spec in TOOL_SPECS.items():
        if can_call(manifest, name):
            server.add_tool(make_tool(spec, binding), name=name, description=spec.description)
    return server


class McpHttpApp:
    """ASGI app that routes each request to the streamable-HTTP server of its `?agent=` agent.

    Behavior:
        Answers on any path, so it works at `/mcp` standalone and when mounted under `/mcp`. Session
        managers need a running task group: the ASGI lifespan starts it, and without a lifespan
        (a mount that does not forward it) the first request starts it. An unknown agent gets 404.
    """

    def __init__(self, vault: Vault | str | os.PathLike | None) -> None:
        self._vault = _resolve(vault)
        self._managers: dict[str, Any] = {}
        self._group: anyio.abc.TaskGroup | None = None
        self._owner: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._lock: asyncio.Lock | None = None

    async def start(self) -> None:
        """Start the task group that runs the session managers; safe to call twice."""
        if self._owner is not None:
            return
        self._stop, self._lock = asyncio.Event(), asyncio.Lock()
        ready = asyncio.Event()
        self._owner = asyncio.get_running_loop().create_task(self._own(ready))
        await ready.wait()

    async def stop(self) -> None:
        """Stop every session manager and wait for them."""
        if self._owner is None or self._stop is None:
            return
        self._stop.set()
        await self._owner
        self._owner = self._group = self._stop = self._lock = None
        self._managers.clear()

    async def _own(self, ready: asyncio.Event) -> None:
        async with anyio.create_task_group() as group:
            self._group = group
            ready.set()
            assert self._stop is not None
            await self._stop.wait()
            group.cancel_scope.cancel()

    @staticmethod
    async def _run_manager(server: MCPServer, *, task_status: Any = anyio.TASK_STATUS_IGNORED) -> None:
        async with server.session_manager.run():
            task_status.started()
            await anyio.sleep_forever()

    async def _manager(self, agent: str) -> Any:
        assert self._lock is not None and self._group is not None
        async with self._lock:
            manager = self._managers.get(agent)
            if manager is None:
                server = await anyio.to_thread.run_sync(build_server, self._vault, agent)
                server.streamable_http_app(streamable_http_path="/", transport_security=_SECURITY)
                await self._group.start(self._run_manager, server)
                manager = self._managers[agent] = server.session_manager
            return manager

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)

    async def _lifespan(self, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await self.start()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.stop()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _http(self, scope: dict, receive: Any, send: Any) -> None:
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        agent = (query.get("agent") or [DEFAULT_AGENT])[0]
        await self.start()
        try:
            manager = await self._manager(agent)
        except PamError as exc:
            await _reply(send, 404, {"error": str(exc)})
            return
        await manager.handle_request(scope, receive, send)


async def _reply(send: Any, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def http_app(vault: Vault | str | os.PathLike | None = None) -> McpHttpApp:
    """Create the streamable-HTTP ASGI app for all agents of a vault.

    Behavior:
        The agent is chosen per request from `?agent=` (default `default`); servers are built on
        first use and a manifest edit takes effect after a restart.
    Exceptions:
        VaultNotFound: No initialized vault resolves.
    Returns:
        An ASGI app; mount it at `/mcp` or serve it directly.
    Parameters:
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    return McpHttpApp(vault)
