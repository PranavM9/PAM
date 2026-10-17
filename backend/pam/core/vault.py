"""Vault path resolution, SPEC §6 path helpers, and vault creation for `pam init`.

Behavior:
    The vault root resolves from an explicit argument, then the global `pam --vault`, then
    `PAM_VAULT`. Every path stored in a contract comes from `Vault.rel()` (vault-relative POSIX).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, get_args
from uuid import UUID

import yaml

from pam.contracts.agent import AgentManifest, ReadScope, ToolName
from pam.core import mdio
from pam.core.errors import PamError, VaultNotFound
from pam.core.time import utcnow

ENV_VAR = "PAM_VAULT"
CONFIG_FILE = "pam.toml"
PersonaKind = Literal["identity", "rules", "style"]
PERSONA_KINDS: tuple[PersonaKind, ...] = get_args(PersonaKind)

GIT_AUTHOR_NAME = "PAM"
GIT_AUTHOR_EMAIL = "pam@local"

PERSONA_TEMPLATE = (
    "## Derived (auto-generated — edits here are overwritten by `pam derive`)\n"
    "\n"
    "## Custom (yours — never touched by PAM)\n"
)
GITATTRIBUTES = "* text eol=lf\n"
GITIGNORE = ".pam/\n"

_override: Path | None = None


def set_vault_override(path: str | os.PathLike | None) -> None:
    """Set the vault chosen by the global `pam --vault PATH` option.

    Behavior:
        The override takes precedence over `PAM_VAULT`; `None` clears it.
    Parameters:
        path: Vault folder, or `None`.
    """
    global _override
    _override = Path(path) if path is not None else None


def resolve_vault(path: str | os.PathLike | None = None) -> Path:
    """Resolve the vault root folder.

    Behavior:
        Uses `path`, then the global `--vault` override, then `PAM_VAULT`. The folder need not exist.
    Exceptions:
        VaultNotFound: None of the three sources is set.
    Returns:
        The absolute vault path.
    Parameters:
        path: Explicit vault folder, or `None`.
    """
    if path is not None:
        chosen = Path(path)
    elif _override is not None:
        chosen = _override
    elif os.environ.get(ENV_VAR):
        chosen = Path(os.environ[ENV_VAR])
    else:
        raise VaultNotFound(f"no vault given: pass --vault PATH or set {ENV_VAR}")
    return chosen.expanduser().resolve()


class Vault:
    """Path helpers for one vault (SPEC §6).

    Behavior:
        Builds absolute paths for every vault file type and converts them to vault-relative POSIX
        paths. Creates nothing on disk.
    Parameters:
        root: Vault folder.
    """

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def resolve(cls, path: str | os.PathLike | None = None) -> Vault:
        """Create a `Vault` from `resolve_vault(path)`."""
        return cls(resolve_vault(path))

    def __repr__(self) -> str:
        return f"Vault({str(self.root)!r})"

    # -- fixed files -------------------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_FILE

    @property
    def pam_dir(self) -> Path:
        return self.root / ".pam"

    @property
    def index_db(self) -> Path:
        return self.pam_dir / "index.db"

    @property
    def lock_path(self) -> Path:
        return self.pam_dir / "write.lock"

    def is_initialized(self) -> bool:
        return self.config_path.is_file()

    def require_initialized(self) -> Vault:
        """Return this vault if it has a `pam.toml`.

        Exceptions:
            VaultNotFound: The folder is not an initialized vault.
        Returns:
            This vault.
        """
        if not self.is_initialized():
            raise VaultNotFound(f"{self.root} is not a PAM vault (no {CONFIG_FILE}); run `pam init`")
        return self

    # -- §6 path helpers ---------------------------------------------------------------------
    def agent_dir(self, name: str) -> Path:
        return self.root / "agent" / name

    def manifest_path(self, name: str) -> Path:
        return self.agent_dir(name) / "agent.yaml"

    def persona_path(self, name: str, kind: PersonaKind) -> Path:
        if kind not in PERSONA_KINDS:
            raise ValueError(f"unknown persona file {kind!r}")
        return self.agent_dir(name) / f"{kind}.md"

    def import_dir(self, source: str, ts: datetime) -> Path:
        return self.root / "imports" / source / ts.strftime("%Y%m%dT%H%M%SZ")

    def memory_dir(self, scope: str) -> Path:
        return self.root / "memory" / scope

    def episode_path(self, agent: str, id: UUID | str) -> Path:
        return self.memory_dir(agent) / "episodes" / f"{id}.md"

    def fact_path(self, scope: str, id: UUID | str) -> Path:
        return self.memory_dir(scope) / "facts" / f"{id}.md"

    def project_path(self, scope: str, id: UUID | str) -> Path:
        return self.memory_dir(scope) / "projects" / f"{id}.md"

    def skill_path(self, scope: str, id: UUID | str) -> Path:
        return self.root / "skills" / scope / f"{id}.md"

    def working_path(self, session_id: str) -> Path:
        return self.root / "working" / f"{session_id}.md"

    # -- conversions -------------------------------------------------------------------------
    def rel(self, path: str | os.PathLike) -> str:
        """Convert a path to the vault-relative POSIX form used in contracts.

        Behavior:
            Relative inputs are taken as relative to the vault root. Uses forward slashes on Windows.
        Exceptions:
            ValueError: The path is outside the vault.
        Returns:
            The vault-relative path, e.g. `memory/shared/facts/<id>.md`.
        Parameters:
            path: Absolute or vault-relative path.
        """
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve().relative_to(self.root).as_posix()

    def abs(self, rel_path: str) -> Path:
        """Convert a vault-relative POSIX path to an absolute path."""
        return self.root / Path(*rel_path.split("/"))


# -- pam init -------------------------------------------------------------------------------

@dataclass
class InitResult:
    """Outcome of `init_vault`; `created` is false when the vault already existed."""

    root: Path
    created: bool                        # False ⇒ vault already existed, nothing was done
    commit_sha: str | None = None
    files: list[str] = field(default_factory=list)


def default_manifest() -> AgentManifest:
    """Build the manifest for the `default` agent.

    Behavior:
        Follows §7.7: `origin="derived"`, `read.all=True`, `write="shared"`, and all tools.
    Returns:
        The default agent manifest.
    """
    return AgentManifest(
        name="default",
        display_name="Default",
        description="Auto-derived agent that sees all of your memory.",
        origin="derived",
        created_at=utcnow(),
        read=ReadScope(all=True),
        write="shared",
        tools=list(get_args(ToolName)),
    )


def _git(root: Path, *args: str) -> str:
    # Minimal git runner for init only; T02's `pam.sync.git` is the commit helper for all other writers.
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError as e:
        raise PamError("git is not installed or not on PATH") from e
    except subprocess.CalledProcessError as e:
        raise PamError(f"git {' '.join(args)} failed: {e.stderr.strip() or e.stdout.strip()}") from e
    return out.stdout.strip()


def init_vault(path: str | os.PathLike | None = None) -> InitResult:
    """Create a new vault with its git repo and exactly one commit.

    Behavior:
        Creates the §6 folders, `.gitattributes`, `.gitignore`, a default `pam.toml`, and
        `agent/default/` (manifest plus empty persona files), then runs `git init -b main`, sets
        `core.autocrlf=false`, and commits as `PAM <pam@local>`. Does nothing if the vault exists.
    Exceptions:
        VaultNotFound: No vault path is given or configured.
        PamError: The path is a non-empty folder without `pam.toml`, is a file, or a git command fails.
    Returns:
        The created root, whether anything was created, the commit sha, and the committed files.
    Parameters:
        path: Vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    from pam.contracts.config import PamConfig
    from pam.core.config import dump_toml

    vault = Vault.resolve(path)
    root = vault.root
    if vault.is_initialized():
        return InitResult(root=root, created=False)
    if root.exists() and not root.is_dir():
        raise PamError(f"{root} exists and is not a directory")
    if root.is_dir() and any(root.iterdir()):
        raise PamError(f"{root} is not empty and is not a PAM vault (no {CONFIG_FILE}); refusing to init")

    for d in (
        vault.pam_dir,
        vault.agent_dir("default"),
        vault.root / "imports",
        vault.memory_dir("shared") / "facts",
        *(vault.memory_dir("default") / sub for sub in ("episodes", "facts", "projects")),
        vault.root / "skills" / "default",
        vault.root / "working",
    ):
        d.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def put(p: Path, text: str) -> None:
        mdio.write_text(p, text)
        written.append(p)

    put(root / ".gitattributes", GITATTRIBUTES)
    put(root / ".gitignore", GITIGNORE)
    put(vault.config_path, dump_toml(PamConfig()))
    manifest = default_manifest().model_dump(mode="json")
    put(vault.manifest_path("default"), yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
    for kind in PERSONA_KINDS:
        put(vault.persona_path("default", kind), PERSONA_TEMPLATE)

    files = [vault.rel(p) for p in written]
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "add", "--", *files)
    _git(
        root,
        "-c", f"user.name={GIT_AUTHOR_NAME}",
        "-c", f"user.email={GIT_AUTHOR_EMAIL}",
        "commit", "-q", "-m", "pam: init vault",
        "--author", f"{GIT_AUTHOR_NAME} <{GIT_AUTHOR_EMAIL}>",
    )
    return InitResult(root=root, created=True, commit_sha=_git(root, "rev-parse", "HEAD"), files=files)
