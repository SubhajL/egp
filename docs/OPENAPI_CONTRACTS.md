# OpenAPI Contract Generation

The backend FastAPI schema is the source of truth for generated frontend API types.

## Generated Artifacts

The web app commits both generated outputs:

- `apps/web/src/lib/generated/openapi.json`
- `apps/web/src/lib/generated/api-types.ts`

Committing the artifacts keeps `npm run typecheck` deterministic and lets code review see contract
changes alongside backend route changes. Do not edit these files by hand.

## Commands

From `apps/web`:

```bash
npm run generate:api-types
npm run check:api-types
```

`generate:api-types` exports the packaged FastAPI schema through
`scripts/export_openapi_schema.py`, then runs `openapi-typescript`.

`check:api-types` regenerates the schema and TypeScript types in a temporary directory and fails if
the committed artifacts drift.

## Adopted Frontend Domains

`apps/web/src/lib/api.ts` keeps the hand-written fetch wrapper functions, but the first migrated
domains now derive their public TypeScript response and request types from
`apps/web/src/lib/generated/api-types.ts`:

- projects
- documents
- rules and entitlements

Keep wrapper functions stable for pages/hooks, and migrate additional domains by replacing manual
facade types with generated `paths` or `components` aliases plus focused unit/type coverage.
