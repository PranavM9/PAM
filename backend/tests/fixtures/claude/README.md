# Claude export fixture

`export.zip` is an **anonymized 10-conversation sample** of a real Claude.ai data export (exported 2026-10-17). It is the fixture for M1 (`pam import extract`), M2 (`pam import run`), and the M3 acceptance criteria (planted contradiction, repeated rule, 3 topics).

```
export.zip
└── conversations.json     # JSON array of 10 conversations, sorted by created_at
```

The real export ships `conversations.json` alone inside `conversations-000.zip`. This fixture keeps that layout.

## Fields we use

The rows below are what the M1 Claude importer reads. Everything else is present in the file but ignored.

### Conversation (array element)
| Field | Type in export | Maps to (§7.2 `RawConversation`) | Notes |
|---|---|---|---|
| `uuid` | str (UUID) | `source_conversation_id` | unique per export |
| `name` | str | `title` | **can be `""`** (5/70 in the real export, 1/10 here) → `None` → M2 fallback title |
| `summary` | str | `summary` | **always present, never null; `""` when absent** (see below). `""` → `None` |
| `created_at` | str ISO-8601, µs, `Z` | `created_at` | e.g. `2026-08-17T10:58:50.109075Z` |
| `updated_at` | str ISO-8601, µs, `Z` | `updated_at` | drives `--update` re-import |
| `account.uuid` | str (UUID) | `source_metadata.account_uuid` (optional) | replaced with a fake constant here |
| `chat_messages` | list | `messages` | already chronological; treat as a linear list |

### Message (`chat_messages[]`)
| Field | Type | Maps to (`RawMessage`) | Notes |
|---|---|---|---|
| `uuid` | str | `source_metadata` only | |
| `sender` | `"human"` \| `"assistant"` | `role` (`human→user`) | no other values observed |
| `content[]` | list of blocks | `text` (preferred) | join `type=="text"` blocks' `.text` with `\n\n` |
| `text` | str | `text` (fallback) | use only when `content[]` has no text block |
| `created_at` | str ISO-8601 | `created_at` | |
| `updated_at` | str ISO-8601 | — | |
| `attachments[]` | `{file_name, file_size, file_type, extracted_content}` | `AttachmentRef(name=file_name, kind="file", mime_type=file_type)` | `file_type` may be a mime type or a bare extension (`"txt"`) |
| `files[]` | `{file_uuid, file_name}` | `AttachmentRef(name=file_name, kind=image\|file by extension)` | duplicates `attachments` for text files (79/115 real). **Images/PDFs appear only here** (23 jpeg, 4 png, 3 pdf). `file_name` **can be `null`** (2 real cases). Dedupe by name against `attachments`. This fixture has no image-only file. |

### `content[]` block types
| `type` | Use? | Key fields |
|---|---|---|
| `text` | **yes** | `text`, `citations`, `start_timestamp`, `stop_timestamp`, `flags` |
| `thinking` | no (model reasoning, not conversation) | `thinking`, `summaries`, `signature`, … |
| `tool_use` | optional, flatten to a one-liner (`[tool: name]`) | `name`, `input`, `id`, … |
| `tool_result` | optional, flatten or skip | `tool_use_id`, `name`, `content[]`, `is_error`, … |
| `injected_prompt_block` | no (system-injected) | `prompt`, `injection_source` |

### Why prefer `content[]` over `text`
`text` is a flattened legacy field and does **not** equal the joined text blocks for many assistant messages: 312/1737 messages in the real export, all of them assistant messages (25/100 here). It contains:
- the **thinking** text glued onto the front of the answer (230 cases);
- placeholder lines `` ```\nThis block is not supported on your current device yet.\n``` `` where tool calls were (266 cases).

Fallback rule: 25 real messages have non-empty `text` but no `text` block, and 9 have a text block but empty `text`. So use the text blocks when they exist, otherwise use `text`.

## How often `summary` is empty or missing

| | conversations | `summary` key missing | `null` | `""` | populated |
|---|---|---|---|---|---|
| Real export (2026-10-17) | 70 | 0 | 0 | **51 (73%)** | 19 (27%) |
| This fixture | 10 | 0 | 0 | 6 | 4 |

The key is always present and empty means `""`, never `null`. Summaries look like a recent feature. Only 1 of the 51 conversations created before 2026-09-11 has one, while 18 of the 19 created from then on do; the one without is an untitled 2-message chat. Populated summaries are Markdown that starts with `**Conversation Overview**`. The importer must treat `""` (and whitespace-only) as no summary (`has_summary=false`).

## Fixture contents

| # | created_at | name | topic | msgs | summary | notes |
|---|---|---|---|---|---|---|
| 0 | 2026-08-17 | Setting up Tailscale VPN on Ubuntu server | tailscale | 8 | — | **plant: "I study at WSU"**; contains an edit branch (msg 6 repeats msg 4) |
| 1 | 2026-08-17 | Setting up Immich on Ubuntu 26.x | immich | 4 | — | |
| 2 | 2026-08-29 | Backing up Immich photos without metadata | immich | 2 | — | **plant: "no bullet points" #1** |
| 3 | 2026-08-30 | Immich server job queue configuration | immich | 2 | — | attachment + file (`HANDOFF.md`) |
| 4 | 2026-08-31 | Tailscale access over eduroam network | tailscale | 4 | — | **plant: "I go to UW"** |
| 5 | 2026-09-03 | Local LLM gateway setup with Ollama and Tailscale | tailscale | 48 | ✓ | longest; attachments; edit branch (msg 4 repeats msg 0) |
| 6 | 2026-09-05 | *(empty name)* | empty | 2 | — | both messages have `text=""` and `content=[]` → importer must **skip and count** it |
| 7 | 2026-09-14 | F1 visa check-in and service record requirements | university | 2 | ✓ | |
| 8 | 2026-09-15 | Intensive 15-day course prep for UW CS | university | 6 | ✓ | **plant: "no bullet points" #2** (human msg 4) |
| 9 | 2026-09-18 | Finding on-campus winter break jobs | university | 22 | ✓ | heaviest anonymization (names, emails, employer) |

Expected importer output: **9 `RawConversation`s, 1 skipped empty**. The importer drops messages whose text is empty and that have no attachments.

### Planted items (M3 acceptance)
- **Contradiction (school, single slot):** conv 0 (2026-08-17), user msg 0: `I study at WSU, so I'll mostly be reaching it from campus.` → older value `WSU`. Conv 4 (2026-08-31), user msg 0: `I go to UW and they use a network profile called eduroam.` → newer value `UW`.
  - ⚠️ The §8 M3 starter pattern `study_at` matches the WSU line, but **no starter pattern matches "I go to UW"**. T08 needs a pattern like `\bi (?:go to|attend) (?P<v>…)` → `school` (ORG), or the contradiction will never be detected.
  - A real line in conv 8 (`i study at UW cs.`) was rewritten to `i'm in UW cs.` so the two plants are the only `school` evidence.
- **Repeated rule:** `no bullet points` appears in user messages of 2 distinct conversations (conv 2, conv 8). It matches the §M3 rule regex `\bno (?P<v>…bullet points?…)\b`, so `rule_min_evidence=2` is met.
- **3 topics × 3 conversations:** tailscale/remote access (0, 4, 5), Immich photo server (1, 2, 3), university admin/coursework (7, 8, 9).
- Incidental M3 hits, for reference: `job_title` → "international student" (conv 9, several messages).

Plants are written into both `text` and the last `content[]` text block, so both import paths see them.

## Anonymization

- All conversation, message and file UUIDs are remapped (deterministic `uuid5`). `account.uuid` is a fake constant.
- People: the user's name, a supervisor's name, and the local machine username are replaced (`Alex`, `Jordan`, `alex`). Every email address becomes `person@example.edu` or a named `@example.edu` alias.
- Orgs: the user's employer and campus unit names are replaced (`Northside Cafe`, `CDS`). **`UW` / University of Washington is kept on purpose**, because the planted contradiction needs it.
- Network: the tailnet name, Tailscale IP, and public IPs are replaced (`tail0000`, `100.64.0.10`, `203.0.113.x`). Private LAN IPs are left as they are.
- Redacted payloads (keys kept, values replaced): `thinking.thinking`/`summaries`/`signature`, `tool_result.content` (and `structured_content`/`meta`/`display_content` → `null`), and `text.citations` → `[]`. Tool-use inputs and attachment `extracted_content` are scrubbed and truncated.
- **Dropped:** `chat_messages[].parent_message_uuid`. Branching is out of scope (26/70 real conversations are non-linear because of edits/retries; the export lists all branches flattened in time order).
- The build script refuses to write if any known real identifier remains.

Regenerate (the script is kept outside tracked paths because it contains the real-name replacement map):
```
python3 -I demo/fixture_tools/anonymize_claude.py \
    demo/legacy-vault/imports/conversations.json backend/tests/fixtures/claude/export.zip
```
Output is byte-identical across runs.
