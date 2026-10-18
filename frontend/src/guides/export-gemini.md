# Export your Gemini activity

Gemini conversations are exported through **Google Takeout**. Gemini support in PAM is best-effort: Takeout's format is less structured than Claude's or ChatGPT's.

> Menu paths change from time to time. If a step looks different, search Takeout for **Gemini**.

## Steps

1. Open [takeout.google.com](https://takeout.google.com) and sign in.
2. Click **Deselect all**, then select only **Gemini Apps** activity data (in some accounts it is listed under **My Activity → Gemini Apps**).
3. Choose a `.zip` export and create it. Google emails you when it is ready.
4. Download the archive. It holds the Gemini activity as JSON or HTML.

## Import it

- **In the app:** pick **Gemini** on the Import page and drop the zip.
- **From the CLI:** put the file in `./demo/` and run

  ```bash
  pam import run /demo/gemini-takeout.zip --source gemini --all
  ```

## Good to know

- Takeout may not include stable conversation IDs, so PAM groups activity into conversations by time gaps.
- If the import finds nothing, use Gemini as an MCP client instead: it can still read and write the same vault.
