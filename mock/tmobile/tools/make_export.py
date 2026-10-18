"""Build Maya's synthetic Claude export, `demo-export/claude-export.zip` (SPEC M17).

Usage: `python tools/make_export.py [--out FILE]`.
Standard library only. The zip holds one `conversations.json` in the Claude export layout that
PAM's M1 importer reads (see `backend/tests/fixtures/claude/README.md`); a re-run is byte-identical.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "demo-export" / "conversations.json"
DEFAULT_OUT = ROOT / "demo-export" / "claude-export.zip"
NAMESPACE = uuid5(NAMESPACE_URL, "https://pam.local/mock/tmobile/demo-export")
ACCOUNT = "00000000-0000-4000-8000-0000000000bb"
MESSAGE_GAP = timedelta(seconds=40)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def to_claude(conversations: list[dict]) -> list[dict]:
    """Expand the simple source format into Claude export conversations.

    Behavior:
        Ids are `uuid5` values derived from the conversation and message positions. Messages are
        40 seconds apart from the conversation's `created_at`. Each message carries both `text`
        and one `text` content block, as real exports do.
    Returns:
        The export rows, sorted by `created_at`.
    Parameters:
        conversations: Source rows `{"title", "created_at", "messages": [{"role", "text"}]}`.
    """
    rows = []
    for i, conv in enumerate(sorted(conversations, key=lambda c: c["created_at"])):
        start = datetime.strptime(conv["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        messages = []
        for j, msg in enumerate(conv["messages"]):
            at = _stamp(start + MESSAGE_GAP * j)
            messages.append({
                "uuid": str(uuid5(NAMESPACE, f"conversation/{i}/message/{j}")),
                "text": msg["text"],
                "content": [{"start_timestamp": at, "stop_timestamp": at, "flags": None, "type": "text",
                             "text": msg["text"], "citations": []}],
                "sender": "human" if msg["role"] == "user" else "assistant",
                "created_at": at,
                "updated_at": at,
                "attachments": [],
                "files": [],
            })
        rows.append({
            "uuid": str(uuid5(NAMESPACE, f"conversation/{i}")),
            "name": conv["title"],
            "summary": conv.get("summary", ""),
            "created_at": _stamp(start),
            "updated_at": messages[-1]["updated_at"] if messages else _stamp(start),
            "account": {"uuid": ACCOUNT},
            "chat_messages": messages,
        })
    return rows


def build(out: Path, source: Path = SOURCE) -> Path:
    """Write the zip with a fixed timestamp so the bytes never change.

    Exceptions:
        OSError: The source cannot be read or the zip cannot be written.
        json.JSONDecodeError: The source is not valid JSON.
    Returns:
        The zip path.
    Parameters:
        out: Destination zip.
        source: Source `conversations.json`.
    """
    rows = to_claude(json.loads(source.read_text(encoding="utf-8")))
    payload = json.dumps(rows, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo("conversations.json", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(info, payload)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output zip (default: demo-export/claude-export.zip).")
    args = parser.parse_args(argv)
    path = build(args.out)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
