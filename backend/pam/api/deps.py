"""FastAPI dependencies shared by the route modules."""

from __future__ import annotations

from fastapi import Request

from pam.api.jobs import JobRegistry
from pam.core.vault import Vault


def get_vault(request: Request) -> Vault:
    """Return the vault the app was created for."""
    return request.app.state.vault


def get_jobs(request: Request) -> JobRegistry:
    """Return the app's import job registry."""
    return request.app.state.jobs
