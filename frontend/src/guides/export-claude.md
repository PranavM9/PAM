# Export your Claude conversations

PAM reads Claude's official data export. Nothing is uploaded anywhere: the file goes to your own PAM backend and is archived in the vault as-is.

> Menu paths change from time to time. If a step looks different, look for **Export data** under the privacy settings.

## Steps

1. Open [claude.ai](https://claude.ai) and sign in.
2. Go to **Settings → Privacy → Export data**.
3. Confirm the export. Claude emails you a download link, usually within a minute.
4. Open the link and download every file it offers. The links expire after 24 hours.
5. The file PAM needs is the **conversations** zip (`conversations-000.zip`, or a single `.zip` containing `conversations.json`).

## Import it

- **In the app:** pick **Claude** on the Import page and drop the zip.
- **From the CLI:** put the file in `./demo/` and run

  ```bash
  pam import run /demo/claude-export.zip --all
  ```

  `--all` runs import → derive → index → cluster in one go.

## What PAM keeps

- One Markdown episode per conversation, under `memory/default/episodes/`.
- The provider summary (when Claude has one) plus the full verbatim transcript.
- The original zip, byte for byte, under `imports/claude/<timestamp>/`.

Re-importing the same export is safe: conversations that already exist are skipped.
