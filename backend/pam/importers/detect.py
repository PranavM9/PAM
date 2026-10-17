"""Select and run the provider importer for an export."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pam.contracts.common import Source
from pam.contracts.raw import RawConversation
from pam.core.errors import PamError
from pam.importers.base import Importer
from pam.importers.chatgpt import ChatGPTImporter
from pam.importers.claude import ClaudeImporter
from pam.importers.gemini import GeminiImporter

IMPORTERS: tuple[Importer, ...] = (ClaudeImporter(), ChatGPTImporter(), GeminiImporter())


def detect(path: Path) -> Importer:
    """Return the importer with the highest positive confidence score."""
    scores = [(imp.detect(path), imp) for imp in IMPORTERS]
    score, importer = max(scores, key=lambda item: item[0])
    if score <= 0:
        raise PamError(f"could not detect export source for {path}")
    return importer


def extract(path: Path, source: str = "auto") -> tuple[Iterator[RawConversation], list[str], str]:
    """Return the conversation iterator, parse warnings, and selected source."""
    if not path.is_file():
        raise PamError(f"import file not found: {path}")
    if source == "auto":
        importer = detect(path)
    else:
        importer = next((imp for imp in IMPORTERS if imp.source == source), None)
        if importer is None:
            raise PamError(f"unsupported import source: {source}")
    errors: list[str] = []
    return importer.parse(path, errors), errors, importer.source
