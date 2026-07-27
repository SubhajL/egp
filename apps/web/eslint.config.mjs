import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypeScript,
  {
    rules: {
      // Existing forms intentionally hydrate controlled state from fetched or
      // persisted external state. Refactor those flows separately from the
      // release-tooling migration.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  globalIgnores([
    ".next/**",
    ".next-dev/**",
    ".next-playwright/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);
