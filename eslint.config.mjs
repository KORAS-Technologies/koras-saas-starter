// Flat ESLint config for the whole monorepo.
//
// ESLint 9 searches upward from the working directory for this file, so every
// workspace package can run a bare `eslint src` and resolve back to here. That
// keeps one shared rule set instead of a near-identical copy per package, and
// pnpm puts the root node_modules/.bin on PATH for workspace scripts, so the
// binary resolves too.
//
// This mirrors the config the profile templates ship, deliberately minus the
// Next.js block: the starter's apps/, packages/ and services/ are empty
// scaffolding, and its only TypeScript is two Node CLIs. Carrying
// @next/eslint-plugin-next here would be a dependency for rules that could
// never fire. The generated projects, which do have Next applications, keep
// the fuller config in profiles/*/template/eslint.config.mjs.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/.next/**",
      "**/node_modules/**",
      "**/.turbo/**",
      "**/coverage/**",
      "**/.venv/**",
      // Profile templates are not this repository's source. They are rendered
      // through Handlebars, so a .ts.hbs is not valid TypeScript and a plain
      // .ts among them is the *generated* project's code, linted there by the
      // config that project ships.
      "profiles/*/template/**",
      // Vendored third-party skills. Their content is upstream's to lint, and
      // reformatting it here would make every upgrade a conflict.
      ".claude/skills/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{js,mjs,ts}"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    files: ["**/*.ts"],
    rules: {
      // Unused arguments are common in interface implementations; an underscore
      // prefix marks them deliberate.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
