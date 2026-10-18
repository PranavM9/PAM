"""`GET /api/vault/tree` and `GET /api/vault/file`: scope-filtered vault browsing (SPEC §7.14)."""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pam.agents.manifest import load_manifest
from pam.agents.permissions import can_read, doc_ref_from_path
from pam.api.deps import get_vault
from pam.api.errors import NOT_FOUND, PERMISSION_DENIED, VALIDATION_ERROR, ApiError
from pam.contracts.agent import AgentManifest
from pam.core import mdio
from pam.core.vault import Vault

router = APIRouter(tags=["vault"])

_DRIVE = re.compile(r"^[A-Za-z]:")


class VaultTree(BaseModel):
    paths: list[str]


class VaultFile(BaseModel):
    path: str
    frontmatter: dict
    body: str


def _readable(manifest: AgentManifest, rel: str, vault: Vault) -> bool:
    """Apply the agent's read scope to a vault-relative path.

    Behavior:
        `read.all` sees everything. Otherwise memory and skill documents follow `can_read`, and any
        other file is visible only under the agent's own `agent/<name>/` folder.
    """
    if manifest.read.all:
        return True
    ref = doc_ref_from_path(rel)
    if ref is not None:
        return can_read(manifest, ref, vault)
    return rel.startswith(f"agent/{manifest.name}/")


def _check_path(path: str) -> None:
    parts = path.split("/")
    bad = (
        not path
        or "\\" in path
        or "\x00" in path
        or path.startswith("/")
        or _DRIVE.match(path)
        or any(part in ("", ".", "..") or part.startswith(".") for part in parts)
    )
    if bad:
        raise ApiError(400, VALIDATION_ERROR, "path must be a vault-relative POSIX path")
    if not path.endswith(".md"):
        raise ApiError(400, VALIDATION_ERROR, "only Markdown files can be read")


@router.get("/vault/tree", response_model=VaultTree)
def vault_tree(agent: str = "default", vault: Vault = Depends(get_vault)) -> VaultTree:
    """List the Markdown files an agent may read.

    Behavior:
        Walks the vault, skipping hidden folders (`.git`, `.pam`), and returns vault-relative POSIX
        paths sorted alphabetically, filtered by the agent's read scope.
    Exceptions:
        PamError: The agent does not exist (404) or its name is invalid (400).
    Returns:
        The visible paths.
    Parameters:
        agent: Agent whose scope filters the list.
        vault: The served vault.
    """
    manifest = load_manifest(agent, vault)
    found: list[str] = []
    for folder, dirs, files in os.walk(vault.root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.endswith(".md"):
                found.append(vault.rel(os.path.join(folder, name)))
    return VaultTree(paths=sorted(p for p in found if _readable(manifest, p, vault)))


@router.get("/vault/file", response_model=VaultFile)
def vault_file(path: str, agent: str = "default", vault: Vault = Depends(get_vault)) -> VaultFile:
    """Read one Markdown file as frontmatter and body.

    Behavior:
        Rejects absolute paths, drive letters, backslashes, `..` and hidden segments (400), checks
        the agent's read scope before touching the disk (403), then reads the file (404 if absent).
        A path that resolves outside the vault, for example through a symlink, is rejected.
    Exceptions:
        ApiError: Invalid path (400), outside the agent's scope (403), or no such file (404).
        PamError: The agent does not exist (404).
    Returns:
        The path, parsed frontmatter and body.
    Parameters:
        path: Vault-relative POSIX path.
        agent: Agent whose scope applies.
        vault: The served vault.
    """
    _check_path(path)
    manifest = load_manifest(agent, vault)
    if not _readable(manifest, path, vault):
        raise ApiError(403, PERMISSION_DENIED, f"agent {agent!r} may not read {path}")
    target = vault.abs(path)
    try:
        target.resolve().relative_to(vault.root.resolve())
    except ValueError as exc:
        raise ApiError(400, VALIDATION_ERROR, "path resolves outside the vault") from exc
    if not target.is_file():
        raise ApiError(404, NOT_FOUND, f"{path} not found")
    frontmatter, body = mdio.read(target)
    return VaultFile(path=path, frontmatter=frontmatter, body=body)
