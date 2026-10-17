"""Render a `RawConversation` as an episode frontmatter and body (SPEC §7.3, §8 M2)."""

from __future__ import annotations

from datetime import datetime

from pam.contracts.common import Slug
from pam.contracts.episode import EpisodeFrontmatter, episode_id
from pam.contracts.raw import RawConversation, RawMessage
from pam.core.ids import sha256_text
from pam.core.time import iso_z

UNKNOWN_TIME = "unknown"
ROLE_SEPARATOR = "·"


def _title(raw: RawConversation, created_at: datetime) -> str:
    collapsed = " ".join((raw.title or "").split())
    return collapsed or f"Untitled conversation {created_at.date().isoformat()}"


def _message_block(message: RawMessage) -> str:
    when = iso_z(message.created_at) if message.created_at else UNKNOWN_TIME
    lines = [f"### {message.role} {ROLE_SEPARATOR} {when}"]
    if message.text:
        lines.append(message.text)
    lines.extend(f"[attachment: {a.name} ({a.kind})]" for a in message.attachments)
    return "\n".join(lines)


def render_body(raw: RawConversation, title: str) -> str:
    """Render the episode body with the exact §7.3 grammar.

    Behavior:
        Emits `# <title>`, a `## Summary` section only for a non-empty summary, then `## Transcript`
        with one `### <role> · <ISO Z time or unknown>` block per message. Message text is verbatim
        except that CRLF becomes LF, because `mdio` stores LF and the hash must match the file.
        Attachments follow the text as `[attachment: name (kind)]` lines.
    Returns:
        The body text, ending with one newline.
    Parameters:
        raw: The conversation to render.
        title: The already-normalized title.
    """
    parts = [f"# {title}"]
    if raw.summary and raw.summary.strip():
        parts.append(f"## Summary\n{raw.summary}")
    transcript = "## Transcript"
    if raw.messages:
        transcript += "\n\n" + "\n\n".join(_message_block(m) for m in raw.messages)
    parts.append(transcript)
    return "\n\n".join(parts).replace("\r\n", "\n") + "\n"


def render(
    raw: RawConversation, imported_at: datetime, agent: Slug = "default"
) -> tuple[EpisodeFrontmatter, str]:
    """Convert one raw conversation into episode frontmatter and body.

    Behavior:
        The title collapses all whitespace runs, including newlines, and falls back to
        `Untitled conversation YYYY-MM-DD`. `created_at` falls back to the first message time, then
        `imported_at`. `updated_at` falls back to the last message time, then `created_at`.
        `has_summary` is true only for a non-empty summary. `body_sha256` hashes the UTF-8 body.
    Returns:
        The validated frontmatter and the body.
    Parameters:
        raw: The conversation to render.
        imported_at: Time of the import run.
        agent: Agent scope that owns the episode.
    """
    times = [m.created_at for m in raw.messages if m.created_at]
    created_at = raw.created_at or (times[0] if times else imported_at)
    updated_at = raw.updated_at or (times[-1] if times else created_at)
    title = _title(raw, created_at)
    body = render_body(raw, title)
    frontmatter = EpisodeFrontmatter(
        id=episode_id(raw.source, raw.source_conversation_id),
        agent=agent,
        source=raw.source,
        source_conversation_id=raw.source_conversation_id,
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        imported_at=imported_at,
        message_count=len(raw.messages),
        has_summary=bool(raw.summary and raw.summary.strip()),
        body_sha256=sha256_text(body),
    )
    return frontmatter, body
