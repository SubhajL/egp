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
COPY apps/worker/src apps/worker/src

RUN uv sync --frozen --all-packages --all-extras --no-editable

RUN playwright install chromium --with-deps

# Runtime
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /root/.cache/ms-playwright /root/.cache/ms-playwright

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/ packages/
COPY apps/api/ apps/api/
COPY apps/worker/ apps/worker/

# Full Chromium runtime libraries (authoritative Playwright list — includes
# libcups2 and friends the curated list above omits) plus a virtual display so
# headful Chrome can clear Cloudflare Turnstile unattended, and Thai fonts so
# e-GP pages render correctly for parsing.
RUN apt-get update && \
    python -m playwright install-deps chromium && \
    apt-get install -y --no-install-recommends xvfb xauth fonts-thai-tlwg && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

CMD ["uvicorn", "egp_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
