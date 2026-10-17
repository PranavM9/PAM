"""Shared PAM exceptions with CLI exit codes.

Behavior:
    Every PAM error carries an `exit_code` that follows SETUP §5: `1` error, `2` validation error,
    `3` permission denied, `4` vault busy. The CLI maps a raised `PamError` to that exit code.
"""


class PamError(Exception):
    """Base class for expected PAM failures.

    Behavior:
        Uses the class-level `exit_code` unless one is passed explicitly.
    Parameters:
        message: Human-readable error message.
        exit_code: Overrides the class default exit code.
    """

    exit_code = 1

    def __init__(self, message: str, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class VaultNotFound(PamError):
    """No vault path was given, or the path is not an initialized vault."""


class SchemaVersionError(PamError):
    """A file carries a `schema_version` whose major version this build does not read."""

    exit_code = 2


class PermissionDenied(PamError):
    """An agent tried to read or write outside its manifest (§7.7; MCP code `PERMISSION_DENIED`)."""

    exit_code = 3


class VaultBusy(PamError):
    """The vault write lock is held by another writer."""

    exit_code = 4
