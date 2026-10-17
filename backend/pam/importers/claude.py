"""Importer for Anthropic Claude data exports."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pam.contracts.common import Source
from pam.contracts.raw import AttachmentRef, RawConversation, RawMessage
from pam.importers.base import add_error, json_documents, parse_datetime, text_is_empty


class ClaudeImporter:
    source = "claude"

    def detect(self, path: Path) -> float:
        try:
            for name, data in json_documents(path):
                if (name.lower().endswith("conversations.json") and isinstance(data, list)
                        and any(isinstance(row, dict) and "chat_messages" in row for row in data)):
                    return 0.95
        except Exception:
            return 0.0
        return 0.0

    def parse(self, path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
        for name, data in json_documents(path):
            if not name.lower().endswith("conversations.json") or not isinstance(data, list):
                continue
            for index, conv in enumerate(data):
                try:
                    if not isinstance(conv, dict):
                        raise ValueError("conversation is not an object")
                    messages: list[RawMessage] = []
                    for msg in conv.get("chat_messages", []) or []:
                        if not isinstance(msg, dict):
                            continue
                        sender = msg.get("sender")
                        role = {"human": "user", "assistant": "assistant"}.get(sender)
                        if role is None:
                            continue
                        blocks = msg.get("content") or []
                        text_blocks = [str(b.get("text", "")) for b in blocks
                                       if isinstance(b, dict) and b.get("type") == "text"]
                        text = "\n\n".join(x for x in text_blocks if x) if text_blocks else str(msg.get("text") or "")
                        attachments: list[AttachmentRef] = []
                        seen: set[str] = set()
                        for item in msg.get("attachments", []) or []:
                            if isinstance(item, dict) and item.get("file_name"):
                                filename = str(item["file_name"])
                                mime = item.get("file_type")
                                attachments.append(AttachmentRef(name=filename, kind="file", mime_type=mime))
                                seen.add(filename)
                        for item in msg.get("files", []) or []:
                            if isinstance(item, dict) and item.get("file_name"):
                                filename = str(item["file_name"])
                                if filename not in seen:
                                    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                                    kind = "image" if suffix in {"png", "jpg", "jpeg", "gif", "webp", "heic"} else "file"
                                    attachments.append(AttachmentRef(name=filename, kind=kind))
                                    seen.add(filename)
                        message = RawMessage(role=role, text=text, created_at=parse_datetime(msg.get("created_at")), attachments=attachments)
                        if message.text.strip() or message.attachments:
                            messages.append(message)
                    if not messages:
                        add_error(errors, f"{name}[{index}]: empty conversation skipped")
                        continue
                    result = RawConversation(source=Source.CLAUDE, source_conversation_id=str(conv.get("uuid") or ""),
                        title=conv.get("name") or None, created_at=parse_datetime(conv.get("created_at")),
                        updated_at=parse_datetime(conv.get("updated_at")), summary=conv.get("summary") or None,
                        messages=messages)
                    if not text_is_empty(result):
                        yield result
                except Exception as exc:
                    add_error(errors, f"{name}[{index}]: {exc}")


def parse(path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
    return ClaudeImporter().parse(path, errors)
