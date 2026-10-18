"""Error mapping for the REST API: every failure becomes `{"error": {"code", "message"}}` (SPEC §7.14)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from pam.chat.llm import UnknownModel
from pam.core.errors import PamError, PermissionDenied, VaultBusy

log = logging.getLogger(__name__)

VALIDATION_ERROR = "VALIDATION_ERROR"
PERMISSION_DENIED = "PERMISSION_DENIED"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "CONFLICT"
SESSION_ENDED = "SESSION_ENDED"
INTERNAL_ERROR = "INTERNAL_ERROR"

_STATUS_CODES = {
    400: VALIDATION_ERROR,
    403: PERMISSION_DENIED,
    404: NOT_FOUND,
    405: VALIDATION_ERROR,
    409: CONFLICT,
}


class ApiError(PamError):
    """An error raised by a route that already knows its HTTP status and error code.

    Parameters:
        status: HTTP status code.
        code: Machine-readable error code.
        message: Human-readable message.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def classify(exc: PamError) -> tuple[int, str]:
    """Map a `PamError` to an HTTP status and error code.

    Behavior:
        Classes decide first (`ApiError`, `PermissionDenied`, `VaultBusy`, `UnknownModel`). Other
        `PamError`s are told apart by message, because upstream modules raise plain `PamError`:
        "already ended" is 409 `SESSION_ENDED`, "not found" and "does not exist" are 404,
        "already exists" is 409, and exit code 2 is 400. Anything else is a 500.
    Returns:
        `(status, code)`.
    Parameters:
        exc: The error to classify.
    """
    if isinstance(exc, ApiError):
        return exc.status, exc.code
    if isinstance(exc, PermissionDenied):
        return 403, PERMISSION_DENIED
    if isinstance(exc, VaultBusy):
        return 409, CONFLICT
    if isinstance(exc, UnknownModel):
        return 400, VALIDATION_ERROR
    text = str(exc).lower()
    if "already ended" in text or "has ended" in text:
        return 409, SESSION_ENDED
    if "not found" in text or "does not exist" in text:
        return 404, NOT_FOUND
    if "already exists" in text:
        return 409, CONFLICT
    if exc.exit_code == 2:
        return 400, VALIDATION_ERROR
    return 500, INTERNAL_ERROR


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """Build the standard error response."""
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _validation_message(errors: list[dict]) -> str:
    first = errors[0]
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    text = f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg", "invalid value"))
    return text + (f" (and {len(errors) - 1} more)" if len(errors) > 1 else "")


def install(app: FastAPI) -> None:
    """Register the exception handlers on `app`.

    Behavior:
        Handles `PamError`, request and model validation errors (400), HTTP errors raised by
        Starlette (unknown route 404, wrong method 405) and any other exception (500, with a
        generic message; the details are logged).
    Parameters:
        app: The FastAPI app.
    """

    @app.exception_handler(PamError)
    async def _pam_error(_: Request, exc: PamError) -> JSONResponse:
        status, code = classify(exc)
        return error_response(status, code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(400, VALIDATION_ERROR, _validation_message(exc.errors()))

    @app.exception_handler(ValidationError)
    async def _model_invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return error_response(400, VALIDATION_ERROR, _validation_message(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, INTERNAL_ERROR)
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error in the REST API", exc_info=exc)
        return error_response(500, INTERNAL_ERROR, "internal server error")
