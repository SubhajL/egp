# PR-05 Stale SingletonLock Cleanup — Opt-In Gating Coding Log

## Context (2026-06-02 20:22:34 +0700)

Final PR of the residential-proxy crawler hardening series. Root cause: Chrome
launched under `xvfb-run` does **not** remove its `Singleton*` lock files on
exit (the `SingletonLock` is a dangling `hostname-pid` symlink). On a reused
browser profile, the leftover lock makes the **next** Chrome launch fail —
surfacing as "CDP port not reachable" — so unattended back-to-back crawls break.

A helper `clear_stale_singleton_locks(profile_dir)` removes
`("SingletonLock", "SingletonCookie", "SingletonSocket")`, tolerating a missing
dir/files and dangling symlinks, swallowing `OSError`.

## Prior QCHECK HIGH (addressed here)

The first cut called `clear_stale_singleton_locks()` **unconditionally** inside
`launch_real_chrome`. That is unsafe on the **in-run recovery relaunch**
(`browser_discovery.py:300`): it runs right after `safe_shutdown`, where a
just-killed Chrome from the *same run* may not be reaped yet — so its lock is
**not** necessarily stale, and clearing it could let a second Chrome attach to
the same profile.

## Change

Make clearing **opt-in**:

```python
def launch_real_chrome(
    settings: BrowserDiscoverySettings, *, clear_singleton_locks: bool = False
) -> subprocess.Popen:
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    if clear_singleton_locks:
        cleared = clear_stale_singleton_locks(settings.browser_profile_dir)
        if cleared:
            _logger.info("Cleared stale Chrome singleton lock(s) %s in %s", ...)
    ...
```

`clear_singleton_locks=True` is set **only at workflow-entry launches**, where no
prior in-process Chrome exists so a previous run's lock is always stale:

| Site | Call | Flag |
| --- | --- | --- |
| `browser_discovery.py:221` | first discovery launch | `True` |
| `browser_discovery.py:300` | in-run recovery relaunch | default `False` (unchanged) |
| `warmup.py:85` | warm-up tool launch | `True` |
| `browser_close_check.py:55` | close-check workflow launch | `True` |

### `close_check:55` rationale (added beyond original remediation)

`crawl_live_close_check` shares the **same default `browser_profile_dir`** as
discovery and is a workflow-entry launch with no prior in-process Chrome. A stale
lock left by a previous discovery/close-check run would break it identically, so
it gets `clear_singleton_locks=True` for consistency. The only site deliberately
left off is the in-run relaunch.

## TDD

RED first (`tests/phase1/test_worker_singleton_cleanup.py`):

- `test_launch_does_not_clear_locks_by_default` — default leaves the lock in
  place (protects the not-yet-reaped relaunch).
- `test_launch_clears_locks_when_opted_in` — `clear_singleton_locks=True`
  removes it.

Both initially failed (unconditional clear removed the lock; kwarg did not
exist), then passed after the implementation. Existing helper-level tests
(file removal, dangling symlink, no-op cases) retained.

Monkeypatch in `test_worker_browser_discovery.py:3346` widened from
`lambda settings` to `lambda settings, **kwargs` so the new keyword arg passes
through the discovery resume test.

## Quality gates

- New opt-in tests: 6/6 pass.
- Affected suites (singleton + browser_discovery + warm_browser_profile): 84 pass.
- 3× flakiness: stable.
- `ruff check` clean; formatted the new test file only (left a pre-existing,
  unrelated format nit in `browser_close_check.py:242` untouched).
- Wiring verified: the three opt-in call sites + relaunch staying default-off.

## QCHECK

Self-review (Codex skipped — ~15-line, fully-understood diff). No CRITICAL/HIGH:
gating boundary matches the prior HIGH exactly (only the relaunch keeps the lock
that may be non-stale), `close_check` addition justified, keyword-only signature,
both branches test-locked. Cross-process concurrency is prevented upstream
(persistent-mode flock / unique per-run dirs), so any leftover at an entry launch
is stale by construction.
