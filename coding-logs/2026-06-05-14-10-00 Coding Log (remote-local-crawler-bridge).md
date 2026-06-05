# Coding Log — Remote Local Crawler Bridge (Track C)

**Date:** 2026-06-05
**Branch:** `feat/remote-local-crawler-bridge`
**Goal:** Temporary "www" architecture — crawler runs on the local Mac (real Chrome,
beats Cloudflare Turnstile) while the API runs on Lightsail and the frontend on Vercel.

## Decisions (confirmed with user)
- **DB Topology A** — SSH tunnel to Lightsail Postgres (container published to VM
  `127.0.0.1:15432`, forwarded over SSH). Not Supabase-direct.
- **Scheduled enqueuer included** — Lightsail-side systemd timer enqueues `schedule`
  jobs (DB-only, no browser) since the in-box `discovery-executor` is scaled to 0.
- **Always-on launchd** — tunnel + watcher agents on the Mac.

## Key finding
The worker is **DB-coupled** (`run_discover_workflow(database_url=…)` writes
runs/tasks/projects directly; the HTTPS `ApiProjectEventSink` only redirects
project-events). So the Mac must reach the production DB — hence the SSH tunnel.

## Implemented (TDD)
- `apps/api/src/egp_api/services/run_trigger_mapping.py` — maps
  `discovery_jobs.trigger_type` → the `crawl_runs` CHECK set (`schedule|manual|retry|backfill`);
  `schedule` survives so the scheduler's due-tenant accounting works.
- Dispatch threading: `DiscoveryDispatchRequest` gains `trigger_type`/`live`;
  `process_job` threads them; `SubprocessDiscoveryDispatcher.dispatch` writes the
  **mapped** trigger into `create_run` + the worker payload (was hardcoded `manual`).
  `main.py` embedded adapter now calls `spawner.dispatch(request)` so trigger survives
  in embedded mode too.
- `apps/api/src/egp_api/executors/scheduled_discovery_enqueue.py` — enqueue-only
  producer; reuses `run_scheduled_discovery` planning with an enqueue `job_runner`.
- `scripts/remote_crawl_guard.py` — fail-closed guard (env + DB topology), `--env-file`
  strict parser, `print-env` (NUL-delimited safe export), `tunnel-exec` (execs ssh argv
  directly), `tunnel-cmd`.
- `scripts/run_remote_crawl.sh` — guarded runner (never `source`s the env file).
- `scripts/install_launchd.sh` + `deploy/launchd/*.plist` — always-on agents.
- `deploy/systemd/egp-scheduled-enqueue.{service,timer}` — Lightsail enqueue timer.
- `docker-compose.pg-tunnel.yml` — loopback-only Postgres publish.
- `.env.remotecrawl.example` (+ `.gitignore`), `docs/REMOTE_LOCAL_CRAWLER.md`,
  `TRACKS.md` Track C, Lightsail doc pointer, `test_env_template.py` allowlist.

## QCHECK (Codex gpt-5.5 xhigh) — all findings fixed
- HIGH: bash-`source` of env file (spaces/shell-eval) → strict Python parse + safe export.
- HIGH: loopback topology too permissive → require explicit port == tunnel port; reject
  hostless/missing-port/malformed-port.
- HIGH: `exec $tunnel_cmd` word-split → `tunnel-exec` execs argv in Python.
- MEDIUM: embedded adapter dropped trigger → fixed.
- MEDIUM: example pre-acknowledged prod + `CHANGE_ME` accepted → ack placeholder'd, guard
  rejects any `CHANGE_ME`.
- MEDIUM: worker token not required → now required.
- LOW: install_launchd sed/XML-hostile paths → rejected with a clear error.

## Gates
- ruff check (apps/packages/scripts/tests) + format: clean.
- pytest: full operations + worker (178), api+phase2+concurrency (161); new tests 3×
  flake-free. No web changes (frontend gate skipped).
