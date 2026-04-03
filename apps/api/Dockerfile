FROM python:3.12-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
FROM base AS deps

COPY pyproject.toml ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/ packages/

RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir fastapi uvicorn[standard] pydantic \
    python-jose[cryptography] openpyxl psycopg[binary] \
    sqlalchemy boto3 supabase

# Runtime
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY pyproject.toml ./
COPY packages/ packages/
COPY apps/api/ apps/api/

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "egp_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
