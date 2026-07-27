FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies
FROM base AS deps

COPY pyproject.toml ./
COPY uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/ packages/
COPY apps/api/src apps/api/src

RUN uv sync --frozen --package egp-api --no-dev --no-editable

# Runtime
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    groupadd --system --gid 10001 egp && \
    useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/egp egp && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/egp

COPY packages/db/src/migrations packages/db/src/migrations

RUN mkdir -p /var/lib/egp/artifacts && \
    chown -R 10001:10001 /home/egp /var/lib/egp

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

CMD ["uvicorn", "egp_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
