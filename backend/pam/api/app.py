"""M13 REST API app factory: `/api/*` routes, `/mcp` mount, CORS and OpenAPI at `/docs` (SPEC §8 M13)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pam import __version__
from pam.api import errors
from pam.api.jobs import JobRegistry
from pam.api.routes import agents, chat, graph, health, imports, search, sessions, settings, sync, vault
from pam.chat import keystore
from pam.core.vault import Vault
from pam.mcp_server.server import http_app

CORS_ORIGINS = ["http://localhost:5173"]
ROUTERS = (health, imports, vault, search, graph, agents, chat, settings, sessions, sync)


def create_app(vault_path: str | os.PathLike | None = None, *, mcp_url: str | None = None) -> FastAPI:
    """Create the REST API app for one vault.

    Behavior:
        Mounts every §7.14 route under `/api`, the MCP streamable-HTTP app at `/mcp`, CORS for
        `http://localhost:5173` and the `{"error": {...}}` handlers. The MCP session managers start
        and stop with the app's lifespan. Chat reaches MCP in-process unless `mcp_url` is given.
    Exceptions:
        VaultNotFound: The path is not an initialized vault.
    Returns:
        The FastAPI app; its state holds `vault`, `jobs` and `mcp_url`.
    Parameters:
        vault_path: Vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        mcp_url: Public URL of this app's `/mcp/` mount for chat to call, or `None` for in-process.
    """
    root = Vault.resolve(vault_path).require_initialized()
    mcp = http_app(root)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await mcp.start()
        try:
            yield
        finally:
            await mcp.stop()

    app = FastAPI(title="PAM API", version=__version__, lifespan=lifespan)
    app.state.vault = root
    keystore.bind(root)
    app.state.jobs = JobRegistry()
    app.state.mcp_url = mcp_url
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    errors.install(app)
    for module in ROUTERS:
        app.include_router(module.router, prefix="/api")
    app.mount("/mcp", mcp)
    return app


def app_from_env() -> FastAPI:
    """Create the app from `PAM_VAULT` and `PAM_MCP_URL` (uvicorn factory, also used by `--reload`)."""
    vault_path = os.environ.get("PAM_VAULT")
    return create_app(Path(vault_path) if vault_path else None, mcp_url=os.environ.get("PAM_MCP_URL") or None)
