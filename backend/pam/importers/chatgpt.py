"""Importer for OpenAI ChatGPT data exports."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pam.contracts.common import Source
from pam.contracts.raw import AttachmentRef, RawConversation, RawMessage
from pam.importers.base import add_error, json_documents, parse_datetime


class ChatGPTImporter:
    source = "chatgpt"

    def detect(self, path: Path) -> float:
        try:
            return 0.9 if any(
                n.lower().endswith("conversations.json") and isinstance(d, list)
                and any(isinstance(row, dict) and "mapping" in row for row in d)
                for n, d in json_documents(path)
            ) else 0.0
        except Exception:
            return 0.0

    def parse(self, path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
        for name, data in json_documents(path):
            if not name.lower().endswith("conversations.json") or not isinstance(data, list):
                continue
            for index, conv in enumerate(data):
                try:
                    if not isinstance(conv, dict):
                        raise ValueError("conversation is not an object")
                    mapping = conv.get("mapping") or {}
                    current = conv.get("current_node")
                    chain: list[dict] = []
                    visited: set[str] = set()
                    while current and current in mapping and current not in visited:
                        visited.add(current)
                        node = mapping[current]
                        if not isinstance(node, dict):
                            break
                        chain.append(node)
                        current = node.get("parent")
                    chain.reverse()
                    messages: list[RawMessage] = []
                    for node in chain:
                        msg = node.get("message")
                        if not isinstance(msg, dict):
                            continue
                        metadata = msg.get("metadata") or {}
                        if (metadata.get("is_hidden") or metadata.get("is_visually_hidden_from_conversation")
                                or metadata.get("message_type") in {"system", "notification", "hidden"}):
                            continue
                        author = msg.get("author") or {}
                        role = author.get("role")
                        if role not in {"user", "assistant"}:
                            continue
                        content = msg.get("content") or {}
                        parts = content.get("parts") or []
                        text = "\n\n".join(str(p) for p in parts if isinstance(p, str))
                        attachments: list[AttachmentRef] = []
                        for part in parts:
                            if isinstance(part, dict) and (
                                str(part.get("content_type", "")).startswith("image")
                                or any(k in part for k in ("image", "image_url", "asset_pointer"))
                            ):
                                attachments.append(AttachmentRef(name="image", kind="image"))
                        raw_message = RawMessage(role=role, text=text,
                            created_at=parse_datetime(msg.get("create_time"), epoch=True), attachments=attachments)
                        if raw_message.text.strip() or raw_message.attachments:
                            messages.append(raw_message)
                    if not messages:
                        add_error(errors, f"{name}[{index}]: empty conversation skipped")
                        continue
                    created = parse_datetime(conv.get("create_time"), epoch=True)
                    updated = parse_datetime(conv.get("update_time"), epoch=True)
                    yield RawConversation(source=Source.CHATGPT,
                        source_conversation_id=str(conv.get("id") or ""), title=conv.get("title") or None,
                        created_at=created, updated_at=updated, messages=messages)
                except Exception as exc:
                    add_error(errors, f"{name}[{index}]: {exc}")


def parse(path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
    return ChatGPTImporter().parse(path, errors)
