# PAM — Portable Agent Memory · Technical Spec

> **Status:** v1.0.0 (baseline, see CHG-0000) · **Event:** DubHacks (24 h) · **Team:** 3
> **Companion docs:** [`SETUP.md`](./SETUP.md) (install + full CLI reference) · [`research/TODO.md`](./research/TODO.md) (what we need to learn)

## 0. How to use this spec (read first — humans and agents)

1. This spec is the **single source of truth**. Code that disagrees with the spec is wrong unless an **APPROVED** change in §10 says otherwise.
2. Modules are built **sequentially** in the order of §9. Each module ships with its CLI commands, and those commands are its test harness.
3. **Agents may edit only** the paths listed under *Allowed paths* for their current task (§9), plus **append** to §10 *Changes*.
4. **Agents never delete** anything in this spec, in §10, or in the vault's episode bodies. Corrections are new appended entries.
5. **Any change to a data contract (§7) requires human approval.** The agent appends a `PROPOSED` change entry and **stops**. A human appends `APPROVED` or `REJECTED`, and only then may the agent implement it.
6. Every section below is tagged with who may edit it:
   - 🔒 **human-only**: changes go through §10 and are applied by a human.
   - ➕ **append-only**: agents may add, but never edit or delete existing text.

---

## 1. Goals and non-goals 🔒

### 1.1 Problem
Switching LLM providers (Claude → ChatGPT → a local model) loses all accumulated context. Users either start over or paste huge histories, wasting tokens and time.

### 1.2 Goals
| # | Goal | Measurable "done" |
|---|------|-------------------|
| G1 | Import chat exports from **Claude (P0)**, **ChatGPT (P1)**, **Gemini (P1, best-effort)** | `pam import <file>` writes one episode `.md` per conversation; re-running it is idempotent |
| G2 | Normalize history into a **human-readable, git-tracked Markdown vault** | The vault opens cleanly in any editor; `git log` shows every change |
| G3 | Derive **facts, persona (identity/rules/style), and projects** **without an LLM** (rule-based + embeddings + clustering) | `pam derive` and `pam cluster` produce files deterministically |
| G4 | Local **hybrid search** (vector + keyword) over the vault with **sqlite-vec + FTS5** | `pam search "q"` returns ranked hits in < 300 ms on 1k episodes |
| G5 | Assemble a **token-budgeted context bundle** per query, and **report the tokens saved** | `ContextBundle.tokens_used ≤ token_budget`; `tokens_saved` is shown in the UI |
| G6 | Expose memory to **any agent via MCP** (stdio + streamable HTTP) | Claude Desktop can call `get_context` and `add_fact` |
| G7 | Let agents **write back** (facts, episodes, projects, skills, working memory), with conflicts surfaced to the LLM, which asks the user | `supersede_fact` updates the fact, keeps its history, and backlinks the episode |
| G8 | Support **per-agent scope**: the default agent sees everything; custom agents see only what the user allows | Out-of-scope reads/writes return a permission error |
| G9 | **Working memory** lets a session hot-swap models mid-conversation without losing the thread | Switching models in the chat UI keeps goal, decisions, and recent turns |
| G10 | **Frontend**: import wizard, Obsidian-style graph, vault browser, search playground, agent editor, chat with model switcher, Markdown guides | Demo flow (§3.3) runs end to end |
| G11 | **Runs anywhere** via Docker Compose (Windows + macOS primary) | `docker compose up` produces a working app on a clean machine |

### 1.3 Non-goals (explicitly out of scope)
- **Encryption, auth, multi-user, cloud sync.** PAM is local-first and single-user.
- **LLM-based extraction or summarization** inside the pipeline. LLMs are only consumers through MCP and chat.
- **Perfect Gemini import.** Best-effort only. Gemini can always *consume* the vault through MCP or the instructions export.
- **Importing images/attachments.** These are stored as references only.
- **Real-time file watching with OS events.** We poll `git status` instead.
- **Automatic deletion of anything.** History is kept in files and in git.
- **Training or fine-tuning models.**
- **Mobile UI.** Desktop browser only.

---

## 2. Glossary 🔒
| Term | Meaning |
|------|---------|
| **Vault** | The Markdown folder that is the source of truth (§6). It is its own git repo. |
| **Episode** | One imported or logged conversation, stored as one `.md` file. The body is **immutable**. |
| **Fact** | A structured statement (`subject` / `attribute` / `value`). It is updated in place, and its history is kept. |
| **Project** | A cluster of related episodes (auto-detected or created by an agent). |
| **Skill** | A reusable procedure (steps) that an agent can recall. |
| **Persona** | An agent's `identity.md`, `rules.md`, and `style.md`. |
| **Agent** | A named configuration (persona + read/write scope + allowed tools). `default` is auto-derived. |
| **Scope** | Where a memory lives: `shared` (facts about the user) or an agent name. |
| **Working memory** | Short-term memory for one chat session (`working/<session_id>.md`). |
| **Context bundle** | The token-budgeted package of persona + facts + projects + snippets + working memory that is given to a model. |
| **Index** | `vault/.pam/index.db`, a derived SQLite DB that can always be rebuilt from the vault. |

---

## 3. User flows 🔒

### 3.1 CLI flow (developer / testing)
```
pam init                                   # create vault + git repo + default agent
pam import ~/Downloads/claude-export.zip   # extract → normalize → episodes (auto-commit)
pam derive                                 # rule-based facts + default persona
pam index                                  # chunk + embed + store (sqlite-vec + FTS5)
pam cluster                                # episodes → projects
pam search "dubhacks frontend"             # hybrid search
pam context "what was I working on?"       # token-budgeted bundle + tokens saved
pam mcp serve --transport stdio            # plug into Claude Desktop
```
The shortcut `pam import <file> --all` runs import → derive → index → cluster in one go.

### 3.2 Frontend flow
1. **Import wizard.** The user picks a source (Claude / ChatGPT / Gemini), reads the Markdown guide for exporting it, and drops the file. A progress bar shows each stage (extract → normalize → derive → index → cluster).
2. **Graph.** An Obsidian-style force graph appears: projects are large nodes, episodes are small nodes, and similarity links connect related episodes. Nodes can be dragged, pinned, and zoomed. Clicking a node opens it in the vault browser.
3. **Vault browser.** A file tree plus a rendered Markdown viewer for any vault file.
4. **Search playground.** Type a query to see ranked hits with their vector and keyword ranks. A *Build context* button shows the full `ContextBundle` with its token counter.
5. **Agents.** Create or edit an agent: name, description, read scope (pick projects), write level, allowed tools, default model, token budget, and persona Markdown editors.
6. **Chat.** Pick an agent and a model, then chat. A side panel shows the injected context and the tokens used vs. saved. You can switch models mid-session, and working memory carries the thread over. *End session* promotes the session to an episode.
7. **Guides.** In-app Markdown pages (how to export from each provider, how to connect Claude Desktop).

### 3.3 Demo flow (the story for judges)
1. "I was building a project with Claude and ran out of messages." Show the Claude chat.
2. Open PAM, go to **Import wizard**, and drop the (pre-downloaded) Claude export. The pipeline runs live.
3. The **graph** blooms: the project cluster for that work is visible. Drag a few nodes around.
4. Open **Chat**, pick a free OpenRouter or local model, and ask: "Let's keep going on my project. Where did I leave off?"
5. The model answers with the right project, decisions, and next steps. The side panel shows **tokens used vs. a full-history replay** (e.g. 1.8k vs 46k).
6. Switch models mid-chat and ask a follow-up. The thread continues, carried by working memory.
7. (Bonus) Show the same vault answering inside Claude Desktop through MCP.

---

## 4. Architecture 🔒

```
                ┌──────────────── exports (.json / .zip) ────────────────┐
                ▼                                                        │
        [M1 Importers] ── RawConversation ──► [M2 Normalizer] ──► vault/memory/<agent>/episodes/*.md
                                                                         │
                       [M3 Rule Extractor + Persona Deriver] ◄───────────┤
                         └─► facts/*.md, agent/default/*.md              │
                                                                         ▼
                                                 [M4 Indexer] ──► vault/.pam/index.db
                                                                  (documents, chunks, FTS5, vec0)
                                                                         │
                                         [M5 Clusterer + Graph] ◄────────┤──► projects/*.md, GraphData
                                                                         │
 ┌─────────────── [M8 Agents & Permissions] gates every read & write ────┼─────────────────┐
 │                                                                       ▼                 │
 │   [M9 Working Memory]   [M7 Memory Writer] ──► vault files ──► [M10 Vault Sync (git)]   │
 │            │                    ▲                                     │ commit / reindex│
 │            ▼                    │                                     ▼                 │
 │      [M6 Retriever + Context Assembler] ◄────────────── query ─────────┘                 │
 └────────────┬───────────────────────────────────────────────────────────────────────────┘
              ▼
      [M11 MCP Server]  (stdio + streamable HTTP at /mcp)
          ▲          ▲
          │          └── Claude Desktop / Cursor / any MCP client
          │
   [M12 Chat Orchestrator] (MCP client + LiteLLM → Anthropic / OpenRouter / Ollama)
          ▲
   [M13 REST API] (FastAPI: /api/*  +  mounts /mcp)
          ▲
   [M14 Frontend] (Vite + React + TS)
```

**Key principles**
- **The vault is canonical; the index is derived.** `pam index --rebuild` recreates `index.db` from the Markdown files alone.
- **One core library, three faces.** The CLI (Typer), MCP server, and REST API are thin wrappers over the same `pam.*` Python functions. No business logic lives in wrappers.
- **One writer at a time.** Every vault write takes a file lock (`vault/.pam/write.lock`) and ends with a git commit (M10).
- **No LLM inside the pipeline.** Extraction is regex + spaCy patterns; projects come from embeddings + HDBSCAN + c-TF-IDF keywords.
- **Deterministic IDs.** Episodes and facts use UUIDv5, so re-imports and re-derivations never create duplicates.

**Runtime (Docker Compose)**
| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| `backend` (`container_name: pam-backend`) | `backend/Dockerfile` (python:3.12-slim + git) | 8000 | FastAPI `/api/*` + MCP streamable HTTP at `/mcp`; also hosts the CLI via `docker compose exec backend pam …` |
| `frontend` | `frontend/Dockerfile` (node build → nginx) | 5173→80 | Static UI; nginx proxies `/api` and `/mcp` to the backend |
| `ollama` (profile `local`) | `ollama/ollama` | 11434 | Optional local models |

The vault is bind-mounted at `./vault:/vault`. The embedding model cache is a named volume (`pam-models`).

---

## 5. Repo layout 🔒

```
pam/
├── SPEC.md                      # this file
├── SETUP.md                     # install + CLI reference
├── research/
│   └── TODO.md                  # learning checklist
├── docker-compose.yml
├── .env.example                 # ANTHROPIC_API_KEY, OPENROUTER_API_KEY, OLLAMA_BASE_URL, PAM_VAULT
├── .gitignore                   # ignores vault/, .env, node_modules, __pycache__
├── schemas/                     # GENERATED JSON Schemas (pam schema export) — do not hand-edit
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml           # uv-managed, Python 3.12, entry point `pam = pam.cli.main:app`
│   ├── pam/
│   │   ├── __init__.py
│   │   ├── contracts/           # M0 — Pydantic models (§7). The ONLY place schemas are defined.
│   │   │   ├── common.py  raw.py  episode.py  fact.py  project.py  skill.py
│   │   │   ├── agent.py   retrieval.py  working.py  writes.py  reports.py
│   │   │   ├── api.py     graph.py  config.py
│   │   ├── core/                # M0 — config loading, vault paths, md+frontmatter IO, tokens, ids, locking
│   │   ├── importers/           # M1 — base.py, detect.py, claude.py, chatgpt.py, gemini.py
│   │   ├── normalize/           # M2 — render.py (episode md grammar), writer.py
│   │   ├── extract/             # M3 — patterns.py, facts.py, rules.py, style.py, persona.py, templates/*.j2
│   │   ├── index/               # M4 — db.py, schema.sql, chunker.py, embedder.py, indexer.py
│   │   ├── cluster/             # M5 — cluster.py, naming.py, assign.py, graph.py
│   │   ├── retrieve/            # M6 — search.py, context.py, render.py
│   │   ├── memory/              # M7 — writer.py, conflicts.py
│   │   ├── agents/              # M8 — manifest.py, permissions.py
│   │   ├── working/             # M9 — session.py
│   │   ├── sync/                # M10 — git.py, watcher.py
│   │   ├── mcp_server/          # M11 — server.py, tools.py
│   │   ├── chat/                # M12 — llm.py, mcp_client.py, orchestrator.py
│   │   ├── api/                 # M13 — app.py, routes/{imports,vault,search,agents,chat,graph,sync}.py
│   │   └── cli/                 # one Typer sub-app per module; main.py wires them
│   └── tests/
│       ├── fixtures/{claude,chatgpt,gemini}/   # tiny anonymized exports
│       └── test_m01_importers.py … test_m13_api.py
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json  vite.config.ts  tailwind.config.ts  tsconfig.json
│   └── src/
│       ├── api/client.ts        # typed fetch + SSE helpers
│       ├── types/generated.ts   # GENERATED from /schemas — do not hand-edit
│       ├── pages/{Import,Graph,Vault,Search,Agents,Chat,Guides}.tsx
│       ├── components/
│       └── guides/*.md          # in-app instructions (export-claude.md, connect-claude-desktop.md, …)
└── vault/                       # created by `pam init`; separate git repo; ignored by the outer repo
```

---

## 6. Vault layout 🔒

```
vault/
├── .git/                         # vault history (every PAM write = 1 commit)
├── .gitattributes                # "* text eol=lf"
├── .gitignore                    # ".pam/"
├── pam.toml                      # vault config (PamConfig, §7.13)
├── .pam/                         # DERIVED, gitignored
│   ├── index.db                  # sqlite-vec + FTS5 index
│   └── write.lock                # file lock for writers
├── agent/
│   ├── default/
│   │   ├── agent.yaml            # AgentManifest
│   │   ├── identity.md           # Persona (derived section + custom section)
│   │   ├── rules.md
│   │   └── style.md
│   └── <custom-agent>/…          # same 4 files
├── imports/
│   └── <source>/<YYYYMMDDTHHMMSSZ>/<original-filename>   # raw export, byte-for-byte, never modified
├── memory/
│   ├── shared/
│   │   └── facts/<fact_id>.md    # facts about the user, visible to agents with include_shared_facts
│   └── <agent>/
│       ├── episodes/<episode_id>.md
│       ├── facts/<fact_id>.md
│       └── projects/<project_id>.md
├── skills/
│   └── <agent>/<skill_id>.md
└── working/
    └── <session_id>.md
```
> **Changed from the original sketch:** `imports/conversations.json` becomes `imports/<source>/<timestamp>/…` (supports multiple sources and re-imports), and `agent/`, `memory/`, and `skills/` are now namespaced per agent (per-agent scope, G8). The README.md placeholders are replaced by real files.

---
## 7. Data contracts 🔒 (changes require human approval, see §10)

Each contract appears twice: **code**, the literal Pydantic v2 schema in `backend/pam/contracts/`, and **promises**, the guarantees consumers can rely on. JSON Schemas are generated into `/schemas` with `pam schema export`, and TypeScript types are generated from those for the frontend (`json-schema-to-typescript`). If the code and a promise disagree, the promise wins and the code has a bug.

**Global promises (apply to every contract)**
- All models inherit `PamModel` and carry `schema_version` (semver). A **major** bump means breaking. Readers MUST reject files with an unknown major version, and SHOULD accept unknown minor versions.
- `extra="forbid"`: unknown fields are rejected at the boundary.
- All datetimes are **timezone-aware UTC**, serialized as ISO-8601 with a `Z` suffix.
- All paths in contracts are **vault-relative POSIX paths** (forward slashes, even on Windows).
- All IDs are lowercase hyphenated UUID strings.

### 7.1 Common — `contracts/common.py`
```python
from __future__ import annotations
from enum import Enum
from typing import Annotated
from uuid import UUID, NAMESPACE_URL, uuid5
from pydantic import BaseModel, ConfigDict, StringConstraints

SCHEMA_VERSION = "1.0.0"
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
```
**Promises:** `PAM_NAMESPACE` never changes, which is what makes IDs stable across machines and re-imports. `shared` is never an agent name.

### 7.2 RawConversation (M1 output → M2 input) — `contracts/raw.py`
```python
from typing import Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Source

class AttachmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["image", "file", "other"]
    mime_type: str | None = None

class RawMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "system", "tool"]
    text: str
    created_at: AwareDatetime | None = None
    attachments: list[AttachmentRef] = Field(default_factory=list)

class RawConversation(PamModel):
    source: Source
    source_conversation_id: str = Field(min_length=1)
    title: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    summary: str | None = None          # provider-supplied summary if present, else None
    messages: list[RawMessage]
    source_metadata: dict[str, Any] = Field(default_factory=dict)
```
**Promises**
- Each `RawConversation` is exactly one provider conversation, and `(source, source_conversation_id)` is unique within an export.
- `messages` are in **chronological order**. Messages whose text is empty or whitespace and that have no attachments are dropped.
- For ChatGPT's branching tree, **only the final (current) branch** is emitted.
- Code blocks are preserved as fenced Markdown. Rich content blocks (tool use, artifacts) are flattened to text, and images become `AttachmentRef`s.
- `summary` is copied verbatim if the provider gives one and is non-empty. It is never generated.
- Importers are **pure**: they don't touch the vault or the network.

### 7.3 Episode (M2 output; read by M3–M7) — `contracts/episode.py`
```python
from uuid import UUID, uuid5
from pydantic import AwareDatetime, Field
from .common import PamModel, Source, Slug, Sha256, PAM_NAMESPACE

def episode_id(source: Source, source_conversation_id: str) -> UUID:
    return uuid5(PAM_NAMESPACE, f"episode:{source.value}:{source_conversation_id}")

class EpisodeFrontmatter(PamModel):
    id: UUID
    agent: Slug = "default"
    source: Source
    source_conversation_id: str
    title: str                          # fallback: "Untitled conversation YYYY-MM-DD"
    created_at: AwareDatetime           # fallback: first message time, else imported_at
    updated_at: AwareDatetime
    imported_at: AwareDatetime
    message_count: int = Field(ge=0)
    has_summary: bool
    body_sha256: Sha256                 # sha256 of the UTF-8 body (everything after frontmatter)
    tags: list[str] = Field(default_factory=list)
    superseded_facts: list[UUID] = Field(default_factory=list)  # backlinks appended by M7
```
**File:** `memory/<agent>/episodes/<id>.md`, YAML frontmatter plus a body with this exact grammar (parsed by M4):
```markdown
# <title>

## Summary
<provider summary, verbatim>          ← section present only if has_summary

## Transcript

### user · 2026-10-01T18:04:11Z
<message text, verbatim>

### assistant · 2026-10-01T18:04:30Z
<message text, verbatim>
[attachment: diagram.png (image)]
```
(The role heading is `### <role> · <ISO time or "unknown">`; the separator is U+00B7.)

**Promises**
- **One conversation = one file.** The ID is deterministic, so re-importing the same conversation never duplicates it. If the source conversation changed (`updated_at` is newer), the importer writes a **new** episode version only after a human runs `pam import --update`; otherwise it is skipped. *(Default: skip.)*
- **The body is immutable.** After creation, nothing may change the body, and `body_sha256` lets anyone verify this. Only `tags` and `superseded_facts` in the frontmatter may be appended to, and only by M7.
- If `has_summary` is true, **both** the summary and the full verbatim transcript are present.
- Episodes are never deleted by PAM.

### 7.4 Fact — `contracts/fact.py`
```python
import re
from enum import Enum
from uuid import UUID, uuid5
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from .common import PamModel, Actor, SnakeKey, Slug, PAM_NAMESPACE

class FactCategory(str, Enum):
    IDENTITY = "identity"; EDUCATION = "education"; WORK = "work"; LOCATION = "location"
    PREFERENCE = "preference"; TOOLING = "tooling"; PROJECT = "project"
    RELATIONSHIP = "relationship"; OTHER = "other"

class Cardinality(str, Enum):
    SINGLE = "single"   # one value at a time (school, name) → conflicts possible
    MULTI = "multi"     # many values (uses_tool, likes) → values accumulate

class FactStatus(str, Enum):
    ACTIVE = "active"
    CONFLICT = "conflict"

def normalize_value(v: str) -> str:
    return re.sub(r"\s+", " ", v.strip().lower())

def fact_id(scope: str, subject: str, attribute: str, cardinality: Cardinality, value: str) -> UUID:
    key = f"fact:{scope}:{subject}:{attribute}"
    if cardinality is Cardinality.MULTI:
        key += f":{normalize_value(value)}"
    return uuid5(PAM_NAMESPACE, key)

class FactHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    changed_at: AwareDatetime
    changed_by: Actor
    agent: Slug | None = None
    episode_id: UUID | None = None
    reason: str | None = None

class FactConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_value: str
    candidate_source_episode: UUID | None = None
    detected_at: AwareDatetime
    detected_by: Actor

class Fact(PamModel):
    id: UUID
    scope: str                          # "shared" or an agent Slug
    subject: str = "user"
    attribute: SnakeKey                 # e.g. "school", "works_at", "uses_tool"
    value: str = Field(min_length=1)
    cardinality: Cardinality
    category: FactCategory
    confidence: float = Field(ge=0.0, le=1.0)
    status: FactStatus = FactStatus.ACTIVE
    conflict: FactConflict | None = None
    source_episode: UUID | None = None      # where the CURRENT value came from
    updated_by_episode: UUID | None = None  # episode that last changed it
    extractor: Actor
    pattern_id: str | None = None           # M3 pattern that produced it
    created_at: AwareDatetime
    updated_at: AwareDatetime
    history: list[FactHistoryEntry] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _conflict_consistency(self):
        if (self.status is FactStatus.CONFLICT) != (self.conflict is not None):
            raise ValueError("status=conflict iff conflict is set")
        return self
```
**File:** `memory/<scope>/facts/<id>.md`. The frontmatter holds the `Fact`, and the body is one human-readable line: `**school**: University of Washington`.

**Promises**
- **One slot, one file.** A SINGLE fact's ID depends only on `(scope, subject, attribute)`, so updating it overwrites the same file. A MULTI fact gets one file per distinct value.
- **Updated, never deleted.** On overwrite, the previous value is pushed into `history` (the most recent 20 are kept), and git keeps the rest.
- **Conflicts are never auto-resolved by rules.** When M3 extracts a different value for an existing SINGLE slot, the existing value stays, `status` becomes `conflict`, and the candidate is stored in `conflict`. Resolution happens only through `supersede_fact`, which an LLM calls after asking the user, or through a manual edit.
- Writes by an agent (`add_fact` on an existing SINGLE slot) overwrite the value and are recorded in history. The agent is the decider.
- When a value is overwritten, the episode that produced the old value gets the fact's ID appended to its `superseded_facts`.

### 7.5 Project — `contracts/project.py`
```python
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field
from .common import PamModel, Actor, Slug

class Project(PamModel):
    id: UUID                            # uuid4 at creation; stable thereafter
    scope: Slug
    name: str                           # from c-TF-IDF keywords / titles (M5) or set by agent/user
    keywords: list[str] = Field(default_factory=list, max_length=10)
    episode_ids: list[UUID] = Field(default_factory=list)
    origin: Actor                       # cluster | agent | manual
    status: Literal["active", "dormant"] = "active"   # dormant if no activity for N days
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_activity_at: AwareDatetime
```
**File:** `memory/<scope>/projects/<id>.md`. The body has two sections:
```markdown
## Summary (auto)      ← regenerated by M5; extractive: member titles + top keywords
## Notes               ← append-only bullets: "- 2026-10-17T03:12Z (agent:default) Decided to use sqlite-vec"
```
**Promises:** Project IDs survive incremental assignment and `cluster --rebuild` whenever membership overlaps by at least 50% (Jaccard). `## Notes` is append-only. An episode belongs to **at most one** project.

### 7.6 Skill — `contracts/skill.py`
```python
from uuid import UUID
from pydantic import AwareDatetime, Field
from .common import PamModel, Actor, Slug

class Skill(PamModel):
    id: UUID                            # uuid4
    scope: Slug
    name: str
    description: str
    trigger_keywords: list[str] = Field(default_factory=list)
    source_episodes: list[UUID] = Field(default_factory=list)
    created_by: Actor                   # agent | manual (rule-based skill mining is a stretch goal)
    created_at: AwareDatetime
    updated_at: AwareDatetime
```
**File:** `skills/<scope>/<id>.md`. The body is the steps in Markdown. **Promise:** skills are updated in place, and their history lives in git.

### 7.7 Agent & Persona — `contracts/agent.py`
```python
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from .common import PamModel, Slug, RESERVED_SCOPES

ToolName = Literal[
    "get_context", "search_memory", "get_episode", "list_agents",
    "add_fact", "supersede_fact", "log_episode", "update_project",
    "add_skill", "update_working_memory",
]
READ_TOOLS = {"get_context", "search_memory", "get_episode", "list_agents"}

class ReadScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: bool = False                       # True ⇒ every scope (default agent)
    project_ids: list[UUID] = Field(default_factory=list)   # episodes/projects visible
    include_shared_facts: bool = True
    include_own_memory: bool = True         # memory/<self>/**
    include_skills_from: list[Slug] = Field(default_factory=list)

class AgentManifest(PamModel):
    name: Slug
    display_name: str
    description: str = ""
    origin: Literal["derived", "custom"]
    created_at: AwareDatetime
    read: ReadScope
    write: Literal["none", "own", "shared"] = "own"   # shared ⇒ own + memory/shared
    tools: list[ToolName]
    default_model: str | None = None        # LiteLLM model string
    token_budget: int = Field(default=2000, ge=256, le=32000)

    @field_validator("name")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        if v in RESERVED_SCOPES:
            raise ValueError("reserved name")
        return v

class PersonaRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                                 # "r_" + first 8 hex of sha256(normalized text)
    text: str
    origin: Literal["derived", "manual"]
    evidence_count: int = Field(ge=0)
    evidence_episodes: list[UUID] = Field(default_factory=list, max_length=5)

class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Slug
    identity: str                           # rendered markdown
    rules: list[PersonaRule]
    style: str                              # rendered markdown
```
**Files:** `agent/<name>/agent.yaml` holds the `AgentManifest`. `identity.md`, `rules.md`, and `style.md` each have two sections:
```markdown
## Derived (auto-generated — edits here are overwritten by `pam derive`)
## Custom (yours — never touched by PAM)
```
**Promises**
- `default` always exists, with `read.all=True`, `write="shared"`, and all tools.
- Every read and write through M6/M7/M11/M12 is checked against the manifest. Violations raise `PermissionDenied` (MCP error code `PERMISSION_DENIED`).
- `pam derive` rewrites only the `## Derived` sections, never `## Custom`.
- A custom agent's writes go to `memory/<name>/…`. They go to `memory/shared/facts/` only when `write="shared"`.

### 7.8 Index schema (M4 writes; M5/M6 read) — `index/schema.sql`
```sql
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: schema_version, embedding_model, embedding_dim, index_version, last_indexed_commit

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL CHECK (doc_type IN ('episode','fact','project','skill')),
  scope TEXT NOT NULL, path TEXT NOT NULL UNIQUE, title TEXT, created_at TEXT,
  content_sha256 TEXT NOT NULL, token_count INTEGER NOT NULL, indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  rowid INTEGER PRIMARY KEY,               -- shared with chunks_fts and chunks_vec
  chunk_id TEXT NOT NULL UNIQUE,           -- "<doc_id>:<ordinal>"
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  ordinal INTEGER NOT NULL, text TEXT NOT NULL, token_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[384]);
CREATE TABLE IF NOT EXISTS doc_vectors (doc_id TEXT PRIMARY KEY, embedding BLOB NOT NULL);       -- mean of chunk vectors, L2-normalized
CREATE TABLE IF NOT EXISTS project_centroids (project_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, updated_at TEXT NOT NULL);
```
**Promises:** The index is **fully rebuildable** from the vault. Each chunk's `rowid` is identical across `chunks`, `chunks_fts`, and `chunks_vec`. Vectors are float32 and L2-normalized. If `meta.embedding_model` differs from the config, the index MUST be rebuilt (M4 refuses to mix models).

### 7.9 Retrieval — `contracts/retrieval.py`
```python
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Slug, Source, VaultPath
from .fact import Fact
from .agent import Persona
from .working import WorkingMemory

DocType = Literal["episode", "fact", "project", "skill"]

class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    agent: Slug = "default"
    k: int = Field(default=8, ge=1, le=50)
    doc_types: list[DocType] | None = None
    since: AwareDatetime | None = None

class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    doc_id: UUID
    doc_type: DocType
    scope: str
    title: str | None
    snippet: str = Field(max_length=500)
    path: VaultPath
    score: float                         # final fused score (higher = better)
    vector_rank: int | None              # 1-based; None if not in vector candidates
    keyword_rank: int | None             # 1-based; None if not in FTS candidates
    created_at: AwareDatetime | None

class SearchResponse(PamModel):
    query: str
    agent: Slug
    hits: list[SearchHit]
    took_ms: int

class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    agent: Slug = "default"
    session_id: str | None = None
    token_budget: int | None = Field(default=None, ge=256, le=32000)  # None ⇒ agent default
    include_persona: bool = True

class ProjectBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    keywords: list[str]
    status: Literal["active", "dormant"]
    last_activity_at: AwareDatetime
    summary: str

class EpisodeSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: UUID
    title: str
    source: Source
    created_at: AwareDatetime
    text: str
    chunk_ids: list[str]

class ContextBundle(PamModel):
    agent: Slug
    query: str
    persona: Persona | None
    facts: list[Fact]
    conflicts: list[Fact]                # status == conflict; always included when relevant
    projects: list[ProjectBrief]
    episodes: list[EpisodeSnippet]
    working: WorkingMemory | None
    rendered: str                        # markdown block ready to inject into a system prompt
    tokens_used: int                     # tiktoken cl100k_base count of `rendered`
    token_budget: int
    baseline_tokens: int                 # full transcripts of every episode a snippet came from
    tokens_saved: int                    # max(0, baseline_tokens - tokens_used)
    tokenizer: Literal["cl100k_base"] = "cl100k_base"
    generated_at: AwareDatetime
```
**Promises**
- **Scope-safe:** nothing outside the agent's `ReadScope` ever appears in a `SearchResponse` or `ContextBundle`.
- **Budget-safe:** `tokens_used ≤ token_budget`, always. Fill priority: persona (≤ 300 tokens) → conflicts → working memory → facts → project briefs → episode snippets. Lower-priority items are dropped first.
- **Deterministic:** the same vault commit + query + agent produces the same bundle (except `generated_at`).
- **Honest savings:** `baseline_tokens` = the token count of the *full* transcripts of every episode contributing a snippet, i.e. what a user would otherwise paste.
- `rendered` uses fixed headings: `# Agent persona`, `# Known facts`, `# ⚠ Conflicting facts — ask the user`, `# Working memory`, `# Relevant projects`, `# Relevant past conversations`. Every item cites its vault path.

### 7.10 Working memory — `contracts/working.py`
```python
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Slug
from .raw import RawMessage

class ModelSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: AwareDatetime
    from_model: str | None
    to_model: str

class WorkingMemory(PamModel):
    session_id: str = Field(pattern=r"^s_[0-9a-z]{12}$")
    agent: Slug
    status: Literal["active", "ended"] = "active"
    started_at: AwareDatetime
    updated_at: AwareDatetime
    models_used: list[ModelSwitch] = Field(default_factory=list)
    goal: str | None = None                 # default: first user message (truncated 200 chars)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recent_turns: list[RawMessage] = Field(default_factory=list, max_length=8)
    promoted_episode_id: UUID | None = None
```
**File:** `working/<session_id>.md`. The frontmatter holds the model, and the body renders goal, decisions, and questions as Markdown.

**Promises**
- `recent_turns` holds the last ≤ 8 messages. It is updated after every chat turn, *regardless of which model produced it*. This is the hot-swap guarantee.
- `decisions` and `open_questions` are append-only within a session.
- On `end`, the session becomes an episode (`source=pam`) and `status=ended`. The working file is kept, never deleted.

### 7.11 Writes (MCP tool inputs + result) — `contracts/writes.py`
```python
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .common import PamModel, SnakeKey
from .fact import Cardinality, FactCategory, Fact
from .raw import RawMessage

class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

class AddFactInput(_In):
    subject: str = "user"
    attribute: SnakeKey
    value: str = Field(min_length=1)
    category: FactCategory
    cardinality: Cardinality = Cardinality.SINGLE
    confidence: float = Field(default=0.8, ge=0, le=1)
    shared: bool = True                  # write to memory/shared (needs write="shared")
    episode_id: UUID | None = None

class SupersedeFactInput(_In):
    fact_id: UUID
    new_value: str = Field(min_length=1)
    reason: str = Field(min_length=1)    # e.g. "user confirmed they transferred to UW"
    episode_id: UUID | None = None

class LogEpisodeInput(_In):
    title: str
    messages: list[RawMessage] = Field(min_length=1)
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)

class UpdateProjectInput(_In):
    project_id: UUID | None = None       # None ⇒ create new project (name required)
    name: str | None = None
    note: str | None = None              # appended to ## Notes
    add_episode_ids: list[UUID] = Field(default_factory=list)
    status: str | None = Field(default=None, pattern=r"^(active|dormant)$")

class AddSkillInput(_In):
    name: str
    description: str
    steps_markdown: str
    trigger_keywords: list[str] = Field(default_factory=list)

class UpdateWorkingMemoryInput(_In):
    session_id: str
    goal: str | None = None
    add_decisions: list[str] = Field(default_factory=list)
    add_open_questions: list[str] = Field(default_factory=list)

class GetEpisodeInput(_In):
    episode_id: UUID
    max_tokens: int = Field(default=4000, ge=256, le=32000)   # transcript truncated from the middle

class WriteResult(PamModel):
    ok: bool
    action: str                          # "add_fact" | "supersede_fact" | …
    doc_id: UUID | None = None
    path: str | None = None
    commit_sha: str | None = None
    conflict: Fact | None = None         # set if the write revealed a conflict
    message: str
```
**Promises:** Every successful write produces **exactly one git commit**, and its sha is returned. A failed write leaves the vault unchanged. Permission failures return `ok=false` with `message` starting with `PERMISSION_DENIED:`.

### 7.12 Reports & graph — `contracts/reports.py`, `contracts/graph.py`
```python
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Source

class ImportReport(PamModel):
    source: Source
    input_path: str
    archived_path: str                   # imports/<source>/<ts>/<file>
    conversations_found: int
    episodes_written: int
    episodes_skipped_existing: int
    errors: list[str] = Field(default_factory=list)
    commit_sha: str | None
    duration_ms: int

class DeriveReport(PamModel):
    facts_created: int; facts_updated: int; conflicts_flagged: int
    rules_derived: int; commit_sha: str | None; duration_ms: int

class IndexReport(PamModel):
    documents_indexed: int; documents_unchanged: int; documents_removed_from_index: int
    chunks_written: int; embedding_model: str; duration_ms: int

class ClusterReport(PamModel):
    mode: Literal["incremental", "rebuild"]
    projects_created: int; projects_updated: int; episodes_assigned: int; episodes_unassigned: int
    commit_sha: str | None; duration_ms: int

class SyncReport(PamModel):
    dirty_paths: list[str]; reindexed: int; commit_sha: str | None

class JobStatus(PamModel):               # async import job (API)
    job_id: str
    stage: Literal["queued", "extract", "normalize", "derive", "index", "cluster", "done", "error"]
    progress: float = Field(ge=0, le=1)
    report: ImportReport | None = None
    error: str | None = None

class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["project", "episode", "fact"]
    label: str
    cluster_id: str | None
    size: float                          # project: #episodes; episode: log(message_count+1)
    created_at: AwareDatetime | None
    path: str | None

class GraphLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    kind: Literal["member", "similar", "derived_from"]
    weight: float = Field(ge=0, le=1)

class GraphData(PamModel):
    agent: str
    nodes: list[GraphNode]
    links: list[GraphLink]
    generated_at: AwareDatetime
```
**Promises:** Graph data respects agent scope. Every `link.source` and `link.target` refers to a node in `nodes`. Fact nodes are included only when `?facts=true` is passed.

### 7.13 Config — `contracts/config.py` (stored as `vault/pam.toml`)
```python
from pydantic import BaseModel, ConfigDict, Field

class _C(BaseModel):
    model_config = ConfigDict(extra="forbid")

class EmbeddingCfg(_C):
    model: str = "BAAI/bge-small-en-v1.5"; dim: int = 384
    query_prefix: str = "Represent this sentence for searching relevant passages: "
class ChunkCfg(_C):
    max_tokens: int = 512; overlap_tokens: int = 64
class RetrievalCfg(_C):
    candidate_k: int = 50; rrf_k: int = 60
    recency_weight: float = 0.2; recency_half_life_days: float = 30
class ContextCfg(_C):
    default_budget: int = 2000; persona_max_tokens: int = 300
    max_facts: int = 12; max_projects: int = 3
class ClusterCfg(_C):
    min_cluster_size: int = 3; assign_threshold: float = 0.70
    similar_link_threshold: float = 0.75; similar_links_per_node: int = 3
    rebuild_match_jaccard: float = 0.5; dormant_after_days: int = 30
class ExtractCfg(_C):
    rule_min_evidence: int = 2; spacy_model: str = "en_core_web_sm"
class ModelEntry(_C):
    id: str                               # LiteLLM model string, e.g. "openrouter/<org>/<model>:free"
    label: str
    supports_tools: bool = False
class PamConfig(_C):
    schema_version: str = "1.0.0"
    embedding: EmbeddingCfg = EmbeddingCfg(); chunking: ChunkCfg = ChunkCfg()
    retrieval: RetrievalCfg = RetrievalCfg(); context: ContextCfg = ContextCfg()
    clustering: ClusterCfg = ClusterCfg(); extraction: ExtractCfg = ExtractCfg()
    models: list[ModelEntry] = Field(default_factory=list)
    sync_interval_seconds: int = 5
```
**Promise:** Every tunable number in this spec lives here. No magic constants in module code.

### 7.14 REST + SSE (M13 ↔ M14) — `contracts/api.py`
```python
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .common import Slug

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = None         # None ⇒ new session
    agent: Slug = "default"
    model: str                            # must match a PamConfig.models[].id
    message: str = Field(min_length=1)
    mode: Literal["injection", "tool"] = "injection"

class ContextEvent(BaseModel):
    type: Literal["context"] = "context"
    session_id: str; tokens_used: int; baseline_tokens: int; tokens_saved: int
    doc_ids: list[UUID]; rendered: str
class TokenEvent(BaseModel):
    type: Literal["token"] = "token"; text: str
class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"; name: str; arguments: dict; result_summary: str
class DoneEvent(BaseModel):
    type: Literal["done"] = "done"; session_id: str; model: str
    prompt_tokens: int | None; completion_tokens: int | None
class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"; message: str; retryable: bool

ChatEvent = Annotated[Union[ContextEvent, TokenEvent, ToolCallEvent, DoneEvent, ErrorEvent],
                      Field(discriminator="type")]
```
**Endpoints** (all JSON, prefix `/api`):

| Method & path | Body → Response |
|---|---|
| `GET /health` | → `{"ok": true, "vault": str, "index_ok": bool}` |
| `POST /imports` (multipart `file`, form `source?`, `agent?`) | → `JobStatus` |
| `GET /imports/{job_id}` | → `JobStatus` |
| `GET /vault/tree?agent=` | → `{"paths": [str]}` (scope-filtered) |
| `GET /vault/file?path=` | → `{"path", "frontmatter": dict, "body": str}` |
| `POST /search` | `SearchQuery` → `SearchResponse` |
| `POST /context` | `ContextRequest` → `ContextBundle` |
| `GET /graph?agent=&facts=` | → `GraphData` |
| `GET /agents` / `GET /agents/{name}` | → `AgentManifest[]` / `{manifest, persona}` |
| `POST /agents` / `PUT /agents/{name}` | `{manifest, identity_custom, rules_custom, style_custom}` → `AgentManifest` |
| `GET /models` | → `ModelEntry[]` |
| `POST /chat` | `ChatRequest` → **SSE** stream: `event: <type>\ndata: <ChatEvent json>\n\n` |
| `GET /sessions/{id}` / `POST /sessions/{id}/end` | → `WorkingMemory` / `WriteResult` |
| `POST /sync` / `GET /sync/status` | → `SyncReport` |

**Promises:** Errors return `{"error": {"code": str, "message": str}}` with a proper HTTP status (400 validation, 403 permission, 404 missing, 409 conflict/lock, 500). The SSE stream always ends with exactly one `done` or `error` event. The first event of every chat turn is `context`.

### 7.15 MCP tool surface (M11) — the external promise
| Tool | Input model | Output | Read/Write |
|------|-------------|--------|-----------|
| `get_context` | `ContextRequest` (agent fixed by server) | `ContextBundle.rendered` + JSON `ContextBundle` | R |
| `search_memory` | `SearchQuery` | `SearchResponse` | R |
| `get_episode` | `GetEpisodeInput` | episode Markdown (truncated to `max_tokens`) | R |
| `list_agents` | — | `[{name, display_name, description}]` | R |
| `add_fact` | `AddFactInput` | `WriteResult` | W |
| `supersede_fact` | `SupersedeFactInput` | `WriteResult` | W |
| `log_episode` | `LogEpisodeInput` | `WriteResult` | W |
| `update_project` | `UpdateProjectInput` | `WriteResult` | W |
| `add_skill` | `AddSkillInput` | `WriteResult` | W |
| `update_working_memory` | `UpdateWorkingMemoryInput` | `WriteResult` | W |

**Promises:** The server is bound to one agent per connection (`--agent` for stdio, `?agent=` for HTTP; default `default`). Tools not in that agent's `tools` list are **not advertised**. Tool descriptions instruct the model: *"If `get_context` returns conflicting facts, ask the user which is correct, then call `supersede_fact`."*

---
## 8. Modules 🔒

Each module has a fixed structure:
- **Form:** what it physically is.
- **Function:** what it does.
- **Input / Output:** referencing §7 contracts.
- **Tools:** libraries.
- **Implementation:** the algorithm.
- **CLI:** the full reference is in SETUP.md.
- **Edge cases.**
- **Acceptance:** what must pass before moving on.

Python 3.12. All modules use `pam.core` for config, paths, locking, and Markdown IO.

### M0 — Contracts & Core
- **Form:** packages `pam/contracts/*` and `pam/core/*`.
- **Function:** defines every schema (§7) and provides the shared plumbing:
  - config loading
  - vault path resolution
  - frontmatter read/write
  - token counting
  - ID helpers
  - the write lock
- **Input:** `PAM_VAULT` env var or `--vault` flag; `vault/pam.toml`.
- **Output:** importable APIs:
  - `core.config.load() -> PamConfig`
  - `core.vault.Vault(path)`, with path helpers like `episode_path(agent, id)` and `fact_path(scope, id)`
  - `core.mdio.read(path) -> (dict, str)` and `core.mdio.write(path, frontmatter: PamModel, body)`
  - `core.tokens.count(text) -> int`
  - `core.lock.vault_write_lock()` (context manager)
  - `core.time.utcnow()`
- **Tools:**
  - `pydantic` v2
  - `python-frontmatter` + `PyYAML` (safe_dump, `sort_keys=False`)
  - `tomllib` / `tomli-w`
  - `tiktoken` (`cl100k_base`)
  - `filelock`
  - `typer` + `rich`
- **Implementation:**
  - `mdio.write` writes atomically (temp file + `os.replace`) with LF line endings and UTF-8.
  - `pam init` creates the §6 tree, writes a default `pam.toml`, and runs `git init` with `.gitattributes` and `.gitignore`.
  - It also creates `agent/default/` (an empty persona with both sections) and makes the initial commit.
  - `pam schema export` dumps `model_json_schema()` for every public model into `/schemas`.
- **Edge cases:**
  - Running `init` on an existing vault is a no-op with a warning.
  - Windows paths are always converted to POSIX in contracts.
- **Acceptance:**
  - `pam init --vault /tmp/v` creates the tree and 1 commit.
  - `pam schema export` writes one JSON file per model.
  - `pytest tests/test_m00_core.py` passes (round-trip every model via `mdio`).

### M1 — Importers (extractor)
- **Form:** `pam/importers/{base,detect,claude,chatgpt,gemini}.py`.
- **Function:** parse a provider export (`.zip` or `.json`) into `RawConversation` objects. Pure functions; nothing is written.
- **Input:** a file path; `source` = `auto|claude|chatgpt|gemini`.
- **Output:** `Iterator[RawConversation]` and a list of non-fatal parse errors.
- **Tools:** `zipfile`, `json` (stdlib; switch to `ijson` streaming only if exports exceed ~200 MB), `python-dateutil`, `beautifulsoup4` (Gemini HTML fallback).
- **Implementation:**
  - `base.Importer` protocol: `detect(path) -> float` (a confidence score) and `parse(path) -> Iterator[RawConversation]`.
  - `detect.py` opens the zip, picks the importer with the highest confidence, and unzips into a temp dir.
  - **Claude (P0):** read `conversations.json`, a list of conversations with `uuid`, `name`, `summary`, `created_at`, `updated_at`, and `chat_messages[]` (each with `sender` ∈ {human, assistant}, `text`, `content[]`, `created_at`, `attachments`, `files`). Map `human→user`. Prefer `content[]` text blocks over `text` when present. *(Verify the exact field names against a real export — research R1.)*
  - **ChatGPT (P1):** read `conversations.json`, a list with `id`, `title`, `create_time` (epoch), `mapping{node_id: {message, parent, children}}`, and `current_node`. Walk the **parents from `current_node` up to the root**, then reverse the order. Skip system/hidden messages. Join `content.parts` that are strings. *(R2)*
  - **Gemini (P1, best-effort):** Google Takeout "Gemini Apps" activity (`MyActivity.json`, or `.html` as a fallback). Each activity has a prompt and, when present, a response. Group entries into conversations by time gap (> 30 min starts a new one). `source_conversation_id` = `sha1(first_timestamp + first_prompt)`. *(R3)*
- **Edge cases:**
  - Empty conversations are skipped and counted.
  - Malformed entries are logged to `errors`, and parsing continues.
  - Non-UTF-8 text is decoded with `errors="replace"`.
- **Acceptance:** `pam import extract tests/fixtures/claude/export.zip --out /tmp/raw.jsonl` emits valid `RawConversation` lines. The same works for ChatGPT, and Gemini yields at least 1 conversation from its fixture.

### M2 — Normalizer (episode writer)
- **Form:** `pam/normalize/{render,writer}.py`.
- **Function:**
  - Archive the raw export.
  - Turn each `RawConversation` into an episode `.md` file (§7.3).
  - Commit everything once.
- **Input:** `Iterable[RawConversation]`, `agent` (default `default`), the original file path.
- **Output:** episode files plus an `ImportReport`.
- **Tools:** `pam.core.mdio`, `hashlib`, M10 `git.commit`.
- **Implementation:**
  1. Under the write lock, copy the original export to `imports/<source>/<ts>/` byte-for-byte.
  2. For each conversation, compute `episode_id`. If the file exists, skip it, unless `--update` is set and the source `updated_at` is newer; then write a *new* episode with id `uuid5(…:<updated_at>)` and tag `supersedes:<old_id>`.
  3. Render the body using the exact grammar and compute `body_sha256`.
  4. Write frontmatter + body.
  5. Make one commit: `import: <source> <n> episodes (<file>)`.
- **Edge cases:**
  - Titles containing newlines are collapsed.
  - Very long messages (> 100k characters) are kept intact.
  - If the run crashes mid-import, nothing is committed, and the next run continues idempotently.
- **Acceptance:**
  - `pam import run <fixture>` writes N episodes and 1 commit.
  - Re-running writes 0 new episodes.
  - `pam episode verify` confirms every `body_sha256`.

### M3 — Rule Extractor & Persona Deriver (no LLM)
- **Form:** `pam/extract/{patterns,facts,rules,style,persona}.py` and `templates/{identity,style}.md.j2`.
- **Function:**
  - Mine **user** messages for structured facts.
  - Mine repeated instructions into rules.
  - Compute style statistics.
  - Render the `default` agent's persona.
  - Flag conflicts.
- **Input:** episodes (all, or `--episode ID`); existing facts; `ExtractCfg`.
- **Output:** fact files, `agent/default/{identity,rules,style}.md` (Derived sections only), and a `DeriveReport`.
- **Tools:** `re`, `spacy` (`en_core_web_sm`: `Matcher`, NER, noun chunks), `jinja2`.
- **Implementation:** the industry-standard simple approach is **pattern-based information extraction** (regex + spaCy token patterns, in the spirit of Hearst patterns).
  - Each pattern is a declarative dict in `patterns.py`: `{id, regex | spacy_pattern, attribute, category, cardinality, confidence, value_group, ner_filter?}`. The extractor runs every pattern over every *user* message sentence (split with spaCy's `sents`).
  - **Skip** a match if a negation (`not`, `n't`, `never`, `no longer`) appears within 3 tokens before the trigger, or if the sentence is a question (`?`) or hypothetical (`if`, `would`, `imagine`, `pretend`).
  - **Values:** trim the captured value at the first clause boundary (`,`, `.`, ` and `, ` but `, ` because `) and cap it at 60 characters. If `ner_filter` is set (e.g. `ORG`, `GPE`), keep the match only if the span overlaps an entity of that type.
  - **Merging:** `fact_id()` gives each match a slot.
    - New slot → create the fact (`extractor=rule`).
    - Same value → bump confidence by `+0.05`, capped at `0.95`, and record the evidence.
    - Different value on a SINGLE slot → set `status=conflict` with the candidate (§7.4). Exception: if the existing fact came from the rule extractor *and* the new evidence is from a newer episode, overwrite and push the old value to history, since the user's own later statement wins.
  - **Starter pattern set** (extend it during the hackathon):

    | id | Trigger (regex, case-insensitive) | attribute | cat | card. | NER |
    |---|---|---|---|---|---|
    | `name` | `\bmy name is (?P<v>[A-Z][\w'-]+(?: [A-Z][\w'-]+)?)` | `name` | identity | single | — |
    | `call_me` | `\b(?:call me\|i go by) (?P<v>[A-Z][\w'-]+)` | `preferred_name` | identity | single | — |
    | `study_at` | `\bi(?:'m\| am)? (?:study(?:ing)?\|a (?:\w+ )?student) at (?P<v>.+)` | `school` | education | single | ORG |
    | `major` | `\bi(?:'m\| am) (?:majoring\|studying) (?:in )?(?P<v>[\w &]+)` | `major` | education | single | — |
    | `work_at` | `\bi (?:work\|intern(?:ing)?) (?:at\|for) (?P<v>.+)` | `works_at` | work | single | ORG |
    | `job_title` | `\bi(?:'m\| am) an? (?P<v>(?:senior \|junior \|lead )?[\w ]*(?:engineer\|developer\|designer\|student\|researcher\|manager\|scientist))` | `role` | work | single | — |
    | `live_in` | `\bi (?:live\|am based\|'m based) in (?P<v>.+)` | `location` | location | single | GPE |
    | `from` | `\bi(?:'m\| am) from (?P<v>.+)` | `hometown` | location | single | GPE |
    | `prefer` | `\bi (?:prefer\|really like\|love) (?P<v>.+)` | `likes` | preference | multi | — |
    | `dislike` | `\bi (?:hate\|dislike\|can't stand) (?P<v>.+)` | `dislikes` | preference | multi | — |
    | `use_tool` | `\bi(?:'m\| am)? (?:using\|use\|work with) (?P<v>[A-Z][\w.+#-]*(?:,? (?:and )?[A-Z][\w.+#-]*)*)` | `uses_tool` | tooling | multi | — |
    | `stack` | `\bmy (?:tech )?stack is (?P<v>.+)` | `uses_tool` | tooling | multi (split on `,`/`and`) | — |
    | `building` | `\bi(?:'m\| am) (?:building\|working on\|making) (?P<v>.+)` | `working_on` | project | multi | — |

    Confidence: identity/education/work/location = 0.75; preference/tooling/project = 0.6.
  - **Rules (`rules.py`):** detect imperative instructions aimed at the assistant in user messages:
    - `^(?:please )?(?:don't|do not|never|always|stop|avoid) (?:use|using|write|include|add|give|say) (?P<v>.+)`
    - `\bkeep (?:it|answers|responses) (?P<v>short|brief|concise|simple)`
    - `\bno (?P<v>emojis?|bullet points?|markdown|yapping|fluff)\b`

    Normalize each match to a canonical sentence ("Don't use bullet points."), group identical normalized text, and emit a rule if `evidence_count ≥ rule_min_evidence` (default 2 distinct episodes).
  - **Style (`style.py`):** statistics over user messages:
    - median words per message
    - share of messages containing code fences, with the top 3 fenced languages
    - question ratio
    - emoji ratio
    - share of messages with "short", "concise", or "tl;dr"

    Map these to sentences with fixed thresholds, e.g. "The user writes briefly (median 14 words); prefer concise answers," or "Code-heavy (38% of messages); include runnable code blocks; favor Python, TypeScript."
  - **Identity (`persona.py`):** render `identity.md.j2` from active shared facts (name, role, school, works_at, location), the top 5 active projects by recent activity, and top tools. Example: "You are PAM-default, a long-term assistant for {{name}} ({{role}} at {{org}})…"
- **Edge cases:**
  - Assistant messages are **never** mined.
  - Text inside quotes or code fences is ignored.
  - "I'm building a list of…" yields junk; mitigate with a stopword filter on values (`a list`, `a function`, `it`, `this`, etc.) and a length cap.
- **Acceptance:** On the fixture, `pam derive` produces ≥ 3 correct facts and ≥ 1 rule, with zero facts from assistant text. A planted contradiction ("I study at WSU" in an older episode vs. "I go to UW" in a newer one) is handled per the merge rules. `tests/test_m03_extract.py` holds a table of sentence → expected fact / no fact (≥ 30 cases, including negations and hypotheticals).

### M4 — Indexer (chunk + embed + store)
- **Form:** `pam/index/{db,chunker,embedder,indexer}.py` and `schema.sql`.
- **Function:** keep `.pam/index.db` in sync with the vault: chunk documents, embed the chunks, and store them in vec0 + FTS5.
- **Input:** vault files (episodes, facts, projects, skills); `--rebuild`; an optional list of paths (for incremental sync from M10).
- **Output:** `index.db` (§7.8) and an `IndexReport`.
- **Tools:** `sqlite3` + `sqlite-vec` (`sqlite_vec.load(conn)`), `fastembed` (`TextEmbedding("BAAI/bge-small-en-v1.5")`, ONNX, CPU), `numpy`.
- **Implementation:**
  - **Change detection:** for each file, compute `content_sha256`. If it is unchanged, skip the file. If it changed, delete that document's chunks from all three tables and re-insert them. If a file is gone, remove it from the index (index only; the vault is never touched).
  - **Episode chunking:** parse the transcript headings, then group turns into **user+assistant pairs**. Emit one chunk per pair. If a pair is over `max_tokens`, split it on paragraph boundaries with an `overlap_tokens` window.
    - Prefix every chunk with `"[<title>] "` for context.
    - If a summary exists, it becomes chunk 0.
  - **Other documents:**
    - Facts: one chunk, `"<subject> <attribute>: <value>"`.
    - Projects: one chunk, `name + keywords + summary`.
    - Skills: one chunk, `name + description + first 300 tokens of steps`.
  - **Embedding:** batch size 64. Documents are embedded as-is, and queries get `query_prefix`. Vectors are L2-normalized and stored with `serialize_float32`.
  - **Document vectors:** after an episode's chunks are written, store the normalized mean of its chunk vectors in `doc_vectors` (used by M5).
  - Write `meta`. If `embedding_model` differs from the stored value, error unless `--rebuild` is set.
- **Edge cases:** First run downloads the model (about 130 MB) into the `pam-models` volume, so show progress. An empty vault yields an empty index with no error.
- **Acceptance:** `pam index` on the fixture is idempotent (a second run reports all documents unchanged). `pam index --rebuild` produces identical chunk counts. `pam index stats` prints counts per `doc_type`.

### M5 — Clusterer & Graph
- **Form:** `pam/cluster/{cluster,naming,assign,graph}.py`.
- **Function:**
  - Group related episodes into projects (like reflective memory: "these sessions are all about X").
  - Keep projects stable over time.
  - Produce the force-graph data.
- **Input:** `doc_vectors` for episodes in scope; existing projects; `ClusterCfg`; mode `incremental|rebuild`.
- **Output:** project files, `project_centroids`, a `ClusterReport`, and `GraphData`.
- **Tools:** `scikit-learn` (`sklearn.cluster.HDBSCAN`, `CountVectorizer`), `numpy`.
- **Implementation:**
  - **Incremental (default):** for each episode not in any project, compute its cosine similarity to every project centroid. If the best is `≥ assign_threshold`, add it to that project and update the centroid (running mean). Otherwise leave it unassigned. Once ≥ `min_cluster_size` episodes are unassigned, run HDBSCAN on *only the unassigned ones* to spawn new projects.
  - **Rebuild (`--rebuild`):** run HDBSCAN (`metric="euclidean"` on normalized vectors, which is equivalent to cosine; `min_cluster_size` from config) over all episodes in scope. Match each new cluster to existing projects by Jaccard similarity of membership; if it is `≥ rebuild_match_jaccard`, reuse the old ID and name. Otherwise create a new project. Old projects with no match keep their files but become `status=dormant` with an emptied `episode_ids` list, and a Notes line records why.
  - **Naming (`naming.py`), class-based TF-IDF:**
    1. Concatenate the titles plus user messages of each cluster into one "class document."
    2. Run `CountVectorizer(ngram_range=(1,2), stop_words="english", min_df=1)`.
    3. Compute c-TF-IDF = tf × log(1 + A / f), where A is the average word count per class and f is the term frequency across all classes.
    4. Take the top 5 terms as `keywords`.
    5. The name is the most frequent title n-gram if it appears in ≥ 30% of member titles; otherwise the top 2 keywords title-cased (e.g. "Sqlite Vec · Rag Pipeline").
  - **Summary (auto):** extractive. List the top keywords, the 5 most recent member titles with dates, and the date range.
  - **Dormancy:** if `last_activity_at` is older than `dormant_after_days`, the status becomes `dormant`.
  - **Graph (`graph.py`):**
    - Nodes: projects (size = #episodes) and episodes (size = log(messages+1)).
    - Links: `member` (episode→project); `similar` (episode↔episode where cosine ≥ `similar_link_threshold`, top `similar_links_per_node` per node, deduplicated); optional fact nodes with `derived_from` links to `source_episode`.
  - Writes are committed as `cluster: <mode> +<created> ~<updated>`.
- **Edge cases:**
  - With fewer than `min_cluster_size` episodes, there are no projects and every episode is unassigned (no error).
  - HDBSCAN's noise label `-1` means unassigned.
  - Agents may also create projects manually (`update_project`), and clustering never renames `origin=agent|manual` projects.
- **Acceptance:** On the fixture, there are at least 2 projects with sensible keywords. Running `pam cluster` twice is a no-op. `pam cluster --rebuild` keeps the project IDs. `pam graph export --out g.json` validates against `GraphData`.

### M6 — Retriever & Context Assembler
- **Form:** `pam/retrieve/{search,context,render}.py`.
- **Function:** scope-filtered hybrid search, plus a token-budgeted `ContextBundle`.
- **Input:** `SearchQuery` / `ContextRequest`; agent manifest (M8); working memory (M9).
- **Output:** `SearchResponse` / `ContextBundle`.
- **Tools:** `sqlite-vec`, FTS5, `fastembed`, `tiktoken`, `jinja2` (render template).
- **Implementation:**
  - **Hybrid search with Reciprocal Rank Fusion (RRF)**, the standard way to merge two ranked lists without tuning score scales:
    1. **Vector side:** `SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH :q AND k = :candidate_k`.
    2. **Keyword side:** `SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH :q ORDER BY bm25 LIMIT :candidate_k`. The query is sanitized: tokens are quoted and joined with `OR`.
    3. **Scope filter:** join with `chunks` and `documents` and drop anything outside the `ReadScope`. Over-fetch (×3) when the agent is restricted.
    4. **Fusion:** `score = Σ 1/(rrf_k + rank_i)` over the lists the chunk appears in.
    5. **Recency boost:** `score *= 1 + recency_weight · 0.5^(age_days / half_life)`.
    6. Deduplicate to at most 2 chunks per document. Return the top k.
  - **Context assembly:**
    1. Load the persona.
    2. Run search with k=20.
    3. Gather facts: always include the `identity`, `education`, and `work` categories, plus fact hits, up to `max_facts`. Conflicts in scope are always included when their attribute is mentioned in the query or hits; otherwise they go in only if budget remains.
    4. Gather projects: those owning hit episodes, plus the most recently active, up to `max_projects`.
    5. Gather snippets: merge adjacent chunks from the same episode.
    6. Add working memory if `session_id` is set.
    7. Greedily fill in the priority order from §7.9, counting tokens of the *rendered* section each time, until the budget is reached.
    8. Compute `baseline_tokens` from `documents.token_count` of the contributing episodes.
- **Edge cases:**
  - An empty index yields a bundle with the persona only and no error.
  - An FTS syntax error falls back to vector-only search.
  - Very small budgets truncate the persona to `persona_max_tokens`, then drop everything else.
- **Acceptance:**
  - `pam search "<known topic>"` returns the right episode in the top 3.
  - `pam context "…" --budget 800` reports `tokens_used ≤ 800`.
  - A restricted agent never sees out-of-scope documents (a property test over 50 random queries).
  - p95 latency is < 300 ms on 1k episodes (warm).

### M7 — Memory Writer & Conflicts
- **Form:** `pam/memory/{writer,conflicts}.py`.
- **Function:** the only code path that writes facts, logged episodes, projects, skills, and backlinks. It enforces "update, never delete; episodes immutable."
- **Input:** the `*Input` models (§7.11) + `agent` + an optional `session_id`.
- **Output:** a `WriteResult` (with commit sha). It triggers an incremental reindex of the touched paths (M4).
- **Tools:** `pam.core`, M8 permissions, M10 git, M4 indexer.
- **Implementation:**
  - Every write follows the same sequence under `vault_write_lock()`: authorize → load → mutate → validate (Pydantic) → atomic write → `git.commit(message)` → `indexer.index_paths([…])`.
  - **`add_fact`:** compute the slot.
    - Missing → create it.
    - Exists with the same value → bump confidence.
    - Exists with a different value (SINGLE) → **overwrite** (the agent decides): push history, set `updated_by_episode`, and backlink the old `source_episode`'s `superseded_facts`.
  - **`supersede_fact`:** same as an overwrite, but by `fact_id`. It clears `status=conflict` and records `reason` in history.
  - **`log_episode`:** build a `RawConversation(source=pam, source_conversation_id=f"{agent}:{utc_iso}:{sha8}")` and pass it through M2's renderer. Then run M3 fact extraction on just that episode.
  - **`update_project`:** create a new project (`origin=agent`), or append a note line and/or add episodes. It never rewrites `## Summary (auto)`.
  - **`add_skill`:** create a new skill; or, if a skill with the same normalized name exists in the scope, update it in place.
  - **Backlinks:** append to the episode frontmatter's `superseded_facts`, then re-verify `body_sha256` (and abort if it changed).
  - Commit message format: `<action>: <short> (agent=<name>[, session=<id>])`.
- **Edge cases:**
  - If the lock can't be acquired within 10 s, return a `409` / `ok=false` "vault busy."
  - If validation fails, write nothing.
  - `supersede_fact` on a nonexistent ID returns a not-found result.
- **Acceptance:** `pam fact add` and `pam fact supersede` each produce exactly 1 commit. History grows, the episode backlink appears, and `pam episode verify` still passes.

### M8 — Agents & Permissions
- **Form:** `pam/agents/{manifest,permissions}.py`.
- **Function:**
  - CRUD for agents.
  - Resolve an agent's visible scopes and paths.
  - Authorize every action.
- **Input:** `agent/<name>/agent.yaml` + persona files.
- **Output:** `AgentManifest`, `Persona`, and the helpers `visible_doc_filter(agent) -> SQL fragment + params`, `can_read(agent, doc)`, `can_write(agent, target_scope)`, `can_call(agent, tool)`.
- **Tools:** `PyYAML`, `pydantic`.
- **Implementation:**
  - **Reads:** `all=True` allows everything. Otherwise an agent may read:
    - documents whose scope is the agent itself (if `include_own_memory`)
    - `shared` facts (if `include_shared_facts`)
    - episodes in `project_ids`, plus those projects themselves
    - skills in `include_skills_from`
  - **Writes:** `none` → deny. `own` → only `memory/<self>/`, `skills/<self>/`, and the agent's own working files. `shared` → also `memory/shared/facts/`.
  - **Creating an agent:** `pam agent create` writes the manifest and empty persona files (`origin=custom`), then commits.
  - Persona parsing reads the `## Derived` and `## Custom` sections. The rendered persona is Derived followed by Custom, so Custom wins on contradictions by appearing last.
- **Acceptance:** `pam agent create research --projects <id>` followed by `pam search "<topic from another project>" --agent research` returns 0 hits from other projects, and `pam fact add --agent research --shared` is denied.

### M9 — Working Memory (sessions)
- **Form:** `pam/working/session.py`.
- **Function:** short-term memory per chat session; hot-swap continuity; promotion to an episode on end.
- **Input:** session start (agent, model), per-turn messages, model switches, `UpdateWorkingMemoryInput`, end.
- **Output:** `working/<session_id>.md` (`WorkingMemory`) and, on end, an episode via M7 `log_episode`.
- **Tools:** `pam.core`, M7.
- **Implementation:**
  - **`start`:** create `s_<12 random base36 chars>`. The goal is set from the first user message.
  - **`record_turn(role, text, model)`:** append to `recent_turns`, keeping only the last 8. If the model differs from the last `models_used` entry, append a `ModelSwitch`. The full transcript is kept in the API process memory and also appended to `working/<id>.transcript.jsonl`, which is gitignored until the session ends.
  - **`end`:** build `LogEpisodeInput` from the full transcript, with a summary of the goal + decisions, then set `status=ended` and `promoted_episode_id`.
  - Working files are committed on start, on end, and when goal or decisions change, but **not** on every turn, to avoid commit spam.
- **Acceptance:** `pam session start`, two `pam chat` calls with different `--model`, then `pam session show` lists 2 models and 4 turns. `pam session end` creates an episode.

### M10 — Vault Sync (git)
- **Form:** `pam/sync/{git,watcher}.py`.
- **Function:**
  - Commit helper for all writers.
  - Detect manual edits (uncommitted changes), incrementally reindex them, and commit them.
- **Input:** the vault path; the polling interval.
- **Output:** commits and a `SyncReport`.
- **Tools:** the `git` CLI via `subprocess` (no GitPython; fewer moving parts in Docker), plus M4.
- **Implementation:**
  - **`git.commit(paths, message)`:** `git add -- <paths>` then `git commit -m <message> --author "PAM <pam@local>"`. Return the sha. On init, the vault repo is configured with `core.autocrlf=false` and `safe.directory=/vault` (needed for Docker bind mounts).
  - **`sync_once()`:**
    1. Run `git status --porcelain -z`.
    2. Classify dirty paths (ignoring `.pam/`).
    3. For modified episode files, verify `body_sha256`. If a **body** was edited, warn and do **not** commit it; report it as `immutable_violation`.
    4. Validate the frontmatter of the other changed `.md` files, call `indexer.index_paths`, and commit with `manual: <n> files`.
  - **Triggers:** run `sync_once()` (a) before every `get_context` and `search` (cheap: `git status` takes about 10 ms), (b) on `POST /sync`, and (c) in a loop with `pam sync --watch`.
- **Edge cases:**
  - Files the user deleted are restored from HEAD with `git checkout -- <path>` (never-delete policy), with a warning.
  - If the lock is held, skip this tick.
- **Acceptance:** Hand-editing a fact's value and running `pam sync` produces 1 commit, and `pam search` finds the new value. Editing an episode body is reported and not committed.

### M11 — MCP Server
- **Form:** `pam/mcp_server/{server,tools}.py`.
- **Function:** expose M6, M7, and M9 as MCP tools (§7.15) over **stdio** (Claude Desktop, Cursor) and **streamable HTTP** at `/mcp`, mounted in the FastAPI app (used by M12 and remote clients).
- **Input:** MCP tool calls; the bound agent.
- **Output:** tool results (text content plus structured JSON).
- **Tools:** the official `mcp` Python SDK (`FastMCP`), `uvicorn`.
- **Implementation:**
  - Each tool is a thin function: validate input with the §7.11 model → call core → return `model_dump(mode="json")` (plus `rendered` text for `get_context`).
  - Tool registration is filtered by the agent's `tools` list.
  - Server instructions (the MCP `instructions` field): *"Call get_context at the start of a task and whenever the topic changes. If conflicts are returned, ask the user and then call supersede_fact. Log important new facts with add_fact. Never invent memories."*
  - **HTTP:** `app.mount("/mcp", mcp.streamable_http_app())`. The agent is chosen with the `?agent=` query parameter.
  - **stdio:** `pam mcp serve --transport stdio --agent default`. Claude Desktop runs it via `docker exec -i pam-backend pam mcp serve --transport stdio` (see SETUP).
- **Acceptance:** `npx @modelcontextprotocol/inspector` lists the tools for `default` and fewer for a restricted agent. In Claude Desktop, "what do you know about me?" triggers `get_context`.

### M12 — Chat Orchestrator (hot-swappable models)
- **Form:** `pam/chat/{llm,mcp_client,orchestrator}.py`.
- **Function:** run a chat turn with any model, injecting memory context or exposing the MCP tools. Stream the tokens and maintain working memory.
- **Input:** `ChatRequest`.
- **Output:** an async iterator of `ChatEvent`; working-memory updates.
- **Tools:**
  - **`litellm`** (`acompletion(stream=True)`): one API for `anthropic/…`, `openrouter/…`, `ollama/…`, reading keys from env.
  - The `mcp` SDK client (`ClientSession` over streamable HTTP to its own `/mcp`).
- **Implementation:**
  1. Load or start the session (M9) and record the user turn.
  2. **Injection mode (default, works with any model):** call `get_context` via MCP with `{query: message, session_id}`. Emit a `ContextEvent`. The system prompt = PAM preamble + `bundle.rendered`. Messages = `recent_turns` (excluding the current one) + the current user message.
  3. **Tool mode** (only if `ModelEntry.supports_tools`): list the MCP tools, convert them to OpenAI tool schema, and loop: model → tool_calls → `session.call_tool` → append results. Cap at 5 rounds, emitting a `ToolCallEvent` each time. Still emit a light `ContextEvent` (persona only) first.
  4. Stream tokens as `TokenEvent`s. When finished, record the assistant turn (with model) in M9 and emit `DoneEvent` with usage if the provider returns it.
  - **PAM preamble:** "You are continuing work with a user whose long-term memory is provided below. Treat it as reliable background, cite it naturally, and ask the user about any ⚠ conflicting facts."
- **Edge cases:**
  - Provider errors or rate limits → `ErrorEvent(retryable=True)`.
  - An unknown model → 400.
  - Free OpenRouter models can disappear, so the model list lives in `pam.toml` and `pam models check` pings each one.
- **Acceptance:** `pam chat "where did I leave off on <project>?" --model <A>`, then `--model <B> --session <id>` with a follow-up. B's answer references A's turn. Both modes work with at least one model each.

### M13 — REST API
- **Form:** `pam/api/app.py` + `routes/*`.
- **Function:** an HTTP facade for the frontend (§7.14); hosts `/mcp`; runs import jobs in the background.
- **Input/Output:** see §7.14.
- **Tools:** `fastapi`, `uvicorn`, `sse-starlette` (`EventSourceResponse`), `python-multipart`; `BackgroundTasks` with an in-memory job registry (a dict keyed by `job_id`).
- **Implementation:**
  - **Import job:** save the upload to a temp file → M1 → M2 → M3 → M4 → M5, updating `JobStatus.stage` and `progress` after each stage.
  - CORS is allowed for `http://localhost:5173`.
  - Errors are mapped to `{"error": {...}}`.
  - OpenAPI is available at `/docs`.
- **Acceptance:** `pytest tests/test_m13_api.py` (FastAPI `TestClient`) covers each endpoint. `curl -N` on `/api/chat` streams events, ending with `done`.

### M14 — Frontend
- **Form:** a Vite + React + TS app in `frontend/`.
- **Function:** the seven pages from §3.2.
- **Input/Output:** REST + SSE (§7.14). Types come from `src/types/generated.ts`.
- **Tools:**
  - `react-router-dom`
  - `@tanstack/react-query` (server state)
  - `tailwindcss` + `@tailwindcss/typography` (the `prose` class styles guides and vault Markdown)
  - `react-markdown` + `remark-gfm`
  - `react-force-graph-2d` (canvas + d3-force: drag, pin, zoom, hover highlight)
  - `@microsoft/fetch-event-source` (SSE over POST; the native `EventSource` is GET-only)
  - `lucide-react` (icons)
  - `json-schema-to-typescript` (codegen script `npm run gen:types`)
- **Implementation:**
  - **Import:** source picker → shows the matching `guides/export-<source>.md` → dropzone → poll `/imports/{id}` every 1 s → stage stepper → "View graph" button.
  - **Graph:**
    - Projects are colored by `cluster_id` (palette hashed from the ID); episodes are smaller.
    - Hovering a node highlights its neighbors and fades the rest. `onNodeDragEnd` pins the node (`fx`, `fy`).
    - Clicking a node opens a side drawer with the rendered file.
    - A toggle shows fact nodes; a search box flies to a node (`centerAt`, `zoom`).
    - Physics: `d3Force('charge').strength(-60)`, link distance 30 for `member` and 60 for `similar`, `cooldownTicks=150`.
  - **Vault:** a tree from `/vault/tree`. The viewer shows a frontmatter table plus the body in `prose`.
  - **Search:** query box, agent select, results with score/vector-rank/keyword-rank badges, and a "Build context" button that opens the bundle with a token meter.
  - **Agents:** list + form (name, description, multi-select projects from the graph data, write level radio, tool checkboxes, model select, budget slider). Three Markdown editors (textarea + live preview) for the Custom sections.
  - **Chat:**
    - Left: session list.
    - Center: the message stream (Markdown rendered). The model dropdown can change at any time; the change appears as an inline divider "switched to X."
    - Right: a context panel (rendered bundle, used/baseline/saved meter) and a mode toggle (injection/tool, enabled only if `supports_tools`).
    - An "End session" button.
  - **Guides:** a list of `src/guides/*.md` (loaded with `import.meta.glob('./guides/*.md', { query: '?raw', eager: true })`) rendered in `prose`. Adding a guide means adding a `.md` file.
  - **Theme:** a dark-first palette defined as CSS variables, with a light mode via `prefers-color-scheme`.
- **Acceptance:** The demo flow (§3.3) works in Chrome against the Docker backend, and the graph stays smooth (≥ 50 fps) with 500 nodes.

### M15 — Docker & packaging
- **Form:** `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.env.example`.
- **Function:** one-command, cross-platform runtime (Windows + macOS).
- **Implementation:**
  - **Backend image:**
    - Base `python:3.12-slim`, plus `apt-get install git`.
    - Install `uv`, then `uv sync --frozen`.
    - `python -m spacy download en_core_web_sm` at build time.
    - Pre-download the fastembed model at build time into `/models` (`FASTEMBED_CACHE_PATH=/models`), so the first run doesn't need the network.
    - `ENTRYPOINT ["pam"]`, `CMD ["api","serve","--host","0.0.0.0","--port","8000"]`.
  - **Frontend:** a multi-stage build (`node:20-alpine` build → `nginx:alpine`). nginx proxies `/api` and `/mcp` to `backend:8000`, with `proxy_buffering off` for SSE.
  - **Compose:** the vault bind mount `./vault:/vault`, `env_file: .env`, a healthcheck on `/api/health`, and the `ollama` service behind `profiles: [local]`.
- **Acceptance:** On a clean Windows machine and a clean Mac, `docker compose up --build`, then `docker compose exec backend pam init`, then opening `http://localhost:5173` gives a working UI.

---
## 9. Agent task breakdown

### 9.1 Agent operating protocol 🔒
Every implementation agent (e.g. a Claude Code session) follows this loop for **one task at a time**:

1. **Load context:** read §0, §7 (all contracts), the task's module in §8, and every **APPROVED** entry in §10.
2. **Plan:** append a plan under the task's `Agent plan` heading. It lists the files to create, the functions with signatures, the test cases, and any risks. The plan may not touch paths outside *Allowed paths*.
3. **Implement** inside *Allowed paths* only. Tests go in `backend/tests/test_mXX_*.py`, and fixtures in `backend/tests/fixtures/`.
4. **Verify:** run every command under *Done when*, then `pytest -q` for this task's tests and all earlier ones (no regressions).
5. **Report:** append a short `Result` line under the task (date, pass/fail, notes).
6. **Need to change a contract, the vault layout, or another module's design?** Append a `PROPOSED` entry in §10 and **stop that part of the work.** Continue only with parts that don't depend on it. Wait for a human to append `APPROVED`.
7. **Never delete** spec text, change entries, episode bodies, or tests written by earlier tasks.

Global allowed paths for every task: `backend/tests/**`, appending to §9 (own task) and §10, and `research/TODO.md` (checking boxes and appending notes).

### 9.2 Phase 0: before the hackathon (humans) 🔒
| ID | Task | Owner | Output |
|----|------|-------|--------|
| P0.1 | Work through `research/TODO.md` (sections R1–R6 first) | all | Checked boxes + notes |
| P0.2 | Request real exports from Claude, ChatGPT, and Gemini **now** (they arrive by email, sometimes with a delay) | each | Raw exports on disk |
| P0.3 | Build **anonymized fixtures**: about 10 conversations per source, including a planted contradiction, repeated rules ("no bullet points" ×2), and 3 obvious topics | 1 person | `backend/tests/fixtures/**` |
| P0.4 | Pick the demo conversation history and pre-download that Claude export | 1 person | `demo/claude-export.zip` (gitignored) |
| P0.5 | Get API keys (OpenRouter free; Anthropic API if credits are available) and pick 2–3 models that support tools | 1 person | `.env`, `pam.toml` model list |
| P0.6 | Install Docker Desktop on all 3 laptops; test `hello-world` + a bind mount on Windows | all | — |

### 9.3 Phase 1: the hackathon build (sequential, agent-driven)
Estimates assume one agent plus one human reviewer. The total is about 19 h, leaving about 5 h for buffer, polish, and pitch.

---
#### T00 · Scaffold (≈ 0.75 h)
- **Module:** M15 (skeleton) + M0 (package skeleton)
- **Allowed paths:** `/docker-compose.yml`, `/.env.example`, `/.gitignore`, `backend/Dockerfile`, `backend/pyproject.toml`, `backend/pam/__init__.py`, `backend/pam/cli/main.py`, `frontend/**` (Vite template only)
- **Depends on:** —
- **Steps:**
  1. `uv init`; add every Python dependency from §8.
  2. Create the Typer app with `pam --version`.
  3. `npm create vite@latest frontend -- --template react-ts`; add Tailwind.
  4. Write a minimal compose file that builds both images.
- **Done when:** `docker compose up --build` starts both containers; `docker compose exec backend pam --version` prints `0.1.0`; the frontend shows the Vite page at :5173.
- **Agent plan (➕):**
  - `backend/pyproject.toml` (hand-written, not `uv init`; it locks to `backend/uv.lock`): Python 3.12, entry point `pam = pam.cli.main:app`, every library named in §8 M0–M13 (pydantic, python-frontmatter, pyyaml, tomli-w, tiktoken, filelock, typer, rich, python-dateutil, beautifulsoup4, ijson, spacy, jinja2, sqlite-vec, fastembed, numpy, scikit-learn, mcp, litellm, fastapi, uvicorn[standard], sse-starlette, python-multipart). Dev group: pytest and httpx, because `docker compose exec backend pytest -q` and the FastAPI TestClient need them.
  - `pam/__init__.py`: `__version__ = "0.1.0"`. `cli/main.py`: Typer app with an eager `--version` option (T01 adds auto-discovery).
  - `backend/Dockerfile`: python:3.12-slim + git + uv 0.11.18; `uv sync --frozen`; `PAM_VAULT=/vault`, `FASTEMBED_CACHE_PATH=/models`; ENTRYPOINT/CMD as in M15 (`pam api serve …`).
  - `frontend/`: create-vite react-ts template + Tailwind v3 (`tailwind.config.ts`, `postcss.config.js`, `@tailwind` layers in `index.css`). M15 multi-stage `Dockerfile` (node:20-alpine → nginx:alpine), `nginx.conf` proxying `/api` and `/mcp` with `proxy_buffering off`, `.dockerignore`.
  - `docker-compose.yml`: backend (`pam-backend`, 8000, `./vault:/vault`, `./demo:/demo`, `pam-models:/models`, optional `env_file: .env`), frontend (5173→80), and `ollama` behind `profiles: [local]`.
  - Risk: `pam api serve` doesn't exist until T14, and T14 can't edit compose. The compose file therefore runs `pam api serve … || exec sleep infinity`, so the container idles now and starts serving automatically once T14 lands. T16 removes the fallback.
  - Deferred to T16 (decided by Yogesh): spaCy/fastembed model baking and the `/api/health` healthcheck.
- **Result (➕):** 2026-10-17 · PASS · `docker compose up --build -d` starts `pam-backend` and `pam-frontend-1`; `docker compose exec backend pam --version` → `0.1.0`; http://localhost:5173 → 200 (Vite page); `/api/*` → 502 as expected until T14; all §8 libraries import in the container; `pytest -q` → no tests yet. Note: this checkout is on `C:\` rather than inside WSL2 (SETUP §1).
- **Result (➕):** 2026-10-17 · PASS · On this Windows/WSL2 Docker Desktop host, `docker compose up --build -d` built both images; `docker compose ps` shows backend and frontend running; `docker compose exec backend pam --version` printed `0.1.0`; `http://localhost:5173` returned HTTP 200; imports for all §8 runtime dependencies succeeded in the backend container. Docker access required running outside the workspace sandbox. macOS line endings remain unverified.
- **Result (➕):** 2026-10-17 · PASS (re-verified inside WSL2, per SETUP §1 and PM feedback) · Moved the checkout from `C:\` to `~/code/pam` in WSL2 Ubuntu. The `C:\` checkout had `core.autocrlf=true`, so CRLF line endings went into the Docker build context and the image (`/app/pam/**/*.py` contained `\r`), and `./vault` was mounted over 9p/drvfs. From WSL2: both containers running; `pam --version` → `0.1.0`; :5173 → 200; `/api/*` → 502 (expected until T14); 0 `.py` files with CR in the image; `/vault` is native ext4 (200 small writes: 10 ms, vs 799 ms from `C:\`); `pytest -q` → 86 passed, 1 skipped. Stored blobs were already LF; no `.gitattributes` added (Yogesh's decision).

#### T01 · Contracts & core (≈ 1.5 h)
- **Module:** M0
- **Allowed paths:** `backend/pam/contracts/**`, `backend/pam/core/**`, `backend/pam/cli/{main,init_cmd,schema_cmd}.py`, `/schemas/**`
- **Depends on:** T00
- **Steps:**
  1. Transcribe §7 verbatim into the `contracts/*` files.
  2. Write the core helpers (config, vault, mdio, tokens, lock, time).
  3. Implement `pam init`, `pam schema export`, and `pam config show`.
  4. Write round-trip tests for every model.
- **Done when:** `pam init --vault /tmp/v && git -C /tmp/v log --oneline` shows 1 commit; `pam schema export` writes `/schemas/*.json`; `pytest tests/test_m00_core.py` is green.
- **Agent plan (➕):**
  - `contracts/*`: §7 verbatim, one file per heading; the §7.12 block is split into `reports.py` + `graph.py` (imports only). §7.8 SQL is T06's. `contracts/__init__.py` adds `all_models()` (every public model + `ChatEvent` as a `TypeAdapter`), used by schema export and the tests.
  - `core/errors.py`: `PamError(msg, exit_code)` → `VaultNotFound` (1), `SchemaVersionError` (2), `PermissionDenied` (3), `VaultBusy` (4) — SETUP §5 exit codes.
  - `core/time.py` `utcnow()`, `iso_z(dt)` · `core/ids.py` `sha256_text`, `new_uuid` · `core/tokens.py` `count(text)` (cached `cl100k_base`) · `core/lock.py` `vault_write_lock(vault=None, timeout=10.0)` (filelock; timeout → `VaultBusy`).
  - `core/vault.py`: `resolve_vault(path=None)` (arg → global `--vault` → `PAM_VAULT`); `Vault` path helpers (`episode_path`, `fact_path`, `project_path`, `skill_path`, `working_path`, `manifest_path`, `persona_path`, `import_dir`, `rel` → POSIX); `init_vault(path) -> InitResult` (no-op + warning if `pam.toml` exists; refuses a non-empty non-vault dir; §6 tree on disk, `.gitattributes`, `.gitignore`, `pam.toml`, `agent/default/` manifest + 3 persona files; `git init -b main`, `core.autocrlf=false`, 1 commit by `PAM <pam@local>`).
  - `core/config.py`: `load(vault=None) -> PamConfig` (defaults if no `pam.toml`; rejects unknown major), `dump_toml(cfg)`.
  - `core/mdio.py`: `read(path) -> (dict, str)`, `write(path, model, body)`, `read_model(path, cls)` (major-version check), `write_text(path, text)`. Own `---` splitter + PyYAML, because `python-frontmatter` strips the body (breaks `body_sha256`). Atomic (temp + `os.replace`), UTF-8, LF, creates parents.
  - `cli/main.py`: global `--vault/--json/-v`; auto-discovers `pam/cli/*_cmd.py` and calls each module's `register(app)` (fallback: a module-level `app` Typer is mounted as `pam <name>`); maps `PamError` → its exit code and `ValidationError` → 2. `cli/init_cmd.py`: `pam init`, `pam config show|path` (`config` isn't in allowed paths). `cli/schema_cmd.py`: `pam schema export [--out]` → one `<Model>.json` per model, default `<repo>/schemas`.
  - Tests `tests/test_m00_core.py`: mdio round trip for every model in `all_models()` (+ guard that every model has a sample), byte-exact bodies, contract promises (extra forbid, `Z` datetimes, fact conflict validator, reserved `shared`, deterministic IDs, major/minor version handling), tokens, lock contention, config, POSIX paths, CLI init (1 commit, idempotent, refuses non-vault), schema export, `config show --json`.
  - Risks/decisions: `safe.directory` is global git config → left to T02 (init-time git config). Empty dirs aren't committed (no `.gitkeep`); writers create parents. tiktoken downloads `cl100k_base` on first use → T16 should bake it (noted in research/TODO.md). Default manifest lives in `core/vault.py` until T05. `pam doctor` out of scope.
- **Result (➕):** 2026-10-17 · PASS · `pam init --vault /tmp/v` → 1 commit (`PAM <pam@local>`, "pam: init vault"); re-running is a no-op with a warning; `pam schema export` writes 54 files (53 models + `ChatEvent`); `pytest -q` → 86 passed (T08's tests-first module skips until `pam.extract` exists), both on Windows (`uv run`) and in the backend container. Docstrings follow `commenting-guidelines.md`; `contracts/*` keep §7 verbatim. Design notes logged as CHG-0001. Note: typer 0.27 vendors click (`typer._click`), so `cli/main.py` raises that `ClickException` for exit codes.

#### T02 · Git helper (≈ 0.5 h)
- **Module:** M10 (commit part only; the watcher comes in T09b)
- **Allowed paths:** `backend/pam/sync/git.py`, `backend/pam/cli/sync_cmd.py` (stub)
- **Depends on:** T01
- **Steps:** implement `commit`, `status_porcelain`, `restore`, `head_sha`, plus the init-time git config.
- **Done when:** the unit test creates a file, commits it, and gets a sha back. It passes on Linux in Docker.
- **Agent plan (➕):**
  - `sync/git.py` (subprocess + pathlib; failures raise `pam.core.errors.PamError`, so the CLI maps them to exit 1):
    - `run(vault, *args, check=True) -> CompletedProcess[str]`: `git -C <vault> -c safe.directory=<vault> -c core.quotePath=false …`, UTF-8; a missing `git` binary or a non-zero exit (with `check`) → `PamError` carrying git's stderr.
    - `configure_repo(vault)`: `core.autocrlf=false` in the repo config; adds the vault path to the **global** `safe.directory` list unless it (or `*`) is already there, because git ignores `safe.directory` in repo config (Docker bind mounts). Idempotent.
    - `commit(vault, paths, message) -> str`: paths may be absolute (inside the vault) or vault-relative, sent to git as POSIX; `git add -- <paths>`, then `git -c user.name=PAM -c user.email=pam@local commit -q -m <message> --author "PAM <pam@local>" -- <paths>` (the pathspec keeps unrelated staged files out of the commit); returns the new HEAD sha. Empty `paths`, a path outside the vault, or nothing staged for `paths` → `PamError` ("nothing to commit").
    - `status_porcelain(vault) -> list[tuple[str, str]]`: parses `git status --porcelain -z --untracked-files=all` into `(XY, path)`; renames/copies report the new path; entries under `.pam/` are dropped.
    - `restore(vault, path)`: `git checkout HEAD -- <path>`; only rewrites tracked files from HEAD, never deletes.
    - `head_sha(vault) -> str | None`: `git rev-parse --verify -q HEAD`; `None` before the first commit.
  - `cli/sync_cmd.py`: module-level Typer `app` (auto-mounted as `pam sync`) whose callback prints `not implemented until T09b`.
  - Tests `tests/test_m10_git.py` on `tmp_path` repos with `GIT_CONFIG_GLOBAL` pointed at a temp file (no user identity, global config untouched): commit → 40-hex sha == `head_sha`; nothing-to-commit and empty paths raise; commit only includes the given paths; status sees modified, untracked, and a path with a space, and ignores `.pam/`; restore brings back a deleted file and refuses an untracked path; `head_sha` is `None` on an empty repo; `configure_repo` sets `core.autocrlf=false` and `safe.directory` once; `pam sync` prints the stub message.
  - Risks: `core/vault.init_vault` (T01) has its own minimal git runner and does not yet call `configure_repo` (not in T02's allowed paths); a follow-up task that owns `core/vault.py` should switch it over.
- **Result (➕):** 2026-10-17 · PARTIAL · macOS 12 (Intel, git 2.37, Python 3.12): `pytest -q tests/test_m10_git.py` → 16 passed; full `pytest -q` → 102 passed, 1 skipped (T08's tests-first module); `pam sync` prints the stub message. The container check (`docker compose exec backend pytest -q tests/test_m10_git.py`) was **not run**: this Mac has no Docker daemon. T01 was already merged, so `git.py` raises `pam.core.errors.PamError` instead of staying stdlib-only. Local env note: `uv sync --frozen` fails on Intel macOS (no `onnxruntime` 1.31 wheel), so it was synced with `--no-install-package onnxruntime`.
- **Result (➕):** 2026-10-17 · PASS · Container check run on Yogesh's machine: `docker compose exec backend pytest -q tests/test_m10_git.py` and the full `pytest -q` pass with no failures.

#### T03 · Importers (≈ 2 h)
- **Module:** M1
- **Allowed paths:** `backend/pam/importers/**`, `backend/pam/cli/import_cmd.py`
- **Depends on:** T01
- **Steps:**
  1. Write the Claude importer first, test it against the fixture, then do the same for ChatGPT, then Gemini.
  2. Implement `detect.py`.
  3. Implement `pam import extract`.
- **Done when:** `pam import extract tests/fixtures/<src>/… --out /tmp/raw.jsonl` passes for all 3 sources, and every line validates as a `RawConversation`.
- **Agent plan (➕):**
  - Follow-up: extend Gemini parsing coverage to both `Prompted …` and `details[]` Takeout layouts; rebuild the Gemini primary ZIP with LF JSON and retain the details layout as a separate variant; normalize ChatGPT fixture root/message IDs and hidden/image metadata; add `pam import detect`; add `test_m01_importers.py` for per-source counts, 29/31-minute grouping, ChatGPT selected branches, detection, invalid rows, and read-only parsing; update fixture READMEs with counts and IDs. `pam import run` stays unchanged.
- **Result (➕):** 2026-10-17 · PASS · Supplied 20-conversation export: `pam import extract` → 19 conversations, 1 skipped, 0 errors; `pytest -q tests/test_m01_importers.py` → 10 passed; full `pytest -q` → 222 passed, 2 skipped. `pam import run` behavior unchanged.

#### T04 · Normalizer (≈ 1 h)
- **Module:** M2
- **Allowed paths:** `backend/pam/normalize/**`, `backend/pam/cli/{import_cmd,episode_cmd}.py`
- **Depends on:** T02, T03
- **Steps:** implement the renderer (the exact grammar), the writer (archive + idempotency + a single commit), `pam import run`, `pam episode list|show|verify`.
- **Done when:** importing the fixture twice yields N episodes and then 0 new ones; `pam episode verify` reports all OK.
- **Agent plan (➕):**
  - Files: `backend/pam/normalize/render.py` (`render(raw, imported_at, agent="default") -> (EpisodeFrontmatter, body)`, `render_body`), `backend/pam/normalize/writer.py` (`write_episodes(vault, raws, source, original_file, agent="default", update=False, dry_run=False) -> ImportReport`), `backend/pam/cli/episode_cmd.py` (`pam episode list|show|verify`), `pam import run` added to T03's `cli/import_cmd.py` (T03's `extract` untouched), `backend/tests/test_m02_normalize.py`.
  - Tests: grammar golden, summary present/absent, attachments, unknown time, title fallback and newline collapse, created_at fallbacks, sha verify and tamper (exit 1), idempotent second run (0 written, 0 commits), `--update` chain, byte-identical archive, POSIX paths, dry-run, crash and failed commit leave nothing, untracked leftover recovery, CRLF text, fixtures for claude/chatgpt/gemini end to end.
  - Risks: see CHG-0002 (archive when nothing is new, CRLF in bodies, large commits, `--all` deferred).
- **Result (➕):** 2026-10-17 · PASS locally (macOS, Python 3.12 venv): `pam init` + `pam import run` writes 9 claude / 5 chatgpt / 3 gemini episodes in 1 commit each; re-run writes 0 and makes no commit; `pam episode verify` all OK; `pytest -q` 131 passed, 1 skipped. Not run in the backend container (no Docker daemon locally). `pam import run --all` is not implemented (needs derive, index, cluster). See CHG-0002.

#### T05 · Agents & permissions (≈ 1 h)
- **Module:** M8
- **Allowed paths:** `backend/pam/agents/**`, `backend/pam/cli/agent_cmd.py`
- **Depends on:** T01, T02
- **Steps:** manifest load/save, persona section parsing, the `can_*` functions and `visible_doc_filter`, `pam agent create|list|show|set-scope`.
- **Done when:** the M8 acceptance criteria pass (the search part is checked again in T07).
- **Agent plan (➕):**
  - `agents/manifest.py`: `load_manifest(name, vault=None)` (rejects an unknown major `schema_version`), `save_manifest(manifest, vault=None)` (no commit), `list_agents(vault=None)`, `create_agent(manifest, vault=None) -> sha` (lock → `agent.yaml` + 3 persona files from `PERSONA_TEMPLATE` + `memory/<name>/{episodes,facts,projects}`, `skills/<name>/` → 1 commit `pam: create agent <name>`), `set_scope(name, *, project_ids, include_shared_facts, write, tools, vault) -> (manifest, sha | None)` (1 commit; `None` when unchanged; refuses `default`). Persona: `split_sections(text) -> (derived, custom)` (text outside both headings counts as Custom), `replace_derived(text, derived)` (Custom kept byte-exact; for T08), `rule_id(text)`, `parse_rules(derived, custom)`, `format_rule(rule)` (for T08), `load_persona(name, vault=None)` (Derived + Custom, so Custom comes last). `rules.md` format per CHG-0002.
  - `agents/permissions.py`: `visible_doc_filter(agent, vault=None, alias="documents") -> (sql, params)`, `can_read(agent, doc, vault=None)` (same rules; `doc` = anything with `doc_id`/`doc_type`/`scope`), `can_write(agent, target_scope)`, `can_call(agent, tool)` (write tools also need `write != "none"`), `doc_ref_from_path(rel)`, `can_write_path(agent, rel, vault=None)`, `project_episode_ids(agent, vault=None)` (episodes of `read.project_ids`, read from the project files). All return booleans; callers raise `PermissionDenied`.
  - `cli/agent_cmd.py`: `pam agent create|list|show|set-scope|check` (SETUP §6; `check` added for debugging permission decisions). Default `--tools` = all, or only read tools with `--write none`. `set-scope --projects` replaces the list. Project ids without a file only warn (projects come from T10).
  - Tests `tests/test_m08_agents.py`: CLI create/list/show/set-scope/check with commit counts and exit codes; persona sections, `replace_derived`, rule round-trip; `visible_doc_filter` matrix over an in-memory §7.8 `documents` table; `can_read` agrees with the filter for 50 random agents; `can_write`/`can_call`/`can_write_path` matrices; the M8 acceptance at function level.
  - Risks: the `rules.md` format sits inside a §7.7 file and is logged as design (CHG-0002); `visible_doc_filter` reads project files on each call (T07 may cache); the CLI half of the acceptance needs T07 (`pam search`) and T09 (`pam fact add`).
- **Result (➕):** 2026-10-17 · PASS · WSL2 checkout, both in the backend container and locally (`uv run --frozen`): `pytest -q tests/test_m08_agents.py` → 81 passed; full `pytest -q` → 183 passed, 1 skipped (T08's tests-first module), no regressions. Acceptance at function level: `research --projects P1` sees 0 documents from P2 through `visible_doc_filter`, and `can_write(research, "shared")` is False; `pam agent check research --path memory/shared/facts/x.md` reports write denied. T07 re-checks the search part through `pam search --agent`, and T09 the write part through `pam fact add --shared`.

#### T06 · Indexer (≈ 2 h)
- **Module:** M4
- **Allowed paths:** `backend/pam/index/**`, `backend/pam/cli/index_cmd.py`
- **Depends on:** T04, T05
- **Steps:**
  1. Write `schema.sql`, plus the `db.py` connection with sqlite-vec loaded.
  2. Implement the chunker (with tests on the grammar).
  3. Implement the embedder wrapper.
  4. Implement incremental indexing and `doc_vectors`.
  5. Add `pam index [--rebuild] [paths…]` and `pam index stats`.
- **Done when:** the M4 acceptance criteria pass.
- **Agent plan (➕):**
  - `index/schema.sql` (§7.8 verbatim); `index/db.py`: `connect(vault)` (creates `.pam/`, loads sqlite-vec, WAL, applies the schema), `delete_index(vault)`, `get_meta(conn)`, `set_meta(conn, values)`.
  - `index/chunker.py`: `parse_episode(body)`, `episode_chunks(body, cfg)` (summary = chunk 0; each user turn opens a group with the following non-user turns; `<role>: <text>` without times; `[<title>] ` prefix inside `max_tokens`), `split_text(text, max_tokens, overlap_tokens)` (paragraphs, hard token split for one huge paragraph, word-aligned overlap tail), `fact_chunk`, `project_chunk` (name + keywords + `## Summary (auto)`), `skill_chunk` (name + description + first 300 tokens of steps).
  - `index/embedder.py`: `Embedder(cfg)` with `embed_documents(texts)` / `embed_query(text)` (adds `query_prefix`), batch 64, L2-normalized float32, lazy model load with a stderr notice; `get_embedder(cfg)` shares one instance per model (T07 reuses it); `l2_normalize`.
  - `index/indexer.py`: `index_vault(vault=None, *, rebuild=False, paths=None, embedder=None) -> IndexReport`, `index_paths(vault, paths, embedder=None) -> IndexReport` (for M7/M10; takes no vault lock), `stats(vault=None) -> dict`, `doc_type_of(rel_path)`. Change detection hashes the whole file; one transaction per run; `doc_vectors` for episodes.
  - `cli/index_cmd.py`: `pam index [PATHS...] [--rebuild]`, `pam index stats` (both with `--json`).
  - Tests `tests/test_m04_index.py`: chunker grammar cases; embedder wrapper with a stub model; indexer on the Claude fixture with a deterministic fake embedder (idempotence, rebuild, rowid alignment, unit vectors, doc vectors, edit/delete, `index_paths`, model mismatch, dim guard, bad and duplicate files, empty vault without a model load); CLI; one real-model acceptance test.
  - Risks: the first real run downloads the model (about 130 MB); a message line that looks exactly like a role heading starts a new turn. Choices logged as CHG-0008.
- **Result (➕):** 2026-10-17 · PASS · WSL2 checkout, locally (`uv run --frozen`) and in the backend container: `pytest -q tests/test_m04_index.py` → 30 passed; full `pytest -q` → 364 passed, 2 skipped (T07's retriever modules are not written yet), no regressions. M4 acceptance on the Claude fixture with bge-small: `pam index` → 9 documents, 70 chunks (largest 508 tokens); a second `pam index` → `0 documents (9 unchanged, 0 removed)`; `pam index --rebuild` → 70 chunks again; `pam index stats` → episode 9 / 70; `chunks`, `chunks_fts`, `chunks_vec` each hold 70 rows and `doc_vectors` 9. Fixed during the run: M2 writes message times with microseconds, so the role-heading pattern accepts fractional seconds (CHG-0008 #1).

#### T07 · Retriever & context (≈ 2 h)
- **Module:** M6
- **Allowed paths:** `backend/pam/retrieve/**`, `backend/pam/cli/{search_cmd,context_cmd}.py`
- **Depends on:** T06 (works without M3/M5/M9 data; those sections are simply empty)
- **Steps:**
  1. Vector query, then FTS query, then RRF + recency, then scope filter.
  2. Context assembler with the greedy budget.
  3. The render template.
  4. `pam search`, `pam context` (`--json`, `--budget`, `--agent`).
- **Done when:** the M6 acceptance criteria pass, including the scope property test.
- **Agent plan (➕):**
  - Added `retrieve/_index.py` as the read-only seam, with T06 helper delegation and a local sqlite-vec/FastEmbed fallback. Implemented hybrid retrieval, context assembly/rendering, CLI commands, and `tests/test_m06_retrieve_stub.py`; this suite builds its own small §7.8 database with deterministic embeddings. T06-dependent indexed acceptance remains pending its merge.
  - Review after T06/T09 merged (Yogesh): 40 spec-traced cases appended to `tests/test_m06_retrieve.py` found 10 gaps against §7.5, §7.8, §7.9, §8 M6 and SETUP §6; fixed in `retrieve/{_index,search,context,render}.py` and `cli/{search,context}_cmd.py` (CHG-0011): fact hits of any category, unrelated conflicts filled last, lower sections dropped first, only consecutive chunks merged, working memory read from `working/<id>.md`, model mismatch refused, persona trimmed by binary search over tokens, project summary = `## Summary (auto)`, `search -k/--type/--since` with ranks in the text output, `context --no-persona`. The seam opens the index read-only and embeds through `pam.index.indexer.get_embedder`.
- **Result (➕):**
  - 2026-10-17 · PASS (pre-T06) · In WSL (`uv run`): pure helpers via `pytest -q tests/test_m06_retrieve.py -k 'rrf_fuse or recency_multiplier or sanitize_fts'` → 10 passed; `test_m06_retrieve_stub.py` → 7 passed; `test_m06_retrieve.py` → 10 passed, 22 skipped; full backend `pytest -q` → 351 passed, 25 skipped. Stub-indexed `pam search --json` and `pam context --json` validate as their contracts. Real-index acceptance, the skipped indexed tests, and the in-container run remain pending T06.
  - 2026-10-18 · PASS · WSL2 checkout, locally and in the backend container, rebased on T09: `pytest -q tests/test_m06_retrieve.py tests/test_m06_retrieve_stub.py` → 79 passed, 2 skipped (T11 working-memory module; opt-in perf); full `pytest -q` → 501 passed, 4 skipped; `PAM_PERF=1 … -k p95` → passed. M6 acceptance with bge-small on the Claude + ChatGPT fixtures: `pam search "Immich photo backup" -k 3` → an Immich episode first; `pam context "…" --budget 800` → 772 tokens; the restricted agent sees only its project's episodes and shared facts (50-query property test). A 20 KB persona at `--budget 256` finishes in about 1 s (was a hang).

#### T08 · Rule extractor & persona (≈ 2 h)
- **Module:** M3
- **Allowed paths:** `backend/pam/extract/**`, `backend/pam/cli/derive_cmd.py`
- **Depends on:** T04, T05 (writes go through a minimal fact writer; T09 then becomes the canonical writer)
- **Steps:**
  1. `patterns.py` (the starter set), then sentence iteration with negation and question filters.
  2. Fact merging with conflict flagging.
  3. Rules, style, and identity templates.
  4. `pam derive [--episode]`.
  5. A test table with ≥ 30 cases.
- **Done when:** the M3 acceptance criteria pass.
- **Agent plan (➕):**
  - Files (all inside Allowed paths): `extract/{patterns,text,facts,rules,style,persona,derive}.py`, `extract/templates/{identity,style}.md.j2`, `cli/derive_cmd.py`, plus a one-sentence fixture plant (`backend/tests/fixtures/claude/export.zip` conv 7, README note) that `test_m03_extract.py` already expects. `text.py` (masking, sentence splitting, lazy spaCy, transcript parsing) and `derive.py` (the pipeline) are additions to the §8 file list.
  - Functions: `facts.extract_candidates(text, role, spacy_model) -> list[Candidate]` and `scan_text` (keeps skipped matches for `pam patterns test`); `facts.Merger(vault, episode_times).add(EpisodeRef, Candidate)` for the §8 merge rules; `facts.write_fact` / `add_backlink` / `write_merge` as the minimal writer T09 reroutes, and `facts.write_candidates(vault, text, agent)` as the route `test_m07_memory.py` expects; `rules.extract_rules(text, role)` and `rules.derive_rules(episodes, min_evidence)`; `style.compute_stats` / `style_sentences`; `persona.render_identity|render_style|render_rules|persona_updates` (uses `agents.manifest.format_rule` / `replace_derived`); `derive.derive(vault, episode, dry_run) -> DeriveReport`.
  - CLI: `pam derive [--episode ID] [--dry-run]` (one commit `derive: +c ~u !k`, none when nothing changed), `pam patterns list|test`, `pam persona show [--agent]`.
  - Tests: the existing `test_m03_extract.py` (64 sentence cases, 13 pattern ids, rules, fixture acceptance) runs unedited with no skips.
  - Risks: `en_core_web_sm` is not in the image, so the regex splitter and capitalization heuristic must pass the same table (the spaCy path is the one more likely to differ); a second `derive` must be a no-op, which needs processed episodes remembered outside the vault history (see CHG-0005); the fixture has no "I live in Seattle" sentence until the follow-up fixture PR, so one is planted here.
- **Result (➕):** 2026-10-17 · PASS · WSL2 checkout, locally (`uv run --frozen`) and in the backend container: `pytest -q tests/test_m03_extract.py` → 109 passed (104 tests-first + 5 review regressions, no skips); full `pytest -q` → 331 passed, 1 skipped (`test_m07_memory.py`, waits for T09), after merging main (T03 follow-up). On the Claude fixture: `pam derive` → `+3 ~0 !0; 1 rules`, one commit (school=UW with WSU in history and a backlink on the WSU episode, location=Seattle, role=international student; rule `Don't use bullet points.` with evidence=2); `--dry-run` writes nothing; a second run and `--episode <done id>` make no commit; `--episode zzzz` exits 1; a held lock exits 4; a `## Custom` rule survives a full re-run with `derive_state.json` deleted; `pam episode verify` → 9 OK. spaCy's `en_core_web_sm` is not installed (local or image), so only the regex/capitalization fallback was exercised. Review fixes logged as CHG-0006.
- **Result (➕):** 2026-10-17 · PASS · Follow-up (CHG-0007): readable `pam derive` output, warnings as plain `Warning:` lines on stderr, and `en_core_web_sm` installed by `uv sync`. WSL2 checkout, locally and in the rebuilt backend container (model loads): `pytest -q tests/test_m03_extract.py` → 112 passed (3 new); full `pytest -q` → 334 passed, 1 skipped. On the Claude fixture with spaCy loaded: same result as above (`+3 ~0 !0`, 1 rule); `--dry-run` prints `Would derive …`, a rerun prints `No changes; …`.

#### T09 · Memory writer (≈ 1.5 h)
- **Module:** M7
- **Allowed paths:** `backend/pam/memory/**`, `backend/pam/extract/facts.py` (only to route writes through M7), `backend/pam/cli/{fact_cmd,project_cmd,skill_cmd,episode_cmd}.py`
- **Depends on:** T06, T08
- **Steps:**
  1. A single write pipeline (lock → validate → write → commit → reindex).
  2. All six write ops.
  3. Backlinks.
  4. `pam fact add|list|show|supersede`, `pam project note|create`, `pam skill add|list`, `pam episode log`.
- **Done when:** the M7 acceptance criteria pass.
- **Agent plan (➕):**
  - Files (inside Allowed paths): `memory/writer.py` (`add_fact`, `supersede_fact`, `log_episode`, `update_project`, `add_skill`, `merge_candidate`, plus `plan_fact`, `Txn`, `reindex`, `commit_message`, `failure_exit_code`, `raise_for_result`), `memory/conflicts.py` (`find_fact_path`, `load_facts`, `replace_value`), `extract/facts.py` (storing routed through the writer: `write_merge`, `write_candidates`, new `store_merge` / `extract_and_store`; `write_fact` and `add_backlink` removed), `cli/{fact,project,skill}_cmd.py` (new) and `cli/episode_cmd.py` (adds `episode log`; `list|show|verify` untouched), tests appended to `tests/test_m07_memory.py`.
  - Pipeline (`_execute`): `vault_write_lock` (10 s, `VaultBusy` → `ok=False` "vault busy") → authorize with `pam.agents.permissions` (`can_call` + `can_write`; an agent without a manifest is denied) → load → mutate → validate (pydantic) → atomic `mdio` writes recorded in a `Txn` → `git.commit` → `index_paths`. A failure rolls the `Txn` back and returns `ok=False` (`PERMISSION_DENIED: …`, `vault busy: …`, `validation failed: …`, or not found); `index_paths` is imported with `try/except ImportError` and called as `index_paths(vault, [vault-relative POSIX paths])`, only after a successful commit.
  - Extraction route: `write_candidates` / `log_episode` run the `Merger`, then replay each fact through `writer.add_fact` when `plan_fact` reproduces exactly what the `Merger` built, else write it with `writer.merge_candidate` (conflicts, older evidence, double-touched slots). `write_merge` (used by `pam derive`) delegates to `merge_candidate`, which neither locks nor commits.
  - Tests (appended): commit-message regex for every action incl. `session=`, `index_paths` spy (once on success, never on failure/denial/no-op/busy), one commit per successful write over a mixed sequence, backlink + `pam episode verify` on an imported episode, `log_episode` id format and extracted fact, tampered-episode abort with rollback, extraction conflict and permission cases, CLI exit codes and one commit per CLI write.
  - Risks: `index_paths`' real signature is T06's (assumed `(vault, paths)` with vault-relative POSIX strings; re-check after T06 merges). Two existing tests in `test_m07_memory.py` had bugs (see CHG-0009).
- **Result (➕):** 2026-10-17 · PARTIAL · Local run (macOS, Python 3.12 pip venv, not `uv`; `en_core_web_sm` absent, so the regex fallback path): `pytest -q` → 391 passed, 1 skipped (`test_m06_retrieve.py`, waits for T07); `test_m07_memory.py` + `test_m03_extract.py` → 169 passed, 0 skipped. CLI on the Claude fixture: `pam derive` → `+3 ~0 !0`, one commit, school=UW with WSU in history; `pam fact add` (overwrite) and `pam fact supersede` each make 1 commit, history grows, the old episode gains the `superseded_facts` backlink, `pam episode verify` → 9 OK; a custom `write=own` agent is denied with exit 3. **Pending:** (1) T06 is not merged, so `index_paths` is skipped and "`pam index stats` / `pam search` sees the new fact" is unchecked; after T06 merges: rebase, make the import hard, rerun everything; (2) the in-container `pytest -q` run. See CHG-0009.
- **Result (➕):** 2026-10-17 · PARTIAL · After T06 (#25) merged: rebased on main, CHG renumbered to CHG-0009, `pam.index.indexer.index_paths` is now a hard import (it takes `(vault, paths)` with vault-relative paths as assumed), and `tests/conftest.py` swaps in a fake embedder so writer reindexing stays offline (`test_m04_index.py` is exempt). Local run (macOS, Homebrew Python 3.13 venv, no fastembed): `pytest -q` → 421 passed, 3 skipped (T07, T12, T13 modules not written), 1 failed (`test_m04_index.py::test_acceptance_real_model…`, needs the real fastembed model). A new test checks that fact, project, and skill writes land in the index (`indexer.stats`). **Pending:** the in-container `pytest -q`, and `pam index stats` / `pam search` on a fact written through the CLI with the real model.

#### T09b · Vault sync watcher (≈ 0.5 h)
- **Module:** M10 (rest)
- **Allowed paths:** `backend/pam/sync/watcher.py`, `backend/pam/cli/sync_cmd.py`, `backend/pam/retrieve/search.py` (one line: call `sync_once()` first)
- **Depends on:** T09
- **Done when:** the M10 acceptance criteria pass.
- **Agent plan (➕):**
  - `sync/watcher.py`:
    - `sync(vault, *, lock_timeout=0.0) -> SyncResult`: one `git.status_porcelain` with no lock; a clean tree returns at once. Otherwise take `vault_write_lock(timeout=lock_timeout)` (busy → `SyncResult(busy=True)`, nothing touched), re-read the status under the lock, and classify each dirty path: unmerged → left alone; deleted (`D` in `XY`) → `git.restore` from HEAD; episode → `EpisodeFrontmatter` must validate and the body must hash to `body_sha256` and (for a tracked file) equal the HEAD body, else `immutable_violation` and not committed; fact / project / skill / `working/*.md` → frontmatter validated against its §7 model, invalid → not committed; anything else → committed as-is. Valid paths go into one `git.commit(..., "manual: <n> files")`, then committed + restored paths go to `index_paths` once (an indexer error is logged; the commit stands).
    - `SyncResult` (dataclass, not a contract): `dirty_paths`, `committed`, `restored`, `immutable_violations`, `invalid` (path → reason), `reindexed`, `commit_sha`, `busy`; `.report` → §7.12 `SyncReport(dirty_paths, reindexed, commit_sha)`.
    - `sync_once(vault) -> SyncReport` (= `sync(vault).report`, logging a warning per restored, violated, or invalid path); `sync_before_read(vault) -> SyncReport | None` wraps it, logs and swallows any exception, and never raises; `watch(vault, interval, on_result=None, ticks=None)` polls `sync`.
  - `retrieve/search.py`: `sync_before_read(vault)` as the first statement of `search()`, plus its import (two lines, not one: the import cannot share the call's line idiomatically). `build_context` calls `search()`, so it is covered too.
  - `cli/sync_cmd.py`: `pam sync [--watch] [--interval SECONDS]`; `--json` prints the `SyncReport` (one JSON line per tick that changed something with `--watch`); human output lists committed, restored, and refused paths; a busy vault exits 4 (`--json` prints the report first).
  - Tests `tests/test_m10_sync.py` (tmp_path vaults via `init_vault`, isolated git config): edited fact → 1 commit, `manual: 1 files`, `index_paths` spy gets that path; untracked fact committed; deleted file restored and reported, no commit; second call no-op; `.pam/` ignored; episode body edit reported, not committed; episode frontmatter-only edit committed; forged `body_sha256` refused; invalid fact frontmatter refused; held lock → `busy`, no crash, CLI exit 4; `search()` works when `sync_once` raises; `search()` sees a hand-edited fact; `pam sync --json` validates as `SyncReport`; `watch(ticks=2)`.
  - Differences from the task prompt: SyncReport (§7.12) has no field for restored paths or body violations, and changing it needs a `PROPOSED` contract entry; they go into `dirty_paths` and the richer `SyncResult` instead (logged by `sync_before_read`, printed by the CLI). The `search.py` edit is two lines (import + call).
  - Risks: a commit whose reindex fails leaves a stale index until `pam index`; a hand-edited episode body stays dirty and is re-reported on every sync until the user reverts it.
- **Result (➕):** 2026-10-18 · PENDING · Code and `tests/test_m10_sync.py` written; not run on this machine (macOS, Python 3.9, no env). `pytest -q` (local and in the backend container), the fresh-vault `pam sync` / `pam search` check, and the real-vault check on the 65-episode import are run by Pranav on WSL. See CHG-0012.

#### T10 · Clusterer & graph (≈ 1.5 h)
- **Module:** M5
- **Allowed paths:** `backend/pam/cluster/**`, `backend/pam/cli/{cluster_cmd,graph_cmd}.py`
- **Depends on:** T06, T09
- **Steps:** incremental assignment, then rebuild with Jaccard ID matching, then c-TF-IDF naming, then the summary, then graph export.
- **Done when:** the M5 acceptance criteria pass.
- **Agent plan (➕):**
  - Files: `cluster/assign.py` (`load_vectors`, `centroid`, `save_centroids`, `assign_incremental`, `cluster_labels`, `jaccard`, `match_clusters`), `cluster/naming.py` (`ctfidf`, `project_name`, `display_term`, `summary_section`, `replace_summary`), `cluster/cluster.py` (`run_cluster(vault, agent="default", rebuild=False, now=None) -> ClusterReport`), `cluster/graph.py` (`build_graph(vault, agent="default", facts=False) -> GraphData`), `cli/cluster_cmd.py` (`pam cluster [--rebuild] [--agent]`), `cli/graph_cmd.py` (`pam graph export [--agent] [--facts] [--out]`). Tests: `tests/test_m05_cluster.py`.
  - Flow: under `vault_write_lock`, read `memory/<agent>/episodes` + `doc_vectors` + `memory/<agent>/projects`; assign/cluster; write changed project files with `mdio`; one `git.commit` `cluster: <mode> +c ~u`; store `project_centroids`; `index_paths` for the touched files.
  - Tests: offline topic embedder (fixture topics on fixed dimensions); fixtures give >= 2 projects incl. Immich; cluster twice is a no-op; `--rebuild` keeps ids; < `min_cluster_size` gives none; a noise episode stays unassigned; agent project never renamed; rebuild-unmatched project goes dormant with a note; dormancy by `now`; c-TF-IDF hand corpus; naming rules; GraphData endpoints, facts flag, restricted agent; CLI `--json` and `graph export --out`.
  - Risks: HDBSCAN on tiny inputs returns all noise; a second run assigning the first run's noise would break "cluster twice is a no-op" (both handled in CHG-0016).
- **Result (➕):** 2026-10-18 · PASS (local) · macOS scratch venv (uv CPython 3.12, `onnxruntime<1.20`): `test_m05_cluster.py` 27 passed; full suite 645 passed, 2 skipped. With the real bge model on the Claude + ChatGPT fixtures: 3 projects (Immich, Tailscale, CSE · CDS), second `pam cluster` and `pam cluster --rebuild` make no commit, `pam graph export --out g.json` validates. Tailscale is `dormant` (last episode 2026-09-06, more than `dormant_after_days` ago). Not yet run: backend container; real 65-episode export (Pranav).
- **Result (➕):** 2026-10-18 · PASS · B-04 (CHG-0019): on the 3 fixtures with the real bge model (macOS 12, uv CPython 3.12 venv, `onnxruntime<1.20`), `pam cluster` named the university project "Day" before the fix and now gives Immich, CSE · CDS, Tailscale (17 assigned); the offline test embedder gives Immich, Tailscale, CSE · Jobs, Checklist · Day Hike. `test_m05_cluster.py` 32 passed; full suite 707 passed, 2 skipped. Rebased on main (T13).
- **Result (➕):** 2026-10-18 · PASS · T10 review (Yogesh), WSL2 checkout, locally (`uv run --frozen`) and in the backend container: CHG-0020 (an unreadable project file stops `pam cluster` instead of its episodes moving to another project; `graph export --out` creates folders, no traceback) and CHG-0021 (`assign_threshold` 0.70). With the real bge model on the 3 fixtures: Immich 7, Tailscale 4, CSE · CDS 4, lentils and hike unassigned; second `pam cluster` and `--rebuild` make no commit; `graph export --out` validates. `test_m05_cluster.py` and the full suite pass (counts in PR #35).

#### T11 · Working memory (≈ 0.75 h)
- **Module:** M9
- **Allowed paths:** `backend/pam/working/**`, `backend/pam/cli/session_cmd.py`
- **Depends on:** T09
- **Done when:** the M9 acceptance criteria pass (`pam chat` is stubbed until T13; test with `pam session record`).
- **Agent plan (➕):**
  - `pam/working/session.py`: `start(vault, agent, model) -> WorkingMemory`, `record_turn(vault, session_id, role, text, model) -> WorkingMemory`, `update(vault, UpdateWorkingMemoryInput, agent="default") -> WriteResult` (alias `update_working_memory`, the name M11 imports), `show(vault, id)`, `list(vault)` / `list_sessions`, `end(vault, session_id, agent=None) -> WriteResult`, `transcript_path`, `render_body`. Every write holds `vault_write_lock`; the transcript is never `git add`ed.
  - `pam/cli/session_cmd.py`: `pam session start --agent --model`, `record ID --role user|assistant --text --model`, `show ID`, `update ID [--goal] [--decision ...] [--question ...]`, `list`, `end ID [--agent]`; `--json` prints the contract models.
  - `tests/test_m09_working.py`: id format; 8-turn window; 2 models + 4 turns; no commit per turn; 1 commit each for start, goal, update; append-only decisions; transcript order; `pam sync` after 4 turns makes no commit and leaves the jsonl untracked; end → `source=pam` episode with every turn, `promoted_episode_id`, `pam episode verify`; ending twice; contract round-trip; CLI acceptance.
  - Risks: per-turn state vs. sync (CHG-0014 item 1); `end` is two commits (item 3).
- **Result (➕):** 2026-10-18 · PASS · WSL2 checkout, locally (`uv run --frozen`) and in the backend container: `pam session start`, 4 `pam session record` on two models, then `pam session show` lists 2 models and 4 turns, and `pam session end` creates a `source=pam` episode with every turn (`pam episode verify` OK); `pam sync` after the turns makes no commit and the transcript stays untracked. `tests/test_m09_working.py` 43 passed; the previously skipped `test_m06_retrieve.py::test_context_includes_working_memory_when_supported` and `test_m11_mcp.py::test_update_working_memory_returns_write_result` now pass. Full `pytest -q`: 596 passed, 2 skipped (T14 app, opt-in perf). See CHG-0014.

#### T12 · MCP server (≈ 1 h)
- **Module:** M11
- **Allowed paths:** `backend/pam/mcp_server/**`, `backend/pam/cli/mcp_cmd.py`
- **Depends on:** T07, T09, T11
- **Steps:** FastMCP tools wired to the core, agent-filtered registration, stdio + HTTP app factory, then a test with MCP Inspector.
- **Done when:** the M11 acceptance criteria pass.
- **Agent plan (➕):**
  - Files: `mcp_server/tools.py` (`TOOL_SPECS` for the ten tools, `Binding`, `make_tool`, `_deps`, `NotAvailable`), `mcp_server/server.py` (`build_server`, `McpHttpApp`, `http_app`), `cli/mcp_cmd.py` (`pam mcp serve|tools`). Tests: `tests/test_m11_mcp.py`.
  - Each tool is registered with a keyword-only signature copied from its contract model (`get_context` without `agent`), so the advertised schema equals the model's; the handler re-validates with the model, forces `agent` to the bound agent, calls core in a worker thread and returns a `CallToolResult` (structured JSON plus one text block; `rendered` for `get_context`).
  - `pam.retrieve.*` and `pam.working.session` are imported inside the tool; a missing module returns `NOT_AVAILABLE: <module> not merged yet`. All tools a manifest allows are registered.
  - HTTP: one ASGI app that answers on any path and picks the server from `?agent=` per request; unknown agent gives 404, `build_server` raises `PamError`.
  - Tests added: `NOT_AVAILABLE` for a blocked import (read and write tool), `get_context` wiring with a faked retriever, unknown agent (build and HTTP), stdio `initialize` through a subprocess, `update_working_memory` (importorskip).
  - Risks: the installed SDK is mcp 2.3.0 (`MCPServer`, snake_case result fields), not `FastMCP` of mcp 1.x; the T11 entry point `pam.working.session.update_working_memory(vault, data, agent=)` is assumed.
- **Result (➕):** 2026-10-17 · PARTIAL · Local run (macOS, Python 3.12 pip venv, no loadable sqlite extension, so the `pam index` step of the `vault` fixture was stubbed outside the repo): `test_m11_mcp.py` 18 passed, 4 skipped (3 wait for T07: `get_context`, `search_memory`, Z-datetimes; 1 waits for T11: `update_working_memory`); full suite 409 passed, 6 skipped, 1 failed (`test_writes_are_indexed_for_real`, the missing sqlite extension). Not yet run: `docker compose exec backend pytest -q`, MCP Inspector, Claude Desktop. PM reruns after T07 and T11 merge.

#### T13 · Chat orchestrator (≈ 1.5 h)
- **Module:** M12
- **Allowed paths:** `backend/pam/chat/**`, `backend/pam/cli/{chat_cmd,models_cmd}.py`
- **Depends on:** T12
- **Steps:** a LiteLLM streaming wrapper, then an MCP client session, then injection mode, then tool mode, then `pam chat`, `pam models list|check`.
- **Done when:** the M12 acceptance criteria pass.
- **Agent plan (➕):**
  - Part 1 (LLM layer + models CLI; MCP client, orchestrator and `pam chat` are T13 rest). Files: `chat/llm.py`, `cli/models_cmd.py`, `tests/test_m12_chat.py`.
  - `llm.py`: `PAM_PREAMBLE`; `resolve_model(cfg, model_id) -> ModelEntry` (raises `UnknownModel`, exit 2); `async stream_chat(model, messages, tools=None) -> AsyncIterator[LLMDelta]` with `LLMDelta(text, tool_calls: list[ToolCall], finish_reason, usage: Usage)` and `ToolCall(id, name, arguments: dict).as_openai()`; `async ping(model) -> PingResult(ok, latency_ms, error)`; `LLMError(message, retryable)`. Constants `REQUEST_TIMEOUT_S`, `PING_TIMEOUT_S`, `PING_MAX_TOKENS`.
  - `models_cmd.py`: `pam models list` (`--json`), `pam models check` (concurrent pings, exit 1 only if every model fails or none are configured).
  - Tests: text join, tool-call fragment assembly (and order, invalid JSON), usage from last chunk, tools only with `supports_tools`, env keys / Ollama base, `UnknownModel`, retryable mapping (rate limit, timeout mid-stream, auth), ping ok/fail, `models list --json`, fresh vault, `models check` exit codes and JSON.
  - Risks: OpenRouter free models may reject `max_tokens=1` or vanish; the live check shows it.
  - T13 rest (MCP client, orchestrator, `pam chat`). Files: `chat/mcp_client.py`, `chat/orchestrator.py`, `cli/chat_cmd.py`, `tests/test_m12_chat_orchestrator.py`.
  - `mcp_client.py`: `open_session(vault, agent, url=None)` yielding the SDK `ClientSession` (in-process `build_server` for the CLI and tests, streamable HTTP `<url>?agent=` for T14); helpers `openai_tools(session)`, `call_tool(session, name, args) -> ToolOutcome(text, structured, is_error)`, `get_context(session, query, session_id) -> ContextBundle`; `McpToolError(message, retryable)`.
  - `orchestrator.py`: `async run_turn(vault, req: ChatRequest, *, mcp_url=None) -> AsyncIterator[ChatEvent]`, `stream_chat` imported into the module namespace; constants `MAX_TOOL_ROUNDS = 5`, `TOOL_SUMMARY_CHARS = 200`; `ToolRoundLimit`, `ToolsUnsupported`.
  - `chat_cmd.py`: `pam chat MESSAGE --model [--session] [--agent] [--mode] [--show-context]`, `--json` = NDJSON events.
  - Tests: event order and prompt shape, `doc_ids`, `get_context` args, usage/no usage, both turns recorded, hot swap A→B sees A's turn, 8-turn history window, empty reply, real `get_context`; with the Claude fixture imported and indexed (offline embedder): context fields vs. the bundle, hot swap, tool mode calling `get_context`; tool mode round trip, text across rounds and summed usage, parallel calls, disallowed tool, answer on the last allowed round, endless loop stopped by an error at the cap, tool mode on a model without tools = context then error; unknown model writes nothing, LLM errors mid-stream and in a tool round, an unexpected exception, unknown/ended session, agent mismatch vs. adoption, missing `get_context` (context first, then error), `VaultBusy` on the reply, unreachable MCP URL; MCP client session type, schemas and errors; CLI text with the closing session line, `--show-context`, NDJSON, tool lines, exit codes 1/2, follow-up, log quieting, `--help` options; a `ChatEvent` sample guard. Every stream is checked against §7.14 (context first, one terminal event, last).
  - Risks: live A→B acceptance needs keys (Pranav).
- **Result (➕):**
  - 2026-10-18 · part 1 PASS · `pytest -q tests/test_m12_chat.py` 22 passed, no network (macOS 12 Intel, Python 3.12 pip venv, `onnxruntime<1.20`, litellm 1.106.0). Full suite: 486 passed, 2 skipped, 22 failed, 89 errors; the failing set is identical to main's (no loadable sqlite extension in this Python: test_m04/m06/m07/m10/m11 `pam index` paths). Docker not run (daemon down). `pam models list` on a fresh vault: hint, exit 0. Live `pam models check` on vault/pam.toml: 3/3 OK (nemotron-3.5-lightning 13129 ms, nemotron-3.5-super-vl 728 ms, dots-3-note-preview 962 ms); live `stream_chat` on nemotron-3.5-super-vl streamed text with usage and assembled one `search_memory` tool call. See CHG-0015.
  - 2026-10-18 · rest PASS (offline) · WSL2 checkout, locally (`uv run --frozen`) and in the backend container: `pytest -q tests/test_m12_chat_orchestrator.py tests/test_m12_chat.py` 79 passed (57 new); full `pytest -q` 675 passed, 2 skipped. `pam chat --help` lists the SETUP M12 options. Real `pam chat` on a scratch vault without keys: `session <id> · context ...` header, then `ErrorEvent` (AuthenticationError, exit 1) in text and `--json`, persona-only context then an error in tool mode on a model without tools, unknown model exit 2, stdout free of LiteLLM logs. Live M12 acceptance (model A, then model B with `--session`; tool mode calling `get_context`) not run here: no provider keys on this machine; pending Pranav. See CHG-0018.

#### T14 · REST API (≈ 1.25 h)
- **Module:** M13
- **Allowed paths:** `backend/pam/api/**`, `backend/pam/cli/api_cmd.py`
- **Depends on:** T10, T13
- **Steps:** the app factory (mounting `/mcp`), each route file, the import job runner, SSE chat, error mapping, `pam api serve`.
- **Done when:** the M13 acceptance criteria pass, and `/docs` lists every endpoint from §7.14.
- **Agent plan (➕):**
- **Result (➕):**

#### T15 · Frontend (≈ 3.5 h total, built page by page in this order)
- **Module:** M14
- **Allowed paths:** `frontend/**`
- **Depends on:** T14
- **Subtasks:**
  - **a.** Layout, routing, theme, API client + type generation (0.5 h)
  - **b.** Import wizard + guides (0.5 h)
  - **c.** Graph (0.75 h)
  - **d.** Chat with model switch + context panel (0.75 h)
  - **e.** Search playground (0.35 h)
  - **f.** Vault browser (0.3 h)
  - **g.** Agent editor (0.35 h)
- **Done when:** the M14 acceptance criteria pass.
- **Agent plan (➕):**
- **Result (➕):**

#### T16 · Docker hardening & demo (≈ 1 h)
- **Module:** M15
- **Allowed paths:** `/docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `/SETUP.md` (🔒 human review), `demo/**`
- **Depends on:** T15
- **Steps:**
  1. Bake the models into the image; add a healthcheck and SSE proxying.
  2. Do a clean-machine test on Windows and macOS.
  3. Write `demo/run-demo.md`, a step-by-step script for §3.3.
  4. Rehearse twice.
- **Done when:** the M15 acceptance criteria pass and the demo runs in under 4 minutes.
- **Agent plan (➕):**
- **Result (➕):**

### 9.4 Cut list (if behind schedule, cut from the top) 🔒
1. Gemini importer (show that Gemini consumes memory via MCP instead).
2. Tool mode in chat (injection mode alone proves the claim).
3. Fact nodes in the graph.
4. `pam sync --watch` loop (keep the on-request `sync_once`).
5. Agent editor UI (create agents via the CLI).
6. Skills (keep the tool, drop the UI).

---

## 10. Changes ➕ (append-only log)

**Rules**
- Entries are **appended at the bottom** and **never edited or deleted**. Status changes are new lines appended inside the entry's `Status log`.
- **Type `contract`** (anything in §7), **`layout`** (§5/§6), and **`scope`** (§1) start as `PROPOSED`. An agent **must not implement them** until a human appends `APPROVED`.
- **Type `design`** (internal algorithm or a module's implementation choice that doesn't affect any contract) and **`dependency`** (adding or removing a library) may be logged by an agent as `IMPLEMENTED` directly, but must still be logged.
- A contract change that is approved must also bump `SCHEMA_VERSION`: minor for additive changes, major for breaking ones. The human applying it updates §7 and regenerates `/schemas` + TS types.
- IDs increase monotonically: `CHG-0001`, `CHG-0002`, …

**Template**
```markdown
### CHG-XXXX — <short title>
- **Type:** contract | layout | scope | design | dependency
- **Module(s):** Mx
- **Proposed by:** agent (task Txx) | human (<name>)
- **Date:** YYYY-MM-DD HH:MM
- **Motivation:** why the current spec doesn't work
- **Proposal:** exact change — for contracts, include the full new Pydantic code
- **Impact:** affected modules / files / data migration
- **Status log:**
  - YYYY-MM-DD HH:MM · PROPOSED · <who>
```

### CHG-0000 — Baseline spec v1.0.0
- **Type:** scope
- **Module(s):** all
- **Proposed by:** human (team) with Claude
- **Date:** 2026-10-16
- **Motivation:** initial spec
- **Proposal:** this document as written
- **Impact:** none (baseline)
- **Status log:**
  - 2026-10-16 · PROPOSED · team
  - _(human: append `APPROVED` here once the team has reviewed §11)_
  - 2026-10-17 12:36 · APPROVED · team (Pranav)

<!-- Append new change entries below this line. Never edit above it. -->

### CHG-0001 — M0 implementation choices: CLI auto-discovery, own frontmatter splitter, `pam config` placement
- **Type:** design
- **Module(s):** M0 (affects how every later task adds CLI commands)
- **Proposed by:** agent (task T01)
- **Date:** 2026-10-17 13:45
- **Motivation:** Only T00/T01 may edit `cli/main.py`, but every later task adds commands. `python-frontmatter` strips the body, which breaks `body_sha256` (§7.3). `pam config` (SETUP §6) has no `config_cmd.py` in T01's allowed paths.
- **Proposal:**
  1. `cli/main.py` imports every `pam/cli/*_cmd.py` (alphabetically) and calls its `register(app: typer.Typer)`. That function adds top-level commands (`app.command("x")(fn)`) or groups (`app.add_typer(sub, name="x")`). If a module has no `register` but defines a module-level `app = typer.Typer()`, it is mounted as `pam <name>` (from `<name>_cmd.py`). Global options go into `ctx.obj` (`json`, `verbose`), and `--vault` goes into `pam.core.vault.set_vault_override`. Raising `pam.core.errors.PamError` (or a subclass) exits with its SETUP §5 code, and a pydantic `ValidationError` exits with 2. `*_cmd.py` modules must not import `pam.cli.main`, because that creates a circular import.
  2. `pam.core.mdio` parses `---\n<yaml>---\n<body>` itself with PyYAML and returns the body byte-for-byte. `python-frontmatter` stays a dependency but is unused.
  3. `pam config show|path` lives in `cli/init_cmd.py`.
- **Impact:** Every later `*_cmd.py` defines `register(app)` (preferred) or a module-level `app`. No contract changes.
- **Status log:**
  - 2026-10-17 13:45 · IMPLEMENTED · agent (T01)

### CHG-0002 — M8 implementation choices: `rules.md` format, project-scoped episodes, persona fallbacks
- **Type:** design
- **Module(s):** M8 (affects M3/T08, which writes Derived persona sections, and M6/T07, which applies the read filter)
- **Proposed by:** agent (task T05)
- **Date:** 2026-10-17 22:20
- **Motivation:** §7.7 fixes the two persona headings but not how `PersonaRule` fields are stored in `rules.md`. The §7.8 `documents` table has no project column, so "episodes in `project_ids`" cannot be filtered from the index alone. §8 M8 does not say what happens with persona files missing a heading.
- **Proposal:**
  1. `rules.md`: one `- ` bullet per rule. Derived rules carry their metadata in a trailing HTML comment: `- Don't use bullet points. <!-- r_1a2b3c4d evidence=3 episodes=<uuid>,<uuid> -->`. A plain bullet in Custom is `origin=manual`, `evidence_count=0`, id = `rule_id(text)` (`"r_"` + first 8 hex of sha256 of the lowercased, whitespace-collapsed text). T08 writes rules with `pam.agents.manifest.format_rule` and replaces the Derived section with `replace_derived`.
  2. `visible_doc_filter(agent, vault=None, alias="documents")` takes the vault and reads `memory/*/projects/<id>.md` for each `read.project_ids` entry; their `episode_ids` become a `doc_id IN (...)` term. A project without a file adds nothing.
  3. Persona text before `## Derived`, or in a file with no headings, counts as Custom. `replace_derived` on a file without a Derived heading inserts both headings and keeps the existing text under Custom.
  4. `can_*` return booleans and callers raise `PermissionDenied`. `can_call` denies write tools when `write="none"`. `set_scope` refuses `default` to keep the §7.7 promise.
- **Impact:** T08 uses `format_rule`/`replace_derived`; T07 passes the vault (and an alias) to `visible_doc_filter`. No contract changes.
- **Status log:**
  - 2026-10-17 22:20 · IMPLEMENTED · agent (T05)

### CHG-0002 — M2 implementation choices: lazy archive, update ids, LF bodies, folder commits
- **Type:** design
- **Module(s):** M2
- **Proposed by:** agent (task T04)
- **Date:** 2026-10-17 17:00
- **Motivation:** §8 M2 leaves several cases open: an archive copy would be an uncommitted stray file when nothing is new; `mdio` stores LF while a message may contain CRLF; the `--update` id format and the commit size are unspecified.
- **Proposal:**
  1. The raw export is archived (and committed) only when at least one episode is written. A run with nothing new makes no archive and no commit, and `ImportReport.archived_path` is `""`. With `--dry-run`, it holds the path that would be used.
  2. A same-second archive collision moves to the next free second, so an archived file is never overwritten.
  3. `--update` id is `uuid5(PAM_NAMESPACE, "episode:<source>:<id>:<updated_at>")` with `updated_at` as ISO-8601 UTC `Z`. The `supersedes:<old_id>` tag points at the newest stored version of that conversation, so versions form a chain. A conversation without `updated_at` is never updated.
  4. CRLF in message text becomes LF in the body before hashing, because `mdio` writes LF; otherwise `body_sha256` would not verify.
  5. After a crash or failed commit the writer deletes the files it created. Episode files that are untracked in git (left by a killed process) count as not yet written and are rewritten.
  6. With 1000 or more written files the commit passes the archive folder and the agent's `episodes/` folder instead of every file, to stay under the OS argument limit.
  7. `ImportReport.errors` from `write_episodes` holds only writer warnings; `pam import run` prepends the importer's parse warnings.
  8. `pam import run --all` (SETUP §4) is deferred until derive, index and cluster exist.
- **Impact:** M2 only. No contract changes.
- **Status log:**
  - 2026-10-17 17:00 · IMPLEMENTED · agent (T04)

### CHG-0005 — M3 implementation choices: new patterns, spaCy fallback, merge bookkeeping, rule anchoring
- **Type:** design
- **Module(s):** M3 (affects M7/T09, which reroutes the fact writer, and the Claude fixture)
- **Proposed by:** agent (task T08)
- **Date:** 2026-10-17 16:20
- **Motivation:** §8 M3 leaves the pattern details, the merge bookkeeping, and the no-spaCy case open, and `test_m03_extract.py` pins several choices the starter table does not cover.
- **Proposal:**
  1. Pattern changes: a new `attend` pattern (`\bi (?:go to|attend) (?P<v>.+)` → `school`, education, single, ORG); `use_tool` and `stack` values split on `,` / `and`, one MULTI fact per tool; capitalized value groups (`name`, `call_me`, `use_tool`) match case-sensitively through a scoped `(?-i:...)` flag; `job_title` is non-greedy and allows at most 3 words before the role keyword (`(?:\w+ ){0,3}?`); `major` does not fire on "studying at" and rejects values that start with a preposition or pronoun; `live_in` also matches "I'm based in" (`I(?: live|'m based| am based) in`); apostrophes match straight or curly. Confidence follows §8 (0.75 identity/education/work/location, 0.6 otherwise).
  2. Values: a clause ends at `,`, `;`, `(`, a masked span, ` and `, ` but `, ` because `, or `.` only before whitespace or the end (so `Node.js` survives); list-valued patterns keep `,` and `and` and split on them. Values are capped at 60 characters at a word boundary. The junk filter drops pronouns and generic nouns with an optional article (`it`, `this`, `a list`, `a function`, `the thing`, …).
  3. Skips: a question mark anywhere in the sentence; `if|would|imagine|pretend` plus `suppose|assuming|hypothetically`; `not|never|cannot|nor|neither|no longer|…n't` within the 3 tokens before the trigger (the trigger's own words do not count, so "I can't stand Java" is a dislike). Double quotes, curly quotes, inline code, and code fences are masked before matching.
  4. NER filter: the value must contain a capitalized token and either be an acronym (`UW`, `WSU`) or, when spaCy ran, overlap an `ORG`, `GPE`, `LOC`, `FAC`, or `PRODUCT` entity (ORG filter) or a `GPE`, `LOC`, or `FAC` entity (GPE filter), because the small model often labels companies and places loosely. Without spaCy the capitalization test alone decides.
  5. spaCy: `en_core_web_sm` is loaded lazily on first use. If spaCy or the model is missing, `pam.extract.text` warns once and falls back to a regex sentence splitter, so the suite passes either way. Rules use the same splitter and need no entities.
  6. Merging: facts always land in the `shared` scope, whichever agent's episode is mined. Confidence is bumped once per distinct episode, not per mention. An overwrite pushes a history entry (`value=<old>`, `changed_by=rule`, `changed_at=<now>`, `episode_id=<old source episode>`), sets `source_episode` and `updated_by_episode` to the new episode, resets confidence to the pattern default, and appends the fact id to the old episode's `superseded_facts` (frontmatter only; the body hash is re-checked first). A slot already in `status=conflict` is never changed by rules, and an episode that already appears in a fact's `source_episode`, `updated_by_episode`, or history is not applied again.
  7. Idempotence: processed episode ids are stored in `.pam/derive_state.json` (derived, gitignored, §6), so a second `pam derive` adds no confidence and makes no commit. Deleting the file re-processes every episode; the history check above prevents false conflicts in that case.
  8. Rules: `^(?:please )?(?:don't|do not|never|always|stop|avoid) (?:use|using|write|include|add|give|say) ...` also accepts leading filler words and the gerunds of those verbs; the `no <noun>` regex must start a sentence or clause (so "I have no markdown files" is not a rule); rules skip questions and negations but not hypotheticals (`if possible` is common in instructions). Canonical text is `Don't <verb> <value>.`, `Always <verb> <value>.`, `Keep answers <word>.`; `emoji` / `bullet point` are pluralized. Evidence counts distinct episodes; `evidence_episodes` keeps the first five by time.
  9. Persona: rules, style, and identity are recomputed from all episodes on every run (also with `--episode`); only the Derived sections are rewritten, with `format_rule` / `replace_derived`. `DeriveReport.rules_derived` is the number of derived rules in the persona, `facts_updated` counts pre-existing facts that gained confidence or a new value, and `conflicts_flagged` counts slots newly flagged.
  10. The tunable numbers the spec fixes in prose (bump 0.05, cap 0.95, 60 characters, 3 tokens, style thresholds) are named module constants in `patterns.py` and `style.py`, because §7.13 `ExtractCfg` only has `rule_min_evidence` and `spacy_model`.
  11. `facts.write_candidates(vault, text, agent)` extracts from one message and commits the facts; it is the hook `test_m07_memory.py` expects T09 to route through `pam.memory`.
  12. Fixture: conv 7 of `tests/fixtures/claude/export.zip` now says "I live in Seattle and i just re-entered the US for my first quarter of sophomore year." (was "i just re-entered seattle for my first quarter"), in both `text` and the `content[]` block, because `test_m03_extract.py` requires `location=Seattle` and the fixture had no such sentence. `tests/fixtures/claude/README.md` lists it.
- **Impact:** M3 only, plus the fixture sentence above. T09 replaces `write_fact` / `write_merge` with `pam.memory` calls. No contract changes.
- **Status log:**
  - 2026-10-17 16:20 · IMPLEMENTED · agent (T08)

### CHG-0006 — M3 review fixes: rule punctuation, bump evidence, older evidence after newer
- **Type:** design
- **Module(s):** M3
- **Proposed by:** Yogesh (review of T08)
- **Date:** 2026-10-17
- **Motivation:** Manual testing of T08 found three cases where the result depended on wording, on re-processing, or on processing order.
- **Proposal:**
  1. Rules: trailing punctuation is stripped again after a polite tail (`thanks`, `please`, `pls`) is removed, so "Please don't use emojis, thanks" gives `Don't use emojis.` (was `Don't use emojis,.`) and counts as the same rule.
  2. Same-value merge: the confirming episode becomes `updated_by_episode` (kept when the evidence has no episode). `_seen` then stops that episode from bumping confidence a second time when it is mined again (lost `derive_state.json`, repeated `write_candidates`). An older confirming episode can still bump again; that is bounded by the 0.95 cap, and a full evidence list would need a §7.4 contract change.
  3. Different value on a SINGLE rule-extracted slot from an **older** episode than the current value's source (e.g. `pam derive --episode <newer>` first, then the rest): the current value stays, the older value is appended to `history` (`changed_by=rule`, `episode_id=<older episode>`), and the older episode gets the `superseded_facts` backlink. No conflict is flagged, so the end state matches one chronological run. Equal timestamps and non-rule facts still conflict. `Merger.add` returns `superseded` for this case.
- **Impact:** M3 only (`extract/rules.py`, `extract/facts.py`), plus 5 tests appended to `tests/test_m03_extract.py`. No contract changes.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · Yogesh (T08 review)

### CHG-0007 — M3 CLI output, warnings, and the spaCy model as a uv dependency
- **Type:** dependency, design
- **Module(s):** M3 (touches T00's `backend/pyproject.toml` and `uv.lock`; overlaps T16's model baking)
- **Proposed by:** Yogesh (manual testing of T08)
- **Date:** 2026-10-17
- **Motivation:** `pam derive` printed a raw Python `RuntimeWarning` (source path and code line) and a terse `derive: +3 ~0 !0; 1 rules; …` line. The spaCy model was never installed, and SETUP §7's `uv run python -m spacy download en_core_web_sm` cannot work because `spacy download` calls pip and the uv venv has no pip.
- **Proposal:**
  1. Dependency: `en-core-web-sm` is a project dependency, pinned in `[tool.uv.sources]` to the `en_core_web_sm-3.8.0` wheel URL (hatchling rejects direct references in `[project]`). `uv sync` installs it locally and in the image, so the regex fallback only runs when the model is genuinely missing. The fallback warning now says to run `uv sync`.
  2. Output follows the other commands (a plain sentence, then `commit <sha> · <time>`): `Derived N new facts (U updated, K conflicts); the default persona has R derived rules`, plus two hints (`pam --vault <root> persona show`, `git -C <root> show --stat <sha>`). A dry run prints `Would derive …(dry run, nothing written)`, and a run with no commit prints `No changes; …`. `--json` is unchanged; the commit message stays `derive: +c ~u !k`.
  3. Warnings raised during `pam derive` and `pam patterns test` print once each on stderr as `Warning: <message>`, with no source location.
- **Impact:** `backend/pyproject.toml`, `backend/uv.lock`, `extract/text.py` (warning text), `cli/derive_cmd.py`, plus 3 tests appended to `tests/test_m03_extract.py`. No contract changes. Needs human edits outside T08's paths: SETUP §7 should drop the `spacy download` step, and the `backend/Dockerfile` header comment ("T16 bakes the spaCy … models") is now only true for fastembed.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · Yogesh (T08 follow-up)

### CHG-0008 — M4 implementation choices: heading times, chunk format, change hash, no lock, edge cases
- **Type:** design
- **Module(s):** M4 (affects M5/T10 and M6/T07, which read the index, and M7/T09 and M10/T09b, which call `index_paths`)
- **Proposed by:** agent (task T06)
- **Date:** 2026-10-17
- **Motivation:** §8 M4 leaves open how turns are rendered in a chunk, what `content_sha256` covers, whether indexing takes the vault lock, and what happens with bad files. The §7.3 example shows whole-second times, but M2 writes message times with microseconds.
- **Proposal:**
  1. Role headings match `### <user|assistant|system|tool> · <YYYY-MM-DDTHH:MM:SS[.ffffff]Z | unknown>`. Any other line is message text.
  2. Episode chunks: chunk 0 is `[<title>] Summary: <summary>` when there is one. Each user turn opens a group, and the following non-user turns join it (a leading non-user turn forms its own group). A group renders as `<role>: <text>` blocks separated by blank lines, without timestamps; attachment lines stay. The `[<title>] ` prefix counts toward `max_tokens`. An episode with no turns and no summary gets one title-only chunk, so every episode has a `doc_vectors` row.
  3. Splitting: paragraphs (blank-line separated) are packed greedily; a paragraph over the budget is cut into token windows; each new piece starts with about `overlap_tokens` of the previous piece's tail, cut at a word boundary, unless that would exceed the budget.
  4. `content_sha256` hashes the whole file (frontmatter and body), because fact, project, and skill values live in the frontmatter. `documents.token_count` is the token count of the full body (T07 uses it as the episode baseline).
  5. Indexing takes no vault lock and makes no commit: it writes only `.pam/index.db` (SQLite locking, WAL, 10 s busy timeout). `index_paths(vault, paths, embedder=None)` can therefore run inside M7/M10's lock. Relative paths are vault-relative; non-document paths are ignored; a missing file is removed from the index.
  6. A file that fails to parse is skipped with a `Warning:` on stderr and its old rows are removed. A second file carrying an id that another existing file already has (a copy) is skipped with a warning. `embedding.dim` other than 384 is refused, because `chunks_vec` is `float[384]`.
  7. The model loads only when something must be embedded, so an empty or unchanged vault never loads it. `get_embedder(cfg)` keeps one instance per model per process for T07 to reuse.
  8. `pam index stats` is recognized as the single argument `stats`, since Typer cannot mix `[PATHS...]` with a subcommand; `--json` prints `{types: {doc_type: {documents, chunks}}, documents, chunks, embedding_model, embedding_dim, last_indexed_commit, db_bytes}`. `--rebuild` with paths is an error.
  9. Named constants from §8 prose: `BATCH_SIZE = 64`, `SKILL_STEPS_TOKENS = 300`; `index_version` is `1`.
  10. A `[chunking]` change in `pam.toml` is not detected: unchanged files keep their old chunks until `pam index --rebuild`, which the `--rebuild` help text says. Detecting it would need a new `meta` key, and §7.8 fixes the key list. Only a model change is refused (§8 M4).
- **Impact:** M4 only. No contract changes.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · agent (T06)

### CHG-0009 — M7 implementation choices: write pipeline, unknown agents, extraction route, test fixes
- **Type:** design
- **Module(s):** M7 (touches M3's `extract/facts.py` writer half; M4 `index_paths` call; two tests in `test_m07_memory.py`)
- **Proposed by:** agent (task T09)
- **Date:** 2026-10-17
- **Motivation:** §8 M7 fixes the pipeline but not failure reporting, the slot rules of a direct `add_fact`, how M3's merge reaches the writer without a second commit, or what an unknown agent may do. Two tests written first contradict the spec or each other.
- **Proposal:**
  1. Failures are returned, never raised: `ok=False` with `PERMISSION_DENIED: …`, `vault busy: …`, `validation failed: …`, or a plain not-found message. The CLI maps them to exit 3, 4, 2, 1 (`writer.failure_exit_code`). An agent with no `agent.yaml`, or an invalid name, is denied. Writes roll back through a `Txn` (previous bytes restored, new files removed) and make 0 commits.
  2. `add_fact`: same normalized value raises confidence to the larger value and follows `updated_by_episode`; an exact repeat is `ok` with no commit and no `commit_sha`. A different SINGLE value overwrites: history entry (old value, `changed_by`, agent name only for agent writes, old `source_episode`, reason), last 20 kept, conflict cleared, `extractor` becomes the writer, backlink on the old `source_episode`. A backlink whose episode body no longer matches `body_sha256`, or changes while writing, aborts the write (`validation failed`); a missing episode file is skipped. `pam derive` (`merge_candidate`) keeps its earlier warn-and-skip for that case.
  3. `supersede_fact`: keeps confidence, `source_episode` = `episode_id` (may be none), always records a history entry with the reason (also when the value is unchanged), and refuses MULTI facts (their id depends on the value; use `add_fact`).
  4. Keyword-only internals on `add_fact` (public signature unchanged): `extractor`, `pattern_id`, `now`, `reason`, and `txn`. Passing a `txn` joins the caller's transaction: no lock, no commit, no reindex, no rollback. (This replaces the `commit` / `locked` pair proposed in the task discussion with one argument.)
  5. `write_candidates` and `log_episode` merge with the unchanged `Merger`, then `store_merge` replays each fact through `writer.add_fact` when `writer.plan_fact` produces the same fact the `Merger` built (new slots, bumps, overwrites), and writes the rest verbatim with `writer.merge_candidate` (conflicts, older evidence recorded as history, a slot touched twice in one run), so CHG-0005/0006 hold. `merge_candidate(vault, result, agent="default", *, txn=None) -> (changed, created)` neither locks nor commits; `facts.write_merge` delegates to it. `facts.write_fact` and `facts.add_backlink` are removed. `write_candidates` now needs the agent to be allowed to write shared facts (`PermissionDenied` otherwise) and reindexes after its single `derive: +c ~u !k` commit.
  6. `log_episode`: id `memory/<agent>/episodes/<uuid5>.md` from `source_conversation_id = "{agent}:{utc_iso}:{sha8}"` (sha8 of title, summary, messages), `tags` stored, the session id only in the commit message. Fact extraction runs on the user messages in the same commit and is skipped when the agent may not write shared facts. Logging an identical conversation within one second is an `ok` no-op.
  7. `update_project`: a new project has `## Summary (auto)` (empty) and `## Notes`; a note becomes one single-line bullet; an episode may belong to only one project of a scope (otherwise `validation failed`); `name` and `status` on an existing project update it; nothing to change is an `ok` no-op. `add_skill` keeps the stored name when the normalized name matches (`Release checklist` = `release-checklist`).
  8. Reindex: `index_paths(vault, paths)` receives vault-relative POSIX strings, after a successful commit only. An indexer error is logged and does not fail the committed write. Until T06 merges the import falls back to `None` and the step is skipped.
  9. Test fixes (assertions unchanged): `test_fact_scope_tracks_shared_flag` now creates the `research` agent first (`write="own"` for `shared=False`, `"shared"` for `shared=True`), because it contradicted `test_permission_cases_wait_until_m8_is_available` (same call, no manifest); `test_supersede_clears_conflict_and_records_reason` writes `detected_by: "rule"` instead of `"extractor"`, which is not an `Actor` and cannot be read back.
  10. CLI: ids may be unique prefixes; `--agent` on `fact list|show` and `skill list` filters by `can_read`; `pam project add-episodes` is included (SETUP §6); `pam episode log --messages` reads JSONL of `RawMessage` (`-` for stdin).
- **Impact:** M7, `extract/facts.py`, four CLI modules, `test_m07_memory.py`. No contract changes. Pending T06: the real `index_paths` signature.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · agent (T09)
  - 2026-10-17 · IMPLEMENTED · agent (T09, after T06 merged) · item 8 now holds without the fallback: the `index_paths` import is hard, and `tests/conftest.py` patches `indexer.get_embedder` with a fake for every module except `test_m04_index.py`.

### CHG-0010 — M11 implementation choices: lazy dependencies, NOT_AVAILABLE, per-connection agent, mcp 2 API
- **Type:** design
- **Module(s):** M11 (touches `tests/test_m11_mcp.py`)
- **Proposed by:** agent (task T12)
- **Date:** 2026-10-17
- **Motivation:** §8 M11 does not say what a tool does while M6/M9 are missing, how one HTTP app serves several agents, or which SDK API to use. The locked SDK is mcp 2.3.0, where `FastMCP` is `mcp.server.mcpserver.MCPServer` and results use snake_case fields.
- **Proposal:**
  1. Lazy dependencies: `pam.retrieve.context.build_context(vault, ContextRequest)`, `pam.retrieve.search.search(vault, SearchQuery)` and `pam.working.session.update_working_memory(vault, data, agent=)` are imported inside the tool. A missing module (or entry point) returns `NOT_AVAILABLE: <module> not merged yet`: an error result for read tools, a `WriteResult(ok=false, message=...)` for write tools. Only a missing module itself counts; an import error inside an existing module propagates. All ten tools stay registered.
  2. Registration: a tool is advertised when `can_call(manifest, tool)` holds (the `tools` list, and write tools only if `write != "none"`). `build_server` raises `PamError("cannot serve MCP for agent ...")` for an unknown agent.
  3. Results: structured content is `model_dump(mode="json")`; the text block is `ContextBundle.rendered` for `get_context`, the truncated Markdown for `get_episode`, JSON otherwise. `list_agents` returns `{"agents": [...]}` because structured content must be an object. Failed writes (`ok=false`) also set `is_error`. `get_episode` truncates the transcript body from the middle with a marker so the result is at most `max_tokens`, and checks `can_read` on the episode's scope.
  4. HTTP: `http_app(vault)` is one ASGI app that ignores the path (works at `/mcp` and when mounted under it) and builds a server plus session manager per `?agent=` on first use; an unknown agent is a 404. Its lifespan starts the managers; without one (a mount that does not forward it) the first request starts them. Servers are cached, so a manifest edit needs a restart. DNS-rebinding host checks are off, as for the REST API.
  5. CLI: `pam mcp serve --transport stdio|http --agent --host (127.0.0.1) --port (8765)` and `pam mcp tools --agent` (SETUP §M11).
  6. Test fixes (assertions unchanged): helpers read `structured_content` / `is_error` (mcp 2 names) as well as the mcp 1 names; the schema test compares `get_context` to `ContextRequest` minus `agent`, which it asserts is absent two lines later.
- **Impact:** `mcp_server/{server,tools}.py`, `cli/mcp_cmd.py`, `test_m11_mcp.py`. No contract changes. T14 mounts `http_app(vault)` at `/mcp` and forwards its lifespan if it can. Pending T07/T11: the three entry points above.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · agent (T12)

---

### CHG-0010 — M6 index seam and FTS query sanitization
- **Type:** design
- **Module(s):** M6
- **Proposed by:** agent (task T07)
- **Date:** 2026-10-17
- **Motivation:** T07 starts before T06 merges, so retrieval needs a stable boundary to read the future index without creating or changing M4 files. Raw user syntax also cannot be passed directly to FTS5.
- **Proposal:** Keep all M4 access in `pam.retrieve._index` with `connect`, `embed_query`, and `doc_token_counts`. Delegate to `pam.index.db` and `pam.index.embedder` when available; otherwise use a read-only SQLite connection, sqlite-vec, and a cached FastEmbed model. Sanitize FTS input by tokenizing, double-quoting every term with embedded quotes escaped, and joining with `OR`; an empty input yields an empty phrase.
- **Impact:** M6 retrieval only. The seam is read-only and can drop its fallback after T06 merges; no schema or contract changes.
- **Status log:**
  - 2026-10-17 · IMPLEMENTED · agent (task T07)
  - 2026-10-18 · renumbered from CHG-0008 before merge (T06 took CHG-0008 on main); the fallback is removed by CHG-0011 · Yogesh

### CHG-0011 — M6 review fixes: fact hits, conflict relevance, fill order, snippets, working memory, model guard
- **Type:** design
- **Module(s):** M6 (one test-setup line in `tests/test_m06_retrieve_stub.py`)
- **Proposed by:** Yogesh (review of T07)
- **Date:** 2026-10-18
- **Motivation:** Spec-traced tests appended to `test_m06_retrieve.py` failed in 10 places against §7.5, §7.8, §7.9, §8 M6, and SETUP §6, and a 20 KB persona at a 256-token budget hung `pam context`. §8 M6 leaves open what "mentioned in the query or hits" means and how the greedy fill treats an item that does not fit.
- **Proposal:**
  1. Facts: every active identity/education/work fact (by category, attribute, value), then active fact hits of any category in hit order, capped at `max_facts`.
  2. Conflicts: relevant when an attribute part (split on `_`, stop words skipped) equals a query word or shares a prefix of at least 4 letters with it (`work` ~ `works_at`), or when the conflict fact is a keyword (FTS) hit. Relevant conflicts fill first; the others fill last, after snippets ("only if budget remains").
  3. Fill: order relevant conflicts → working memory → facts → projects → snippets → other conflicts, counting the whole rendered bundle each time. After the first item that does not fit, the rest of its section is still tried, but no lower section is (§7.9 "lower-priority items are dropped first").
  4. Persona: trimmed by a binary search over a text-token limit (identity, then rules, then style), so its section is at most `persona_max_tokens` and the empty bundle fits the budget. `None` only if the bare headings do not fit.
  5. Snippets: hit chunks of one episode are merged only when their ordinals are consecutive; the `[<title>] ` chunk prefix is removed; snippets keep the order of their best hit.
  6. Projects: owning a hit episode (best hit first), then other active projects by `last_activity_at`; `ProjectBrief.summary` is the `## Summary (auto)` section only.
  7. Working memory: `working/<session_id>.md` is read through the §7.10 contract when the session id is `[A-Za-z0-9_-]{1,64}` and the file's `agent` is the requesting agent; otherwise it is left out without an error.
  8. Index access: read-only (`mode=ro`); a vault without `index.db` returns no hits and loads no model. `meta.embedding_model` different from the config raises `PamError` ("run `pam index --rebuild`", exit 1), as `pam index` does. Queries are embedded through `pam.index.indexer.get_embedder`, the indexer's own embedder; the FastEmbed fallback of CHG-0010 is removed.
  9. Rendering: project summaries on one line; snippet lines indented two spaces so chat text cannot look like a bundle heading; working memory as `Goal:` / `Decision:` / `Open question:` bullets, each citing its path.
  10. CLI (SETUP §6): `pam search QUERY [--agent] [-k|--k] [--type episode,fact,…] [--since DATE]`, printing `score (vector r, keyword r) type title`, the path, and a one-line snippet; `pam context QUERY [--agent] [--budget] [--session] [--no-persona]`. A bad `--type`/`--since` exits 2.
  11. Test setup: `test_m06_retrieve_stub.py` now writes the configured model name into its stub index `meta` (was `fake`), because of item 8; its assertions are unchanged.
- **Impact:** M6 only, plus the test lines above. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · Yogesh (T07 review)

### CHG-0012 — M10 implementation choices: lock-free fast path, refusal rules, SyncResult, search hook
- **Type:** design
- **Module(s):** M10 (one call in M6 `retrieve/search.py`; test setup in `tests/test_m06_retrieve_stub.py` and `tests/test_m10_git.py`)
- **Proposed by:** agent (task T09b)
- **Date:** 2026-10-18
- **Motivation:** §8 M10 does not say how a sync avoids committing a PAM writer's half-written files, what "validate the frontmatter" covers, how restored and refused paths are reported when §7.12 `SyncReport` has only `dirty_paths`, `reindexed`, and `commit_sha`, or what `search()` does when the sync fails.
- **Proposal:**
  1. Fast path: one `git.status_porcelain` with no lock; a clean tree returns at once. A dirty tree takes `vault_write_lock(timeout=0)` and re-reads the status under it, so a writer's uncommitted files are never committed as `manual:`. A held lock skips the pass (`busy`) and touches nothing.
  2. Classification: unmerged entries are left alone; any `D` in `XY` is restored with `git.restore` from HEAD (§11 item 9), and a path that is not in HEAD is reported as invalid; episodes must validate as `EpisodeFrontmatter`, their body must hash to `body_sha256` **and** equal the HEAD body (a body edit with a rewritten hash is also refused); a refused episode is left as it is on disk, never rewritten or restored; fact, project, skill, and `working/*.md` frontmatter must validate against its §7 model; every other dirty path (personas, `agent.yaml`, `pam.toml`, imports) is committed as-is. One commit `manual: <n> files`; a change git sees as empty (line endings only) makes no commit.
  3. Reindex: `index_paths(vault, committed + restored)` once, under the lock, after the commit. An indexer error is logged and the commit stands (as CHG-0009 item 8); `SyncReport.reindexed` is `IndexReport.documents_indexed`.
  4. Reporting without a contract change: `SyncReport.dirty_paths` lists every dirty path found (committed, restored, or refused). The richer `SyncResult` dataclass (`committed`, `restored`, `immutable_violations`, `invalid`, `busy`) is internal; `sync_once` logs one warning per restored or refused path, and `pam sync` prints them as `Warning:` lines. A refused episode stays dirty and is reported on every sync until the user reverts it.
  5. Search hook: `search()` first calls `sync_before_read(vault)`, which wraps `sync_once` and logs and swallows any exception. That is two lines in `search.py` (import + call). `build_context` calls `search()`, so `get_context` syncs too.
  6. CLI: `pam sync [--watch] [--interval 2.0]`. `--json` prints the `SyncReport` (one JSON line per pass that found dirty paths with `--watch`). A busy vault exits 4 (`--json` prints the report first). Problems do not change the exit code.
  7. Test setup (assertions unchanged where they still apply): `test_m06_retrieve_stub.py` commits its two hand-written files, because the sync in `search()` would otherwise commit and reindex them over the hand-built stub index; `test_m10_git.py::test_sync_cli_stub` now runs `pam sync` on a real vault and checks the T02 placeholder text is gone.
- **Impact:** M10 only, plus the hook and the test lines above. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T09b)
  - 2026-10-18 · IMPLEMENTED · agent (T09b) · `working/*.transcript.jsonl` is skipped by sync (neither committed nor reported), per §8 M9 and CHG-0013.

### CHG-0014 — M9 implementation choices: turn state from the transcript, goal commit, two-commit end
- **Type:** design
- **Module(s):** M9
- **Proposed by:** agent (task T11)
- **Date:** 2026-10-18
- **Motivation:** §8 M9 keeps `recent_turns` in the tracked `working/<id>.md` but forbids a commit per turn, so a per-turn `.md` write would be committed by `pam sync` as `manual:`. §8 M9 does not say how `end` combines M7's own `log_episode` commit with the `status=ended` change, nor what the episode's title and summary are.
- **Proposal:**
  1. Turn state: `record_turn` only appends `{role, text, created_at, model}` (a `RawMessage` plus `model`) to the untracked `working/<id>.transcript.jsonl`. `show`, `record_turn`, and `list` rebuild `recent_turns` (last 8) and `models_used` from the transcript; `models_used[0]` is the `start` model (`from_model=None`). The `.md` is refreshed with that state whenever it is committed (start, goal, update, end), so between commits its `recent_turns` lags behind the transcript (M6 renders only goal, decisions, and questions). Without a transcript (e.g. a fresh clone) the `.md` values are used as stored.
  2. Commits: `session: start|goal|end (agent=<a>, session=<id>)` and `update_working_memory: <id> (agent=<a>, session=<id>)`. The goal is set once, from the first user message (whitespace collapsed, 200 characters), only if no goal is set yet. `update` with nothing new is `ok` with no commit; blank decisions or questions are dropped.
  3. `end`: `writer.log_episode` (its own commit) with title = goal or `Session <id>` (200 characters), summary `Goal: ...` plus `Decisions: a; b`, tag `session:<id>`, and every transcript turn; then the `session: end` commit. The `WriteResult` carries the episode's `doc_id` and `path` and the end commit's sha. The episode's owner is the `--agent` given, else the session's agent. `ok=False` (session stays active): `already ended`, no turns, or a failed `log_episode` (its message passed through). The working file and the transcript are kept; the transcript stays untracked.
  4. No permission checks: any agent may update or end any session (the M8 "own working files" rule is not enforced here); `start` only requires the agent's manifest to exist. Ids are `s_` + 12 `secrets` base36 characters, retried on collision; an id that does not match the pattern is "not found" (no path traversal).
  5. Errors: `start`, `record_turn`, and `show` raise `PamError` / `VaultBusy`; `update` and `end` return `WriteResult(ok=False)` with the M7 prefixes (`vault busy:`, `validation failed:`), so the CLI exit codes match `pam fact`.
- **Impact:** M9 only (`working/session.py`, `cli/session_cmd.py`, `tests/test_m09_working.py`). No contract changes. T13 calls `record_turn` per chat turn and `show` for hot-swap context. Once CHG-0013's vault `.gitignore` line lands, the transcript is also ignored by git itself.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T11)

### CHG-0015 — M12 LLM layer choices: delta shape, error mapping, env keys, `models check` exit codes
- **Type:** design
- **Module(s):** M12 (part 1: `chat/llm.py`, `cli/models_cmd.py`)
- **Proposed by:** agent (task T13 part 1)
- **Date:** 2026-10-18
- **Motivation:** §8 M12 names LiteLLM streaming and `pam models check` but not the internal stream shape, which failures are retryable, or how keys reach LiteLLM. CHG-0013 is reserved for the vault `.gitignore` change and CHG-0014 is M9, so this entry is CHG-0015.
- **Proposal:**
  1. `stream_chat` yields `LLMDelta(text, tool_calls, finish_reason, usage)`. Tool-call fragments merge by `index`; the complete `ToolCall(id, name, arguments: dict)` list is set once, on the delta with `finish_reason` (or a final delta if none arrives). Invalid or non-object JSON arguments raise `LLMError(retryable=True)`. `ToolCall.as_openai()` gives the assistant-message form. Calls pass `stream_options.include_usage` and `drop_params=True`.
  2. `LLMError(message, retryable)`: rate limit, timeout, connection, 5xx (and any status 429/≥500) are retryable; auth, permission, not-found and bad-request are not. Only LiteLLM/OpenAI/httpx/asyncio timeout errors are mapped; other exceptions propagate. `UnknownModel` exits 2. Both subclass `PamError`.
  3. Keys: `api_key` from `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` by model prefix, `api_base` from `OLLAMA_BASE_URL` for `ollama/` and `ollama_chat/`; unset vars are not passed. `llm.py` sets `LITELLM_LOCAL_MODEL_COST_MAP=True` (no fetch at import) and `litellm.suppress_debug_info`.
  4. `ping` never raises; it reports any exception as `error`. `pam models check` exits 1 if every model fails or none are configured, else 0; `--json` prints `[{id, ok, latency_ms, error}]`. `pam models list` on a vault without models prints a hint to stderr and exits 0.
- **Impact:** T13 rest builds on `stream_chat`, `resolve_model`, `PAM_PREAMBLE`, `LLMError`. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T13 part 1)

### CHG-0016 — M5 implementation choices: scope, settle loop, single-cluster fallback, stable names, graph ids
- **Type:** design
- **Module(s):** M5
- **Proposed by:** agent (task T10)
- **Date:** 2026-10-18
- **Motivation:** §8 M5 leaves open which episodes a run covers, how "cluster twice is a no-op" holds when the first run's HDBSCAN noise could be assigned to its new centroids on the second run, what happens when HDBSCAN finds one dense group (sklearn returns all noise), when names and keywords are recomputed, what `episodes_assigned` counts, and the graph's node ids.
- **Proposal:**
  1. Scope: `pam cluster --agent A` (default `default`) clusters `memory/A/episodes` into `memory/A/projects`. Episodes without a `doc_vectors` row are skipped with a warning (run `pam index`). The agent must exist; no permission check (system process).
  2. Settle loop (incremental): assign to centroids (cosine >= `assign_threshold`, running mean, oldest episode first), then HDBSCAN on the rest when >= `min_cluster_size`; repeat while either step changed something. A run therefore leaves nothing a second run would change; episodes that end as noise stay unassigned.
  3. HDBSCAN: `metric="euclidean"`, `min_cluster_size` from config, sklearn's default `min_samples` (= `min_cluster_size`, capped at n-1). If every point is noise, it runs once more with `allow_single_cluster=True`, so one dense topic still forms a project; outliers stay noise. Turning that on always merged the whole fixture into one cluster.
  4. Rebuild: episodes held by `agent`/`manual` projects are not re-clustered (those projects keep their members). The rest go through HDBSCAN; clusters are matched to `cluster` projects greedily by highest Jaccard (>= `rebuild_match_jaccard`, each used once), keeping id and name; then the settle loop runs on the noise. A matched project with the same member set keeps its stored order. Unmatched `cluster` projects become `dormant`, `episode_ids: []`, and get a `## Notes` bullet `- <ts> (cluster) Dormant after cluster --rebuild: …`.
  5. Names are set once, when the clusterer creates a project; later runs never rename (so `agent`/`manual` are never renamed either). Keywords (c-TF-IDF over all projects of the scope) are recomputed for new projects, projects whose members changed, every project on `--rebuild`, and projects with no keywords. `## Summary (auto)` is re-rendered for every project; a file is written (and `updated_at` set) only if its content changes.
  6. Naming details: a title n-gram must be in >= 30% of member titles **and** in at least 2 (`TITLE_NGRAM_MIN = 2`), else 3-member projects get one-word names from a single title; ties prefer the higher keyword rank, then a bigram. A term keeps its casing from the titles (then member texts) when that has a capital (`Immich`, `UW CS`, `CSE · CDS`), else it is title-cased. The c-TF-IDF word count `A` counts `\w\w+` tokens.
  7. Dormancy: `last_activity_at` is the later of the stored value (an agent note or episode write moves it) and the newest member `updated_at`; a project the clusterer creates starts from its members' newest `updated_at`; `dormant` when older than `dormant_after_days`, `active` otherwise (an empty `cluster` project stays dormant).
  8. Report: `episodes_assigned` = episodes placed in a project by this run; `episodes_unassigned` = the scope's episodes in no project afterwards.
  9. `project_centroids`: recomputed from member `doc_vectors` each run (normalized mean; an index rebuild loses nothing), rows written only when the bytes change, deleted for projects without vectors. Reindexing after the commit logs and keeps the commit on failure (as CHG-0009 item 8).
  10. Graph: node ids are the document UUIDs; project `cluster_id` is its own id, an episode's is the visible project that holds it; fact `size` = confidence, `label` = `attribute: value`; `derived_from` weight = confidence; `similar` weight = cosine. Visibility uses `can_read` per file. No index means no `similar` links. `pam graph export` without `--out` prints the JSON.
- **Impact:** M5 only. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T10)

### CHG-0018 — M12 orchestrator choices: MCP transport, session agent, tool-mode context, round cap, failures
- **Type:** design
- **Module(s):** M12 (`chat/mcp_client.py`, `chat/orchestrator.py`, `cli/chat_cmd.py`)
- **Proposed by:** agent (task T13 rest), decisions confirmed by Yogesh
- **Date:** 2026-10-18
- **Motivation:** §8 M12 does not say how `pam chat` reaches MCP without a running server, which agent a continued session uses, where tool mode's persona-only context comes from, what ends a tool loop, or which failures raise and which become events. CHG-0016 and CHG-0018 are taken on the T10, T15 and T16 branches, so this entry is CHG-0018.
- **Proposal:**
  1. MCP: `open_session(vault, agent, url=None)` yields the SDK `ClientSession` of an mcp 2 `Client`: in-process on `build_server(vault, agent)` without a URL (CLI, tests) and over streamable HTTP to `<url>?agent=<agent>` with one (T14's own `/mcp`). A connect failure is `McpToolError(retryable=True)`; an error raised in the caller's block is re-raised as is, not as the client task group's `ExceptionGroup`.
  2. Before the stream: `run_turn(vault, req)` resolves the model first (`UnknownModel`, exit 2 / 400, writes nothing), then opens the session and records the user turn. These raise instead of streaming: unknown or ended session (`PamError`), an agent mismatch (`PamError` exit 2), `VaultBusy`. Without `session_id` a session is started; with one, `req.agent == "default"` adopts the session's agent and any other differing agent is the mismatch. The CLI's `--agent` defaults to unset, i.e. `"default"`.
  3. Stream (§7.14): the first event is always `context` and the last is exactly one `done` or `error`. Any exception after the user turn is recorded becomes the `ErrorEvent`, preceded by an empty `ContextEvent` if none was sent yet: `LLMError` and `McpToolError` keep their `retryable`, `VaultBusy` is retryable, everything else is not. On an error no assistant turn is recorded (the user turn stays); an empty reply is not recorded either.
  4. Injection: `get_context(query=message, session_id)` through MCP; `ContextEvent.doc_ids` = fact, conflict, project and episode ids, deduplicated in that order. An agent without `get_context` gets context, then an error.
  5. Tool mode: the light `ContextEvent` is the agent's persona rendered in-process (`load_persona` + `render.persona_section`, `baseline_tokens = tokens_saved = 0`, no `doc_ids`). A model without `supports_tools` then gets `ErrorEvent(retryable=False)`. Otherwise the system prompt is `PAM_PREAMBLE`, the MCP server instructions, then the persona; each round's calls go to MCP in order, each emitting `ToolCallEvent` (`result_summary` = whitespace-collapsed text, first 200 characters, `ERROR: ` prefix for error results) and a `tool` message by `tool_call_id`. A disallowed or failing tool is an error result for the model, not an `ErrorEvent`. At most `MAX_TOOL_ROUNDS = 5` rounds of tool calls run; the model may still answer after the fifth, but asking for more tools then ends the turn with `ErrorEvent("tool round limit (5) reached", retryable=False)`. The recorded reply is the text of all rounds; usage is summed over rounds.
  6. CLI: text mode prints `session <id> · context <n> tok (saved <m>)`, the streamed text, `[tool] name(args) -> summary` lines, and finally `session <id> (continue with --session <id>)`; `--show-context` adds the rendered block; `--json` prints one `ChatEvent` per line. An `ErrorEvent` exits 1 (`error: ...`, plus `(retryable)`, on stderr). The `LiteLLM` and `mcp` loggers are raised to WARNING because LiteLLM logs each call at INFO to stdout.
- **Impact:** M12 only. No contract changes. T14 calls `run_turn(vault, req, mcp_url=...)`, returns 400 for `UnknownModel` and maps the other exceptions raised before the first event to 404/400/409.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T13 rest)

### CHG-0019 — M5 naming: generic title n-grams never name a project (B-04)
- **Type:** fix
- **Module(s):** M5 (`cluster/naming.py`)
- **Proposed by:** agent (bug B-04 on T10), rule chosen by Pranav
- **Date:** 2026-10-18
- **Motivation:** With the bge model, the 3 fixtures put "What should I pack for a rainy day hike?" into the university project, so `day` was in 2 of its 6 titles and passed both title rules: the project was named "Day". Titles like "Untitled conversation 2026-10-17" could likewise give "2026-10". CHG-0016 and CHG-0017 are taken on the T10, T15 and T16 branches and CHG-0018 on main, so this entry is CHG-0019.
- **Proposal:**
  1. `project_name` ignores title n-grams made only of `GENERIC_TITLE_WORDS` (chat, conversation, day, discussion, help, new, notes, project, question, questions, untitled) or numbers, then applies the 30% / 2-title rule to the rest; if none qualifies, the name is the top 2 keywords as §8 M5 says. A partly generic n-gram (`day hike`) still counts.
  2. One-word names stay allowed (`Immich`, `Tailscale`): requiring 2+ words would rename those to `Immich · Backup` and `Caddy · Home`.
- **Impact:** M5 naming only. Names are set once at creation (CHG-0016 #5), so existing projects keep theirs; `origin=agent|manual` projects are still never renamed. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (B-04)

### CHG-0020 — M5 review fixes: unreadable project files stop `pam cluster`; `graph export --out` errors
- **Type:** design
- **Module(s):** M5 (`cluster/cluster.py`, `cli/graph_cmd.py`)
- **Proposed by:** agent (T10 review, Yogesh)
- **Date:** 2026-10-18
- **Motivation:** Testing PR #35 on the three fixtures found two problems. (1) `pam cluster` skipped a project file it could not read (bad frontmatter) with a warning; that project's episodes then looked unassigned and were moved into another project (all 7 Immich episodes went into Tailscale and were committed), so once the file was fixed they belonged to two projects, against §7.5 "an episode belongs to at most one project". (2) `pam graph export --out` into a folder that does not exist ended in a raw `FileNotFoundError` traceback.
- **Proposal:**
  1. `run_cluster` (incremental and `--rebuild`) raises `PamError` (exit 1) naming every unreadable `memory/<agent>/projects/*.md` file before it changes anything; the message says to fix or `git checkout -- <file>` it. Unreadable episode files are still skipped with a warning (they only stay unassigned). `build_graph` keeps skipping unreadable files with a warning, since it writes nothing.
  2. `pam graph export --out FILE` creates missing parent folders; any other write failure (e.g. `FILE` is a folder) is a `PamError` "cannot write FILE: <reason>" (exit 1) instead of a traceback.
  3. Tests: `test_unreadable_project_file_stops_cluster`, `test_graph_export_out_creates_missing_folders`, `test_graph_export_unwritable_out_is_a_clean_error` (all three fail on the code before this change).
- **Impact:** M5 only. No contract changes.
- **Status log:**
  - 2026-10-18 · IMPLEMENTED · agent (T10 review)

### CHG-0021 — `ClusterCfg.assign_threshold` default 0.60 → 0.70 for bge-small
- **Type:** contract
- **Module(s):** contracts (`config.py` `ClusterCfg`), M5
- **Proposed by:** agent (T10 review, Yogesh)
- **Date:** 2026-10-18
- **Motivation:** With `BAAI/bge-small-en-v1.5` (decision 6 in §11), unrelated episodes are already similar: over the 17 Claude + ChatGPT + Gemini fixture episodes the pairwise cosine is min 0.44, **median 0.60**, max 0.84. The default `assign_threshold` 0.60 therefore lets off-topic episodes join a project: Gemini's "Suggest a simple meal plan with lentils." (0.68) and "What should I pack for a rainy day hike?" (0.72) join the UW CS / CSE project. CHG-0019 (B-04) stops that project being named "Day"; this change keeps the off-topic episodes out of it. Measured with a `pam.toml` override on the fixtures, in one run and incrementally (Claude + ChatGPT, then Gemini):
  - 0.60 and 0.65: lentils and hike join the CSE project.
  - **0.70:** Immich 7, Tailscale 4 (incl. "Explain what a reverse proxy does."), CSE · CDS 4; lentils and hike unassigned; identical result and names both ways.
  - 0.75: real members drop out ("Photo library issue", the reverse-proxy episode) and a weak "Checklist · Day Hike" project forms.
- **Proposal:** change the default only (vaults with a `pam.toml` keep their value; users can set it per vault). New code for `backend/pam/contracts/config.py`:
  ```python
  class ClusterCfg(_C):
      min_cluster_size: int = 3; assign_threshold: float = 0.70
      similar_link_threshold: float = 0.75; similar_links_per_node: int = 3
      rebuild_match_jaccard: float = 0.5; dormant_after_days: int = 30
  ```
  The same line in §7.13, then `pam schema export`. `frontend/src/types/generated.ts` carries no defaults, so it is unchanged.
- **Impact:** contracts + regenerated schemas (`PamConfig.json`, `ClusterCfg.json`); M5 behaviour on new vaults. Existing vaults: no change until their `pam.toml` is edited.
- **Status log:**
  - 2026-10-18 · PROPOSED · agent (T10 review)
  - 2026-10-18 · APPROVED · Yogesh
  - 2026-10-18 · IMPLEMENTED · agent (T10 review): contract, §7.13 and schemas updated; full suite passes at 0.70

## 11. Decisions made on the team's behalf (please review before approving CHG-0000) 🔒
These were not explicitly answered in planning and were decided with "your call" or industry-standard defaults. Flip any of them by editing before approval:

1. **Episode frontmatter is appendable** (`tags`, `superseded_facts` backlinks), while the **body is immutable**, enforced by `body_sha256`.
2. **ChatGPT importer is P1** (it was in the original list; Claude is P0; Gemini is P1 best-effort).
3. **Re-imports skip existing conversations by default.** `--update` writes a new episode version that is tagged `supersedes:<id>` rather than modifying the old one.
4. **Rule-extracted facts from the user's newer statements overwrite older rule-extracted values**, while conflicts with agent- or manually-written facts are flagged for the LLM to ask about.
5. **`update_working_memory` was added** to the MCP tool list so external clients (e.g. Claude Desktop) can also use working memory.
6. **fastembed + bge-small-en-v1.5 (384-dim)** instead of sentence-transformers (same model, no PyTorch, smaller Docker image).
7. **Single backend process** serves both `/api` and `/mcp`. stdio MCP for Claude Desktop runs via `docker exec` in the same container, and a file lock serializes writes.
8. **Token savings baseline** = full transcripts of the episodes that contributed snippets (honest, explainable number).
9. **Deleted vault files are auto-restored from git** by the sync step (enforces never-delete).
10. **Python 3.12, uv, Typer**; **Node 20** for the frontend build.
