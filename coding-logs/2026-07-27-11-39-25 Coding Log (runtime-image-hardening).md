# Coding Log: Runtime Image Hardening

## 2026-07-27 11:39:25 +0700 — U6 start

- Goal: deliver U6 `build/split-and-harden-runtime-images` from merged U5 main.
- Scope: lean non-root API image without Playwright/Chromium/worker source; browser-capable
  non-root worker/executor image; correct Compose image wiring; bounded resources and logs;
  executable image-smoke and Compose-contract gates.
- Base: `11b9566e0971f80a4a2061ea6322e9c536cf5a16` (`origin/main`).
- Auggie semantic retrieval was skipped because the available tool path cannot enforce the
  g-coding skill's required two-second timeout. Exploration uses direct reads and exact-string
  searches as the mandated fallback.
- Safety: this phase does not deploy, activate a pilot, change production environment values, or
  weaken the closed S1 gate.

## 2026-07-27 11:51:09 +0700 — U6 implementation and executable image proof

### Goal

- Split the control-plane and browser runtimes, run both as non-root, constrain Compose
  resources/filesystems/logs, and make image behavior an executable CI gate.

### What changed

- `apps/api/Dockerfile`: frozen `egp-api`-only dependency sync; no worker source, Playwright,
  Chromium, or browser libraries; runtime contains only the installed environment and SQL
  migrations; UID/GID `10001:10001`; bytecode disabled; artifact mount point pre-owned.
- `apps/worker/Dockerfile`: frozen `egp-api` + `egp-worker` sync for the discovery executor;
  deterministic `/ms-playwright` browser payload; full Chromium/Xvfb/Thai-font runtime;
  UID/GID `10001:10001`; writable artifact and browser mount points pre-owned.
- `docker-compose.yml`, `docker-compose-localdev.yml`: discovery now builds the worker image;
  all services receive memory/CPU/PID bounds and rotating `json-file` logs; Python services use
  read-only root filesystems with bounded tmpfs; the per-run browser profile root is a UID/GID
  owned tmpfs.
- `.github/workflows/ci.yml`, `scripts/smoke_runtime_images.sh`: CI tags both Python images and
  runs non-root, dependency-boundary, read-only filesystem, named-volume write, live headless
  Chromium, and image-size checks.
- `tests/operations/test_runtime_image_hardening.py`: static contracts for Dockerfiles, Compose,
  CI wiring, smoke execution, and operator documentation.
- `docs/DEPLOYMENT.md`, `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: document the split topology,
  non-root/read-only resource controls, and the container profile path.

### TDD evidence

- Initial RED:
  `.venv/bin/python -m pytest -q tests/operations/test_runtime_image_hardening.py`
  produced `6 failed`; both images still installed all packages/browser assets, discovery still
  used the API image, Compose lacked bounds/read-only mounts, and CI lacked the smoke step.
- Initial GREEN: the same command produced `6 passed`, later extended to `7 passed` with docs
  coverage.
- Browser-launch RED:
  `.venv/bin/python -m pytest -q
  tests/operations/test_runtime_image_hardening.py::test_ci_builds_named_images_and_runs_executable_smoke_contract`
  failed because the smoke did not launch Chromium; after implementation it passed and the real
  smoke launched Chromium successfully.
- Filesystem RED: the executable smoke failed with `PermissionError` writing
  `/var/lib/egp/browser-profiles/.image-smoke`; the Docker tmpfs was root-owned.
- Filesystem GREEN: explicit tmpfs `uid=10001,gid=10001,mode=0700` passed the static contract and
  the same executable smoke, including writes to artifact, persistent-profile, and per-run-profile
  mounts.
- Runtime-source RED/GREEN: Dockerfile contracts first failed on whole application-directory
  copies, then passed after runtime stages were reduced to installed wheels plus API migrations.

### Tests and runtime evidence

- Focused regression set:
  `.venv/bin/python -m pytest -q tests/operations/test_runtime_image_hardening.py
  tests/operations/test_api_readiness_assets.py tests/operations/test_proxy_relay_compose.py
  tests/operations/test_localdev_billing_promptpay.py
  tests/operations/test_vercel_deployment_config.py
  tests/operations/test_reproducible_release_gates.py
  tests/phase2/test_background_runtime_mode.py` -> `57 passed`.
- Both `docker compose -f docker-compose.yml config -q` with non-secret placeholders and
  `docker compose -f docker-compose-localdev.yml config -q` passed.
- Final local images:
  - API `sha256:2503e9041401ca2b930b4b5a977e422a3d7a906ce2a5a371dddb095383102a7d`,
    `286,057,337` bytes, user `10001:10001`.
  - Worker `sha256:da7fbee20ad3eec37a7f5a78b4e4e2acaf5c74881ffc9a717e8ea6e98a89d0a9`,
    `1,733,443,092` bytes, user `10001:10001`.
  - U5 baseline API and worker images were each about `1.8 GB`; the API is now about `286 MB`.
- `./scripts/smoke_runtime_images.sh egp-api:u6 egp-worker:u6` passed under read-only root
  filesystems, proved API has neither `playwright` nor `egp_worker`, imported both worker executor
  packages, wrote every runtime mount, and launched a real Chromium page.

### Wiring verification

| Component | Production wiring | Evidence |
|---|---|---|
| Lean API image | `migrate`, `api`, `webhook-executor` | Both Compose files select `apps/api/Dockerfile` |
| Browser worker image | `discovery-executor` | Both Compose files select `apps/worker/Dockerfile` |
| Image smoke | CI `build` job | Named image builds feed `Smoke runtime images` |
| Resource/log controls | Every Compose service | Static contract iterates every service in both files |
| Writable browser root | Discovery executor | Env path and UID/GID-owned tmpfs match in both files |

### Risks and gaps

- Existing named volumes created by older root-running images may require a one-time ownership
  correction before deploying this non-root release. No volume or production host is modified by
  this PR.
- The worker image remains intentionally large because it carries full Chromium, headless shell,
  Xvfb, and Thai fonts; the size gate requires only the browserless API to stay below `800 MB` and
  below the worker image.
- No deployment, production Compose restart, or pilot activation is performed.

## 2026-07-27 12:01:58 +0700 — Independent Claude QCHECK disposition

- Claude reviewed the staged Docker/Compose/CI/smoke/test surface read-only and returned five
  findings.
- HIGH, existing named-volume ownership: valid rollout risk, already remediated in the staged
  `docs/DEPLOYMENT.md` one-time backup/stop/chown procedure and covered by a documentation
  contract. Fresh-volume writes are executable-smoke verified.
- HIGH, discovery tmpfs headroom: accepted. Both discovery tmpfs caps were reduced from `512m` to
  `256m`, leaving at least `1.5 GB` of the default `2 GB` cgroup limit even if both tmpfs mounts
  fill. RED/GREEN contract coverage asserts both caps.
- MEDIUM, singular persistent-profile path allegedly unmounted: rejected. Production Compose
  already mounts `egp_browser_profile:/var/lib/egp/browser-profile`; localdev does not enable
  persistent mode. The smoke writes that mounted path.
- MEDIUM, root-owned `/ms-playwright`: resolved by evidence without broadening write authority.
  Browser assets should remain immutable; the UID 10001 smoke verifies executable access and
  launches a real Chromium page successfully.
- LOW, no absolute worker-size cap: accepted. The smoke now enforces
  `EGP_WORKER_IMAGE_MAX_BYTES`, default `2,200,000,000`, in addition to the `800,000,000` API cap
  and API-smaller-than-worker invariant.
- Post-remediation focused contracts passed; Compose config passed; executable image smoke passed
  with API `286,057,337` bytes and worker `1,733,443,092` bytes.

## 2026-07-27 12:05:38 +0700 — Full-suite resource-template wiring fix

- The first full Python gate completed `1276 passed, 2 skipped, 1 failed` in `180.00s`.
- Failure:
  `tests/operations/test_env_template.py::test_env_template_covers_all_compose_required_vars`
  found that the 26 new Compose resource/log interpolation variables were missing from
  `deploy/.env.production.example`.
- Fix: added every resource/log variable with the exact Compose default and documented that
  discovery tmpfs usage counts against its cgroup memory limit.
- GREEN:
  `.venv/bin/python -m pytest -q
  tests/operations/test_env_template.py::test_env_template_covers_all_compose_required_vars
  tests/operations/test_env_template.py::test_env_template_is_compose_env_compatible
  tests/operations/test_runtime_image_hardening.py` -> `9 passed`.
- Behavioral wiring:
  `docker compose --env-file deploy/.env.production.example -f docker-compose.yml config -q`
  passed.
- The three-run full-suite reliability gate must restart from run 1 because its first attempt was
  not green.

## 2026-07-27 12:09:23 +0700 — Compose-only env registry wiring fix

- The restarted full gate completed `1276 passed, 2 skipped, 1 failed` in `178.23s`.
- Failure:
  `tests/operations/test_env_template.py::test_every_template_egp_var_is_referenced_by_code_or_allowlisted`
  correctly rejected the new template entries because the AST scanner cannot see
  Docker-Compose-only interpolation.
- Fix: registered all 26 resource/log keys in `TEMPLATE_ONLY_VARS` under an explicit
  Compose-only comment. No runtime variable was hidden or removed.
- GREEN:
  `.venv/bin/python -m pytest -q tests/operations/test_env_template.py
  tests/operations/test_runtime_image_hardening.py` -> `22 passed`.
- The three-run full-suite reliability gate must again restart from run 1.

## Review (2026-07-27 12:21:16 +0700) — U6 working tree

### Reviewed

- Staged U6 diff against `11b9566e0971f80a4a2061ea6322e9c536cf5a16`.
- API and worker Dockerfiles, both Compose files, CI image wiring, executable image smoke,
  environment template, deployment documentation, and focused contracts.
- Existing full-suite, Compose, image-build, non-root runtime, mount-write, and Chromium-launch
  evidence recorded above.
- Independent Claude QCHECK and its primary-agent disposition.
- Auggie semantic search was not used because the available interface cannot enforce the
  required real two-second timeout; review used bounded direct inspection instead.

### Findings

- CRITICAL: none.
- HIGH: none.
- MEDIUM: `scripts/smoke_runtime_images.sh:33-38` launches Playwright Chromium directly with
  `headless=True`, but production defaults `EGP_BROWSER_USE_XVFB=true` and the actual worker
  launch path wraps headful Chrome in `xvfb-run` (`docker-compose.yml:203-204`,
  `apps/worker/src/egp_worker/browser_discovery.py:1473-1500`). A broken `xvfb-run`, `xauth`,
  headful browser dependency, or read-only-filesystem interaction could therefore pass the CI
  image smoke. Add a test-first contract and execute the worker smoke through `xvfb-run` with
  headful Chromium.
- LOW: the background-worker healthcheck comments in `docker-compose.yml:157-159` and
  `docker-compose.yml:231-233` still describe the inherited endpoint as `/health`; the current
  API Dockerfile probes `/ready`. Correct the comments so operator diagnostics remain accurate.

### Tests and residual risks

- No product-code defect was found in the staged U6 implementation.
- GitHub-hosted validation remains unavailable while the account billing lock prevents jobs
  from starting; exact local runtime evidence remains required before submission.
- Production volume ownership migration remains an explicitly documented deployment-time step;
  no production state is changed in U6.

## 2026-07-27 12:32:45 +0700 — Formal review remediation

- The MEDIUM Xvfb-smoke finding was accepted. A new static contract first failed because the
  smoke neither invoked the production launcher nor enabled its Xvfb mode.
- The first attempted headful image smoke exposed two additional HIGH release blockers that the
  earlier headless smoke had masked:
  - `resolve_chrome_binary()` searched only `$HOME/.cache/ms-playwright`, while the hardened
    image installs Chromium at `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`. Production would have
    fallen through to the nonexistent macOS Chrome default.
  - Headful Chromium terminated with `chrome_crashpad_handler: --database is required` because
    its XDG configuration location was on the read-only root filesystem.
- TDD RED:
  - the new Playwright-browser-root resolver contract failed;
  - the worker-image writable-XDG contract failed;
  - the production-launch smoke contract failed.
- Fixes:
  - browser resolution now searches `PLAYWRIGHT_BROWSERS_PATH` before the backward-compatible
    `$HOME/.cache/ms-playwright` location;
  - the worker image sets `XDG_CONFIG_HOME=/tmp/.config`, backed by the bounded `/tmp` tmpfs;
  - the executable smoke now calls `launch_real_chrome(... use_xvfb=True)` and
    `connect_playwright_to_chrome()`, proving the exact `xvfb-run`/CDP path rather than a
    Playwright-managed headless substitute;
  - stale Compose healthcheck comments now name the current `/ready` endpoint.
- GREEN, three consecutive runs:
  `tests/phase1/test_worker_browser_launch.py`,
  `tests/operations/test_runtime_image_hardening.py`, and
  `tests/operations/test_env_template.py` each reported `31 passed`; every run also passed the
  real image smoke.
- GREEN full Python suite after the runtime-code fix:
  `1435 passed, 2 skipped, 113 warnings` in `174.38s`.
- Final images:
  - API `sha256:2503e9041401ca2b930b4b5a977e422a3d7a906ce2a5a371dddb095383102a7d`,
    `286,057,337` bytes, user `10001:10001`;
  - worker `sha256:db795f27be2ed46dc7b997379924b7b4742a34c19aa59cf44b7aa4f1a0335b5d`,
    `1,733,443,281` bytes, user `10001:10001`.

## Review (2026-07-27 12:34:01 +0700) — Final U6 staged tree

### Reviewed

- The complete staged diff against exact current `origin/main`
  `11b9566e0971f80a4a2061ea6322e9c536cf5a16`.
- Split dependency/runtime stages, installed package closure, migrations, browser assets,
  non-root identities, read-only filesystem mounts, writable volume/tmpfs ownership, resource
  limits, log rotation, CI wiring, executable smoke, environment-template wiring, and operator
  upgrade documentation.
- The review-remediation changes to browser binary resolution, writable XDG configuration, and
  exact Xvfb/CDP runtime evidence.

### Findings

- CRITICAL: none.
- HIGH: none.
- MEDIUM: none.
- LOW: none.

### Verification and residual risk

- Frozen dependency resolution was proved by successful API and worker Docker builds, each using
  `uv sync --frozen`; this host has no standalone `uv` executable.
- Ruff check and format, compileall, 35-file migration manifest, shell syntax, production and
  local Compose config, staged diff check, focused tests three times, image smoke three times,
  and the post-remediation full Python suite are green.
- GitHub-hosted jobs are still expected to remain zero-step while the account billing lock is
  unresolved. No deployment or production-state change is part of this U6 branch.
