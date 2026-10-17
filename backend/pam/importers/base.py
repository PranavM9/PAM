"""Shared importer types and helpers for provider exports."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Protocol
import zipfile

from dateutil.parser import isoparse

from pam.contracts.raw import RawConversation


class Importer(Protocol):
    """A provider importer that detects and parses an export."""

    source: str

    def detect(self, path: Path) -> float: ...

    def parse(self, path: Path, errors: list[str] | None = None) -> Iterator[RawConversation]: ...


def json_documents(path: Path) -> Iterator[tuple[str, object]]:
    """Yield JSON documents from a JSON file or every JSON member in a ZIP."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".json") and not name.endswith("/"):
                    try:
                        yield name, json.loads(archive.read(name).decode("utf-8", errors="replace"))
                    except (json.JSONDecodeError, UnicodeError) as exc:
                        raise ValueError(f"{name}: invalid JSON: {exc}") from exc
    else:
        try:
            yield path.name, json.loads(path.read_bytes().decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"{path}: cannot read JSON: {exc}") from exc


def parse_datetime(value: object, *, epoch: bool = False) -> datetime | None:
    """Parse ISO timestamps or provider epoch seconds as aware UTC datetimes."""
    if value is None or value == "":
        return None
    try:
        if epoch:
            return datetime.fromtimestamp(float(value), tz=UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=UTC)
        result = isoparse(str(value))
        return result.replace(tzinfo=UTC) if result.tzinfo is None else result
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def add_error(errors: list[str] | None, message: str) -> None:
    if errors is not None:
        errors.append(message)


def text_is_empty(conversation: RawConversation) -> bool:
    return not any(m.text.strip() or m.attachments for m in conversation.messages)

