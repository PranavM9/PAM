"""UTC time helpers for contract datetimes.

Behavior:
    Every datetime in a contract is timezone-aware UTC and serializes with a `Z` suffix (§7).
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime.

    Behavior:
        Truncates to whole seconds so vault files stay readable.
    Returns:
        The current UTC time.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601 UTC with a `Z` suffix.

    Behavior:
        Converts to UTC first, e.g. `2026-10-01T18:04:11Z`.
    Exceptions:
        ValueError: `dt` is naive.
    Returns:
        The formatted timestamp.
    Parameters:
        dt: An aware datetime.
    """
    if dt.tzinfo is None:
        raise ValueError("naive datetime; PAM only handles aware UTC datetimes")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
