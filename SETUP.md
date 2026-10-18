# PAM — Setup & CLI Reference

> Companion to [`SPEC.md`](./SPEC.md). Every module ships with the CLI commands listed here, and these commands are how each module is tested. 🔒 Human-reviewed; agents propose edits via SPEC §10.

## 1. Prerequisites
| Tool | Version | Why |
|------|---------|-----|
| Docker Desktop | latest (WSL2 backend on Windows) | Runs everything cross-platform |
| git | ≥ 2.40 | Clone the repo (the vault's git runs inside the container) |
| Node.js | 20 LTS *(optional)* | Only for running the frontend with hot reload outside Docker |
| uv | latest *(optional)* | Only for running the backend outside Docker |

> **Windows:** clone the repo **inside the WSL2 filesystem** (e.g. `~/code/pam` in Ubuntu), not under `C:\`. Bind mounts are much faster there, and line endings stay LF.

## 2. First run (Docker, recommended)
```bash
git clone <repo-url> pam && cd pam
cp .env.example .env          # then fill in keys (see §3)
docker compose up --build -d  # first build pre-downloads the embedding + spaCy models
docker compose exec backend pam doctor
open http://localhost:5173    # Windows: start http://localhost:5173
```
The first start creates `./vault` automatically (`pam init` runs only if it has no `pam.toml`).
A handy alias for the rest of this doc (`pamx` = run pam inside the container):
```bash
alias pamx='docker compose exec backend pam'           # macOS/Linux/WSL
# PowerShell: function pamx { docker compose exec backend pam @args }
```
Files you drop into `./vault/` or `./demo/` on the host are visible in the container at `/vault` and `/demo`.

## 3. Environment (`.env`)
```dotenv
PAM_VAULT=/vault                       # path INSIDE the container
ANTHROPIC_API_KEY=                     # optional — Claude API (separate from a Claude subscription)
OPENROUTER_API_KEY=                    # free models for the demo
OLLAMA_BASE_URL=http://ollama:11434    # only with: docker compose --profile local up
PAM_LOG_LEVEL=INFO
```
Models are declared in `vault/pam.toml` (verify the IDs: free OpenRouter models change often):
```toml
[[models]]
id = "openrouter/<org>/<model>:free"
label = "Free model (OpenRouter)"
supports_tools = false

[[models]]
id = "anthropic/<claude-model-id>"
label = "Claude (API)"
supports_tools = true
```

## 4. Getting your exports
In-app versions of these guides live in `frontend/src/guides/`. *Menu paths change; verify against research R1–R3.*
- **Claude:** Settings → Privacy → Export data. You'll get an email link to a `.zip` containing `conversations.json`.
- **ChatGPT:** Settings → Data controls → Export data. You'll get an email link to a `.zip` containing `conversations.json`.
- **Gemini:** takeout.google.com → select the Gemini Apps activity data. Download the archive (activity JSON/HTML).

Put the files in `./demo/` (gitignored) and import them as `/demo/<file>`.

## 5. Global CLI options
```
pam [--vault PATH] [--json] [-v|--verbose] <command> …
```
- `--vault`: overrides `PAM_VAULT`.
- `--json`: prints the contract model as JSON instead of pretty tables, so you can pipe it into `jq`.
- Exit codes: `0` ok · `1` error · `2` validation error · `3` permission denied · `4` vault busy (lock).

## 6. CLI reference by module

### M0 — Core
| Command | Description |
|---|---|
| `pam init [--vault PATH]` | Create the vault tree (SPEC §6), `pam.toml`, the git repo, and the `default` agent; makes the initial commit |
| `pam doctor` | Check git, sqlite-vec loading, embedding model cache, spaCy model, vault schema versions, and API keys present |
| `pam config show` / `pam config path` | Print the effective `PamConfig` / where it is loaded from |
| `pam schema export [--out ../schemas]` | Write the JSON Schema of every contract model |
```bash
$ pamx init
✔ Vault created at /vault (commit 3f2a1c9)
```

### M1 — Importers
| Command | Description |
|---|---|
| `pam import extract FILE [--source auto\|claude\|chatgpt\|gemini] [--out raw.jsonl]` | Parse only. Prints `RawConversation` JSONL to stdout or `--out`; touches nothing |
| `pam import detect FILE` | Show detected source + confidence scores |
```bash
$ pamx import extract /demo/claude-export.zip --out /tmp/raw.jsonl
claude · 142 conversations · 0 errors
```

### M2 — Normalizer
| Command | Description |
|---|---|
| `pam import run FILE [--source …] [--agent default] [--update] [--dry-run]` | Archive raw → write episodes → one commit; prints `ImportReport` |
| `pam import run FILE --all` | Shortcut: run → derive → index → cluster |
| `pam episode list [--agent A] [--source S] [--limit 20]` | List episodes (id, date, title, messages) |
| `pam episode show ID [--raw]` | Rendered or raw Markdown |
| `pam episode verify` | Re-hash every body against `body_sha256` |
```bash
$ pamx import run /demo/claude-export.zip
✔ 142 found · 142 written · 0 skipped · commit a91be02 · 2.1s
$ pamx import run /demo/claude-export.zip
✔ 142 found · 0 written · 142 skipped
```

### M3 — Rule extractor & persona
| Command | Description |
|---|---|
| `pam derive [--episode ID] [--dry-run]` | Extract facts/rules/style; render the `default` persona; prints `DeriveReport` |
| `pam patterns list` | Show all extraction patterns |
| `pam patterns test "SENTENCE"` | Show which patterns fire, the captured value, and why matches were skipped (negation/question) |
| `pam persona show [--agent default]` | Print the rendered persona (Derived + Custom) |
```bash
$ pamx patterns test "I'm building a portable memory app in React"
working_on = "a portable memory app in React"  (pattern: building, conf 0.60)
```

### M4 — Indexer
| Command | Description |
|---|---|
| `pam index [PATHS…] [--rebuild]` | Incremental (default) or full rebuild; prints `IndexReport` |
| `pam index stats` | Documents/chunks per type, embedding model, DB size |

### M5 — Clusterer & graph
| Command | Description |
|---|---|
| `pam cluster [--rebuild] [--agent default]` | Assign new episodes / full recluster with stable IDs; prints `ClusterReport` |
| `pam project list [--agent A] [--status active\|dormant]` | Projects with keyword and episode counts |
| `pam project show ID` | Project file |
| `pam graph export [--agent A] [--facts] --out graph.json` | `GraphData` JSON |

### M6 — Retriever & context
| Command | Description |
|---|---|
| `pam search "QUERY" [--agent A] [-k 8] [--type episode,fact,…] [--since 2026-09-01]` | Hybrid search; shows score, vector rank, and keyword rank |
| `pam context "QUERY" [--agent A] [--budget 2000] [--session ID] [--no-persona]` | Prints `rendered` plus the token line |
```bash
$ pamx context "where did I leave off on the hackathon app?" --budget 2000
…rendered markdown…
tokens: 1,842 / 2,000 · baseline 46,310 · saved 44,468 (96%)
```

### M7 — Memory writer
| Command | Description |
|---|---|
| `pam fact add --attribute ATTR --value V --category CAT [--cardinality single\|multi] [--agent A] [--shared/--no-shared] [--episode ID]` | `add_fact` |
| `pam fact list [--scope shared\|AGENT] [--status active\|conflict]` | List facts |
| `pam fact show ID` | Fact with its history |
| `pam fact supersede ID --value V --reason "…"` | `supersede_fact` |
| `pam project create --name N [--agent A]` | `update_project` (create) |
| `pam project note ID "TEXT"` | Append to `## Notes` |
| `pam project add-episodes ID EP_ID…` | Add membership |
| `pam skill add --name N --description D --steps-file steps.md [--keywords a,b]` | `add_skill` |
| `pam skill list [--agent A]` | List skills |
| `pam episode log --title T --messages msgs.jsonl [--summary S]` | `log_episode` (JSONL of `RawMessage`) |

### M8 — Agents & permissions
| Command | Description |
|---|---|
| `pam agent list` | All agents |
| `pam agent show NAME` | Manifest and persona |
| `pam agent create NAME [--display-name] [--description] [--projects ID,…] [--write none\|own\|shared] [--tools t1,t2] [--model M] [--budget 2000]` | New custom agent |
| `pam agent set-scope NAME [--projects …] [--shared-facts/--no-shared-facts] [--write …] [--tools …]` | Update scope (one commit) |
| `pam agent check NAME --tool T` / `--path P` | Debug permission decisions |

### M9 — Working memory
| Command | Description |
|---|---|
| `pam session start [--agent A] [--model M]` | Prints the new `session_id` |
| `pam session record ID --role user\|assistant --text "…" [--model M]` | Add a turn (for testing before `chat` exists) |
| `pam session update ID [--goal G] [--decision D]… [--question Q]…` | `update_working_memory` |
| `pam session show ID` / `pam session list` | Inspect sessions |
| `pam session end ID` | Promote to an episode |

### M10 — Vault sync
| Command | Description |
|---|---|
| `pam sync` | One pass: detect manual edits → validate → reindex → commit; prints `SyncReport` |
| `pam sync --watch [--interval 5]` | Loop until Ctrl-C |
| `pam sync status` | Dirty paths without acting |
| `pam log [-n 20]` | Pretty `git log` of the vault |

### M11 — MCP server
| Command | Description |
|---|---|
| `pam mcp serve --transport stdio [--agent default]` | For Claude Desktop / Cursor |
| `pam mcp serve --transport http [--host 0.0.0.0] [--port 8765]` | Standalone HTTP (normally mounted at `:8000/mcp` by `api serve`) |
| `pam mcp tools [--agent A]` | List the tools that agent would see |

**Connect Claude Desktop.** Edit the config file:
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
Restart Claude Desktop. **Inspect manually:** `npx @modelcontextprotocol/inspector`, then connect to `http://localhost:8000/mcp?agent=default`.

### M12 — Chat orchestrator
| Command | Description |
|---|---|
| `pam models list` | Models from `pam.toml` |
| `pam models check` | Ping each model with a 1-token request; mark failing models |
| `pam chat "MESSAGE" --model M [--session ID] [--agent A] [--mode injection\|tool] [--show-context]` | One streamed turn; prints the session ID for follow-ups |
```bash
$ pamx chat "where did I leave off?" --model openrouter/<model>:free
session s_8k2m1x0q9zab · context 1,842 tok (saved 44,468)
You were wiring the RAG pipeline…
$ pamx chat "ok, what's next?" --model anthropic/<claude-model-id> --session s_8k2m1x0q9zab
```

### M13 — REST API
| Command | Description |
|---|---|
| `pam api serve [--host 0.0.0.0] [--port 8000] [--reload]` | FastAPI app (`/api/*`, `/mcp`, `/docs`) |
```bash
curl -s localhost:8000/api/health
curl -N -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"model":"openrouter/<model>:free","message":"hi"}'
```

### M14 — Frontend
| Command (in `frontend/`) | Description |
|---|---|
| `npm install` | Dependencies |
| `npm run gen:types` | `../schemas/*.json` → `src/types/generated.ts` (run after `pam schema export`) |
| `npm run dev` | Vite dev server on :5173, proxying `/api` and `/mcp` to `localhost:8000` |
| `npm run build` / `npm run preview` | Production build / preview |

### M15 — Docker
| Command | Description |
|---|---|
| `docker compose up --build -d` | Build + start backend and frontend |
| `docker compose --profile local up -d` | Also start Ollama |
| `docker compose logs -f backend` | Tail backend logs |
| `docker compose exec backend pam …` | Run any CLI command |
| `docker compose down` | Stop (the vault on the host is untouched) |

### M16 — Connectors
A connector is an outside HTTP API offered to agents as tools (CHG-0027). Each one is a YAML file at `vault/connectors/<id>.yaml`, with one git commit per save or archive. Nothing is deleted: archiving hides and disables a connector.

| Command | Description |
|---|---|
| `pam connector list [--all]` | Connectors with state, tool count and agents; invalid files are shown as `INVALID`; `--all` adds archived ones |
| `pam connector show ID` | The connector as YAML (`--json` for JSON) |
| `pam connector add FILE.yaml` | Validate and save; no commit if nothing changed |
| `pam connector archive ID` | `archived: true`, `enabled: false` |
| `pam connector call ID TOOL --arg k=v …` | One call: status, latency and card titles; `--json` prints the `ConnectorResult`; exits 1 if the call failed |

- **Who gets the tools:** only agents listed under `agents:`, and only on models with `supports_tools`. The `default` agent gets none unless it is listed. The model sees each tool as `<connector_id>__<tool>`.
- **Secrets:** `auth.env_var` holds only the secret's *name*. Put the value in `.env` (or the environment) under that name. A same-named entry in `vault/.pam/secrets.json` also works, but saving a key on the Settings page currently rewrites that file and drops it, so `.env` is the reliable place.
- **Safety:** requests stay inside `base_url` (no `/`, `\` or dot segments in path values) and redirects are not followed. Limits come from `[connectors]` in `pam.toml`: `timeout_seconds`, `max_response_bytes`, `max_result_tokens`, `max_tools_per_turn`.
- **Docker:** a `base_url` such as `http://tmobile-mock:8100` resolves only on the compose network, so run calls inside the container.
```bash
docker compose cp mock/tmobile/connector.yaml backend:/tmp/connector.yaml
pamx connector add /tmp/connector.yaml
pamx connector call tmobile get_household --arg customer_id=cust-chen
curl -s localhost:8000/api/connectors
curl -s -X POST localhost:8000/api/connectors/tmobile/tools/search_devices/call \
  -H 'content-type: application/json' -d '{"query":"camera"}'
```

## 7. Local development without Docker (optional)
```bash
cd backend && uv sync && uv run python -m spacy download en_core_web_sm
export PAM_VAULT=../vault && uv run pam init && uv run pam api serve --reload
cd ../frontend && npm install && npm run dev
```
> On macOS, the system or Homebrew Python may not allow loading SQLite extensions (sqlite-vec). Use the `uv`-managed Python, or just use Docker.

## 8. Tests
```bash
docker compose exec backend pytest -q                 # everything
docker compose exec backend pytest -q -k m06          # one module
```

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `dubious ownership in repository` | `pam init` sets `safe.directory`; for older vaults run `docker compose exec backend git config --global --add safe.directory /vault` |
| Files show as modified on Windows with no edits | Line endings: the vault has `.gitattributes` `* text eol=lf`; make sure the repo is cloned inside WSL |
| `sqlite3.OperationalError: not authorized` / extension load fails | You're outside Docker on a Python without extension support; use Docker or the uv Python |
| `pam index` refuses to run: model mismatch | You changed the `embedding.model` config; run `pam index --rebuild` |
| Exit code 4, "vault busy" | Another writer holds the lock; retry, or check for a stuck process with `docker compose top backend` |
| Chat streams nothing behind nginx | Make sure `proxy_buffering off;` is set for `/api/chat` in `nginx.conf` |
| A free model disappears mid-demo | `pam models check`, then switch models in the dropdown (that's the point of the project 🙂) |

## 10. Reset
```bash
docker compose exec backend pam index --rebuild   # rebuild derived index only (safe)
# Full reset (destroys the vault; human-only, never done by agents):
# docker compose down && rm -rf vault && docker compose up -d && pamx init
```

## 11. T-Mobile demo
A synthetic carrier API (SPEC §8 M17) for the T-Mobile side track. It is fictional data only, and PAM reaches it through the `tmobile` connector (M16, T17).
```bash
docker compose up -d --build tmobile-mock                 # healthy at http://localhost:8100/health
curl -s localhost:8100/customers/cust-chen | head -c 300
# images through the frontend: http://localhost:5173/connectors/tmobile/images/devices/kestrel-5-slate.svg
PAM_DOCKER=1 mock/tmobile/demo-setup.sh                   # scratch vault in ./demo/tmobile/vault (needs T17)
cd mock/tmobile && uv run --frozen pytest -q              # the mock's own tests
```
- `MOCK_TODAY` (default `2026-10-18`) fixes "now"; `PUBLIC_BASE` (default `/connectors/tmobile`) prefixes image URLs.
- The tools, the engines and the API conventions are in `mock/tmobile/README.md`; the 3-minute story is in `mock/tmobile/DEMO.md`.
