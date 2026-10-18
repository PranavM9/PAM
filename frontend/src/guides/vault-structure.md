# Vault structure

The vault is the source of truth: readable Markdown files plus the original imports. The `.pam` folder holds rebuildable indexes.

## Folders

| Folder | What it contains |
| --- | --- |
| `agent/<name>/` | Agent configuration and identity, rules, and style notes. |
| `imports/<source>/<timestamp>/` | Original provider exports, kept unchanged. |
| `memory/shared/facts/` | Facts visible across agents when their scope allows it. |
| `memory/<agent>/episodes/` | One Markdown file for each conversation. |
| `memory/<agent>/facts/` | Facts that belong to one agent. |
| `memory/<agent>/projects/` | Project notes and links to related episodes. |
| `skills/<agent>/` | Reusable instructions an agent can recall. |
| `working/` | Short lived context for active chat sessions. |
| `.pam/` | Search indexes and other generated data; safe to rebuild. |

## Finding things

Use the Vault page's filter to search paths. Open a project to see its episode links, or use Graph to follow project and similarity connections. Search results and graph nodes link back to their source files.

The selected agent controls which files appear. If a folder is missing, the current agent may not have access to it, or it may not contain any files yet.
