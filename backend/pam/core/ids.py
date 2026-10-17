"""ID and hash helpers.

Behavior:
    Deterministic UUIDv5 IDs live with their contracts (`episode_id`, `fact_id`); this module holds
    the generic helpers.
"""

import hashlib
from uuid import UUID, uuid4


def sha256_text(text: str) -> str:
    """Hash text with SHA-256.

    Behavior:
        Hashes the UTF-8 encoding, as `EpisodeFrontmatter.body_sha256` requires.
    Returns:
        The lowercase hex digest.
    Parameters:
        text: Text to hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_uuid() -> UUID:
    """Create a random UUID for objects without a natural key, such as projects and skills.

    Returns:
        A new UUIDv4.
    """
    return uuid4()
