# Current assignments & agent prompts

Written by PM at kickoff (2026-10-17). Repo root for every agent is `pam/`. Windows teammates: clone inside WSL2.
Paste your prompt into your own Claude Code session. When you finish, tell PM (via Pranav) "<name> finished <task>". PM runs the Done-when checks before anything counts as done.

## Pranav: P0.3/P0.4 fixtures + R1

```
You are doing SPEC Phase 0 tasks P0.3/P0.4 and research R1, not a Phase 1 task. Repo root is pam/. Read SPEC.md §0, §7.2, §7.3, §8 M1 and the M3 Acceptance criteria, and research/TODO.md R1. Source data is demo/legacy-vault/imports/conversations.json, a real Claude export (gitignored). Never copy it into a tracked path unmodified. Write the anonymizer script outside the repo or under demo/ (gitignored). It picks 10 conversations, anonymizes names, emails and orgs, and keeps the original field structure: uuid, name, summary, created_at, updated_at, account, chat_messages[uuid, text, content, sender, created_at, updated_at, attachments, files]. Conversation branching is out of scope; treat messages as a linear list. Plant three things: 'I study at WSU' in an older conversation and 'I go to UW' in a newer one; 'no bullet points' in 2 different conversations; 3 distinct topics with 3 or more conversations each. Output backend/tests/fixtures/claude/export.zip (containing conversations.json) and backend/tests/fixtures/claude/README.md, which lists every field we use and how often `summary` is empty or missing. Append the R1 findings under R1 in research/TODO.md (append-only; check the boxes). Allowed paths: backend/tests/fixtures/**, research/TODO.md.
```

## Yogesh: T00 Scaffold

```
Task T00 (Scaffold). Repo root is pam/. Follow SPEC.md §9.1 exactly. Read SPEC.md §0, §4 (Runtime), §5, §7 (skim), all of §8 (for the dependency list), §8 M15, §9.3 T00, and every APPROVED entry in §10. Allowed paths: docker-compose.yml, .env.example, .gitignore, backend/Dockerfile, backend/pyproject.toml, backend/pam/__init__.py, backend/pam/cli/main.py, frontend/** (Vite template + Tailwind only). Add every Python dependency named anywhere in §8 to pyproject.toml now, because no later task may edit it. Extend the existing .gitignore, keeping vault/, demo/ and .env, and adding node_modules and __pycache__. Use python:3.12-slim + git + uv for the backend image and node:20 for the frontend. Done when: `docker compose up --build` starts both containers; `docker compose exec backend pam --version` prints 0.1.0; :5173 shows the Vite page. Append your Agent plan and Result under T00 in SPEC.md. We are on Windows 11 inside WSL2.
```

## Yogesh: T01 Contracts & core (after T00)

```
Task T01 (Contracts & core). Repo root is pam/. Follow SPEC.md §9.1. Read SPEC.md §0, all of §7, §6, §8 M0, §9.3 T01, and the APPROVED entries in §10. Allowed paths: backend/pam/contracts/**, backend/pam/core/**, backend/pam/cli/{main,init_cmd,schema_cmd}.py, schemas/**, backend/tests/**. Transcribe §7 verbatim. Make cli/main.py auto-register any Typer sub-app found in pam/cli/*_cmd.py, so later tasks never edit main.py, and log that as a `design` CHG entry with status IMPLEMENTED in §10. Done when: `pam init --vault /tmp/v && git -C /tmp/v log --oneline` shows 1 commit; `pam schema export` writes schemas/*.json; `pytest tests/test_m00_core.py` is green. Any contract change: append a PROPOSED entry and stop.
```

## Aakash: R5/R6 search-library spike

```
Research spike R5+R6 for PAM. Reference only: pam/SPEC.md §7.8, §8 M4, §8 M6 Implementation; pam/research/TODO.md R5 and R6. Write code ONLY in ~/pam-spikes/, outside the repo. Build a Dockerfile FROM python:3.12-slim with sqlite-vec, fastembed and numpy, with the model pre-downloaded into /models (FASTEMBED_CACHE_PATH=/models). The script creates the §7.8 chunks, chunks_fts (porter unicode61) and chunks_vec float[384] tables with shared rowids. It embeds 100 sentences (L2-normalized, serialize_float32), runs a vec0 KNN query (`MATCH ? AND k = ?`) and an FTS5 bm25 query with quoted, OR-joined tokens, and fuses the two with RRF k=60. Also time embedding 1,000 chunks at batch size 64. Answer two questions: can vec0 filter on metadata, or must we post-filter? Does the bge v1.5 query prefix still help? In the repo, edit only pam/research/TODO.md: append findings under R5/R6 and check the boxes.
```

## Aakash: T03 Importers (after T01 is done and the fixtures exist)

```
Task T03 (Importers). Repo root is pam/. Follow SPEC.md §9.1. Read SPEC.md §0, all of §7 (especially §7.2), §8 M1, §9.3 T03, the APPROVED entries in §10, and research/TODO.md R1–R3. Allowed paths: backend/pam/importers/**, backend/pam/cli/import_cmd.py, backend/tests/**. Build the Claude importer first, then ChatGPT, then Gemini, then detect.py and `pam import extract`. Treat Claude messages as linear; branching is out of scope. Done when: `pam import extract tests/fixtures/<src>/… --out /tmp/raw.jsonl` works for all 3 sources and every line validates as a RawConversation. Any contract change: append a PROPOSED entry and stop.
```
