# PAM backend — SPEC §8 M15. Models are baked at build time so the first run needs no network.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /vault

COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PAM_VAULT=/vault \
    FASTEMBED_CACHE_PATH=/models \
    TIKTOKEN_CACHE_DIR=/models/tiktoken

WORKDIR /app

# Dependencies first so code edits don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Models after the dependencies and before the code, so code edits don't redownload them.
# The spaCy model is a uv dependency (CHG-0007); this only checks that it imports.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')" \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && python -c "import en_core_web_sm; en_core_web_sm.load()"

COPY pam/ ./pam/
COPY tests/ ./tests/
RUN uv sync --frozen

ENTRYPOINT ["pam"]
CMD ["api", "serve", "--host", "0.0.0.0", "--port", "8000"]
