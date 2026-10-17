# PM log (append-only)

- 2026-10-17 12:24 PDT · KICKOFF · PM read SPEC.md v1.0.0 (all §0–§11), SETUP.md, TODO.md. Created .pm/team.md, status.md, log.md.
- 2026-10-17 12:24 PDT · STATE · Project root not a git repo; no code; .pm/ existed but empty. CHG-0000 still PROPOSED. Hackathon start/end unknown.
- 2026-10-17 12:24 PDT · FINDING · Legacy prototype at `vault/` (old pre-spec layout: agent/*.md, memory/episodes/ 71 files, imports/conversations.json 8.6 MB real Claude export, 70 convs). Conflicts with §6 (vault created by `pam init`). Recommend moving to `demo/legacy-vault/` before T00. Only a stale `__pycache__/export_manager.cpython-39.pyc` remains of prior code.
- 2026-10-17 12:24 PDT · FINDING · R1 head start: Claude export top-level keys = uuid, name, summary, created_at, updated_at, account, chat_messages; message keys = uuid, text, content, sender, created_at, updated_at, attachments, files, parent_message_uuid. `parent_message_uuid` (branching?) not in M1 spec; R1 should check whether Claude exports contain branches.
- 2026-10-17 12:24 PDT · FINDING · Spec files live in docs/files/, but §5 and the spec header expect SPEC.md + SETUP.md at repo root and research/TODO.md. Asked the team to move them or confirm the current location.
- 2026-10-17 12:24 PDT · FINDING · cli/main.py only in T00/T01 allowed paths -> T01 to implement sub-app auto-discovery. pyproject.toml only in T00 -> all deps up front.
- 2026-10-17 12:24 PDT · PLAN · Critical path T00→T01→T03→T04→{T06∥T08}→T09→T11→T12→T13→T14→T15→T16 = 17.75 h.
- 2026-10-17 12:24 PDT · ASSIGN (proposed, pending CHG-0000 approval + P0.6) · Pranav: P0.0 approval + repo housekeeping, then P0.3/P0.4/R1 fixtures. Yogesh: P0.6 (Win) then T00 -> T01. Aakash: P0.6 (Win) then R5/R6 spike outside repo, then T03 when T01 is done.
- 2026-10-17 12:24 PDT · RISK · macOS 12 Docker support for Pranav unverified. Windows Docker clean-machine testing (T00/T16, R11/R13) assigned to Yogesh/Aakash.
- 2026-10-17 12:30 PDT · DECISION · Project root is now /Users/kalyan/Desktop/claude/PAM/pam/ (official §5 layout); everything outside it is irrelevant. Spec = pam/SPEC.md; TODO = pam/research/TODO.md; SETUP = pam/SETUP.md. docs/files copies not authoritative. .pm/ moved to pam/.pm/.
- 2026-10-17 12:30 PDT · STATE · Main session moved old vault/ -> pam/demo/legacy-vault/ (gitignored). `git init` in pam/, no commits. Minimal pam/.gitignore (vault/, demo/, .env), T00 owns and extends it. PM verified the layout on disk. CHG-0000 still PROPOSED.
- 2026-10-17 12:30 PDT · DONE · P0.6 Docker: user confirms all 3 machines have Docker (Pranav: Docker CLI on macOS 12). macOS Docker risk dropped.
- 2026-10-17 12:30 PDT · SCOPE · Claude conversation branching (parent_message_uuid) is OUT OF SCOPE (user). Removed from the R1/fixtures work.
- 2026-10-17 12:30 PDT · DECISION · User approved the T01 cli/main.py auto-discovery and putting all deps in pyproject.toml in T00.
- 2026-10-17 12:30 PDT · ASSIGN (pending CHG-0000) · Pranav: P0.0 + P0.3/P0.4/R1. Yogesh: T00 -> T01. Aakash: R5/R6 spike -> T03.
