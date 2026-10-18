"""FastAPI app for the synthetic T-Mobile mock (SPEC M17): 7 tools, `/health` and `/images`."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import date

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine import addons, catalog, household, upgrade
from engine.common import ROOT, NotFound, load_catalog

DEFAULT_TODAY = "2026-10-18"
DEFAULT_PUBLIC_BASE = "/connectors/tmobile"


def _json(body: dict, status: int = 200) -> Response:
    """Serialize with a fixed layout so identical requests return identical bytes."""
    text = json.dumps(body, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return Response(text, status_code=status, media_type="application/json")


def _number(params: dict, name: str) -> float | None:
    value = params.get(name)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None


def _integer(params: dict, name: str, default: int) -> int:
    value = _number(params, name)
    if value is None:
        return default
    if value != int(value):
        raise ValueError(f"{name} must be a whole number")
    return int(value)


def _flag(params: dict, name: str) -> bool:
    value = params.get(name)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("", "false", "0", "no"):
        return False
    if text in ("true", "1", "yes"):
        return True
    raise ValueError(f"{name} must be true or false")


def _text(params: dict, name: str, required: bool = False) -> str | None:
    value = params.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{name} is required")
        return None
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value).strip()


def create_app(today: str | None = None, public_base: str | None = None) -> FastAPI:
    """Build the mock app.

    Behavior:
        `today` defaults to `MOCK_TODAY` (else 2026-10-18) and fixes "now" for every engine.
        `public_base` defaults to `PUBLIC_BASE` (else `/connectors/tmobile`) and prefixes image URLs.
        Every tool answers `{"synthetic", "as_of", "data", "reasons", "pam_cards"}`. GET tools read
        the query string; POST tools read a JSON object body, with query parameters as a fallback.
        Unknown ids answer 404 and bad arguments 400, as `{"synthetic", "as_of", "error": {"code",
        "message"}}`.
    Returns:
        The FastAPI application.
    Parameters:
        today: ISO date used as "now".
        public_base: Browser-visible prefix for `/images/...`.
    """
    as_of = today or os.environ.get("MOCK_TODAY") or DEFAULT_TODAY
    now = date.fromisoformat(as_of)
    base = (public_base if public_base is not None else os.environ.get("PUBLIC_BASE", DEFAULT_PUBLIC_BASE)).rstrip("/")
    cat = load_catalog()
    app = FastAPI(title="T-Mobile mock (synthetic)", version="1.0.0",
                  description="Synthetic carrier data for the PAM T-Mobile demo. No real customers or products.")

    def error(status: int, code: str, message: str) -> Response:
        return _json({"synthetic": True, "as_of": as_of, "error": {"code": code, "message": message}}, status)

    def answer(run: Callable[[], tuple]) -> Response:
        try:
            data, reasons, cards = run()
        except NotFound as exc:
            return error(404, "NOT_FOUND", str(exc))
        except ValueError as exc:
            return error(400, "BAD_ARGUMENTS", str(exc))
        return _json({"synthetic": True, "as_of": as_of, "data": data, "reasons": reasons, "pam_cards": cards})

    async def params(request: Request) -> dict:
        merged: dict = dict(request.query_params)
        if request.method == "POST":
            raw = await request.body()
            if raw.strip():
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    raise ValueError("body must be a JSON object") from None
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                merged.update(body)
        return merged

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> Response:
        return error(400, "BAD_ARGUMENTS", "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        return error(exc.status_code, "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}",
                     str(exc.detail))

    @app.get("/health")
    def health() -> Response:
        return _json({"status": "ok", "synthetic": True, "as_of": as_of})

    @app.get("/customers/{customer_id}")
    def get_household(customer_id: str) -> Response:
        return answer(lambda: catalog.run_household(cat, now, base, customer_id))

    @app.get("/catalog/devices")
    async def search_devices(request: Request) -> Response:
        p = dict(request.query_params)
        return answer(lambda: catalog.run_search(cat, now, base, _text(p, "query"), _number(p, "max_monthly"),
                                                 _text(p, "form_factor"), _integer(p, "limit", 3)))

    @app.get("/catalog/plans")
    async def list_plans(request: Request) -> Response:
        p = dict(request.query_params)
        return answer(lambda: catalog.run_plans(cat, now, base, _integer(p, "lines", 1)))

    @app.get("/tradein/{device_id}")
    async def tradein_value(device_id: str, request: Request) -> Response:
        p = dict(request.query_params)
        return answer(lambda: catalog.run_tradein(cat, now, base, device_id, _integer(p, "months_ahead", 12)))

    @app.post("/recommend/upgrade")
    async def recommend_upgrade(request: Request) -> Response:
        try:
            p = await params(request)
        except ValueError as exc:
            return error(400, "BAD_ARGUMENTS", str(exc))
        return answer(lambda: upgrade.run_upgrade(cat, now, base, _text(p, "customer_id", True),
                                                  _text(p, "line_id", True), _number(p, "monthly_budget"),
                                                  _text(p, "needs")))

    @app.post("/recommend/household")
    async def optimize_household(request: Request) -> Response:
        try:
            p = await params(request)
        except ValueError as exc:
            return error(400, "BAD_ARGUMENTS", str(exc))
        return answer(lambda: household.run_optimize(cat, now, base, _text(p, "customer_id", True),
                                                     _flag(p, "include_home_internet")))

    @app.post("/recommend/addons")
    async def suggest_addons(request: Request) -> Response:
        try:
            p = await params(request)
        except ValueError as exc:
            return error(400, "BAD_ARGUMENTS", str(exc))
        return answer(lambda: addons.run_addons(cat, now, base, _text(p, "customer_id", True),
                                                _text(p, "line_id", True), _text(p, "device_id", True)))

    app.mount("/images", StaticFiles(directory=ROOT / "images"), name="images")
    return app


app = create_app()
