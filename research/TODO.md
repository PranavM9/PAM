# Research TODO — what we need to learn before (and during) DubHacks

> Check boxes as you go and append findings under each item (➕ append-only; never delete notes).
> **Priority:** 🔴 must finish before the hackathon · 🟡 nice to know beforehand · 🟢 learn on demand.
> Every item has a **Done when**, so you know when to stop.

## R1 — Claude export format 🔴 (blocks M1)
- [ ] Request a real Claude export and record the exact zip contents (file names, top-level keys).
- [ ] Document the fields of `conversations.json`: conversation id/name/summary/timestamps, the message `sender` values, `text` vs `content[]` blocks, attachments/files.
- [ ] How often is `summary` populated? Is it ever empty-string vs missing?
- [ ] Are there other useful files (projects, memories, users)? Note them for a possible later importer.
- [ ] How long did the export take to arrive? (affects the demo plan)
- **Done when:** a 10-conversation anonymized fixture exists in `backend/tests/fixtures/claude/` with a README listing every field we use.

## R2 — ChatGPT export format 🟡
- [ ] Inspect the `conversations.json` `mapping` tree: `current_node`, `parent`, `children`, `message.author.role`, `content.parts`, `create_time` (epoch float).
- [ ] How do edits/regenerations appear? Confirm that walking up from `current_node` gives the visible thread.
- [ ] Which message types to skip (system, hidden, tool, multimodal parts)?
- **Done when:** fixture + README in `fixtures/chatgpt/`; the branch-walk algorithm is written down in pseudocode.

## R3 — Gemini / Google Takeout 🟡
- [ ] Which Takeout product contains Gemini chats, and in what format (JSON vs HTML)?
- [ ] Does it include model responses or only prompts? Is there any conversation ID?
- [ ] Decide on the grouping heuristic (time gap) and test it on real data.
- **Done when:** a decision recorded here: "parse X from Y" or "Gemini = MCP consumer only."

## R4 — MCP (Model Context Protocol) 🔴 (blocks M11, M12)
- [ ] Read the MCP concepts: tools, resources, prompts, server instructions, transports (stdio vs streamable HTTP).
- [ ] Official Python SDK: `FastMCP` tool definitions with Pydantic models; how to get `streamable_http_app()` and mount it in FastAPI.
- [ ] How to register tools conditionally per connection (agent-filtered), or the fallback: one server instance per agent.
- [ ] Python MCP **client**: `ClientSession` over streamable HTTP, `list_tools`, `call_tool`.
- [ ] Claude Desktop config with `docker exec -i …` for stdio; confirm it works on Windows + macOS.
- [ ] MCP Inspector usage.
- **Done when:** a 20-line toy server with one tool works in both Claude Desktop (stdio) and Inspector (HTTP).

## R5 — sqlite-vec + FTS5 🔴 (blocks M4, M6)
- [ ] Install `sqlite-vec` in `python:3.12-slim`; `sqlite_vec.load(conn)`; check the version.
- [ ] `vec0` virtual table syntax, inserting with `serialize_float32`, KNN query (`MATCH … AND k = ?`), what "distance" means for normalized vectors.
- [ ] Can vec0 filter by metadata columns, or do we post-filter? (Affects scope filtering.)
- [ ] FTS5 basics: `MATCH` syntax, `bm25()`, the porter tokenizer, escaping user queries safely.
- [ ] Reciprocal Rank Fusion: read one short explainer; confirm `k=60`.
- **Done when:** a toy script indexes 100 sentences and runs a hybrid query with RRF in Docker.

## R6 — Embeddings & chunking 🔴 (blocks M4)
- [ ] What embeddings are and why cosine similarity works (watch one 10-min explainer).
- [ ] `fastembed`: `TextEmbedding("BAAI/bge-small-en-v1.5")`, batch embedding, cache dir env var, pre-downloading in a Dockerfile.
- [ ] bge query instruction prefix: confirm it's still recommended for v1.5.
- [ ] Chunking strategies (fixed-size, semantic, turn-based); why turn pairs fit chat logs.
- **Done when:** embedding 1,000 chunks takes a measured time on our laptops (record the number here).

## R7 — Clustering & topic naming 🟡 (M5)
- [ ] `sklearn.cluster.HDBSCAN`: `min_cluster_size`, noise label `-1`, behavior on small datasets.
- [ ] Read how BERTopic does **c-TF-IDF** (we reimplement only that part with `CountVectorizer`).
- [ ] Jaccard matching for stable cluster IDs across reclustering.
- **Done when:** a notebook clusters fixture episodes and prints sensible keyword names.

## R8 — Rule-based information extraction 🟡 (M3)
- [ ] spaCy basics: `nlp(text)`, `doc.sents`, `doc.ents` (ORG, GPE, PERSON), `Matcher` token patterns.
- [ ] Regex named groups in Python; testing patterns quickly (`pam patterns test` is our own tool for this).
- [ ] Simple negation and hypothetical detection heuristics.
- [ ] Collect 30+ real sentences from our own chats for the test table (positive + negative cases).
- **Done when:** the test table draft exists in `research/extraction_cases.md`.

## R9 — LLM provider layer 🔴 (blocks M12 / the demo)
- [ ] LiteLLM: `acompletion(stream=True)`, model string prefixes (`anthropic/`, `openrouter/`, `ollama/`), env var names, tool calling format.
- [ ] Anthropic API access: confirm whether we have API credits (a Claude subscription is separate from API billing); get the current model ID strings.
- [ ] OpenRouter free models: pick 2–3 that are currently available and **support tool calling**; note rate limits.
- [ ] (Optional) Ollama in Docker: a model small enough for our laptops.
- **Done when:** a script streams a reply from 2 different providers through LiteLLM with the same code.

## R10 — Backend web stack 🟡 (M13)
- [ ] FastAPI: routers, `BackgroundTasks`, file uploads (`python-multipart`), CORS.
- [ ] SSE with `sse-starlette` (`EventSourceResponse`); test with `curl -N`.
- [ ] nginx config for SSE (`proxy_buffering off`, timeouts).
- **Done when:** a toy endpoint streams 10 events through nginx in Docker.

## R11 — Git automation 🟡 (M10)
- [ ] `git status --porcelain -z` output format.
- [ ] `safe.directory` and file ownership with Docker bind mounts (especially WSL2).
- [ ] `core.autocrlf` / `.gitattributes` for cross-platform LF.
- **Done when:** a commit from inside the container shows up cleanly in `git log` on the host (Windows + Mac).

## R12 — Frontend 🟡 (M14)
- [ ] Vite + React + TS + Tailwind setup; `@tailwindcss/typography` `prose` class.
- [ ] `react-force-graph-2d`: data format, node/link styling, `onNodeDragEnd` pinning, hover highlight, `centerAt` / `zoom`, d3 force tuning.
- [ ] `react-markdown` + `remark-gfm`; loading `.md` with `import.meta.glob(..., { query: '?raw' })`.
- [ ] SSE over POST with `@microsoft/fetch-event-source`.
- [ ] TanStack Query basics (queries, mutations, polling).
- [ ] `json-schema-to-typescript` codegen from `/schemas`.
- **Done when:** a toy page renders a 500-node force graph that can be dragged, plus one streamed SSE response.

## R13 — Docker cross-platform 🔴 (blocks everything on Windows)
- [ ] Docker Desktop + WSL2 on Windows; why repos should live in the WSL filesystem.
- [ ] Multi-stage builds; baking ML models into the image; image size check.
- [ ] Compose profiles, healthchecks, named volumes vs bind mounts.
- [ ] `uv` in Docker (`uv sync --frozen`), layer caching.
- **Done when:** the T00 scaffold builds and runs on one Windows and one Mac machine.

## R14 — Python tooling 🟢
- [ ] Pydantic v2: `model_json_schema`, `AwareDatetime`, discriminated unions, validators.
- [ ] Typer sub-apps and `rich` tables.
- [ ] `python-frontmatter` round-trips; `uuid5`; `tiktoken`.
- [ ] pytest fixtures and parametrized tables.

## R15 — Demo & pitch 🟡
- [ ] Choose the real project history for the demo; make sure it contains nothing private you wouldn't show on a projector.
- [ ] Time the full pipeline on the demo export (target: import → graph in under 60 s).
- [ ] Prepare the token-savings number and one slide explaining it.
- [ ] Backup plan: a screen recording of the full demo in case the venue Wi-Fi or a free model dies.
- **Done when:** two full rehearsals under 4 minutes.
