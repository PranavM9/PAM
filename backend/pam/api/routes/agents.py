"""`/api/agents`: list, read, create and update agents with their persona Custom sections (SPEC §7.14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from pam.agents.manifest import (
    CUSTOM_HEADING,
    create_agent,
    list_agents,
    load_manifest,
    load_persona,
    save_manifest,
)
from pam.api.deps import get_vault
from pam.api.errors import VALIDATION_ERROR, ApiError
from pam.contracts.agent import AgentManifest, Persona
from pam.core import mdio
from pam.core.lock import vault_write_lock
from pam.core.vault import PERSONA_KINDS, PERSONA_TEMPLATE, Vault
from pam.sync import git

router = APIRouter(tags=["agents"])

_CUSTOM_LINE = PERSONA_TEMPLATE.splitlines()[2]


class AgentDetail(BaseModel):
    manifest: AgentManifest
    persona: Persona


class AgentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: AgentManifest
    identity_custom: str = ""
    rules_custom: str = ""
    style_custom: str = ""


def with_custom(text: str, custom: str) -> str:
    """Return a persona file with its Custom section replaced.

    Behavior:
        Everything up to and including the `## Custom` heading is kept byte-exact (so the Derived
        section is untouched); the text after it becomes `custom`. A file without the heading
        gets the standard one appended.
    Returns:
        The new file contents.
    Parameters:
        text: Current file contents.
        custom: New Custom section body.
    """
    lines = text.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.startswith(CUSTOM_HEADING)), None)
    if index is None:
        head = text if not text or text.endswith("\n") else text + "\n"
        head += _CUSTOM_LINE + "\n"
    else:
        head = "".join(lines[: index + 1])
        if not head.endswith("\n"):
            head += "\n"
    body = custom.strip()
    return head + (f"\n{body}\n" if body else "")


def _write_customs(vault: Vault, data: AgentWrite) -> list:
    name = data.manifest.name
    customs = {"identity": data.identity_custom, "rules": data.rules_custom, "style": data.style_custom}
    paths = []
    for kind in PERSONA_KINDS:
        path = vault.persona_path(name, kind)
        current = path.read_text(encoding="utf-8") if path.is_file() else PERSONA_TEMPLATE
        updated = with_custom(current, customs[kind])
        if updated != current or not path.is_file():
            mdio.write_text(path, updated)
            paths.append(path)
    return paths


def _raw_persona(vault: Vault, name: str) -> Persona:
    persona = load_persona(name, vault)
    texts = {}
    for kind in ("identity", "style"):
        path = vault.persona_path(name, kind)
        texts[kind] = path.read_text(encoding="utf-8") if path.is_file() else PERSONA_TEMPLATE
    return persona.model_copy(update={"identity": texts["identity"], "style": texts["style"]})


@router.get("/agents", response_model=list[AgentManifest])
def get_agents(vault: Vault = Depends(get_vault)) -> list[AgentManifest]:
    """List every agent's manifest."""
    return list_agents(vault)


@router.get("/agents/{name}", response_model=AgentDetail)
def get_agent(name: str, vault: Vault = Depends(get_vault)) -> AgentDetail:
    """Return an agent's manifest and persona.

    Behavior:
        `persona.identity` and `persona.style` are the files' full text including the Derived and
        Custom headings, so the editor can show the Custom part (CHG-0016 (M14), item 6);
        `persona.rules` lists derived rules, then manual ones.
    Exceptions:
        PamError: The agent does not exist (404) or its name is invalid (400).
    Returns:
        The manifest and persona.
    Parameters:
        name: Agent name.
        vault: The served vault.
    """
    return AgentDetail(manifest=load_manifest(name, vault), persona=_raw_persona(vault, name))


@router.post("/agents", response_model=AgentManifest, status_code=201)
def create_agent_route(data: AgentWrite, vault: Vault = Depends(get_vault)) -> AgentManifest:
    """Create an agent and fill its persona Custom sections.

    Behavior:
        Creates the agent with `create_agent` (one commit). When any Custom text is given it is
        written and committed as a second commit `pam: edit persona <name>`.
    Exceptions:
        PamError: The agent already exists (409).
    Returns:
        The saved manifest.
    Parameters:
        data: Manifest and the three Custom section texts.
        vault: The served vault.
    """
    create_agent(data.manifest, vault)
    if data.identity_custom.strip() or data.rules_custom.strip() or data.style_custom.strip():
        with vault_write_lock(vault):
            paths = _write_customs(vault, data)
            if paths:
                git.commit(vault.root, paths, f"pam: edit persona {data.manifest.name}")
    return load_manifest(data.manifest.name, vault)


@router.put("/agents/{name}", response_model=AgentManifest)
def update_agent(name: str, data: AgentWrite, vault: Vault = Depends(get_vault)) -> AgentManifest:
    """Replace an agent's manifest and persona Custom sections in one commit.

    Behavior:
        The manifest name must match the path. Derived sections are never touched. A request that
        changes nothing makes no commit.
    Exceptions:
        ApiError: The manifest name differs from the path (400).
        PamError: The agent does not exist (404).
    Returns:
        The saved manifest.
    Parameters:
        name: Agent to update.
        data: Manifest and the three Custom section texts.
        vault: The served vault.
    """
    if data.manifest.name != name:
        raise ApiError(400, VALIDATION_ERROR, "manifest.name must match the URL")
    load_manifest(name, vault)
    with vault_write_lock(vault):
        paths = [save_manifest(data.manifest, vault), *_write_customs(vault, data)]
        if git.run(vault.root, "status", "--porcelain", "--", *[str(p) for p in paths]).stdout.strip():
            git.commit(vault.root, paths, f"pam: update agent {name}")
    return load_manifest(name, vault)
