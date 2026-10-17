"""Read and write Markdown files with YAML frontmatter.

Behavior:
    The file grammar is `---\\n<yaml>---\\n<body>`. The body is everything after the closing `---`
    line and is returned byte-for-byte, because episode bodies are hashed into `body_sha256`.
    python-frontmatter strips the body, so this module splits the file itself. Writes are atomic
    (temp file plus `os.replace`), UTF-8, with LF line endings.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from pam.contracts.common import SCHEMA_VERSION
from pam.core.errors import PamError, SchemaVersionError

M = TypeVar("M", bound=BaseModel)

_DELIM = "---\n"


def split(text: str) -> tuple[dict, str]:
    """Split file text into frontmatter and body.

    Behavior:
        Converts CRLF to LF first. Text that does not start with `---` has no frontmatter.
    Exceptions:
        PamError: The frontmatter is unterminated or is not a mapping.
        yaml.YAMLError: The frontmatter is not valid YAML.
    Returns:
        The frontmatter mapping (empty if absent) and the exact body.
    Parameters:
        text: Full file contents.
    """
    text = text.replace("\r\n", "\n")
    if not text.startswith(_DELIM):
        return {}, text
    end = text.find("\n" + _DELIM, len(_DELIM) - 1)
    if end == -1:
        raise PamError("unterminated frontmatter (missing closing '---')")
    raw = text[len(_DELIM) : end + 1]
    body = text[end + 1 + len(_DELIM) :]
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise PamError("frontmatter is not a mapping")
    return data, body


def dumps(frontmatter: BaseModel, body: str) -> str:
    """Render a model and body as file text.

    Behavior:
        Dumps the model in JSON mode (UUIDs and `Z` datetimes as strings) with keys in field order.
    Returns:
        The file text.
    Parameters:
        frontmatter: Model to place in the frontmatter.
        body: Body text, appended unchanged.
    """
    data = frontmatter.model_dump(mode="json")
    fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return _DELIM + fm + _DELIM + body


def read(path: str | os.PathLike) -> tuple[dict, str]:
    """Read a Markdown file with optional frontmatter.

    Exceptions:
        OSError: The file cannot be read.
        PamError: The frontmatter is malformed.
    Returns:
        The frontmatter mapping and the exact body.
    Parameters:
        path: File to read.
    """
    return split(Path(path).read_text(encoding="utf-8"))


def write(path: str | os.PathLike, frontmatter: BaseModel, body: str) -> None:
    """Atomically write a model and body as a Markdown file.

    Behavior:
        Creates parent folders as needed.
    Exceptions:
        OSError: The file cannot be written.
    Parameters:
        path: Destination file.
        frontmatter: Model to place in the frontmatter.
        body: Body text.
    """
    write_text(path, dumps(frontmatter, body))


def check_schema_version(version: str | None) -> None:
    """Check that a stored `schema_version` has a major version this build reads.

    Behavior:
        Unknown minor versions are accepted; a missing version is accepted (§7 global promises).
    Exceptions:
        SchemaVersionError: The major version differs from `SCHEMA_VERSION`.
    Parameters:
        version: The stored version string, or `None`.
    """
    if version is None:
        return
    major = str(version).split(".", 1)[0]
    if major != SCHEMA_VERSION.split(".", 1)[0]:
        raise SchemaVersionError(f"unsupported schema_version {version!r} (this build reads {SCHEMA_VERSION})")


def read_model(path: str | os.PathLike, cls: type[M]) -> tuple[M, str]:
    """Read a Markdown file and validate its frontmatter as a contract model.

    Exceptions:
        OSError: The file cannot be read.
        PamError: The frontmatter is malformed.
        SchemaVersionError: The major `schema_version` is unknown.
        pydantic.ValidationError: The frontmatter does not match `cls`.
    Returns:
        The validated model and the exact body.
    Parameters:
        path: File to read.
        cls: Contract model class.
    """
    data, body = read(path)
    check_schema_version(data.get("schema_version"))
    return cls.model_validate(data), body


def write_text(path: str | os.PathLike, text: str) -> None:
    """Atomically write UTF-8 text with LF line endings.

    Behavior:
        Creates parent folders, writes a temp file in the same folder, then replaces the target.
        The temp file is removed if the write fails.
    Exceptions:
        OSError: The file cannot be written.
    Parameters:
        path: Destination file.
        text: Text to write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\r\n", "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
