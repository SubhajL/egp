FROM python:3.12-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
FROM base AS deps

COPY pyproject.toml ./
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/ packages/

RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir playwright psycopg[binary] httpx \
    sqlalchemy boto3 supabase openpyxl prometheus-client

RUN playwright install chromium --with-deps

# Runtime
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY --from=deps /root/.cache/ms-playwright /root/.cache/ms-playwright

COPY pyproject.toml ./
COPY packages/ packages/
COPY apps/worker/ apps/worker/

RUN pip install --no-cache-dir -e .

# Full Chromium runtime libraries (authoritative Playwright list — includes
# libcups2 and friends the curated list above omits) plus a virtual display so
# headful Chrome can clear Cloudflare Turnstile unattended, and Thai fonts so
# e-GP pages render correctly for parsing.
RUN apt-get update && \
    python -m playwright install-deps chromium && \
    apt-get install -y --no-install-recommends xvfb xauth fonts-thai-tlwg && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "egp_worker.main"]
