// Flat ESLint config for the whole monorepo.
//
// ESLint 9 searches upward from the working directory for this file, so every
// workspace package can run a bare `eslint src` and resolve back to here. That
// keeps one shared rule set instead of a near-identical copy per package, and
// pnpm puts the root node_modules/.bin on PATH for workspace scripts, so the
// binary resolves too.
import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/.next/**",
      "**/node_modules/**",
      "**/.turbo/**",
      "**/coverage/**",
      "**/next-env.d.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // `next lint` is removed in Next.js 16, so the apps run the ESLint CLI like
    // every other package and pick up the Next rules from here instead.
    files: ["apps/**/*.{ts,tsx}"],
    plugins: { "@next/next": nextPlugin },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      // Unused arguments are common in generated stubs and in interface
      // implementations; an underscore prefix marks them deliberate.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
