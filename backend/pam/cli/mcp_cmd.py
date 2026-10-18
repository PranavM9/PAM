"""`pam mcp serve|tools`: run the MCP server over stdio or HTTP, or list an agent's tools (SPEC §8 M11)."""

from __future__ import annotations

from enum import Enum

import typer

from pam.core.vault import Vault

app = typer.Typer(help="Serve PAM over MCP.", no_args_is_help=True)


class Transport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


@app.command("serve")
def serve(
    transport: Transport = typer.Option(Transport.STDIO, "--transport", help="stdio or http."),
    agent: str = typer.Option("default", "--agent", help="Agent the stdio server is bound to."),
    host: str = typer.Option("127.0.0.1", "--host", help="http only: bind address."),
    port: int = typer.Option(8765, "--port", help="http only: port."),
) -> None:
    """Serve the MCP tools; stdio binds one agent, http picks the agent per request (`?agent=`)."""
    from pam.mcp_server.server import build_server, http_app  # lazy: keeps `pam --help` fast

    vault = Vault.resolve().require_initialized()
    if transport is Transport.STDIO:
        build_server(vault, agent).run("stdio")
        return
    import uvicorn

    uvicorn.run(http_app(vault), host=host, port=port, log_level="info")


@app.command("tools")
def tools(agent: str = typer.Option("default", "--agent", help="Agent to list tools for.")) -> None:
    """List the tools an agent would see."""
    import anyio

    from pam.mcp_server.server import build_server

    server = build_server(Vault.resolve().require_initialized(), agent)
    for tool in anyio.run(server.list_tools):
        typer.echo(tool.name)
