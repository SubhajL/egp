FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
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

RUN uv sync --frozen --package egp-api --package egp-worker --no-dev --no-editable

RUN playwright install chromium

# Runtime
FROM python:3.12-slim-bookworm AS runtime

ARG EGP_RELEASE_SHA
RUN case "$EGP_RELEASE_SHA" in \
      localdev) ;; \
      *) \
        release_sha_length="$(printf '%s' "$EGP_RELEASE_SHA" | wc -c)" && \
        release_sha_invalid="$(printf '%s' "$EGP_RELEASE_SHA" | LC_ALL=C tr -d '0123456789abcdef' | wc -c)" && \
        test "$release_sha_length" -eq 40 && \
        test "$release_sha_invalid" -eq 0 \
        ;; \
    esac || { echo "release revision must be localdev or an exact 40-character lowercase Git SHA" >&2; exit 1; }
LABEL org.opencontainers.image.revision="${EGP_RELEASE_SHA}"

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /ms-playwright /ms-playwright

ENV PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CONFIG_HOME=/tmp/.config \
    HOME=/home/egp \
    EGP_RELEASE_SHA="${EGP_RELEASE_SHA}"

# Full Chromium runtime libraries (authoritative Playwright list — includes
# libcups2 and friends the curated list above omits) plus a virtual display so
# headful Chrome can clear Cloudflare Turnstile unattended, and Thai fonts so
# e-GP pages render correctly for parsing.
RUN apt-get update && \
    /app/.venv/bin/python -m playwright install-deps chromium && \
    apt-get install -y --no-install-recommends xvfb xauth fonts-thai-tlwg && \
    groupadd --system --gid 10001 egp && \
    useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/egp egp && \
    mkdir -p /var/lib/egp/artifacts /var/lib/egp/browser-profiles \
      /var/lib/egp/browser-profile && \
    chown -R 10001:10001 /home/egp /var/lib/egp && \
    rm -rf /var/lib/apt/lists/*

USER 10001:10001

CMD ["python", "-m", "egp_worker.main"]
