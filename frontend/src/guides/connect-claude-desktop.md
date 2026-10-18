# Connect Claude Desktop (MCP)

PAM exposes your vault as an MCP server, so Claude Desktop (or Cursor) can read your memory and write new facts while you chat.

## 1. Start PAM

```bash
docker compose up -d
```

The backend container is named `pam-backend`.

## 2. Edit the Claude Desktop config

Open the config file:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Add the `pam` server:

```json
{
  "mcpServers": {
    "pam": {
      "command": "docker",
      "args": ["exec", "-i", "pam-backend", "pam", "mcp", "serve", "--transport", "stdio", "--agent", "default"]
    }
  }
}
```

Change `--agent default` to another agent's name to give Claude a narrower scope. Tools that agent may not use are not advertised.

## 3. Restart Claude Desktop

Ask: *"What do you know about me?"* Claude should call `get_context` and answer from your vault.

## Inspect the server manually

```bash
npx @modelcontextprotocol/inspector
```

Then connect to `http://localhost:8000/mcp?agent=default` (streamable HTTP).

## Tools

`get_context`, `search_memory`, `get_episode`, `list_agents` (read) and `add_fact`, `supersede_fact`, `log_episode`, `update_project`, `add_skill`, `update_working_memory` (write). If `get_context` returns conflicting facts, the model is told to ask you which is correct and then call `supersede_fact`.
