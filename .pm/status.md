# PAM status board

- **Hackathon start:** UNKNOWN (asked 2026-10-17 12:24 PDT) · **End:** UNKNOWN (start + 24 h, DubHacks)
- **Project root:** /Users/kalyan/Desktop/claude/PAM/pam/ (official §5 layout; everything outside it is irrelevant)
- **Spec:** pam/SPEC.md · **Version:** v1.0.0 (CHG-0000 APPROVED 2026-10-17 12:36 by team (Pranav)) · companions pam/SETUP.md, pam/research/TODO.md (docs/files copies are NOT authoritative)
- **Repo:** github.com/PranavM9/PAM (private). main = 703ab4f initial + 456e9dc §5 skeleton (SKELETON.md). Legacy vault at pam/demo/legacy-vault/ (gitignored, real data, never commit).
- **Plan times are relative (H+x from hackathon start) until start time is known.**

Gates: chk = Done-when commands pass (PM ran) · reg = earlier tests pass (PM ran) · man = human manual test confirmed · rev = reviewed by non-implementer

## Phase 0 (humans, §9.2)

| ID | Title | Owner | State | Notes |
|----|-------|-------|-------|-------|
| P0.0 | Approve CHG-0000 | Pranav | done 12:36 | in SPEC §10 |
| P0.1 | Research TODO | — | CUT 13:25 (user) | agents learn what they need inside each task; R1 already done by Pranav |
| P0.2 | Request real exports (Claude/ChatGPT/Gemini) | each | partial | Claude export exists locally (70 convs). ChatGPT/Gemini unknown |
| P0.3a | Claude fixture + R1 | Pranav | PR pending (branch p0/claude-fixture-r1 @ dd0c934) | PM verified: 10 convs, 1 empty, WSU(08-17)->UW(08-31), "no bullet points" x2, 3 topics x3, emails -> example.edu. Covers T03's Claude needs. Review: Aakash |
| P0.3b | ChatGPT + Gemini fixtures | Aakash | assigned 13:25 (branch p0/chatgpt-gemini-fixtures) | T03 Done-when needs all 3 sources |
| P0.4 | Demo Claude export -> `demo/claude-export.zip` (gitignored) | Pranav | todo | candidate: demo/legacy-vault/imports/conversations.json; privacy check pending |
| P0.5 | API keys + 2–3 tool-capable models | unassigned | unknown | needed by T13 (~H+10.5) |
| P0.6 | Docker on all 3 | all | done (user-confirmed 12:30) | all 3 have Docker; Windows bind-mount/git check still worth doing inside T00 |

## Phase 1 (§9.3)

| ID | Title | Owner | State | Depends on | Started | Finished | Est (h) | Actual (h) | chk | reg | man | rev |
|----|-------|-------|-------|-----------|---------|----------|---------|-----------|-----|-----|-----|-----|
| T00 | Scaffold | Yogesh | awaiting merge + checks (Yogesh reports finished ~13:25; branch not on origin) | — | ~12:40? | | 0.75 | ? | | | | |
| T01 | Contracts & core | Yogesh | next after T00 merge (t01/contracts-core) | T00 | | | 1.5 | | | | | |
| T02 | Git helper | Yogesh (planned, t02/git-helper) | todo | T01 | | | 0.5 | | | | | |
| T03 | Importers | Aakash (planned, t03/importers) | todo (needs P0.3a+b) | T01 | | | 2.0 | | | | | |
| T04 | Normalizer | Yogesh (planned) | todo | T02, T03 | | | 1.0 | | | | | |
| T05 | Agents & permissions | Yogesh (planned, t05/agents-permissions) | todo | T01, T02 | | | 1.0 | | | | | |
| T06 | Indexer | Yogesh (planned) | todo | T04, T05 | | | 2.0 | | | | | |
| T07 | Retriever & context | Aakash (planned) | todo | T06 | | | 2.0 | | | | | |
| T08 | Rule extractor & persona | Pranav (test table now on t08/extract-test-table; impl later on t08/rule-extractor) | test table assigned 13:25 | T04, T05 | | | 2.0 | | | | | |
| T09 | Memory writer | — | todo | T06, T08 | | | 1.5 | | | | | |
| T09b | Vault sync watcher | — | todo | T09 (+ after T07: shares retrieve/search.py) | | | 0.5 | | | | | |
| T10 | Clusterer & graph | — | todo | T06, T09 | | | 1.5 | | | | | |
| T11 | Working memory | — | todo | T09 | | | 0.75 | | | | | |
| T12 | MCP server | — | todo | T07, T09, T11 | | | 1.0 | | | | | |
| T13 | Chat orchestrator | — | todo | T12 | | | 1.5 | | | | | |
| T14 | REST API | — | todo | T10, T13 | | | 1.25 | | | | | |
| T15 | Frontend (a–g) | Pranav (15a early vs mocks after T01, if approved; t15a/frontend-shell) | todo | T14 (early-start pending approval) | | | 3.5 | | | | | |
| T16 | Docker hardening & demo | — | todo | T15 | | | 1.0 | | | | | |

## Critical path (with 3 people in parallel)
T00 → T01 → T03 → T04 → {T06 ∥ T08} → T09 → T11 → T12 → T13 → T14 → T15 → T16
= 0.75+1.5+2+1+2+1.5+0.75+1+1.5+1.25+3.5+1 = **17.75 h** (vs 19 h fully sequential). Slack: T07 0.25 h, T10 ~1.75 h, T05 ~1.5 h, T02 ~1.5 h.
Buffer at 24 h: ~6.25 h before sleep/pitch. Earliest-start schedule (H+):
T00 0–0.75 · T01 0.75–2.25 · T02 2.25–2.75 · T03 2.25–4.25 · T05 2.75–3.75 · T04 4.25–5.25 · T06 5.25–7.25 · T08 5.25–7.25 · T07 7.25–9.25 · T09 7.25–8.75 · T11 8.75–9.5 · T10 8.75–10.25 · T12 9.5–10.5 · T13 10.5–12 · T14 12–13.25 · T15 13.25–16.75 · T16 16.75–17.75

## Path-overlap sequencing notes
- `cli/import_cmd.py`: T03 then T04. `cli/episode_cmd.py`: T04 then T09. `extract/facts.py`: T08 then T09. `retrieve/search.py`: T07 then T09b. `frontend/**`: T00 then T15. Compose/Dockerfiles: T00 then T16.
- `cli/main.py` is only in T00/T01 allowed paths, but every later task adds a Typer sub-app -> T01 must make main.py auto-discover `pam/cli/*_cmd.py` (design, log as CHG `design` IMPLEMENTED).
- `backend/pyproject.toml` only in T00 -> T00 must add ALL deps from §8 up front.

## Agreed fixes (user-confirmed 12:30)
- T01: cli/main.py auto-discovers pam/cli/*_cmd.py (log as CHG `design` IMPLEMENTED).
- T00: all §8 Python deps in pyproject.toml up front.
- Claude branching (parent_message_uuid) is OUT OF SCOPE.

## Plan v2 (13:25, user request: no research, concrete tasks + branches)
- Pranav: p0/claude-fixture-r1 PR -> T08 test table (backend/tests/test_m03_extract.py) -> T15a frontend shell after T01 (if early-frontend approved; else T02) -> T08 impl after T04 -> later T10/T11.
- Yogesh: T00 merge -> T01 -> T02 -> T05 -> T04 (after T03) -> T06.
- Aakash: review T00 PR + Windows manual test -> ChatGPT/Gemini fixtures -> T03 (after T01) -> T07 (after T06) -> T09 after T08/T06.
- T08 note (from Pranav's fixture): no starter pattern matches "I go to UW". T08 must add an `attend`/`go to` -> school pattern (M3 says extend the starter set: design, not contract).

## Branch + merge flow
- Branch names: `t<NN>/<slug>` for §9.3 tasks (t01/contracts-core, t03/importers), `p0/<slug>` for fixtures. Branch from fresh main: `git checkout main && git pull && git checkout -b <branch>`.
- One task per branch. Touch only that task's Allowed paths + backend/tests/** + your own §9 Agent plan/Result in SPEC.md + appends to §10.
- Done implementing: rebase on main, push, open PR "T<NN>: <title>" into main.
- Reviewer = a teammate other than the implementer (gate 4). Reviewer also runs the PM's manual checklist where possible (gate 3).
- PM runs the Done-when commands + full pytest on the PR branch (gates 1+2) before merge. Merge only when all 4 gates pass; then PM marks done.
- SPEC.md conflicts: §9 Result lines and §10 appends from parallel branches can collide. On conflict, keep BOTH sides and never delete.
