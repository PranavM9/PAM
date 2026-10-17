# Current assignments & agent prompts (plan v2, 2026-10-17 13:25 PDT)

Repo root for every agent is `pam/` (github.com/PranavM9/PAM). Windows: clone inside WSL2.
Flow: `git checkout main && git pull && git checkout -b <branch>` -> work -> rebase on main -> push -> PR "T<NN>: <title>" -> a non-implementer reviews -> PM runs the checks -> merge.
Every prompt ends the same way: follow SPEC.md §9.1; touch only Allowed paths + backend/tests/** + your own task's Agent plan/Result in SPEC.md + appends to §10. Any contract (§7) change: append a PROPOSED entry and stop.

## Pranav: T08 test table (now)
Branch: `git checkout main && git pull && git checkout -b t08/extract-test-table`
```
Task: write the T08 test table FIRST (implementation comes later on a separate branch). Repo root is pam/. First read CLAUDE.md, commenting-guidelines.md and git-guidelines.md. Read SPEC.md §0, §7.4, §7.7 (PersonaRule), §8 M3 in full, §9.3 T08, and backend/tests/fixtures/claude/README.md. Create ONLY backend/tests/test_m03_extract.py: a pytest parametrized table of at least 40 cases, user sentence -> expected (attribute, value) or no fact. Cover every starter pattern, negations ("I don't work at X", "I no longer live in Y"), questions, hypotheticals (if/would/imagine/pretend), clause trimming at , . and/but/because, the 60-char cap, the stopword junk filter ("I'm building a list of..."), text in quotes or code fences (ignored), assistant messages (never mined), the 3 rule regexes, and "I go to UW" / "I attend UW" -> school=UW (the fixture README notes no starter pattern matches this yet; T08 must add one). Add fixture-level tests: derive on backend/tests/fixtures/claude/export.zip gives >=3 correct facts, >=1 rule ("no bullet points"), and the WSU(older)->UW(newer) handling per the M3 merge rules. Import from the module names in §8 M3 (pam.extract.patterns etc.) and guard the module with pytest.importorskip("pam.extract.facts") so the file passes (skips) before T08 exists. Do not create anything under backend/pam/. Open a PR "T08 (tests-first): extraction test table".
```

## Pranav: next, after T01 merges
- If early frontend is approved: T15a on `t15a/frontend-shell`. Layout, routing, theme, `src/api/client.ts` (typed fetch + SSE helper), `npm run gen:types` from schemas/, and mock data per §7.14. Allowed paths: `frontend/src/**`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tailwind.config.ts`, `frontend/tsconfig.json`. Not the Dockerfile or nginx.conf (T16).
- If not approved: T02 on `t02/git-helper` (Yogesh then goes straight to T05).
- Then T08 implementation on `t08/rule-extractor` once T04 + T05 have merged.

## Yogesh: T00 (done), then T01 Contracts & core (as soon as T00 is merged)
Branch: `git checkout main && git pull && git checkout -b t01/contracts-core`
```
Task T01 (Contracts & core). Repo root is pam/. First read CLAUDE.md, commenting-guidelines.md and git-guidelines.md. Follow SPEC.md §9.1. Read SPEC.md §0, all of §7, §6, §8 M0, §9.3 T01, and the APPROVED entries in §10. Allowed paths: backend/pam/contracts/**, backend/pam/core/**, backend/pam/cli/{main,init_cmd,schema_cmd}.py, schemas/**, backend/tests/**. Transcribe §7 verbatim into the contracts/* files listed in §5. Make cli/main.py auto-register every Typer sub-app found in pam/cli/*_cmd.py, so later tasks never edit main.py, and log that in §10 as a `design` CHG entry with status IMPLEMENTED. Implement pam init, pam schema export, and pam config show. Done when: `pam init --vault /tmp/v && git -C /tmp/v log --oneline` shows 1 commit; `pam schema export` writes schemas/*.json; `pytest tests/test_m00_core.py` is green (round-trip every model through mdio). Run everything inside the backend container. Open a PR "T01: Contracts & core".
```

## Yogesh: next, T02 then T05 (after T01 merges)
- `t02/git-helper`. Allowed paths: `backend/pam/sync/git.py`, `backend/pam/cli/sync_cmd.py` (stub). Done when the commit unit test passes in Docker.
- `t05/agents-permissions`. Allowed paths: `backend/pam/agents/**`, `backend/pam/cli/agent_cmd.py`. Done when the M8 acceptance criteria pass.
- Then T04 (after T03 merges), then T06.

## Aakash: now, review T00 + ChatGPT/Gemini fixtures
1. Review Yogesh's T00 PR and run the T00 checklist on Windows (gate 3 + gate 4).
2. Branch: `git checkout main && git pull && git checkout -b p0/chatgpt-gemini-fixtures`
```
Task: Phase 0 fixtures P0.3 for ChatGPT and Gemini (the Claude one already exists on branch p0/claude-fixture-r1). Repo root is pam/. First read CLAUDE.md, commenting-guidelines.md and git-guidelines.md. Read SPEC.md §7.2, §8 M1 (ChatGPT + Gemini bullets), §9.3 T03, and backend/tests/fixtures/claude/README.md as the model to follow. Allowed paths: backend/tests/fixtures/chatgpt/**, backend/tests/fixtures/gemini/** only. If you have a real export, anonymize it with a script kept OUTSIDE the repo; otherwise build a realistic synthetic one matching the documented formats. ChatGPT: export.zip with conversations.json, about 6 conversations, a list of {id, title, create_time (epoch float), update_time, mapping{node_id:{id, message{author.role, content{content_type, parts}, create_time}, parent, children}}, current_node}. Include at least 1 conversation with an edited/regenerated branch (so the walk from current_node must pick the final branch), 1 system/hidden message, 1 multimodal (non-string) part, and 1 empty conversation. Gemini: a Google Takeout 'Gemini Apps' MyActivity.json with about 10 activities whose time gaps split into at least 2 conversations (>30 min gap), some with and some without responses; optionally a MyActivity.html fallback. Write a README.md per source listing the fields used, the expected RawConversation count, and which edge case each conversation covers. Mark clearly in the README whether the data is real-anonymized or synthetic. Open a PR "P0.3: ChatGPT + Gemini fixtures".
```

## Aakash: next, T03 Importers (after T01 + both fixture PRs merge)
Branch: `git checkout main && git pull && git checkout -b t03/importers`
```
Task T03 (Importers). Repo root is pam/. First read CLAUDE.md, commenting-guidelines.md and git-guidelines.md. Follow SPEC.md §9.1. Read SPEC.md §0, all of §7 (especially §7.2), §8 M1, §9.3 T03, the APPROVED entries in §10, and the README.md in each of backend/tests/fixtures/{claude,chatgpt,gemini}/. Allowed paths: backend/pam/importers/**, backend/pam/cli/import_cmd.py, backend/tests/**. Build the Claude importer first (treat chat_messages as linear; branching is out of scope; prefer content[] text blocks, otherwise text; "" summary means None), then ChatGPT (walk parents from current_node), then Gemini (time-gap grouping), then detect.py and `pam import extract`. Done when: `pam import extract tests/fixtures/<src>/... --out /tmp/raw.jsonl` works for all 3 sources, every line validates as a RawConversation, and the Claude fixture yields 9 conversations with 1 skipped. Add backend/tests/test_m01_importers.py. Open a PR "T03: Importers".
```
- Then T07 (after T06), then T09.
