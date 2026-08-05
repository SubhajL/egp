# Coding Log: PR-CANARY-01 — correlated, bounded runtime evidence

## Metadata

- Created: 2026-08-05 18:30:00 Asia/Bangkok
- Repository: `/Users/subhajlimanond/dev/egp`
- Planning base: `main` at `722b1e0ece9571bddc710c5dc69c9ac45a14c066`
- Source spec: `egp-ops-main/coding-logs/2026-08-05-17-58-04 Coding Log (crawler-completeness-parity-canary-hardening).md`, section PR-CANARY-01
- Lifecycle: g2-planning → g2-coding → g2-qcheck (+ codex g-check as second-tier QCHECK)

## Scope

First PR in the 7-PR canary-hardening sequence. Makes subsequent fault injection
and production rehearsal diagnosable without changing crawl decisions.

Key deliverables:
1. Structured JSON logging module (`egp_observability.logging`)
2. Correlated, sequenced child stdout/stderr capture in the dispatcher
3. Framed final-result record so log lines cannot corrupt result parsing
4. Tail-oriented bounded redacted stderr preview (replaces first-500-char)
5. Aggregate watcher log rotation/retention
6. `EGP_RELEASE_SHA` injection (never shell out to git at runtime)

## Planning Phase

- **DREP file:** `coding-logs/2026-08-05-18-30-00 DREP (pr-canary-01-correlated-runtime-evidence).md`
- **Codex adversarial review:** 12 findings (6 HIGH, 6 MEDIUM); all accepted or partially accepted
- **Key changes from draft → final:**
  - Removed stream-merging (FN7 was overengineered); stdout/stderr stay separate
  - Added 3 missed test files to do-not-touch list
  - Clarified per-run logs NEVER rotate (run-log API dependency)
  - Scoped framing to discover-only (noop/close_check unchanged)
  - Added explicit sink contract for make_event (never stdout)
  - Added EGP_RELEASE_SHA to docker-compose files
- **Slices:** S1 (primitives, DeepSeek) → S2 (dispatcher wiring, Claude) → S3 (env/docs, DeepSeek)
- **Planning complete:** 2026-08-05 ~20:00 ICT
