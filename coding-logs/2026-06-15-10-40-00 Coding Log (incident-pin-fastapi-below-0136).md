# Coding Log: incident — pin FastAPI <0.136 (2026-06-15)

## Incident
During the post-WS2 Lightsail redeploy (`docker compose up -d --build api webhook-executor`),
the rebuilt `egp-api` container crash-looped (unhealthy):

```
fastapi.exceptions.FastAPIError: Prefix and path cannot be both empty
(path operation: get_admin_snapshot)
```

## Root cause
`fastapi` was unpinned. The prod no-cache rebuild resolved **fastapi 0.137.0**
(starlette 1.3.1), which rejects empty-path routes — and the API uses that pattern
pervasively: `@router.get("")` included under a prefix, e.g. `/v1/admin`, `/v1/runs`,
`/v1/projects`, `/v1/webhooks`, `/v1/rules` (7 routes). The previously-running image
(built ~47h earlier) and local dev/tests use **0.135.3**, which tolerates it — so the
whole 1044-test suite was green and the bug was latent until a fresh dependency
resolution. Two unpinned install paths existed:
- `apps/api/pyproject.toml`: `fastapi>=0.115`
- `apps/api/Dockerfile`: `pip install --no-cache-dir fastapi ...` (no cap) — the
  authoritative source for the image build (all Python services build from this
  Dockerfile).

## Fix (incident hotfix)
Cap to the tested range in **both** paths:
- `apps/api/pyproject.toml`: `fastapi>=0.115,<0.136`
- `apps/api/Dockerfile`: `pip install ... 'fastapi<0.136' ...`

Capping (vs refactoring 7 public routes mid-outage) restores all routes to verified
0.135.x behavior with no URL changes. Verified locally: `create_app` builds (83 routes,
`/v1/admin` preserved); `tests/phase2/test_observability_metrics.py` 16/16.

QCHECK (Codex) round 1 → BLOCK: HIGH = pyproject pin alone doesn't fix the Docker build
(the Dockerfile's explicit unpinned `fastapi` install). Fixed by capping the Dockerfile
too. (This catch prevented a second failed redeploy.)

## Follow-up (separate PR)
Refactor the 7 empty-path routes (`@router.get("")` → explicit non-empty path that
preserves the URL) + add a startup/`create_app` smoke test on the latest FastAPI, then
lift the `<0.136` cap. Tracked as a GitHub issue.
