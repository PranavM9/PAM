# PAM backend — SPEC §8 M15. T00 skeleton; T16 bakes the spaCy + fastembed models and adds the healthcheck.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PAM_VAULT=/vault \
    FASTEMBED_CACHE_PATH=/models

WORKDIR /app

# Dependencies first so code edits don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY pam/ ./pam/
COPY tests/ ./tests/
RUN uv sync --frozen

ENTRYPOINT ["pam"]
CMD ["api", "serve", "--host", "0.0.0.0", "--port", "8000"]
