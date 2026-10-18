"""`pam api serve`: run the REST API, `/mcp` and `/docs` with uvicorn (SPEC §8 M13, SETUP §5)."""

from __future__ import annotations

import os

import typer

from pam.core.vault import Vault

api_app = typer.Typer(help="Run the REST API.", no_args_is_help=True)


@api_app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address."),  # noqa: S104 - container default
    port: int = typer.Option(8000, "--port", help="Port."),
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes (development)."),
) -> None:
    """Serve `/api/*`, `/mcp` and `/docs` for the active vault.

    Behavior:
        Resolves the vault (`--vault`, then `PAM_VAULT`), then starts uvicorn on one process. Chat
        calls this server's own `/mcp/` over loopback; set `PAM_MCP_URL` to override.
    """
    import uvicorn  # noqa: PLC0415 - keeps `pam --help` fast

    vault = Vault.resolve().require_initialized()
    os.environ["PAM_VAULT"] = str(vault.root)
    os.environ.setdefault("PAM_MCP_URL", f"http://127.0.0.1:{port}/mcp/")
    uvicorn.run("pam.api.app:app_from_env", factory=True, host=host, port=port, reload=reload)


def register(app: typer.Typer) -> None:
    app.add_typer(api_app, name="api")
