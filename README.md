# PAM: Portable Agent Memory

Take your AI chat history with you when you switch models.

[![PAM demo video](https://img.youtube.com/vi/o143isuJBGE/maxresdefault.jpg)](https://www.youtube.com/watch?v=o143isuJBGE)

## Why

When you move from Claude to ChatGPT to a local model, you lose everything the
last one knew about you and your work. You either start over or paste in a huge
history and burn tokens on it.

PAM imports your chat exports into a local folder of Markdown files, figures out
your projects, facts, and preferences, and gives any model only the context it
needs for the question you're asking. In the demo, picking up a project takes
about 1.8k tokens instead of the 46k it would take to replay the full history.

## What it does

- **Imports** exports from Claude, ChatGPT, and Gemini (Gemini is best-effort).
- **Stores** everything as plain Markdown in a git-tracked vault you can open in
  any editor. Every change is a commit, and nothing is ever deleted.
- **Derives** facts about you, your projects, and a persona (identity, rules,
  style) without using an LLM. It uses rules, embeddings, and clustering.
- **Searches** the vault locally with hybrid vector + keyword search.
- **Builds context** for each question within a token budget and reports how
  many tokens it saved.
- **Serves** that memory to any MCP client, such as Claude Desktop or Cursor.
  Agents can also write back new facts, notes, and skills.
- **Keeps the thread** when you switch models mid-conversation, using working
  memory for the session.
- **Scopes agents**: the default agent sees everything; custom agents see only
  the projects you allow.

Everything runs on your machine. No accounts, no cloud.

## Quick start

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and git.

```bash
git clone https://github.com/PranavM9/PAM.git pam && cd pam
cp .env.example .env            # add an OpenRouter and/or Anthropic key
docker compose up --build -d    # first build downloads the embedding and spaCy models
curl -s localhost:8000/api/health   # {"ok": true, ...} once the backend is up
```

Open http://localhost:5173. The vault is created in `./vault` on first start.

> **Windows:** clone the repo inside the WSL2 filesystem (e.g. `~/code/pam`),
> not under `C:\`. It's much faster, and line endings stay LF.

To also run local models with Ollama: `docker compose --profile local up -d`.

### Environment

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Free and paid models through OpenRouter |
| `ANTHROPIC_API_KEY` | Claude through the API (separate from a Claude subscription) |
| `OLLAMA_BASE_URL` | Local models; only with the `local` profile |
| `PAM_VAULT` | Vault path inside the container (default `/vault`) |
| `PAM_LOG_LEVEL` | Log level (default `INFO`) |

Models are listed in `vault/pam.toml` and can be edited from the Settings page.

### Getting your exports

- **Claude:** Settings → Privacy → Export data
- **ChatGPT:** Settings → Data controls → Export data
- **Gemini:** [takeout.google.com](https://takeout.google.com) → Gemini Apps activity

Each sends you a download link. Step-by-step guides are in the app under **Guides**.

## Using the app

| Page | What it's for |
|---|---|
| **Import** | Pick a source, drop the export, and watch each stage run |
| **Graph** | Obsidian-style map of your projects and conversations. Drag, pin, zoom, click to open |
| **Vault** | Browse and read any file in the vault |
| **Search** | Try queries, see ranked hits, and build a context bundle with its token count |
| **Agents** | Create agents with their own scope, tools, model, token budget, and persona |
| **Chat** | Chat with any model using your memory. Switch models mid-chat; the side panel shows tokens used vs. saved |
| **Settings** | Manage models and API keys |
| **Guides** | How to export from each provider and connect Claude Desktop |

## Connect Claude Desktop (MCP)

Add PAM to `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "pam": {
      "command": "docker",
      "args": ["exec", "-i", "pam-backend", "pam", "mcp", "serve", "--transport", "stdio", "--agent", "default"]
    }
  }
}
```

Restart Claude Desktop. Other clients can use streamable HTTP at
`http://localhost:8000/mcp?agent=default`.

| Tool | Does |
|---|---|
| `get_context` | Token-budgeted context for a question |
| `search_memory` | Hybrid search over the vault |
| `get_episode` | Read one conversation |
| `list_agents` | List available agents |
| `add_fact` / `supersede_fact` | Record or correct a fact (history is kept) |
| `log_episode` | Save a conversation |
| `update_project` | Create a project or add notes and episodes |
| `add_skill` | Save a reusable procedure |
| `update_working_memory` | Update the current session's goal, decisions, and questions |

Each connection is bound to one agent, and it only sees the tools that agent is
allowed to use. When facts conflict, the model is told to ask you which one is
right before correcting it.

## CLI

Every feature is also a CLI command. Inside Docker:

```bash
alias pamx='docker compose exec backend pam'
# PowerShell: function pamx { docker compose exec backend pam @args }
```

Files in `./demo/` on your machine are available at `/demo` in the container.

```bash
pamx import run /demo/claude-export.zip         # one episode per conversation
pamx derive && pamx index && pamx cluster       # facts and persona, search index, projects
pamx search "dubhacks frontend"                 # hybrid search
pamx context "where did I leave off?"           # context bundle + tokens saved
pamx chat "let's keep going" --model <model-id> # one chat turn; prints a session id
```

The pipeline commands:

| Command | Does |
|---|---|
| `pam init` | Create the vault, its git repo, and the `default` agent |
| `pam import run FILE` | Write one episode per conversation. Re-running is safe |
| `pam derive` | Extract facts, rules, and style; write the default persona |
| `pam index [--rebuild]` | Chunk, embed, and index the vault |
| `pam cluster [--rebuild]` | Group episodes into projects |

Other command groups:

| Group | Covers |
|---|---|
| `pam episode` | list, show, verify, log |
| `pam fact` | add, list, show, supersede |
| `pam project` | list, show, create, note, add-episodes |
| `pam skill` | add, list |
| `pam agent` | list, show, create, set-scope, check |
| `pam session` | start, record, update, show, list, end |
| `pam models` | list, check |
| `pam mcp` | serve, tools |
| `pam sync` | Pick up manual edits to the vault, reindex, and commit |
| `pam graph export` | Export the graph as JSON |
| `pam config` | show, path |
| `pam schema export` | Write JSON Schemas for every data contract |

Global options: `--vault PATH`, `--json` (machine-readable output for `jq`), and
`-v`. Exit codes: `0` ok, `1` error, `2` validation error, `3` permission denied,
`4` vault busy.

The full reference with examples is in [SETUP.md](./SETUP.md).

## REST API

The backend serves the API at `http://localhost:8000/api` and interactive docs
at http://localhost:8000/docs.

| Method & path | Does |
|---|---|
| `GET /health` | Health and index status |
| `POST /imports` | Upload an export (multipart `file`); returns a job |
| `GET /imports/{job_id}` | Import job progress |
| `GET /vault/tree` · `GET /vault/file?path=` | List and read vault files |
| `POST /search` | Hybrid search |
| `POST /context` | Build a context bundle |
| `GET /graph` | Graph data |
| `GET /agents` · `GET /agents/{name}` | List agents or get one with its persona |
| `POST /agents` · `PUT /agents/{name}` | Create or update an agent |
| `GET /models` · `PUT /models` · `POST /models/check` | Read, edit, and test models |
| `GET /settings/keys` · `PUT /settings/keys` | API key status |
| `POST /chat` | One chat turn, streamed as SSE |
| `GET /sessions/{id}` · `POST /sessions/{id}/end` | Session memory; end saves it as an episode |
| `POST /sync` · `GET /sync/status` | Sync manual vault edits |

`/api/chat` streams `context`, `token`, `tool_call`, and then exactly one `done`
or `error` event:

```bash
curl -N -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"model": "<model-id>", "message": "where did I leave off?"}'
```

Errors return `{"error": {"code": "...", "message": "..."}}` with status 400,
403, 404, 409, or 500.

## How it works

```
export ─► importers ─► normalizer ─► vault/*.md (git)
                                        │
             rule extractor ◄───────────┤──► facts, persona
             indexer        ◄───────────┤──► .pam/index.db (sqlite-vec + FTS5)
             clusterer      ◄───────────┘──► projects, graph
                                        │
              retriever + context assembler (per-agent permissions)
                                        │
                     MCP server ◄── chat orchestrator ◄── REST API ◄── frontend
```

- **The vault is the source of truth.** The index is derived and can be rebuilt
  with `pam index --rebuild`.
- **No LLM in the pipeline.** Facts come from regex and spaCy patterns; projects
  come from embeddings, HDBSCAN, and c-TF-IDF keywords.
- **One core, three interfaces.** The CLI, MCP server, and REST API are thin
  wrappers over the same Python library.
- **Safe writes.** One writer at a time (file lock), and every write is a git
  commit. IDs are deterministic, so re-imports never create duplicates.

### Vault layout

```
vault/
├── pam.toml                    # config and models
├── agent/<name>/               # agent.yaml, identity.md, rules.md, style.md
├── imports/<source>/<time>/    # raw exports, never modified
├── memory/shared/facts/        # facts about you
├── memory/<agent>/             # episodes/, facts/, projects/
├── skills/<agent>/
├── working/                    # live chat sessions
└── .pam/                       # index and lock (gitignored)
```

### Stack

| Part | Built with |
|---|---|
| Backend | Python 3.12, uv, Typer, FastAPI, Pydantic v2 |
| Search | sqlite-vec, SQLite FTS5, fastembed |
| Extraction & clustering | spaCy, HDBSCAN, c-TF-IDF |
| Models | LiteLLM → Anthropic, OpenRouter, Ollama |
| MCP | stdio and streamable HTTP |
| Frontend | Vite, React, TypeScript, Tailwind, react-force-graph |
| Runtime | Docker Compose |

## Development

Run without Docker:

```bash
cd backend && uv sync && uv run python -m spacy download en_core_web_sm
export PAM_VAULT=../vault && uv run pam init && uv run pam api serve --reload
cd ../frontend && npm install && npm run dev
```

On macOS, use the uv-managed Python. System and Homebrew Python often can't load
SQLite extensions.

Tests:

```bash
docker compose exec backend pytest -q          # all
docker compose exec backend pytest -q -k m06   # one module
```

After changing a data contract, regenerate the schemas and frontend types with
`pam schema export`, then `npm run gen:types` in `frontend/`.

| Doc | Contents |
|---|---|
| [SPEC.md](./SPEC.md) | Full technical spec: contracts, modules, and design decisions |
| [SETUP.md](./SETUP.md) | Install, full CLI reference, and troubleshooting |
| [git-guidelines.md](./git-guidelines.md) | Branches, PRs, and merging |
| [commenting-guidelines.md](./commenting-guidelines.md) | Code comment style |

## Team

Made with ❤️ at DubHacks by

- **Pranav Moolapattu** · [@PranavM9](https://github.com/PranavM9)
- **Yogeshwara Sai Kurapaty** · [@YogeshwaraSai](https://github.com/YogeshwaraSai)
- **Aakash Ghosh** · [@Aakash-Ghosh08](https://github.com/Aakash-Ghosh08)
