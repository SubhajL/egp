# AGENTS.md

## Package Identity

- `apps/web` is the Next.js 15 + React 19 frontend.
- The app now includes operator-facing dashboard, projects, project-detail, runs, rules, and login flows under `src/app/`, with shared API/query helpers under `src/lib/`.

## Setup & Run

```bash
cd apps/web && npm install
cd apps/web && npm run dev
cd apps/web && npm run test:unit
cd apps/web && npm run typecheck
cd apps/web && npm run build
cd apps/web && npm run lint
```

Current test status: fast Vitest unit/contract tests now cover shared frontend helpers, while Playwright browser smoke tests cover the auth lifecycle pages plus a protected-route auth gate.

## Patterns & Conventions

- ✅ DO keep all frontend source under `src/`, because [`tsconfig.json`](tsconfig.json) only includes `src/**/*.ts` and `src/**/*.tsx`.
- ✅ DO use the `@/*` import alias defined in [`tsconfig.json`](tsconfig.json) for new internal modules.
- ✅ DO keep this app in strict TypeScript mode; [`tsconfig.json`](tsconfig.json) has `"strict": true`.
- ✅ DO prefer extending [`src/lib/api.ts`](src/lib/api.ts) and [`src/lib/hooks.ts`](src/lib/hooks.ts) instead of scattering fetch logic through page components.
- ✅ DO keep route-group UI under `src/app/(app)/` consistent with the existing dashboard/projects/runs/rules layout.
- ✅ DO use [`package.json`](package.json) as the source of truth for available npm scripts.
- ✅ DO use [`docs/PRD.md`](../../docs/PRD.md) as the current reference for planned page structure until real components exist.
- ❌ DON'T add JavaScript-only files outside `src/` and expect them to be typechecked.
- ❌ DON'T import crawler logic directly from [`egp_crawler.py`](../../egp_crawler.py) into the frontend.
- ❌ DON'T invent local copies of shared status strings when they should come from API contracts or shared definitions.
- ❌ DON'T delete or hand-edit [`next-env.d.ts`](next-env.d.ts); keep the generated Next ambient types file checked in.

## Touch Points / Key Files

- Frontend scripts and dependencies: [`package.json`](package.json)
- Frontend compiler and path alias config: [`tsconfig.json`](tsconfig.json)
- Next ambient types: [`next-env.d.ts`](next-env.d.ts)
- App routes: [`src/app/`](src/app)
- Shared data access: [`src/lib/api.ts`](src/lib/api.ts), [`src/lib/hooks.ts`](src/lib/hooks.ts)
- Planned page structure: [`docs/PRD.md`](../../docs/PRD.md)
- Universal platform rules: [`CLAUDE.md`](../../CLAUDE.md)

## JIT Index Hints

```bash
find apps/web/src -name "*.ts" -o -name "*.tsx"
rg -n "\"strict\"|\"@/\\*\"" apps/web/tsconfig.json apps/web/tsconfig.typecheck.json
rg -n "\"dev\"|\"build\"|\"lint\"|\"typecheck\"" apps/web/package.json
rg -n "fetch[A-Z]|use[A-Z].*Query|readRuntimeEnv" apps/web/src
```

## Common Gotchas

- Run `npm run test:unit` for the fast contract layer.
- Run `npm test` or `npm run test:e2e` to execute the Playwright browser smoke suite.
- Keep new code inside `src/` or TypeScript will ignore it.
- `next-env.d.ts` and `.next/types` are part of the expected Next.js TypeScript setup; don't remove them to quiet the tree.

## Pre-PR Checks

Current frontend gate:

```bash
cd apps/web && npm run test:unit && npm test && npm run typecheck && npm run lint && npm run build
```
