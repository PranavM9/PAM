Synthetic ChatGPT export fixture; no real export or account data is included.

# ChatGPT export fixture

`export.zip` contains a root-level `conversations.json` with six synthetic conversations. It exercises the fields and branch behavior used by the ChatGPT importer in M1.

```
export.zip
└── conversations.json
```

## Fields represented

| Field | Use in fixture |
|---|---|
| `id` | Synthetic conversation identifier. |
| `title` | Conversation title; `null` in conversation 5. |
| `create_time`, `update_time` | Epoch seconds for conversation timestamps. |
| `mapping` | Nodes with `id`, `message`, `parent`, and `children`. |
| `message.author.role` | `user`, `assistant`, or `system`. |
| `message.content.content_type`, `parts` | Text parts and a non-string image part; text parts should be joined while image content becomes an image attachment. |
| `message.create_time` | Epoch seconds; absent on one assistant message. |
| `current_node` | End of the selected branch. Walk parent links and reverse to get the final chronological path. |

The data follows the ChatGPT shape described in SPEC §8 M1. All identifiers and message text are invented; there are no real names, account IDs, emails, or image files.

## Conversations and expected result

| # | Conversation | Expected edge case |
|---|---|---|
| 1 | Immich backup verification | Four-message back-and-forth; assistant reply preserves a fenced shell code block. |
| 2 | Edited prompt branch | Two sibling user branches; the selected `current_node` follows only the edited prompt and its answer. |
| 3 | Regenerated response | Two sibling assistant answers; only the second, selected answer is imported. |
| 4 | Photo library issue | A system message is hidden/skipped; the user message has a synthetic image part that maps to an image attachment. |
| 5 | Untitled multilingual chat | Missing title, Spanish text with emoji, and one assistant message without a timestamp. |
| 6 | Empty conversation | No mapping nodes; skipped and counted. |

Expected: **5 RawConversations imported and 1 empty conversation skipped**. Hidden/system messages are excluded. The ChatGPT ZIP has only `conversations.json` at its root.
