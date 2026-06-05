# Coding Log — Track C artifacts: Supabase → Cloudflare R2

**Date:** 2026-06-05
**Branch:** `feat/remote-crawl-r2-artifacts`
**Goal:** Drop Supabase; the remote-local crawler (Track C) and the production
control-plane write/serve TOR documents via Cloudflare R2 (the `s3` backend).

## Key finding
No application code change needed: boto3 (≥1.35, botocore 1.42) reads
`AWS_ENDPOINT_URL_S3` + `AWS_*` creds from the environment, so the existing
`S3ArtifactStore` (`boto3.client("s3")`) talks to R2. Supabase was only ever the
artifact-storage backend — the DB is Lightsail Postgres, auth is local JWT.

## Changes (TDD)
- `scripts/remote_crawl_guard.py` `_validate_artifact_store`: accept
  `EGP_ARTIFACT_STORE=s3` (require `S3_BUCKET`/`AWS_S3_BUCKET`, R2
  `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION`) OR `supabase`; reject `local`.
- `.env.remotecrawl.example`: Supabase block → R2/S3 block.
- `deploy/.env.production.example`: default `EGP_ARTIFACT_STORE=s3` + R2 vars;
  Supabase vars kept present-but-optional (drift test stays green).
- `docker-compose.yml`: pass the storage creds (R2 + Supabase) into the `api` and
  `discovery-executor` `environment:` blocks — they were never passed before, so
  no remote store actually worked in the prod compose.
- Docs: `REMOTE_LOCAL_CRAWLER.md`, `TRACKS.md` (Supabase → R2; DB Topology B
  vendor-neutral).

## QCHECK (Codex gpt-5.5 xhigh) — all HIGH fixed
- HIGH-1: `AWS_REGION=auto` yields **SigV2** presigned URLs that R2 rejects.
  Verified empirically; fixed → require/use `AWS_DEFAULT_REGION=auto` (SigV4).
- HIGH-2: endpoint validation presence-only. Fixed → require
  `*.r2.cloudflarestorage.com`, reject truthy `AWS_IGNORE_CONFIGURED_ENDPOINT_URLS`.
- HIGH-3: prod template still defaulted to Supabase → migrated to R2 + wired the
  compose env passthrough.

## Gates
- ruff clean; guard/assets/env-template + proxy-relay tests pass; new tests 3×
  flake-free; `docker compose config -q` validates prod + pg-tunnel overlay.

## Follow-up to flag
- CLAUDE.md design decisions #5/#7 still say "Supabase-managed backend" — update
  separately to reflect R2 as the artifact store.
