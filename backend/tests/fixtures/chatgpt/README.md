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
| `message.id`, `message.author.role` | Unique node-matching message IDs; `user`, `assistant`, or hidden `system`. |
| `message.content.content_type`, `parts` | Text parts and a non-string image part; text parts should be joined while image content becomes an image attachment. |
| `message.create_time` | Epoch seconds; absent on one assistant message. |
| `current_node` | End of the selected branch. Walk parent links and reverse to get the final chronological path. |
| Root nodes | Each mapping has an explicit null-message root whose ID is the parent of its top-level nodes. |

The data follows the ChatGPT shape described in SPEC §8 M1. All identifiers and message text are invented; there are no real names, account IDs, emails, or image files.

## Conversations and expected result

| # | Conversation | Expected edge case |
|---|---|---|
| 1 | Immich backup verification | ID `00000000-0000-4000-8000-000000000001`; 4 imported messages; fenced shell code. |
| 2 | Edited prompt branch | ID `00000000-0000-4000-8000-000000000002`; 3 imported messages; only edited branch selected. |
| 3 | Regenerated response | ID `00000000-0000-4000-8000-000000000003`; 2 imported messages; only selected regenerated answer imported. |
| 4 | Photo library issue | ID `00000000-0000-4000-8000-000000000004`; 2 imported messages; hidden system message omitted and image attached. |
| 5 | Untitled multilingual chat | ID `00000000-0000-4000-8000-000000000005`; 3 imported messages; Spanish text and missing timestamp. |
| 6 | Empty conversation | ID `00000000-0000-4000-8000-000000000006`; 0 imported messages; skipped and counted. |

Expected: **5 RawConversations, 14 imported messages, and 1 empty conversation skipped**. Hidden/system messages are excluded. The ChatGPT ZIP has only `conversations.json` at its root.
