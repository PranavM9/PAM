# Research TODO — what we need to learn before (and during) DubHacks

> Check boxes as you go and append findings under each item (➕ append-only; never delete notes).
> **Priority:** 🔴 must finish before the hackathon · 🟡 nice to know beforehand · 🟢 learn on demand.
> Every item has a **Done when**, so you know when to stop.

## R1 — Claude export format 🔴 (blocks M1)
- [x] Request a real Claude export and record the exact zip contents (file names, top-level keys).
- [x] Document the fields of `conversations.json`: conversation id/name/summary/timestamps, the message `sender` values, `text` vs `content[]` blocks, attachments/files.
- [x] How often is `summary` populated? Is it ever empty-string vs missing?
- [x] Are there other useful files (projects, memories, users)? Note them for a possible later importer.
- [x] How long did the export take to arrive? (affects the demo plan)
- **Done when:** a 10-conversation anonymized fixture exists in `backend/tests/fixtures/claude/` with a README listing every field we use.

### R1 findings (2026-10-17) ➕
- **Delivery:** the export arrived in ~30 s. It is a `manifest-<id>.json` with 6 download links (each expires in 24 h; download each one fully on first open): `light_metadata-000.zip`, `projects-000.zip`, `memories-000.zip`, `feedback-000.zip`, `frames-000.zip`, `conversations-000.zip`. The conversations zip holds just `conversations.json`, a top-level JSON array. Exports from two dates (70 and 20 conversations) have the identical schema.
- **Conversation keys (all always present):** `uuid`, `name`, `summary`, `created_at`, `updated_at`, `account{uuid}`, `chat_messages[]`. Timestamps look like `2026-08-17T10:58:50.109075Z` (µs, `Z`). `name` can be `""` (5/70).
- **Message keys (all always present):** `uuid`, `text`, `content[]`, `sender`, `created_at`, `updated_at`, `attachments[]`, `files[]`, `parent_message_uuid`. `sender` ∈ {`human`, `assistant`} only. Messages are already in chronological order.
- **`text` vs `content[]`:** prefer the `content[]` blocks with `type=="text"` (join with `\n\n`). `text` differs from them in 312/1737 messages, all assistant: it has thinking text glued on the front and `This block is not supported on your current device yet.` placeholders where tools ran. Fall back to `text` only when there is no text block (25 cases).
- **Block types:** `text`, `thinking`, `tool_use`, `tool_result`, `injected_prompt_block`. Only `text` is conversation content.
- **Attachments/files:** `attachments[]` = `{file_name, file_size, file_type, extracted_content}` (text files with their extracted text; `file_type` is sometimes a bare extension like `txt`). `files[]` = `{file_uuid, file_name}`; it duplicates attachments for text files, but **images/PDFs appear only in `files`**, and `file_name` can be `null`.
- **Summary:** the key is always present and never `null`; absent means `""`. 51/70 (73%) were `""` in the older export, 1/20 in the newer one. It looks like a recent feature: almost every conversation since about 2026-09-11 has one. When `""`, fall back to the verbatim transcript (`has_summary=false`).
- **Empty conversations:** 3/70 have only messages with `text=""`, `content=[]` and no files. The importer must skip and count them.
- **Branching (out of scope for now):** 26/70 conversations are non-linear; edits and retries leave sibling branches flattened into `chat_messages` by time. A linear read duplicates edited prompts. A later fix is to walk `parent_message_uuid` back from the last message (root parent = `00000000-0000-4000-8000-000000000000`).
- **Other files for later importers:** `memories` (Claude's saved memory, an obvious P2 source for facts), `projects` (project docs/instructions → `Project`), `light_metadata`/`frames`/`feedback` (not inspected yet).
- **Fixture:** `backend/tests/fixtures/claude/export.zip` + `README.md` (10 anonymized conversations, 3 topics × 3, WSU→UW contradiction, "no bullet points" ×2, 1 empty conversation). Gap for T08: no §M3 starter pattern matches "I go to UW". Add a `go to|attend` → `school` pattern.

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
- [x] Install `sqlite-vec` in `python:3.12-slim`; `sqlite_vec.load(conn)`; check the version. (Docker was initially unavailable; a later Docker 29.8.2 build/run succeeded with `sqlite-vec` 0.1.6.)
- [x] `vec0` virtual table syntax, inserting with `serialize_float32`, KNN query (`MATCH … AND k = ?`), what "distance" means for normalized vectors.
- [x] Can vec0 filter by metadata columns, or do we post-filter? (Affects scope filtering.)
- [x] FTS5 basics: `MATCH` syntax, `bm25()`, the porter tokenizer, escaping user queries safely.
- [x] Reciprocal Rank Fusion: read one short explainer; confirm `k=60`.
- **Done when:** a toy script indexes 100 sentences and runs a hybrid query with RRF in Docker. ✓
- **Findings (2026-10-17, append-only):** See `~/pam-spikes/R5.md`. Host spike verified 100 shared rowids, FTS5 porter/unicode61 + quoted OR/BM25, vec0 KNN and RRF. vec0 supports typed metadata filters when declared in the vec0 schema, but §7.8 `chunks_vec` declares only `embedding`, so M6 must join and post-filter by `ReadScope` (with its specified over-fetch). Docker image/run is still unverified because Docker Desktop could not start.
- **Findings (update 2026-10-17, append-only):** Docker later started successfully. The `python:3.12-slim` image built, pre-downloaded the model to `/models`, and the container passed the 100-row hybrid query and metadata-filter probe. The earlier note records the initial Docker failure; this update supersedes its run status.

## R6 — Embeddings & chunking 🔴 (blocks M4)
- [ ] What embeddings are and why cosine similarity works (watch one 10-min explainer).
- [x] `fastembed`: `TextEmbedding("BAAI/bge-small-en-v1.5")`, batch embedding, cache dir env var, pre-downloading in a Dockerfile.
- [x] bge query instruction prefix: confirm it's still recommended for v1.5.
- [x] Chunking strategies (fixed-size, semantic, turn-based); why turn pairs fit chat logs.
- **Done when:** embedding 1,000 chunks takes a measured time on our laptops (record the number here). ✓ Docker median: 3.493 s.
- **Findings (2026-10-17, append-only):** See `~/pam-spikes/R6.md`. The BAAI model card still recommends `Represent this sentence for searching relevant passages: ` for short-query-to-passage retrieval. In a small synthetic 10-query check, Recall@10 was 0.43 with the prefix and 0.44 without; this is effectively no demonstrated benefit and is too small to override the recommendation. On this Windows 11 Intel host (22 logical CPUs), 1,000 chunks at batch size 64 took 2.806 s, 2.577 s, and 2.626 s (median 2.626 s). Docker pre-download remains unverified.
- **Findings (update 2026-10-17, append-only):** The Docker image successfully pre-downloaded the model into `/models`. In the Linux/WSL2 container, three warmed 1,000-chunk runs at batch size 64 took 3.493 s, 3.567 s, and 3.349 s (median 3.493 s). The earlier note records the first attempt; this update supplies the completed container results. The video suggestion in the first R6 checkbox was not watched; the concept is explained in `~/pam-spikes/R6.md` and validated by the normalized-vector run.

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
- **Note (T01, 2026-10-17):** tiktoken downloads the `cl100k_base` BPE file on first `core.tokens.count()`. For offline runs, T16 should bake it into the image like the fastembed model (set `TIKTOKEN_CACHE_DIR` and call `tiktoken.get_encoding("cl100k_base")` at build time).

## R14 — Python tooling 🟢
- [ ] Pydantic v2: `model_json_schema`, `AwareDatetime`, discriminated unions, validators.
- [ ] Typer sub-apps and `rich` tables.
- [ ] `python-frontmatter` round-trips; `uuid5`; `tiktoken`.
- [ ] pytest fixtures and parametrized tables.
- **Note (T01, 2026-10-17):** `python-frontmatter` strips the body (`'\n# T\n\nbody  \n\n'` → `'# T\n\nbody'`), which would break `body_sha256`. `pam.core.mdio` splits frontmatter itself and uses PyYAML. Typer 0.27 vendors click as `typer._click`; raise `typer._click.exceptions.ClickException` (not `click.ClickException`) if you need custom exit codes.

## R15 — Demo & pitch 🟡
- [ ] Choose the real project history for the demo; make sure it contains nothing private you wouldn't show on a projector.
- [ ] Time the full pipeline on the demo export (target: import → graph in under 60 s).
- [ ] Prepare the token-savings number and one slide explaining it.
- [ ] Backup plan: a screen recording of the full demo in case the venue Wi-Fi or a free model dies.
- **Done when:** two full rehearsals under 4 minutes.
