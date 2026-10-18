"""§7.1 Common — transcribed verbatim from SPEC.md. Do not edit without an APPROVED §10 change."""

from __future__ import annotations
from enum import Enum
from typing import Annotated
from uuid import UUID, NAMESPACE_URL, uuid5
from pydantic import BaseModel, ConfigDict, StringConstraints

SCHEMA_VERSION = "1.1.0"
PAM_NAMESPACE: UUID = uuid5(NAMESPACE_URL, "https://pam.local/v1")   # never change

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
SnakeKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
VaultPath = Annotated[str, StringConstraints(pattern=r"^[^\\:]+$")]  # vault-relative POSIX
RESERVED_SCOPES = {"shared"}            # cannot be used as an agent name

class Source(str, Enum):
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    PAM = "pam"          # logged by an agent / promoted session
    MANUAL = "manual"    # written by the user by hand

class Actor(str, Enum):
    RULE = "rule"        # rule-based extractor (M3)
    AGENT = "agent"      # an LLM via MCP/chat
    MANUAL = "manual"    # the user (UI or text editor)
    CLUSTER = "cluster"  # clusterer (M5)

class PamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: str = SCHEMA_VERSION
