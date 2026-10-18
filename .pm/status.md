# PAM status board

- **Hackathon start:** UNKNOWN (asked 2026-10-17 12:24 PDT) · **End:** UNKNOWN (start + 24 h, DubHacks)
- **Project root:** /Users/kalyan/Desktop/claude/PAM/pam/ (official §5 layout; everything outside it is irrelevant)
- **Spec:** pam/SPEC.md · **Version:** v1.0.0 (CHG-0000 APPROVED 2026-10-17 12:36 by team (Pranav)) · companions pam/SETUP.md, pam/research/TODO.md (docs/files copies are NOT authoritative)
- **Repo:** github.com/PranavM9/PAM (private). main @ 73fa8cf (13:49): PRs #1–#5 merged (fixture, T00, agent guidelines, R5/R6 notes, T08 test table). Agents must read CLAUDE.md, commenting-guidelines.md, git-guidelines.md first. Legacy vault at pam/demo/legacy-vault/ (gitignored, real data, never commit).
- **Plan times are relative (H+x from hackathon start) until start time is known.**

Gates: chk = Done-when commands pass (PM ran) · reg = earlier tests pass (PM ran) · man = human manual test confirmed · rev = reviewed by non-implementer

## Phase 0 (humans, §9.2)

| ID | Title | Owner | State | Notes |
|----|-------|-------|-------|-------|
| P0.0 | Approve CHG-0000 | Pranav | done 12:36 | in SPEC §10 |
| P0.1 | Research TODO | — | CUT 13:25 (user) | R5/R6 notes were still merged as PR #4 (Aakash, docs only, harmless) |
| P0.2 | Request real exports (Claude/ChatGPT/Gemini) | each | partial | Claude export exists locally (70 convs). ChatGPT/Gemini unknown |
| P0.3a | Claude fixture + R1 | Pranav | merged PR #1 20:21Z | content verified by PM 13:25; no GitHub review (rev gate open) |
| P0.3b | ChatGPT + Gemini fixtures | Aakash | merged PR #7 (21:20Z) BEFORE PM review, no GitHub review. PM review 14:36: counts/tree/PII OK; fixes F1–F5 needed (folded into T03 branch) | ChatGPT 6 -> 5 + 1 skipped (msgs 4/3/2/2/3); Gemini 10 -> 3 convs 4/3/3, 18 msgs |
| P0.4 | Demo Claude export -> `demo/claude-export.zip` (gitignored) | Pranav | todo | candidate: demo/legacy-vault/imports/conversations.json; privacy check pending |
| P0.5 | API keys + 2–3 tool-capable models | Pranav | DONE: PR #21 (R9 notes) | keys are in local .env (Pranav verifies) |
| P0.6 | Docker on all 3 | all | done (user-confirmed 12:30) | all 3 have Docker; Windows bind-mount/git check still worth doing inside T00 |

## Phase 1 (§9.3)

| ID | Title | Owner | State | Depends on | Started | Finished | Est (h) | Actual (h) | chk | reg | man | rev |
|----|-------|-------|-------|-----------|---------|----------|---------|-----------|-----|-----|-----|-----|
| T00 | Scaffold | Yogesh | merged; gates 3 of 4 | — | ? | 13:25 | 0.75 | ? | pass (Yogesh+Aakash Docker on Windows; PM `pam --version` locally) | pass (pytest 1 skipped) | pass for Windows (Aakash 13:57, a932e14); macOS not checked | pending: Pranav to review PR #2 |
| T01 | Contracts & core | Yogesh | merged PR #6 (21:10Z); gates 2 of 4 | T00 | ~13:30? | 14:10 | 1.5 | ~0.7? | pass (PM 14:36: init -> 1 commit, schema export 54 files identical to schemas/, config show OK, re-init no-op) | pass (pytest 86 passed, 1 skipped) | n/a for CLI-only? pending: someone runs `pam init` in the container | pending (no GitHub review) |
| T02 | Git helper | Pranav | DONE: merged PR #9 (21:50Z) | T01 | 14:09 | 14:50 | 0.5 | ~0.7 | pass (PM 14:36, macOS) | pass | n/a (library only) | waived per git-guidelines change 15f8138 (needs explicit confirmation) |
| T03 | Importers | Aakash | DONE: PR #10 + follow-up PR #14 merged (23:42Z) | T01 | 14:36 | 16:40 | 2.0 | ~1.5 | pass (PM 16:43 on main: extract + detect on all 3 fixtures, Gemini zip byte-identical to the loose copy; real export via Pranav on b0e6bc7: claude · 65 conversations · 5 skipped · 0 errors) | pass (222 passed, 2 skipped) | real-data check done by Pranav | waived? |
| T04 | Normalizer | Pranav | MERGED PR #11 (22:49Z) | T02, T03 | 14:54 | 15:49 | 1.0 | ~0.9 | pass (PM 15:50, scratch copy of main: 9/5/3 episodes, 1 commit each; re-run 0 written, no commit; verify 17 OK; tamper -> FAIL, exit 1; archive byte-identical) | pass (131 passed, 1 skipped) | pending (container run) | waived? |
| T05 | Agents & permissions | Yogesh | DONE: merged PR #12 (22:56Z) | T01, T02 | ~14:50 | 15:56 | 1.0 | ~1.1 | pass (PM 15:50; main 16:05: 212 passed, 2 skipped) | pass | pending | waived? |
| T06 | Indexer | Yogesh | DONE: PR #25 | T04, T05 | ~16:00 | ~18:50 | 2.0 | ~2.8 (+40%) | pass (PM 20:15, uv Python: index 17 docs / 81 chunks in 36.5 s with the real model; re-run 17 unchanged; stats per doc_type) | pass (522 passed, 4 skipped) | pending | waived? |
| T07 | Retriever & context | Aakash | DONE: PR #28 (t07/retriever-fixes; CHG-0010 (M6), CHG-0011) | T06 | 18:32 | ~20:10 | 2.0 | ~1.6 | pass (PM 20:15 real model: 'tailscale eduroam' -> the right episode at #1; context --budget 800 -> 776 used, baseline 5251, saved 4475) | pass | pending | waived? |
| T08 | Rule extractor & persona | Pranav | DONE: PRs #15, #16, #17, #20 merged (latest 00:24Z) | T04, T05 | 15:50 | 17:24 | 2.0 | ~1.6 | pass (PM 16:58 + 17:26) | pass (334 passed, 2 skipped) | PASS (Pranav + team cross-check, 17:26) | PASS (team cross-check) |
| T09 | Memory writer | Pranav | DONE: PR #22 | T06, T08 | 17:42 | ~19:00 | 1.5 | ~1.3 | pass (PM 20:15 full suite incl. the real-index write test) | pass | pending | waived? |
| T09b | Vault sync watcher | Yogesh (took it instead of T11) | PR #31 OPEN, mergeable | T09 ✓, T07 ✓ | | ~22:20 | 0.5 | ? | pass (PM 22:26, uv Python: branch pytest 543 passed, 4 skipped; M10 acceptance: hand-edited fact -> `pam sync` 1 commit 'manual: 1 files', search finds the new value; edited episode body reported, not committed; deleted fact restored) | pass | n/a | waived? |
| T10 | Clusterer & graph | Pranav (t10/cluster-graph), after T13 part 1 | todo, READY | T06 ✓, T09 ✓ | | | 1.5 | | | | | |
| T11 | Working memory | Yogesh (t11/working-memory), NOT started at 22:26 (he did T09b + fix #30 first) | todo, READY, CRITICAL | T09 ✓ | | | 0.75 | | | | | |
| T12 | MCP server | Aakash | DONE: PR #29 (7fac367; CHG-0010 (M11)) | T07, T09, T11 | 19:12 | ~20:10 | 1.0 | ~1.0 | pass (test_m11 green; `pam mcp serve --help` lists both transports) | pass | Pranav verifies (Inspector / Claude Desktop) | waived? |
| T13 | Chat orchestrator | Pranav part 1 (t13/chat-llm), NOT started at 22:26; Yogesh rest after T11 + part 1 | todo, READY | T12 ✓ (+T11 for turn recording) | | | 1.5 | | | | | |
| T14 | REST API | Yogesh (after T13 rest; needs T10) | todo | T10, T13 | | | 1.25 | | | | | |
| T15 | Frontend (a–g) | Aakash: draft on t15/frontend-draft, a–f pushed (e5018d3), g pending; real wiring after T14 | in progress | T14 (wiring) | 19:50 | | 3.5 | ~0.4 so far | | | | |
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

## Plan v3 (14:09, Pranav: frontend deferred, backend first)
- Pranav: T02 now (early start, merges after T01) -> T09 tests-first (backend/tests/test_m07_memory.py) + reviews -> T08 impl after T04+T05 -> T10/T11.
- Yogesh: T01 -> T05 -> T04 (after T03) -> T06 -> T09.
- Aakash: P0.3b fixtures -> T03 -> T07 (after T06) -> T12.
- Critical path unchanged at 17.75 h: T00 → T01 → T03 → T04 → {T06 ∥ T08} → T09 → T11 → T12 → T13 → T14 → T15 → T16. T15 (3.5 h) is the biggest single block. Option: after T14, split T15 b–g across the 3 people by page file (pages/Import, Graph, Chat ...), after T15a lands. That brings T15 to about 1.6 h and the path to about 15.9 h. Needs agreement because T15 is one task with allowed paths frontend/**.
- Process note: Aakash pushed a932e14 (T00 Result line) directly to main without a PR (62440b4). Docs-only, accepted; remind everyone: PRs only.

## Process issues (14:36)
- PRs #1–#7 were all merged by Pranav with zero GitHub reviews; PR #7 was merged before the PM review it was waiting for. Rule from now: no merge without one GitHub approval from a non-author + PM check message.
- PR #8 (t00/wsl2-reverify, Yogesh, SPEC Result line only) is open. Stray remote branch Task-T00-wsl2.

## Plan v4 (14:54)
- Pranav: T04 now (critical path) -> T08 impl (after T04+T05).
- Yogesh: T05 -> T06.
- Aakash: T03 fixes (PR #10) -> T09 tests-first (backend/tests/test_m07_memory.py) -> T07 (after T06).
- Team decision 15f8138 (Pranav, git-guidelines.md): "No code review is required". The PM board keeps the rev gate but marks it 'waived' only after the user confirms.

## Blockers (15:50)
- spaCy model en_core_web_sm is not in the backend image (T00 deferred it to T16), but T08 needs it now, and `spacy download` may fail in a uv venv without pip. Draft CHG-0004 (design: T08 may add one RUN line to backend/Dockerfile) awaiting human APPROVED. T08 must also degrade gracefully (regex sentence split + acronym ORG rule) when the model is missing.
- PR #12 must rebase: SPEC.md conflict, and renumber its CHG-0002 to CHG-0003 (T04 already took 0002).

## 16:05 notes
- SPEC §10 on main has TWO entries numbered CHG-0002 (M8 at line ~1692, M2 at ~1707). Append-only, so do not renumber in place; a human appends a note (draft in log 16:05). The next free number is CHG-0003 (CHG-0004 is reserved for the drafted spaCy entry, still unapproved).
- T09 tests pin `merge_candidate` as the extraction path through M7. Pranav's T08 minimal writer should mirror that name so T09 can reroute cleanly.

## Plan v5 (16:10) — assumes T08 merges before T06 finishes
- Yogesh: T06 -> T09 -> T10 -> (T14 after T10 + T13).
- Pranav: T08 -> P0.5 keys + T13 part 1 (LiteLLM wrapper, models list/check) -> T11 -> T13 rest (after T12).
- Aakash: T03 follow-up -> T07 tests-first -> T07 -> T12.
- Path check: T09 (memory/**, extract/facts.py, cli fact/project/skill/episode) vs T07 (retrieve/**, cli search/context) vs T13 (chat/**, cli chat/models): no overlap. extract/facts.py: T08 then T09 (sequenced by the assumption). retrieve/search.py: T07 then T09b.
- Critical path from now: T06 (2) -> T09 (1.5) -> T11 (0.75) -> T12 (1) -> T13 rest (~0.75 with part 1 done early) -> T14 (1.25) -> T15 (3.5) -> T16 (1) = about 11.75 h.

## Rule (16:43)
- Any check that depends on gitignored files (demo/**, vault/, .env, keys) is marked "Pranav verifies this". Agents note "pending Pranav" and still open the PR.

## 16:58 notes
- CHG numbers on main: 0000, 0001, 0002 (x2), 0005, 0006 (T08 skipped 0003/0004). My spaCy-image draft is renumbered to CHG-0007 (IDs must keep increasing). Next free for agents: CHG-0008.
- Demo data quality (PM ran it on the real export, which is local on this Mac): derive -> 5 facts, 1 rule, 962 ms; 2 of the 5 values are noisy (trailing words/clauses). Not blocking; tune the patterns later if time allows.

## 17:26 notes
- CHG-0007 now exists on main (T08 follow-up PR #20): the spaCy model en_core_web_sm is a uv dependency via [tool.uv.sources] (edits backend/pyproject.toml + uv.lock, outside T08's listed paths but team-approved). This supersedes my drafted spaCy-image entry, which is withdrawn. Next free: CHG-0008.
- Plan v6: Yogesh T06 -> T09 -> T10 -> T14. Pranav: P0.5 -> T13 p1 -> T11 p1 -> T11 end -> T09b -> T13 rest. Aakash: T12 tests-first -> T14 tests-first -> T07 -> T12.

## Plan v7 (17:42): Pranav takes T09
- Pranav: T09 now (lazy index_paths until T06) -> T09b (after T07) -> T13 rest (after T12 + T13 part 1).
- Yogesh: T06 -> T13 part 1 -> T11 part 1 -> T11 end (after T09) -> T10 (after T09) -> T14 (after T10 + T13).
- Aakash: T12 tests-first -> T14 tests-first -> T07 (after T06) -> T12 (after T07 + T09 + T11).
- Critical path now runs through T07: T06 (~0.6) -> T07 (2) -> T12 (1) -> T13 rest (0.75) -> T14 (1.25) -> T15 (3.5) -> T16 (1) = ~10.1 h. T09 (1.5, started now) and T11 finish before T07 does.
- Path check: T09 = memory/**, extract/facts.py, cli fact/project/skill/episode; T13 p1 = chat/llm.py, cli/models_cmd.py; T11 = working/**, cli/session_cmd.py; T07 = retrieve/**; tests-first = new test files only. No overlap.

## 19:12 notes
- Merged since 17:42: PR #23 (T12 tests), #24 (T14 tests), #25 (T06), #22 (T09). PR #26 (T07) CLOSED unmerged: ask whether that was deliberate; if not, reopen (critical path).
- PM's scratch Python lacks sqlite3.enable_load_extension, so the index-dependent checks are unverified here (SETUP §7). Pranav verifies them in Docker / uv until PM has a uv Python.
- Latest CHG on main: CHG-0009. Next free: CHG-0010.
- Plan: Aakash T12 (early) -> T15 pages. Yogesh T13 part 1 -> T11 (T09 is in, so part 1 + end together) -> T10 -> T14. Pranav T09b (after T07) -> T13 rest (after T12 + T13 p1).

## 19:48 notes
- Pranav wants a draft frontend early. Decision: REST + SSE is the UI transport (a browser can't run the CLI). CLI parity comes via a <CliHint> showing the equivalent `pam …` command on every page. No dev bridge, no spec change.
- Aakash order: 1) reopen/merge T07 (PR #26 closed unmerged, critical path; minutes), 2) T12 MCP server (critical path, ~1 h), 3) T15 draft (3.5 h). If the frontend must start right away, swap: Pranav takes T12 (he is free after T09; T09b waits on T07 anyway).
- Critical path effect: drafting T15 against mocks now takes most of T15's 3.5 h off the end of the chain, leaving ~0.5 h of real wiring after T14. Remaining path ≈ T07 merge -> T12 1 -> T13 rest 0.75 -> T14 1.25 -> T15 wiring 0.5 -> T16 1 ≈ 4.5–5 h.

## Plan v8 (20:15)
- Pranav: T13 part 1 (0.75) -> T10 (1.5) -> T09b (0.5) -> demo prep. Yogesh: T11 (0.75) -> T13 rest (0.75) -> T14 (1.25). Aakash: finish T15 draft (g) -> CLI-audit bug fixes (B-NN) -> T15 wiring after T14 -> T16 with Pranav.
- Remaining critical path: T11 0.75 -> T13 rest 0.75 -> T14 1.25 -> T15 wiring 0.5 -> T16 1 ≈ 4.25 h (T10 runs alongside and must finish before T14 merges; T13 part 1 alongside T11).
- CLI audit: discrepancies come to the PM as bugs B-NN and are slotted to the module owner on fix/b<NN>-<slug>. Demo-path bugs first.
## Risks (20:15)
- Pranav's Mac (macOS 12, Intel x86_64): `uv sync --frozen` FAILS because onnxruntime 1.31 has no macosx_12 x86 wheel. Native runs need `onnxruntime<1.20` in a scratch venv (PM verified 1.19.2 works); otherwise Docker only. Do not change uv.lock without a CHG.
- Indexing speed on this Mac: 81 chunks in 36.5 s with the real model, so the 65-episode real export (several hundred chunks) may take minutes. For the demo, pre-index before going on stage, or run on a faster machine (Pranav verifies this).
- §10 has two duplicated IDs now: CHG-0002 and CHG-0010. Next free: CHG-0012. A human should append a note.

## Bugs (CLI audit and others)
| ID | Summary | Owner | Branch / PR | State |
|----|---------|-------|-------------|-------|
| B-01 | Empty/whitespace id prefix matched every file (project note/add-episodes, fact show/supersede, episode show, derive --episode); plus a Pydantic warning in test_m07 | Yogesh | fix/empty-id-prefix, PR #30 | PM verified 22:26 (206 targeted tests pass; `project note ""` -> exit 1 "project id must not be empty", no commit). Ready to merge. Touches finished tasks' files only (derive.py, episode/fact/project cmds) |

## 22:26 notes
- Nothing merged since 20:15. Critical path stalled ~2 h: T11 not started (Yogesh did T09b + B-01), T13 part 1 not started (Pranav). Remaining path still ~4.25 h, but it has to start now.
- T15 draft: t15/frontend-draft at 9eba842 (20:52), incl. CHG-0012 and a 'lavender glass' restyle; no PR yet.
- Next free CHG: CHG-0013 (T15 draft took CHG-0012 on its branch).
- .pm/ edits keep getting stashed by branch switches in Pranav's checkout (stash@{0} recovered 22:26). Commit .pm via a docs PR, or keep it out of feature branches.
