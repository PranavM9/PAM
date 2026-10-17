Synthetic Gemini Takeout fixture; no real export or account data is included.

# Gemini Takeout fixture

`export.zip` contains ten synthetic Google My Activity exchange records in the Gemini Apps Takeout path. `MyActivity.json` is also provided as a loose byte-for-byte copy for direct JSON importer use.

```
export.zip
└── Takeout/
    └── My Activity/
        └── Gemini Apps/
            └── MyActivity.json
MyActivity.json
```

## Fields represented

| Field | Use in fixture |
|---|---|
| `header`, `title`, `products` | Standard activity metadata; title is the generic `Used Gemini Apps`. |
| `titleUrl` | Synthetic conversation URL, useful metadata for each activity. |
| `time` | ISO 8601 UTC timestamp. Entries are newest first; adjacent activity gaps are 29 or 31 minutes. |
| `details[]` | Named `Request`/`Response` key-value pairs; a missing `Response` represents a prompt with no reply. |

This uses the Takeout `details` array shape (`name` and `value`) and the expected `Takeout/My Activity/Gemini Apps/MyActivity.json` layout. Prompt text is invented; all thread IDs are synthetic, with no real names, account IDs, emails, or image files.

## Grouping and expected result

The ten activities, listed newest first, fall into groups of **4, 3, and 3 prompts** when a gap greater than 30 minutes starts a new conversation. Each within-group gap is 29 minutes; the two group boundaries are 31 minutes. The records contain eight responses and two prompts without replies.

Expected: **3 RawConversations, 18 messages total** (10 user prompts and 8 assistant replies). One assistant reply contains a fenced HTML code block. The newest four-prompt conversation contains the two prompt-only records.
