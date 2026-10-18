# T-Mobile mock API (SPEC §8 M17): synthetic carrier data on port 8100.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    MOCK_TODAY=2026-10-18 \
    PUBLIC_BASE=/connectors/tmobile

WORKDIR /app

# Dependencies first so data and code edits don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py ./
COPY engine ./engine
COPY data ./data
COPY images ./images

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
