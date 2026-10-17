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
    min_cluster_size: int = 3; assign_threshold: float = 0.60
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
- **Result (➕):**

#### T02 · Git helper (≈ 0.5 h)
- **Module:** M10 (commit part only; the watcher comes in T09b)
- **Allowed paths:** `backend/pam/sync/git.py`, `backend/pam/cli/sync_cmd.py` (stub)
- **Depends on:** T01
- **Steps:** implement `commit`, `status_porcelain`, `restore`, `head_sha`, plus the init-time git config.
- **Done when:** the unit test creates a file, commits it, and gets a sha back. It passes on Linux in Docker.
- **Agent plan (➕):**
- **Result (➕):**

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
- **Result (➕):**

#### T04 · Normalizer (≈ 1 h)
- **Module:** M2
- **Allowed paths:** `backend/pam/normalize/**`, `backend/pam/cli/{import_cmd,episode_cmd}.py`
- **Depends on:** T02, T03
- **Steps:** implement the renderer (the exact grammar), the writer (archive + idempotency + a single commit), `pam import run`, `pam episode list|show|verify`.
- **Done when:** importing the fixture twice yields N episodes and then 0 new ones; `pam episode verify` reports all OK.
- **Agent plan (➕):**
- **Result (➕):**

#### T05 · Agents & permissions (≈ 1 h)
- **Module:** M8
- **Allowed paths:** `backend/pam/agents/**`, `backend/pam/cli/agent_cmd.py`
- **Depends on:** T01, T02
- **Steps:** manifest load/save, persona section parsing, the `can_*` functions and `visible_doc_filter`, `pam agent create|list|show|set-scope`.
- **Done when:** the M8 acceptance criteria pass (the search part is checked again in T07).
- **Agent plan (➕):**
- **Result (➕):**

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
- **Result (➕):**

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
- **Result (➕):**

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
- **Result (➕):**

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
- **Result (➕):**

#### T09b · Vault sync watcher (≈ 0.5 h)
- **Module:** M10 (rest)
- **Allowed paths:** `backend/pam/sync/watcher.py`, `backend/pam/cli/sync_cmd.py`, `backend/pam/retrieve/search.py` (one line: call `sync_once()` first)
- **Depends on:** T09
- **Done when:** the M10 acceptance criteria pass.
- **Agent plan (➕):**
- **Result (➕):**

#### T10 · Clusterer & graph (≈ 1.5 h)
- **Module:** M5
- **Allowed paths:** `backend/pam/cluster/**`, `backend/pam/cli/{cluster_cmd,graph_cmd}.py`
- **Depends on:** T06, T09
- **Steps:** incremental assignment, then rebuild with Jaccard ID matching, then c-TF-IDF naming, then the summary, then graph export.
- **Done when:** the M5 acceptance criteria pass.
- **Agent plan (➕):**
- **Result (➕):**

#### T11 · Working memory (≈ 0.75 h)
- **Module:** M9
- **Allowed paths:** `backend/pam/working/**`, `backend/pam/cli/session_cmd.py`
- **Depends on:** T09
- **Done when:** the M9 acceptance criteria pass (`pam chat` is stubbed until T13; test with `pam session record`).
- **Agent plan (➕):**
- **Result (➕):**

#### T12 · MCP server (≈ 1 h)
- **Module:** M11
- **Allowed paths:** `backend/pam/mcp_server/**`, `backend/pam/cli/mcp_cmd.py`
- **Depends on:** T07, T09, T11
- **Steps:** FastMCP tools wired to the core, agent-filtered registration, stdio + HTTP app factory, then a test with MCP Inspector.
- **Done when:** the M11 acceptance criteria pass.
- **Agent plan (➕):**
- **Result (➕):**

#### T13 · Chat orchestrator (≈ 1.5 h)
- **Module:** M12
- **Allowed paths:** `backend/pam/chat/**`, `backend/pam/cli/{chat_cmd,models_cmd}.py`
- **Depends on:** T12
- **Steps:** a LiteLLM streaming wrapper, then an MCP client session, then injection mode, then tool mode, then `pam chat`, `pam models list|check`.
- **Done when:** the M12 acceptance criteria pass.
- **Agent plan (➕):**
- **Result (➕):**

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

---

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
