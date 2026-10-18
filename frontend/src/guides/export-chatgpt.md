# Export your ChatGPT conversations

PAM reads ChatGPT's official data export and turns each conversation into a Markdown episode in your vault.

> Menu paths change from time to time. If a step looks different, look for **Export data** under the data settings.

## Steps

1. Open [chatgpt.com](https://chatgpt.com) and sign in.
2. Go to **Settings → Data controls → Export data**.
3. Confirm the export. OpenAI emails you a download link; large accounts can take a while.
4. Download the `.zip`. It contains `conversations.json` (and a `chat.html` viewer PAM does not need).

## Import it

- **In the app:** pick **ChatGPT** on the Import page and drop the zip.
- **From the CLI:** put the file in `./demo/` and run

  ```bash
  pam import run /demo/chatgpt-export.zip --all
  ```

## Good to know

- ChatGPT stores each conversation as a tree (edits and regenerations create branches). PAM keeps the thread you actually see: the path ending at the last message.
- System and hidden messages are skipped.
- The original zip is archived under `imports/chatgpt/<timestamp>/`, and re-imports skip conversations that already exist.
