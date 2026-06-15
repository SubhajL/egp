# Coding Log: env-template-browser-warmup-vars (2026-06-15)

Fixes the long-standing pre-existing failure in
`tests/operations/test_env_template.py::test_env_template_tracks_runtime_egp_vars`
(flagged during WS2 as out-of-scope/pre-existing). Unrelated to WS2; split into
its own PR.

## Problem
The env-template drift test AST-scans runtime sources for `EGP_*` env reads and
fails when one isn't declared in `deploy/.env.production.example`. Two
persistent-profile warmup knobs read by `SubprocessDiscoveryDispatcher` (via
`apps/api/src/egp_api/config.py` getters) were missing:
- `EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS` (`get_browser_warmup_stale_after_seconds`, default `1800.0`)
- `EGP_BROWSER_PREDISPATCH_WARM_SECONDS` (`get_browser_predispatch_warm_seconds`, default `0.0`)

These are real operator-tunable production knobs (siblings of the
`EGP_BROWSER_WARMUP_*` vars already in the template), so they belong in the
template — not in `SOURCE_ONLY_VARS`.

## Change
Added both to `deploy/.env.production.example` under `# Section: optional`, next
to the existing warm-up tool knobs, with a comment and defaults matching the code
(`1800` / `0`). No code change. (The protected `.env` edit was made with explicit
operator approval — the protect-files hook gates `.env` edits.)

## Verification
- RED→GREEN: `tests/operations/test_env_template.py` 15/15 pass (was 1 failing).
- Full sweep: **1044 passed, 0 failed**; `ruff` clean.
- QCHECK (Codex gpt-5.5 xhigh) on the diff → **SHIP**, 0 findings (values match
  getter defaults; correct section; no secret/shell-substitution; not duplicated).
