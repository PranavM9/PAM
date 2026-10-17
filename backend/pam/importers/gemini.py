"""Best-effort importer for Google Takeout Gemini Apps activity exports."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from hashlib import sha1
from pathlib import Path

from pam.contracts.common import Source
from pam.contracts.raw import RawConversation, RawMessage
from pam.importers.base import add_error, json_documents, parse_datetime


def _details(entry: dict) -> dict[str, str]:
    details = entry.get("details") or []
    if isinstance(details, dict):
        return {str(k).lower(): str(v) for k, v in details.items()}
    return {str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in details if isinstance(item, dict)}


def _value(details: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        for key, value in details.items():
            if label in key and value.strip():
                return value.strip()
    return None


def _prompt_from_title(title: str) -> str | None:
    if not title.lower().startswith("prompted "):
        return None
    value = title[len("Prompted "):].strip()
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, str):
                return decoded.strip() or None
        except json.JSONDecodeError:
            pass
    return value.strip('"').strip() or None


class GeminiImporter:
    source = "gemini"

    def detect(self, path: Path) -> float:
        try:
            for name, data in json_documents(path):
                lname = name.lower()
                if "myactivity" in lname and isinstance(data, list):
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        title = str(row.get("title") or "").lower()
                        details = _details(row)
                        if title.startswith("prompted ") or _value(details, "request", "prompt"):
                            return 0.85
        except Exception:
            pass
        return 0.0

    def parse(self, path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
        entries: list[tuple] = []
        for name, data in json_documents(path):
            if "myactivity" not in name.lower() or not isinstance(data, list):
                continue
            for index, entry in enumerate(data):
                try:
                    if not isinstance(entry, dict):
                        raise ValueError("activity is not an object")
                    details = _details(entry)
                    prompt = _value(details, "request", "prompt")
                    response = _value(details, "response")
                    # The Takeout title commonly carries "Prompted ..." when details are absent.
                    title = str(entry.get("title") or "")
                    if not prompt:
                        prompt = _prompt_from_title(title)
                    stamp = parse_datetime(entry.get("time")) or parse_datetime(entry.get("timestamp"))
                    if not prompt:
                        continue
                    entries.append((stamp, prompt, response, name, index))
                except Exception as exc:
                    add_error(errors, f"{name}[{index}]: {exc}")
        entries.sort(key=lambda row: row[0] or parse_datetime("1970-01-01T00:00:00Z"))
        groups: list[list[tuple]] = []
        for item in entries:
            if not groups or (item[0] and groups[-1][-1][0] and item[0] - groups[-1][-1][0] > timedelta(minutes=30)):
                groups.append([item])
            else:
                groups[-1].append(item)
        for group in groups:
            messages: list[RawMessage] = []
            for stamp, prompt, response, _, _ in group:
                messages.append(RawMessage(role="user", text=prompt, created_at=stamp))
                if response:
                    messages.append(RawMessage(role="assistant", text=response, created_at=stamp))
            first_stamp = group[0][0].isoformat() if group[0][0] else ""
            first_prompt = group[0][1]
            conv_id = sha1(f"{first_stamp}{first_prompt}".encode("utf-8")).hexdigest()
            yield RawConversation(source=Source.GEMINI, source_conversation_id=conv_id,
                title=first_prompt[:120], created_at=group[0][0], updated_at=group[-1][0], messages=messages)


def parse(path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]:
    return GeminiImporter().parse(path, errors)
