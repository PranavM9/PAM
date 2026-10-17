Synthetic Gemini Takeout fixture; no real export or account data is included.

# Gemini export fixture

`export.zip` contains ten synthetic Google My Activity records in the Gemini Apps Takeout path using the `Prompted …` title layout. `MyActivity.json` is the loose primary-layout copy. `MyActivity.details.json` preserves the previous named `details[]` layout as a separate compatibility variant.

```
export.zip
└── Takeout/
    └── My Activity/
        └── Gemini Apps/
            └── MyActivity.json
MyActivity.json
MyActivity.details.json
```

## Fields represented

| Field | Use in fixture |
|---|---|
| `header`, `products` | Standard activity metadata. |
| `title` | Primary layout stores the request as `Prompted "<request>"`; the compatibility layout uses the generic `Used Gemini Apps` title. |
| `titleUrl` | Synthetic conversation URL useful as activity metadata. |
| `time` | ISO 8601 UTC timestamp. Entries are newest first; adjacent activity gaps are 29 or 31 minutes. |
| `details[]` | Primary layout carries the optional named `Response` field; the compatibility variant uses named `Request` and `Response` fields. Missing `Response` means the prompt has no reply. |

The primary layout uses only the Takeout title field for request text. All prompts and thread IDs are synthetic, with no real names, account IDs, emails, or image files.

## Grouping and expected result

The ten activities, listed newest first, fall into groups of **4, 3, and 3 prompts** when a gap greater than 30 minutes starts a new conversation. Every within-group gap is 29 minutes; both group boundaries are 31 minutes. The records contain eight responses and two prompts without replies.

| Conversation (oldest first) | Prompt count | Imported message count | Raw conversation ID |
|---|---:|---:|---|
| Lentil meal plan | 3 | 6 | `726a26fcb2066952cf112bb687a4979a3706dd67` |
| Reverse proxy | 3 | 6 | `9baccb2b5a5912800fd2ab4de43617cafc149221` |
| Rainy hike packing | 4 | 6 | `149dbdfbcdcb37c5c23fcc7a4105803485a7239d` |

Expected for either layout: **3 RawConversations, 18 messages total** (10 user prompts and 8 assistant replies). One assistant reply contains a fenced HTML code block. The newest four-prompt conversation contains the two prompt-only records.
